"""Quality Gate, Quality Pass (judge → repair → rejudge) и сертификация: /api/quality-gate, /api/quality-pass, /api/quality-pass/codex-step, /api/quality/certify."""
import base64
import copy
import io
import json
from typing import Literal
from pydantic import BaseModel
from quality_certification_adapter import certify_from_reports
import llm_client as llm
import cache_store
import run_registry
import qualitygate
import rules as project_rules
from ir_render import render_png
import generator_policy
from fastapi import APIRouter
from api.common import (  # noqa: F401
    APP_ROOT, CANCELLED_STATUS, DATA_ROOT, ROOT, _finish_run, err, parse_ir_response,
    sanitize_font_face_weights, validate_ir,
)

router = APIRouter()


class QualityGateReq(BaseModel):
    ir: dict
    fix: bool = True  # авто-доводка solver'ом (без LLM) того, что чинится
    strictTokens: bool = False  # ДС strict: цвета вне палитры снапятся всегда


class QualityPassReq(BaseModel):
    ir: dict
    provider: str = "auto"
    effort: str = "medium"
    brief: str = ""
    min_score: int = 80
    repair: bool = True
    rejudge: bool = True
    designSystem: dict | None = None
    surface: Literal["auto", "landing", "catalog", "detail", "checkout", "dashboard", "form", "editor", "ai-workspace", "article", "feed", "component"] = "auto"
    visualReview: bool = False
    runId: str | None = None


class QualityPassCodexOutputs(BaseModel):
    judge: str | None = None
    repair: str | None = None
    rejudge: str | None = None


class QualityPassCodexReq(QualityPassReq):
    outputs: QualityPassCodexOutputs = QualityPassCodexOutputs()


@router.post("/api/quality/certify")
def quality_certify(request: dict):
    """Create an auditable, fail-closed certificate from completed QA reports."""
    try:
        return certify_from_reports(request)
    except (TypeError, ValueError) as exc:
        return err(422, str(exc))


@router.post("/api/quality-gate")
def quality_gate(req: QualityGateReq):
    """Детерминированный Quality Gate: правила v1 + авто-доводка без LLM.

    passed/violations — по входному IR; fixed_ir/journal — результат solver'а
    (починено только то, что чинится детерминированно: сетка 8px, overflow).
    """
    violations = qualitygate.check(req.ir)
    if req.fix:
        fixed_ir, journal = qualitygate.autofix(req.ir, strict_tokens=req.strictTokens)
    else:
        fixed_ir, journal = copy.deepcopy(req.ir), []
    return {"passed": qualitygate.passed(violations), "violations": violations,
            "fixed_ir": fixed_ir, "journal": journal}


QUALITY_JUDGE_SYSTEM = """Ты — строгий арт-директор и pixel QA-судья DesignAI.
Главное доказательство — приложенный скриншот реально отрендеренного Design IR.
Design IR дан только как карта для адресных путей правок. Не хвали, не додумывай
невидимые свойства и не подменяй визуальную оценку чтением JSON.
Верни только JSON-объект:
{
  "score": 0,
  "verdict": "pass|needs_repair",
  "summary": "краткий вывод",
  "issues": [{"category": "hierarchy|rhythm|density|typography|color|slop|brief", "severity": "critical|major|minor", "path": "путь IR или (root)", "problem": "что не так", "instruction": "как исправить"}],
  "repair_instruction": "единая точная инструкция; пустая строка, если repair не нужен"
}
score — целое 0..100. Следуй приложенной рубрике и учитывай только наблюдаемое."""


COMPONENT_RUBRIC = """## Component mode
This IR is one component/source section, not a complete page. Do not apply page-level
requirements such as a single H1, hero hierarchy, page grid, section count or page density.
Score only readability, spacing/rhythm inside the component, clipping/overlap, and visual
correspondence to the supplied Source master. A pass requires score >= 80."""


def _component_quality_mode(ir: dict) -> bool:
    meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
    tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
    return bool(meta.get("strictRecovery") or
                (len(tree) == 1 and isinstance(tree[0], dict)
                 and tree[0].get("type") == "source-block"))


def _quality_violations(ir: dict) -> list[dict]:
    violations = qualitygate.check(ir)
    if not _component_quality_mode(ir):
        return violations
    page_rules = {"single-h1", "grid-8", "frame-overflow"}
    return [item for item in violations if item.get("rule") not in page_rules]


