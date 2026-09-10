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
from ir import sanitize_generated_ir
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
    # Раунды «починка → повторная оценка», пока результат не пройдёт порог.
    # Останавливаемся на приёмке или регрессии; итог — лучший допустимый IR.
    max_rounds: int = 3


class QualityPassCodexOutputs(BaseModel):
    judge: str | None = None
    # repair/rejudge — первый раунд (старые клиенты); repairs/rejudges — все раунды по порядку.
    repair: str | None = None
    rejudge: str | None = None
    repairs: list[str] = []
    rejudges: list[str] = []


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
    return generator_policy.digest({"ir": ir, "brief": brief, "policy": generator_policy.fingerprint(), "evidenceVersion": 2,
        "engine": engine_stamp, "renderer": llm._file_stamp(APP_ROOT / "ir_render.py")})


def _render_quality_evidence(ir: dict, brief: str) -> dict:
    """Keep each viewport's first screen identifiable even when it has many tiles."""
    images, first_screen_indices = [], []
    for width in (1440, 390):
        first_screen_indices.append(len(images))
        images.extend(_judge_images(render_png(ir, width=width, webfonts=True, viewport="mobile" if width == 390 else "desktop")))
    evidence = {"images": images, "widths": [1440, 390], "firstScreenIndices": first_screen_indices}
    cache_store.put("generator-visual", _quality_visual_key(ir, brief), evidence)
    return evidence


def _quality_desktop_messages(ir: dict, brief: str, visual: bool, surface: str = "auto") -> list[dict]:
    if not visual:
        return _quality_judge_messages(ir, brief, surface)
    key = _quality_visual_key(ir, brief)
    evidence = cache_store.get("generator-visual", key)
    if not evidence or "firstScreenIndices" not in evidence:
        evidence = _render_quality_evidence(ir, brief)
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


_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
REPAIR_DS_BUDGET = 3000


def _repair_design_system_block(design_system: dict | None, brief: str, surface: str) -> str:
    """Компактный профиль ДС для починки: токены, атмосфера, декор — чтобы починка
    «поднимала контраст» токеном primary, а не новым цветом."""
    if not isinstance(design_system, dict) or not design_system.get("systemId"):
        return ""
    try:
        from design_system import compiler, resolver, store
        document, error = store.resolve_ref(design_system)
        if error or not document:
            return ""
        context = resolver.resolve_context(document, brief, usage_mode=str(design_system.get("usageMode") or "strict"))
        compiled = compiler.compile_profile(context, brief=brief, token_budget=REPAIR_DS_BUDGET, surface=surface)
        return compiled["promptBlock"]
    except Exception:  # noqa: BLE001 — профиль ДС для починки желателен, но не обязателен
        return ""


def _repair_images(ir: dict, brief: str) -> list[str]:
    """Первый экран desktop и mobile из кэша судьи: починка видит, что именно не так."""
    evidence = cache_store.get("generator-visual", _quality_visual_key(ir, brief))
    images = list((evidence or {}).get("images") or [])
    indices = (evidence or {}).get("firstScreenIndices") or []
    # Legacy flat caches cannot identify the mobile boundary reliably.
    return [images[index] for index in indices if isinstance(index, int) and 0 <= index < len(images)]