def _quality_judge_messages(ir: dict, brief: str, surface: str = "auto") -> list[dict]:
    mode = _component_quality_mode(ir)
    return [
        {"role": "system", "content": QUALITY_JUDGE_SYSTEM + generator_policy.judge_rules(brief, ir, surface)
         + ("\n\n" + COMPONENT_RUBRIC if mode else "")
         + "\nEvidence: Design IR only. Visual, keyboard and performance checks are unknown."},
        {"role": "user", "content": "## Бриф\n" + (brief.strip() or "(не указан)")
         + "\n\n## Design IR\n" + json.dumps(ir, ensure_ascii=False)},
    ]


def _quality_visual_key(ir: dict, brief: str) -> str:
    engine = APP_ROOT / "static" / "flow" / "engine.js"
    try:
        engine_stamp = llm._file_stamp(engine)
    except FileNotFoundError:
        engine_stamp = None  # A concurrent build must not crash cache lookup; render reports missing engine.
    return generator_policy.digest({"ir": ir, "brief": brief, "policy": generator_policy.fingerprint(),
        "engine": engine_stamp, "renderer": llm._file_stamp(APP_ROOT / "ir_render.py")})


def _quality_desktop_messages(ir: dict, brief: str, visual: bool, surface: str = "auto") -> list[dict]:
    if not visual:
        return _quality_judge_messages(ir, brief, surface)
    key = _quality_visual_key(ir, brief)
    evidence = cache_store.get("generator-visual", key)
    if not evidence:
        images = []
        for width in (1440, 390):
            images.extend(_judge_images(render_png(ir, width=width, webfonts=True, viewport="mobile" if width == 390 else "desktop")))
        evidence = {"images": images, "widths": [1440, 390]}
        cache_store.put("generator-visual", key, evidence)
    text = (generator_policy.judge_rules(brief, ir, surface) + "\nFirst group: desktop 1440px. Second group: mobile 390px. "
            "Only these viewports were rendered; keyboard and performance remain unknown.\nBrief: " + brief
            + "\nIR: " + json.dumps(ir, ensure_ascii=False))
    return [{"role": "system", "content": QUALITY_JUDGE_SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": text}]
             + [{"type": "image_url", "image_url": {"url": url}} for url in evidence["images"]]}]


def _parse_quality_scorecard(raw: str, model_route: str) -> dict:
    """Нормализует недоверенный JSON judge до публичного контракта."""
    try:
        parsed = json.loads(llm.extract_json(raw))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"судья вернул невалидный JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("судья вернул не объект")
    try:
        score = int(parsed.get("score"))
    except (TypeError, ValueError) as e:
        raise ValueError("судья не вернул числовой score") from e
    issues = []
    for item in parsed.get("issues", []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "minor"))
        if severity not in {"critical", "major", "minor"}:
            severity = "minor"
        issues.append({
            "category": str(item.get("category", "consistency")),
            "severity": severity,
            "path": str(item.get("path", "(root)")),
            "problem": str(item.get("problem", "")),
            "instruction": str(item.get("instruction", "")),
        })
    verdict = str(parsed.get("verdict", "needs_repair"))
    return {
        "score": max(0, min(score, 100)),
        "verdict": verdict if verdict in {"pass", "needs_repair"} else "needs_repair",
        "summary": str(parsed.get("summary", "")),
        "issues": issues[:12],
        "repair_instruction": str(parsed.get("repair_instruction", "")),
        "model_route": model_route,
    }


def _quality_repair_messages(ir: dict, scorecard: dict, brief: str, surface: str = "auto") -> tuple[list[dict] | None, str | None]:
    """Готовит адресную починку только по замечаниям judge."""
    instructions = scorecard.get("repair_instruction", "").strip()
    if not instructions:
        instructions = "\n".join(
            str(issue.get("instruction", "")) for issue in scorecard.get("issues", [])
            if issue.get("severity") in {"critical", "major"}
        ).strip()
    if not instructions:
        return None, "судья не дал инструкций для repair"
    user = (
        "Исправь Design IR строго по замечаниям Quality Pass. Сохрани полезный контент, "
        "не добавляй неупомянутые секции и верни только полный валидный JSON.\n"
        "Ограничения починки: элементы image с imagePrompt — штатные заглушки, их не заменять "
        "«нарисованным интерфейсом» из примитивов и не удалять; во free-раскладке дети не должны "
        "перекрываться и выходить за границы родителя — при сомнении переводи группу в auto-layout "
        "(frame.layout row/column с gap), а не подбирай координаты.\n\n"
        f"## Бриф\n{brief.strip() or '(не указан)'}\n\n"
        f"## Инструкции\n{instructions}\n\n"
        f"## Входной Design IR\n{json.dumps(ir, ensure_ascii=False)}"
    )
    return [
            {"role": "system", "content": llm.build_system_prompt("edit", policy=generator_policy.judge_rules(brief, ir, surface)
             + "\nRepair must preserve all tokens, exact componentRefs, masters and their geometry/styles. "
               "A problem in a locked master is a DS gap; do not change the instance.")},
            {"role": "user", "content": user},
        ], None