def _quality_repair_messages(ir: dict, scorecard: dict, brief: str, surface: str = "auto", *,
                             round_index: int = 1, history: list[dict] | None = None, min_score: int = 80,
                             design_system: dict | None = None, images: list[str] | None = None,
                             ) -> tuple[list[dict] | None, str | None]:
    """Адресная починка по всем замечаниям judge: список с серьёзностью, путём,
    проблемой и инструкцией, цель по баллу, история прошлых раундов, профиль ДС и
    скриншоты текущего состояния (десктоп и мобильный)."""
    issues = sorted(scorecard.get("issues", []), key=lambda item: _SEVERITY_ORDER.get(str(item.get("severity")), 3))
    lines = []
    for index, issue in enumerate(issues, start=1):
        problem = str(issue.get("problem") or "").strip()
        instruction = str(issue.get("instruction") or "").strip()
        if not problem and not instruction:
            continue
        lines.append(f"{index}. [{issue.get('severity', 'minor')}] {issue.get('path') or '(root)'}: {problem}"
                     + (f" → {instruction}" if instruction else ""))
    general = str(scorecard.get("repair_instruction") or "").strip()
    if not lines and not general:
        return None, "судья не дал инструкций для repair"
    instructions = "\n".join(lines)
    if general:
        instructions = (instructions + "\n\n" if instructions else "") + f"Общая инструкция судьи: {general}"
    score = scorecard.get("score")
    goal = (f"Текущая оценка {score}/100, порог {min_score}. Закрой каждое замечание, начиная с critical и major; "
            "minor тоже исправляй, если это не ломает раскладку.")
    if history:
        goal += "\nПрошлые раунды: " + "; ".join(
            f"раунд {item.get('round')}: {item.get('score')}/100"
            + (f", осталось замечаний {item.get('issues')}" if item.get("issues") is not None else "")
            for item in history) + ". Не повторяй прежнюю правку, если она не помогла."
    user = (
        f"Исправь Design IR строго по замечаниям Quality Pass (раунд {round_index}). Сохрани полезный контент, "
        "не добавляй неупомянутые секции и верни только полный валидный JSON.\n"
        "Ограничения починки: элементы image с imagePrompt — штатные заглушки, их не заменять "
        "«нарисованным интерфейсом» из примитивов и не удалять; во free-раскладке дети не должны "
        "перекрываться и выходить за границы родителя — при сомнении переводи группу в auto-layout "
        "(frame.layout row/column с gap), а не подбирай координаты. Цвета, шрифты и радиусы — только "
        "из токенов документа: контраст поднимай ролями primary/text/surface, а не новым hex.\n\n"
        f"## Цель\n{goal}\n\n"
        f"## Бриф\n{brief.strip() or '(не указан)'}\n\n"
        f"## Замечания судьи\n{instructions}\n\n"
    )
    ds_block = _repair_design_system_block(design_system, brief, surface)
    if ds_block:
        user += f"## Дизайн-система (соблюдать при починке)\n{ds_block}\n\n"
    if images:
        user += ("## Скриншоты текущего состояния\nПервый — первый экран desktop 1440×900, второй — мобильный 390px. "
                 "Замечания судьи относятся к этим изображениям.\n\n")
    user += f"## Входной Design IR\n{json.dumps(ir, ensure_ascii=False)}"
    content: str | list = user
    if images:
        content = [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": url}} for url in images]
    return [
            {"role": "system", "content": llm.build_system_prompt("edit", policy=generator_policy.judge_rules(brief, ir, surface)
             + "\nRepair must preserve all tokens, exact componentRefs, masters and their geometry/styles. "
               "A problem in a locked master is a DS gap; do not change the instance.")},
            {"role": "user", "content": content},
        ], None


def _needs_repair(scorecard: dict, min_score: int, deterministic: list | None = None) -> bool:
    return bool(deterministic) or not _passes(scorecard, min_score)


def _passes(scorecard: dict, min_score: int) -> bool:
    important = any(issue.get("severity") in {"critical", "major"} for issue in scorecard.get("issues", []))
    return int(scorecard.get("score", 0)) >= min_score and scorecard.get("verdict") == "pass" and not important


def _important_count(scorecard: dict) -> int:
    return sum(1 for issue in scorecard.get("issues", []) if issue.get("severity") in {"critical", "major"})


def _better(candidate: dict, best: dict) -> bool:
    """Break equal scores by major/critical count, then the judge's acceptance."""
    if int(candidate.get("score", 0)) != int(best.get("score", 0)):
        return int(candidate.get("score", 0)) > int(best.get("score", 0))
    if _important_count(candidate) != _important_count(best):
        return _important_count(candidate) < _important_count(best)
    return candidate.get("verdict") == "pass" and best.get("verdict") != "pass"


def _round_failure(req: QualityPassReq, repaired: dict, initial: dict, current: dict, scorecard: dict, surface: str) -> str | None:
    """A rejected candidate must never replace the best validated round."""
    failure = generator_policy.repair_guard(req.ir, repaired, surface, req.designSystem, brief=req.brief)
    if failure:
        return failure
    old_critical = sum(issue.get("severity") == "critical" for issue in initial.get("issues", []))
    new_critical = sum(issue.get("severity") == "critical" for issue in scorecard.get("issues", []))
    if int(scorecard["score"]) < int(current.get("score", 0)) or new_critical > old_critical:
        return "Повторная оценка выявила регрессию; раунд отклонён"
    return None


def _round_outputs(outputs: QualityPassCodexOutputs) -> tuple[list[str], list[str]]:
    repairs = list(outputs.repairs) if outputs.repairs else ([outputs.repair] if outputs.repair is not None else [])
    rejudges = list(outputs.rejudges) if outputs.rejudges else ([outputs.rejudge] if outputs.rejudge is not None else [])
    return repairs, rejudges


def _max_rounds(req: QualityPassReq) -> int:
    return max(0, min(int(req.max_rounds), 5)) if req.repair else 0


def _parse_quality_repair(raw: str) -> tuple[dict | None, str | None]:
    try:
        repaired, parse_error = parse_ir_response(raw)
        if repaired is None:
            return None, parse_error
        # Те же нормализации, что у генератора: frame секций, плотность, резиновые
        # ширины — иначе починка возвращает дефекты, которые санитайзер уже снимал.
        repaired = sanitize_generated_ir(repaired)
        # Невидимый текст (цвет = фон) чинится детерминированно и после починки модели.
        repaired, _journal = qualitygate.autofix(
            repaired, rules=[rule for rule in qualitygate.RULES if rule["id"] == "invisible-text"])
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
    # Server rejudges render afresh; repairs reuse these exact first screens.
    image_data_url = _render_quality_evidence(ir, brief)["images"]
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
        if not req.rejudge or final is initial:
            failure = failure or "Починка не прошла повторную оценку"
        # Регрессия — ниже балл или новые critical-замечания. Раньше любое
        # переформулированное судьёй замечание считалось «новым» и откатывало
        # починку, поэтому результат оставался с первой оценкой.
        old_critical = sum(1 for i in initial.get("issues", []) if i.get("severity") == "critical")
        new_critical = sum(1 for i in final.get("issues", []) if i.get("severity") == "critical")
        if final.get("score", 0) < initial.get("score", 0) or new_critical > old_critical:
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
    from asset_quality import audit as audit_assets
    resource_evidence = audit_assets(output_ir)
    resource_unknown = passed and resource_evidence["status"] == "unknown"
    passed = passed and resource_evidence["status"] == "pass"
    acceptance = generator_policy.report(passed=bool(passed), visual=visual, surface=surface, ds_check=ds_check)
    acceptance["checks"]["resources"] = resource_evidence["status"]
    acceptance["checks"]["editUndo"] = "unknown"
    acceptance["checks"]["exportReopen"] = "unknown"
    if resource_unknown:
        acceptance["status"] = "unverified"
    return {"ir": output_ir, "passed": bool(passed), "min_score": min_score,
            "scorecard": final, "initial_scorecard": initial,
            "deterministic": {"before": before, "after": after}, "repair": repair,
            "designSystem": ds_check,
            "resourceEvidence": resource_evidence, "acceptance": acceptance}


def _quality_repair(ir: dict, scorecard: dict, brief: str, *, provider: str = "auto", effort: str = "medium",
                    surface: str = "auto", round_index: int = 1, history: list[dict] | None = None,
                    min_score: int = 80, design_system: dict | None = None) -> tuple[dict | None, str | None]:
    """Серверный LLM-путь standalone веб-сервера (Sol по ключу или Codex/Claude CLI)."""
    messages, error = _quality_repair_messages(
        ir, scorecard, brief, surface, round_index=round_index, history=history, min_score=min_score,
        design_system=design_system, images=_repair_images(ir, brief))
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

    Если repair не удался, возвращаем лучший уже проверенный IR (либо исходник,
    если ни один раунд не принят), не подменяя граф битым ответом модели.
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
    surface = generator_policy.surface_for(req.brief, req.surface, req.ir)
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None, "rounds": []}
    final = initial
    current_ir, current = copy.deepcopy(req.ir), initial
    max_rounds = _max_rounds(req)
    for index in range(1, max_rounds + 1):
        deterministic = deterministic_before if index == 1 else generator_policy.lint(current_ir, surface)
        if not _needs_repair(current, min_score, deterministic):
            break
        repair["attempted"] = True
        run_registry.stage(run_id, "repair", f"Починка по замечаниям судьи ({index}/{max_rounds})")
        repaired, repair_error = _quality_repair(
            current_ir, current, req.brief, provider=req.provider, effort=req.effort, surface=req.surface,
            round_index=index, history=repair["rounds"], min_score=min_score, design_system=req.designSystem)
        if repaired is None:
            repair["error"] = repair_error
            repair["rounds"].append({"round": index, "applied": False, "error": repair_error})
            break
        if not req.rejudge:
            output_ir, repair["applied"] = repaired, True
            repair["rounds"].append({"round": index, "applied": True, "score": None, "issues": None})
            break
        if run_registry.is_cancelled(run_id):
            return err(CANCELLED_STATUS, "Quality Pass отменён")
        run_registry.stage(run_id, "rejudge", f"Повторная оценка ({index}/{max_rounds})")
        try:
            scorecard = _quality_scorecard(repaired, req.brief, run_id, provider=req.provider, effort=req.effort, surface=req.surface)
        except Exception as e:
            repair["error"] = f"rejudge недоступен: {e}"
            repair["rounds"].append({"round": index, "applied": False, "error": repair["error"]})
            break
        failure = _round_failure(req, repaired, initial, current, scorecard, surface)
        repair["rounds"].append({"round": index, "applied": not failure, "score": scorecard["score"],
                                 "issues": len(scorecard["issues"]), **({"error": failure} if failure else {})})
        if failure:
            repair["error"] = failure
            break
        current_ir, current = repaired, scorecard
        if _better(scorecard, final):
            output_ir, final, repair["applied"] = repaired, scorecard, True
        if not _needs_repair(scorecard, min_score, generator_policy.lint(repaired, surface)):
            break
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
    repairs, rejudges = _round_outputs(outputs)
    for stage, raw in [("judge", outputs.judge), *(("repair", item) for item in repairs), *(("rejudge", item) for item in rejudges)]:
        if raw is not None and len(raw.encode("utf-8")) > 2 * 1024 * 1024:
            return err(413, f"Quality Pass {stage}: ответ Codex слишком большой")
    if outputs.judge is None and (repairs or rejudges):
        return err(422, "Quality Pass: repair/rejudge без judge — неконсистентное состояние Codex")
    if len(rejudges) > len(repairs):
        return err(422, "Quality Pass: rejudge без repair — неконсистентное состояние Codex")

    surface = generator_policy.surface_for(req.brief, req.surface, req.ir)
    deterministic_before = generator_policy.lint(req.ir, surface)
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
    needs_repair = _needs_repair(initial, min_score, deterministic_before)
    if repairs and (not req.repair or not needs_repair):
        return err(422, "Quality Pass: repair не запрашивался — неконсистентное состояние Codex")
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None, "rounds": []}
    final = initial
    current_ir, current = copy.deepcopy(req.ir), initial
    max_rounds = _max_rounds(req)
    consumed = 0  # сколько rejudge-ответов действительно вошли в раунды

    for index in range(1, max_rounds + 1):
        deterministic = deterministic_before if index == 1 else generator_policy.lint(current_ir, surface)
        if not _needs_repair(current, min_score, deterministic):
            break
        messages, message_error = _quality_repair_messages(
            current_ir, current, req.brief, req.surface, round_index=index, history=repair["rounds"],
            min_score=min_score, design_system=req.designSystem,
            images=_repair_images(current_ir, req.brief) if req.visualReview else None)
        if messages is None:
            repair["error"] = message_error
            break
        repair["attempted"] = True
        if index > len(repairs):
            return {"pending": {"stage": "repair", "profile": "quality_repair", "round": index, "messages": messages}}
        repaired, repair_error = _parse_quality_repair(repairs[index - 1])
        if repaired is None:
            repair["error"] = repair_error
            repair["rounds"].append({"round": index, "applied": False, "error": repair_error})
            break
        if not req.rejudge:
            output_ir, repair["applied"] = repaired, True
            repair["rounds"].append({"round": index, "applied": True, "score": None, "issues": None})
            break
        if index > len(rejudges):
            return {"pending": {
                "stage": "rejudge", "profile": "quality_judge", "round": index,
                "messages": _quality_desktop_messages(repaired, req.brief, req.visualReview, req.surface),
            }}
        try:
            scorecard = _parse_quality_scorecard(rejudges[index - 1], "Codex app-server / quality_judge")
            scorecard["mode"] = "component" if _component_quality_mode(repaired) else "page"
        except Exception as e:
            return err(502, f"Quality Pass rejudge вернул неверный ответ: {e}")
        consumed = index
        failure = _round_failure(req, repaired, initial, current, scorecard, surface)
        repair["rounds"].append({"round": index, "applied": not failure, "score": scorecard["score"],
                                 "issues": len(scorecard["issues"]), **({"error": failure} if failure else {})})
        if failure:
            repair["error"] = failure
            break
        current_ir, current = repaired, scorecard
        if _better(scorecard, final):
            output_ir, final, repair["applied"] = repaired, scorecard, True
        if not _needs_repair(scorecard, min_score, generator_policy.lint(repaired, surface)):
            break

    if rejudges and consumed == 0 and not repair["applied"]:
        return err(422, "Quality Pass: rejudge без применённого repair — неконсистентное состояние Codex")
    visual = bool(req.visualReview and cache_store.get("generator-visual", _quality_visual_key(output_ir, req.brief)))
    return _quality_finish(req, output_ir, initial, final, repair, visual=visual)