def _parse_quality_repair(raw: str) -> tuple[dict | None, str | None]:
    try:
        repaired, parse_error = parse_ir_response(raw)
        if repaired is None:
            return None, parse_error
        schema_errors = validate_ir(repaired)
        if schema_errors:
            return None, "; ".join(schema_errors[:5])
        return repaired, None
    except Exception as e:
        return None, str(e)


JUDGE_FIRST_SCREEN_H = 900


JUDGE_TILE_H = 1400


JUDGE_MAX_TILES = 4


def _judge_images(screenshot: bytes) -> list[str]:
    """Скриншот страницы → набор изображений для vision-судьи.

    Одна высокая картинка (1440×7000) при даунскейле выглядит как мобильный
    макет с нечитаемым текстом. Отдаём первый экран 1:1 и страницу по частям.
    """
    def data_url(png: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(screenshot))
        width, height = image.size
        out: list[str] = []
        first = image.crop((0, 0, width, min(height, JUDGE_FIRST_SCREEN_H)))
        buf = io.BytesIO(); first.save(buf, format="PNG", optimize=True); out.append(data_url(buf.getvalue()))
        if height > JUDGE_FIRST_SCREEN_H:
            tile_h = max(JUDGE_TILE_H, -(-height // JUDGE_MAX_TILES))  # не больше JUDGE_MAX_TILES плиток
            for top in range(0, height, tile_h):
                tile = image.crop((0, top, width, min(height, top + tile_h)))
                scale = min(1, 1024 / width)
                tile = tile.resize((min(width, 1024), max(1, round(tile.height * scale))))
                buf = io.BytesIO(); tile.save(buf, format="PNG", optimize=True); out.append(data_url(buf.getvalue()))
        return out
    except Exception:  # noqa: BLE001 — без PIL/на битом PNG отдаём как есть
        return [data_url(screenshot)]


def _quality_scorecard(ir: dict, brief: str, run_id: str | None = None, *, provider: str = "auto", effort: str = "medium", surface: str = "auto") -> dict:
    """Render IR and ask the standalone server's vision model for a scorecard."""
    run_registry.stage(run_id, "render", "Рендерю IR для визуальной проверки")
    screenshot = render_png(ir, width=1440, webfonts=True)
    image_data_url = _judge_images(screenshot)
    mobile_screenshot = render_png(ir, width=390, webfonts=True, viewport="mobile")
    image_data_url.extend(_judge_images(mobile_screenshot))
    rubric = (APP_ROOT / "prompts" / "RUBRIC.md").read_text(encoding="utf-8")
    component_mode = _component_quality_mode(ir)
    if component_mode:
        rubric = COMPONENT_RUBRIC
    rubric += generator_policy.judge_rules(brief, ir, surface)
    rules_block = project_rules.prompt_block("judge")
    if rules_block:
        rubric += "\n\n" + rules_block
    prompt = (
        rubric
        + "\n\n## Изображения\nПервое — первый экран 1440×900 в масштабе 1:1 (десктоп); "
          "следующие — вся страница по частям сверху вниз, уменьшены до 1024px по ширине. "
          "Последняя группа изображений — мобильный рендер шириной 390px. "
          "Оцени отдельно desktop и mobile; остальные viewport и интерактивное поведение не проверены."
        + "\n\n## Бриф\n" + (brief.strip() or "(не указан)")
        + "\n\n## Карта Design IR для адресных правок\n"
        + json.dumps(ir, ensure_ascii=False)
    )
    run_registry.stage(run_id, "judge", "Vision-судья оценивает скриншот")
    raw = llm.chat_vision(
        provider, image_data_url, prompt, QUALITY_JUDGE_SYSTEM, 0.2,
        role="quality_judge", reasoning_effort=effort,
    )
    scorecard = _parse_quality_scorecard(raw, "LLM vision / quality_judge")
    scorecard["mode"] = "component" if component_mode else "page"
    scorecard["evidence"] = {"visual": True, "widths": [1440, 390], "keyboard": "unknown", "performance": "unknown"}
    return scorecard


def _quality_finish(req, output_ir, initial, final, repair, *, visual=False):
    """Shared acceptance for server and desktop, independent of the judge's claims."""
    surface = generator_policy.surface_for(req.brief, req.surface, req.ir)
    before = generator_policy.lint(req.ir, surface)
    if repair["applied"]:
        failure = generator_policy.repair_guard(req.ir, output_ir, surface, req.designSystem, brief=req.brief)
        old_issues = {(i.get("category"), i.get("path"), i.get("problem")) for i in initial.get("issues", [])}
        new_issues = [i for i in final.get("issues", [])
                      if (i.get("category"), i.get("path"), i.get("problem")) not in old_issues]
        if not req.rejudge or final is initial:
            failure = failure or "Починка не прошла повторную оценку"
        if final.get("score", 0) < initial.get("score", 0) or new_issues:
            failure = failure or "Повторная оценка выявила регрессию; починка отменена"
        if failure:
            output_ir, final = copy.deepcopy(req.ir), initial
            repair.update(applied=False, error=failure)
    after = generator_policy.lint(output_ir, surface)
    ds_check = None
    if req.designSystem:
        from design_system import resolver, store
        document, error = store.resolve_ref(req.designSystem)
        if error:
            ds_check = {"errors": [{"message": str(error)}]}
        else:
            ds_check = resolver.validate_generation(output_ir, resolver.resolve_context(
                document, req.brief, usage_mode=req.designSystem.get("usageMode") or "strict"))
    important = any(i.get("severity") in {"critical", "major"} for i in final.get("issues", []))
    min_score = max(0, min(int(req.min_score), 100))
    passed = (final["score"] >= min_score and final["verdict"] == "pass" and not important
              and qualitygate.passed(after) and not (ds_check or {}).get("errors")
              and not repair.get("error"))
    return {"ir": output_ir, "passed": bool(passed), "min_score": min_score,
            "scorecard": final, "initial_scorecard": initial,
            "deterministic": {"before": before, "after": after}, "repair": repair,
            "designSystem": ds_check,
            "acceptance": generator_policy.report(passed=bool(passed), visual=visual,
                                                   surface=surface, ds_check=ds_check)}


def _quality_repair(ir: dict, scorecard: dict, brief: str, *, provider: str = "auto", effort: str = "medium", surface: str = "auto") -> tuple[dict | None, str | None]:
    """Серверный LLM-путь standalone веб-сервера (Sol по ключу или Codex/Claude CLI)."""
    messages, error = _quality_repair_messages(ir, scorecard, brief, surface)
    if messages is None:
        return None, error
    try:
        raw = llm.chat(provider, messages, 0.25, role="quality_repair", reasoning_effort=effort)
    except Exception as e:
        return None, str(e)
    return _parse_quality_repair(raw)


@router.post("/api/quality-pass")
def quality_pass(req: QualityPassReq):
    """Обёртка run_registry: стадии judge → repair → rejudge и кооперативная отмена."""
    run_id = run_registry.start(req.runId, "quality-pass")
    resp = None
    try:
        resp = _quality_pass(req, run_id)
        return resp
    finally:
        _finish_run(run_id, resp)


def _quality_pass(req: QualityPassReq, run_id: str | None):
    """Премиальный контур: детерминированные правила → независимый judge → repair → rejudge.

    API всегда возвращает исходный валидный IR, если repair не удался: результат
    контролируем и не подменяем граф битым ответом модели.
    """
    schema_errors = validate_ir(sanitize_font_face_weights(req.ir))
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    deterministic_before = generator_policy.lint(req.ir, generator_policy.surface_for(req.brief, req.surface, req.ir))
    try:
        initial = _quality_scorecard(req.ir, req.brief, run_id, provider=req.provider, effort=req.effort, surface=req.surface)
    except Exception as e:
        return err(502, f"Quality Pass judge недоступен: {e}")
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Quality Pass отменён")
    min_score = max(0, min(int(req.min_score), 100))
    important = any(i["severity"] in {"critical", "major"} for i in initial["issues"])
    needs_repair = bool(deterministic_before) or important or initial["score"] < min_score
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None}
    final = initial
    if req.repair and needs_repair:
        repair["attempted"] = True
        run_registry.stage(run_id, "repair", "Починка по замечаниям судьи")
        repaired, repair_error = _quality_repair(req.ir, initial, req.brief, provider=req.provider, effort=req.effort, surface=req.surface)
        if repaired is None:
            repair["error"] = repair_error
        else:
            output_ir = repaired
            repair["applied"] = True
            if req.rejudge:
                if run_registry.is_cancelled(run_id):
                    return err(CANCELLED_STATUS, "Quality Pass отменён")
                run_registry.stage(run_id, "rejudge", "Повторная оценка")
                try:
                    final = _quality_scorecard(output_ir, req.brief, run_id, provider=req.provider, effort=req.effort, surface=req.surface)
                except Exception as e:
                    repair["error"] = f"rejudge недоступен: {e}"
    return _quality_finish(req, output_ir, initial, final, repair, visual=True)


@router.post("/api/quality-pass/codex-step")
def quality_pass_codex_step(req: QualityPassCodexReq):
    """Pure Quality Pass state machine for the desktop Codex transport.

    This endpoint prepares prompts and validates model outputs, but never calls
    an LLM itself. Every request is reconstructed from the source IR plus the
    three bounded raw outputs, so the renderer cannot smuggle trusted state.
    """
    schema_errors = validate_ir(sanitize_font_face_weights(req.ir))
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    outputs = req.outputs
    for stage in ("judge", "repair", "rejudge"):
        raw = getattr(outputs, stage)
        if raw is not None and len(raw.encode("utf-8")) > 2 * 1024 * 1024:
            return err(413, f"Quality Pass {stage}: ответ Codex слишком большой")
    if outputs.judge is None and (outputs.repair is not None or outputs.rejudge is not None):
        return err(422, "Quality Pass: repair/rejudge без judge — неконсистентное состояние Codex")
    if outputs.rejudge is not None and outputs.repair is None:
        return err(422, "Quality Pass: rejudge без repair — неконсистентное состояние Codex")

    deterministic_before = generator_policy.lint(req.ir, generator_policy.surface_for(req.brief, req.surface, req.ir))
    if outputs.judge is None:
        return {"pending": {
            "stage": "judge",
            "profile": "quality_judge",
            "messages": _quality_desktop_messages(req.ir, req.brief, req.visualReview, req.surface),
        }}
    try:
        initial = _parse_quality_scorecard(outputs.judge, "Codex app-server / quality_judge")
        initial["mode"] = "component" if _component_quality_mode(req.ir) else "page"
    except Exception as e:
        return err(502, f"Quality Pass judge вернул неверный ответ: {e}")

    min_score = max(0, min(int(req.min_score), 100))
    important = any(i["severity"] in {"critical", "major"} for i in initial["issues"])
    needs_repair = bool(deterministic_before) or important or initial["score"] < min_score
    if outputs.repair is not None and (not req.repair or not needs_repair):
        return err(422, "Quality Pass: repair не запрашивался — неконсистентное состояние Codex")
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None}
    final = initial

    if req.repair and needs_repair:
        repair["attempted"] = True
        messages, message_error = _quality_repair_messages(req.ir, initial, req.brief, req.surface)
        if messages is None:
            repair["error"] = message_error
        elif outputs.repair is None:
            return {"pending": {
                "stage": "repair",
                "profile": "quality_repair",
                "messages": messages,
            }}
        else:
            repaired, repair_error = _parse_quality_repair(outputs.repair)
            if repaired is None:
                repair["error"] = repair_error
            else:
                output_ir = repaired
                repair["applied"] = True
                if req.rejudge:
                    if outputs.rejudge is None:
                        return {"pending": {
                            "stage": "rejudge",
                            "profile": "quality_judge",
                            "messages": _quality_desktop_messages(output_ir, req.brief, req.visualReview, req.surface),
                        }}
                    try:
                        final = _parse_quality_scorecard(
                            outputs.rejudge, "Codex app-server / quality_judge"
                        )
                        final["mode"] = "component" if _component_quality_mode(output_ir) else "page"
                    except Exception as e:
                        return err(502, f"Quality Pass rejudge вернул неверный ответ: {e}")

    if outputs.rejudge is not None and not repair["applied"]:
        return err(422, "Quality Pass: rejudge без применённого repair — неконсистентное состояние Codex")
    visual = bool(req.visualReview and cache_store.get("generator-visual", _quality_visual_key(output_ir, req.brief)))
    return _quality_finish(req, output_ir, initial, final, repair, visual=visual)
