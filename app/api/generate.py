"""Генератор экранов, Mix, Clone и Reskin: /api/generate, /api/mix, /api/clone, /api/reskin."""
import contextvars
import copy
import json
import re
import uuid
from pydantic import BaseModel
import llm_client as llm
from colorutils import mix_hex_colors
from urlguard import fetch_public_bytes, validate_public_url
import cache_store
import run_registry
import mergeback
import qualitygate
import rules as project_rules
import project_store
import typography
import designkb
import generator_policy
import agent_contract
from ir import apply_tokens as apply_ir_tokens
from ir import bind_element_styles as bind_ir_element_styles
from ir import ensure_current as ensure_current_ir
from ir import sanitize_generated_ir
from fastapi import APIRouter
from api.common import (  # noqa: F401
    APP_ROOT, CANCELLED_STATUS, DATA_ROOT, ROOT, _finish_run, err, parse_ir_response,
    sanitize_font_face_weights, validate_ir,
)
import api.common as common

router = APIRouter()


COLOR_TOKEN_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"]


MAX_CLONE_HTML_BYTES = 2_000_000


def _locked_generation_dna(tokens: dict | None) -> tuple[dict | None, dict | None]:
    """Return prompt-safe public DNA and a complete DNA used to style output IR.

    Older callers may provide only the schema-level color/font/radius fields,
    while Source Import also provides semantic/primitives.  Generation needs
    both forms: compact public tokens in the LLM prompt and semantic values for
    deterministic application to inline styles returned by the model.
    """
    if not isinstance(tokens, dict):
        return None, None
    # Порт Design System отдаёт плоскую shadcn-карту или foundations, старые
    # Style DNA — частичные tokens v1. Всё приводим к ПОЛНЫМ tokens v1: лок
    # одного совпавшего ключа (radius) ронял IR на схеме.
    from design_system.style_review import coerce_ir_tokens
    coerced = coerce_ir_tokens(tokens)
    if coerced is None:
        return None, None
    public_keys = ("mode", "color", "font", "radius", "spacing", "shadow")
    public = {key: copy.deepcopy(coerced[key]) for key in public_keys}
    tokens = {**coerced, **{key: tokens[key] for key in ("primitives", "semantic", "provenance") if key in tokens}}
    complete = copy.deepcopy(public)
    for key in ("primitives", "semantic", "provenance"):
        if key in tokens:
            complete[key] = copy.deepcopy(tokens[key])
    if not isinstance(complete.get("semantic"), dict):
        colors = complete.get("color") if isinstance(complete.get("color"), dict) else {}
        fonts = complete.get("font") if isinstance(complete.get("font"), dict) else {}
        radii = complete.get("radius") if isinstance(complete.get("radius"), dict) else {}
        spacing = complete.get("spacing") if isinstance(complete.get("spacing"), dict) else {}
        radius_px = {"none": 0, "xs": 2, "sm": 4, "md": 8, "lg": 16, "xl": 24, "full": 1000}
        section_px = {"sm": 64, "md": 80, "lg": 96, "xl": 128}
        complete["semantic"] = {
            **copy.deepcopy(colors),
            "displayFont": copy.deepcopy(fonts.get("display") or {"family": "Inter", "weight": 700}),
            "bodyFont": copy.deepcopy(fonts.get("body") or {"family": "Inter", "weight": 400}),
            "buttonRadius": radius_px.get(str(radii.get("button") or "md"), 8),
            "cardRadius": radius_px.get(str(radii.get("card") or "lg"), 16),
            "inputRadius": radius_px.get(str(radii.get("input") or "md"), 8),
            "sectionGap": section_px.get(str(spacing.get("section") or "lg"), 96),
            "containerWidth": 1200,
        }
    else:
        # DOM capture represents pill radii as 9999px, while the IR semantic
        # contract caps numeric radii at 1000. Preserve the pill result without
        # emitting an invalid generated document.
        for key in ("buttonRadius", "cardRadius", "inputRadius"):
            value = complete["semantic"].get(key)
            if isinstance(value, (int, float)):
                complete["semantic"][key] = min(1000, max(0, value))
    return public, complete


def call_llm_ir(provider: str, user_content: str, temperature: float = 0.8,
                mode: str = "generate", effort: str = "medium",
                run_id: str | None = None):
    """Вызов LLM с системным промптом генератора -> (ir, error)."""
    pending_chars = 0

    def on_delta(delta: str) -> None:
        nonlocal pending_chars
        if run_registry.is_cancelled(run_id):
            raise RuntimeError("cancelled")
        pending_chars += len(delta)
        if pending_chars >= 512:
            run_registry.add_received_chars(run_id, pending_chars)
            pending_chars = 0

    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt(mode)},
            {"role": "user", "content": user_content},
        ], temperature, role="generator" if mode == "generate" else "edit",
            reasoning_effort=effort, on_delta=on_delta)
    except Exception as e:
        return None, str(e)
    finally:
        run_registry.add_received_chars(run_id, pending_chars)
    return parse_ir_response(raw)


class GenerateReq(BaseModel):
    brief: str = ""
    count: int = 3
    provider: str = "openai"
    effort: str = "medium"
    styleHint: str | None = None
    seedTag: str | None = None
    tokens: dict | None = None  # Style DNA: залоченные design-токены
    preset: str = ""  # стилевой пресет: minimal|bento|editorial|brutal|glass
    prepareOnly: bool = False
    rawOutputs: list[str] | None = None
    selectedDirection: str = "all"
    surface: str = "auto"
    designStyle: str = "auto"
    preparedContextId: str | None = None
    allowStrictFallback: bool = False
    # ТЗ §19: закреплённая ревизия дизайн-системы {systemId, revision, contentHash, usageMode}
    designSystem: dict | None = None
    # Существующие экраны проекта (порт reference): агент видит их паттерны и
    # мастера, а не «забывает, с чего начинали» на пятом экране.
    referenceIrs: list[dict] | None = None
    # Клиентский id запуска для стадий/отмены (run_registry); старые клиенты не шлют
    runId: str | None = None


class MixReq(BaseModel):
    irs: list
    weights: list


class CloneReq(BaseModel):
    url: str = ""
    component: str = ""
    provider: str = "openai"
    effort: str = "medium"


class ReskinReq(BaseModel):
    ir: dict
    prompt: str = ""
    tokens: dict | None = None  # источник нового стиля (design-токены)
    mask: dict = {}             # чекбоксы: colors/fonts/radii/shadows/texts/images
    provider: str = "openai"    # legacy values migrate to the fixed Sol route
    effort: str = "medium"
    prepareOnly: bool = False     # desktop: вернуть промпты вместо LLM-вызова
    rawOutput: str | None = None  # desktop: ответ подключённого аккаунта
    designSystem: dict | None = None


@router.post("/api/generate")
def generate(req: GenerateReq):
    """Обёртка: регистрирует запуск (стадии/отмена) и закрывает его по итогу."""
    run_id = run_registry.start(req.runId, "generate")
    run_registry.stage(run_id, "prompt", "Собираю промпт")
    resp = None
    try:
        try:
            policy = generator_policy.context(req.brief, surface=req.surface, style=req.designStyle,
                                              ds=req.designSystem, locked=bool(req.tokens), edit=bool(req.styleHint))
        except ValueError as exc:
            return err(422, str(exc))
        prepared = None
        request_key = generator_policy.digest(req.model_dump(exclude={"prepareOnly", "rawOutputs", "runId", "preparedContextId"}))
        if req.preparedContextId:
            prepared = cache_store.get("generator-prepared", req.preparedContextId)
            if not prepared or prepared.get("requestKey") != request_key:
                return err(409, "Контекст генератора изменился или истёк. Запустите генерацию заново.")
        # Pin the same resolved revision in both phases, including refs that omitted a revision.
        resolved = None
        if req.designSystem:
            from design_system import store as ds_store
            resolved, ds_error = ds_store.resolve_ref(req.designSystem)
            if ds_error:
                return err(422, f"Design System: {ds_error}")
        context_key = generator_policy.digest({"policy": policy, "ds": resolved,
            "rules": project_rules.prompt_block("generation"),
            "promptFiles": [llm._file_stamp(llm.ROOT / name) for name in llm._PROMPT_FILES]})
        if prepared and prepared.get("contextKey") != context_key:
            return err(409, "Дизайн-система или правила изменились после подготовки. Запустите генерацию заново.")
        resp = _generate(req, run_id, prepared=prepared, resolved_document=resolved)
        if isinstance(resp, dict):
            records = resp.pop("_directionRecords", [])
            fallback = (resp.get("generationLog") or {}).get("strictFallback")
            policy["effectiveMode"] = fallback or policy["requestedMode"]
            resp["designPolicy"] = policy
            resp.setdefault("generationLog", {})["policy"] = policy
            if req.prepareOnly:
                receipt = uuid.uuid4().hex
                cache_store.put("generator-prepared", receipt, {"requestKey": request_key,
                    "contextKey": context_key, "directions": records})
                resp["preparedContextId"] = receipt
        return resp
    finally:
        _finish_run(run_id, resp)


def _walk_ir_elements(node):
    """Рекурсивно по children секции/элемента."""
    if not isinstance(node, dict):
        return
    for child in node.get("children") or []:
        if isinstance(child, dict):
            yield child
            yield from _walk_ir_elements(child)


def _reference_pinned_component_keys(reference_irs, document: dict) -> list[str]:
    """Resolve DS masters carried by a reference, even when editor metadata is partial."""
    if not isinstance(reference_irs, list):
        return []
    from design_system.compiler import component_shape_hash

    components = {
        str(component.get("componentKey") or key): component
        for key, component in (document.get("components") or {}).items()
        if isinstance(component, dict) and isinstance(component.get("masterIr"), dict)
    }
    result: list[str] = []

    def pin(value) -> None:
        key = str(value or "")
        if key in components and key not in result:
            result.append(key)

    def inspect(value, parent_key: str = "") -> None:
        if isinstance(value, dict):
            if parent_key in ("_dsMaster", "dsMaster", "designSystemMaster"):
                pin(value.get("componentKey"))
            ref = value.get("componentRef")
            if isinstance(ref, dict):
                pin(ref.get("componentKey"))
            for key, child in value.items():
                inspect(child, str(key))
        elif isinstance(value, list):
            for child in value:
                inspect(child, parent_key)

    master_shapes: dict[str, str] = {}
    for key, component in components.items():
        tree = component["masterIr"].get("tree")
        if isinstance(tree, list) and tree and isinstance(tree[0], dict):
            master_shapes[key] = component_shape_hash(tree[0])

    for reference in [item for item in reference_irs if isinstance(item, dict)]:
        inspect(reference)
        tree = reference.get("tree") if isinstance(reference.get("tree"), list) else []
        candidates = [root for root in tree if isinstance(root, dict)]
        for root in list(candidates):
            if root.get("type") == "source-block" and root.get("variant") == "component-master":
                candidates.extend(child for child in (root.get("children") or []) if isinstance(child, dict))
        candidate_shapes = {component_shape_hash(candidate) for candidate in candidates}
        for key, shape in master_shapes.items():
            if shape in candidate_shapes:
                pin(key)
    return result


def _reference_screens_block(irs) -> str:
    """Компактный дайджест существующих экранов: секции, мастера ДС, роли текста.

    Полные IR в промпт не кладём (бюджет), но агент видит, из чего собраны
    соседние экраны, и повторяет те же паттерны — то, чего не умеют
    «креативные» AI-редакторы при росте числа экранов."""
    if not isinstance(irs, list):
        return ""
    lines = []
    for i, ir in enumerate([x for x in irs if isinstance(x, dict)][:3], 1):
        tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
        sections, masters, roles = [], set(), set()
        for sec in tree:
            if not isinstance(sec, dict):
                continue
            label = str(sec.get("type") or "section")
            if sec.get("variant"):
                label += f"/{sec.get('variant')}"
            props = sec.get("props") if isinstance(sec.get("props"), dict) else {}
            head = props.get("heading") or props.get("title") or ""
            if head:
                label += f" «{str(head)[:60]}»"
            sections.append(label)
            for el in [sec, *list(_walk_ir_elements(sec))]:
                meta = el.get("sourceMeta") if isinstance(el.get("sourceMeta"), dict) else {}
                ref = meta.get("componentRef") if isinstance(meta.get("componentRef"), dict) else None
                if ref and ref.get("componentKey"):
                    masters.add(str(ref["componentKey"]))
                if isinstance(el.get("typeRole"), str):
                    roles.add(el["typeRole"])
        tokens = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else {}
        mode = tokens.get("mode") or ""
        lines.append(
            f"Экран {i}{' (' + str(mode) + ')' if mode else ''}: секции — {', '.join(sections) or 'нет'}; "
            f"мастера ДС — {', '.join(sorted(masters)) or 'нет'}; роли текста — {', '.join(sorted(roles)) or 'нет'}."
        )
    if not lines:
        return ""
    return (
        "## Существующие экраны проекта (референс)\n" + "\n".join(lines)
        + "\nСделай так же: те же мастера ДС для тех же ролей (кнопки, карточки, шаги, поля), "
          "та же плотность и ритм секций, те же роли текста и та же тема. Не изобретай новый "
          "компонент там, где на референсе уже используется мастер."
    )


_TYPE_ROLE_RULE = (
    "\n\nТекстовые стили: у heading/text задавай поле typeRole "
    "(display/h1/h2/h3/lead/body/small/eyebrow) вместо инлайновых style.fontSize/"
    "lineHeight/fontWeight/letterSpacing — кегль, интерлиньяж, вес и разрядку даёт роль "
    "из tokens.v2.type.roles, поэтому все абзацы и заголовки одной роли одинаковы. "
    "В style у текста оставляй только цвет."
)


def _embed_mode_block(usage_mode: str) -> str:
    """Режим встраивания зависит от usageMode ДС, а не один текст на все режимы."""
    common = (
        "Результат вставят в существующий сайт из описания выше. "
        "Если бриф просит компонент или секцию — верни ровно её (одна секция в tree), "
        "без навигации, hero и футера; если просит страницу — повтори порядок секций "
        "сайта. Копирайт — в голосе сайта, на его языке, без плейсхолдеров «Lorem»."
    )
    if usage_mode == "extend":
        return (
            "\n\n## Режим встраивания: EXTEND\n"
            "Собирай из зарегистрированных мастеров и их вариантов там, где они подходят; "
            "недостающее строй из примитивов строго в токенах ДС, наследуя геометрию, "
            "радиусы, рамки и типографику мастеров. Новый элемент допустим только если "
            "ни один мастер не закрывает роль. " + common
        )
    if usage_mode == "style-only":
        return (
            "\n\n## Режим встраивания: STYLE ONLY\n"
            "Мастера — стилевой ориентир (характер углов, плотность, рамки, тени), "
            "копировать их не обязательно; токены ДС (цвета, шрифты, радиусы) обязательны, "
            "сырые значения вне токенов — провал. " + common
        )
    return (
        "\n\n## Режим встраивания: STRICT\n"
        "Собирай результат из зарегистрированных мастеров и их вариантов как из "
        "строительных блоков; новые элементы наследуют их геометрию, радиусы, рамки и "
        "типографику. " + common
    )


def _materialize_exact_master(primary: dict, ds_context: dict, ds_compiled: dict | None, reason: str):
    """Точная копия мастера ДС как вариант генерации — без модели.

    Наблюдённый мастер целой секции (шрифты, evidence, responsive) весит десятки
    тысяч токенов и в промпт не помещается; копировать его моделью бессмысленно —
    приложение материализует exact master само и проверяет strict-валидацией.
    Возвращает (ir, check) или (None, check) если копия не прошла проверку."""
    from design_system import compiler as ds_compiler, document as ds_document, resolver as ds_resolver
    recovered = ds_document.preview_ir_for_master(copy.deepcopy(primary["masterIr"]))
    recovered_root = recovered["tree"][0]
    if (recovered_root.get("type") == "source-block"
            and recovered_root.get("variant") == "component-master"
            and recovered_root.get("children")):
        recovered_root = recovered_root["children"][0]
    recovered_root.setdefault("sourceMeta", {})["componentRef"] = ds_compiler.component_handle(
        primary, ds_context.get("systemRef") or {})
    recovered_root["sourceMeta"].setdefault("kind", "component-instance")
    recovered.setdefault("meta", {}).update({
        "designSystemRef": ds_context.get("systemRef"),
        "compiledContextHash": (ds_compiled or {}).get("compiledContextHash"),
        "strictRecovery": "exact-master-materialized",
        "strictRecoveryReason": reason,
        "requestedComponentKey": primary.get("componentKey"),
    })
    check = ds_resolver.validate_generation(recovered, ds_context)
    return (recovered if not check["errors"] else None), check


_CONTENT_SLOT_KEYS = ("text", "title", "placeholder", "value", "label", "alt")


_CONTENT_SLOT_LIMIT = 80


def _content_slots(ir: dict) -> list[dict]:
    """Текстовые слоты точной копии мастера: {id, path, key, role, text}.

    Модель переписывает только их — структура, стили и геометрия мастера
    остаются пиннутыми (component_shape_hash игнорирует контентные ключи)."""
    slots: list[dict] = []

    def role_of(node: dict, key: str) -> str:
        if node.get("typeRole"):
            return str(node["typeRole"])
        t = str(node.get("type") or "")
        if t == "heading":
            return f"h{node.get('level') or 2}"
        if t in ("button", "badge", "input", "stat"):
            return t if key != "placeholder" else "placeholder"
        return "text"

    def walk(node, path):
        if isinstance(node, dict):
            for key in _CONTENT_SLOT_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value.strip() and len(slots) < _CONTENT_SLOT_LIMIT:
                    slots.append({"id": f"s{len(slots) + 1}", "path": f"{path}.{key}", "key": key,
                                  "role": role_of(node, key), "text": value})
            for i, child in enumerate(node.get("children") or []):
                walk(child, f"{path}.children.{i}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}.{i}")

    for i, section in enumerate(ir.get("tree") or []):
        walk(section, f"tree.{i}")
    return slots


def _content_rewrite_messages(slots: list[dict], brief: str, ds_doc: dict | None,
                              variant_index: int, count: int, rules_block: str = "") -> list[dict]:
    """Промпт «тот же мастер, другой контент»: только слоты, без IR — влезает в любой бюджет."""
    site = (ds_doc or {}).get("siteBrief") or {}
    voice = {k: site.get(k) for k in ("summary", "audience", "offer", "tone") if site.get(k)}
    system = (
        "Ты копирайтер и дизайнер интерфейсов. Тебе дан список текстовых слотов существующего компонента "
        "дизайн-системы (структура, стили и геометрия зафиксированы и меняться не будут). "
        "Перепиши тексты под бриф: тот же смысловой порядок и роли слотов, близкая длина (±30%), "
        "тот же формат чисел/валют, без плейсхолдеров и «Lorem». Язык — как в брифе, если бриф не просит иначе. "
        "Верни ТОЛЬКО JSON вида {\"slots\": [{\"id\": \"s1\", \"text\": \"...\"}, ...]} со всеми id из списка."
    )
    user = (
        f"## Бриф\n{brief}\n\n"
        + (f"## Голос сайта\n{json.dumps(voice, ensure_ascii=False)}\n\n" if voice else "")
        + (f"{rules_block}\n\n" if rules_block else "")
        + (f"Вариант {variant_index} из {count}: сделай контент отличным от других вариантов "
           f"(другие акценты/формулировки при том же смысле).\n\n" if count > 1 else "")
        + "## Слоты (id · роль · текущий текст)\n"
        + "\n".join(f"{s['id']} · {s['role']} · {json.dumps(s['text'], ensure_ascii=False)}" for s in slots)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _apply_content_answer(ir: dict, slots: list[dict], raw: str) -> tuple[dict, int, str]:
    """Применить ответ модели к копии мастера. Возвращает (ir, число заменённых слотов, ошибка)."""
    out = copy.deepcopy(ir)
    try:
        parsed = json.loads(llm.extract_json(raw or ""))
    except Exception as exc:  # noqa: BLE001 — ответ модели произвольный
        return out, 0, f"ответ не JSON: {exc}"
    items = parsed.get("slots") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return out, 0, "в ответе нет slots"
    by_id = {str(item.get("id")): item.get("text") for item in items
             if isinstance(item, dict) and isinstance(item.get("text"), str)}
    replaced = 0
    for slot in slots:
        text = by_id.get(slot["id"])
        if text is None or text == slot["text"]:
            continue
        found, container = qualitygate.get_path(out, slot["path"].rsplit(".", 1)[0])
        if found and isinstance(container, dict):
            container[slot["key"]] = text.strip()[:600]
            replaced += 1
    return out, replaced, ""


def _generate(req: GenerateReq, run_id: str | None, *, prepared: dict | None = None,
              resolved_document: dict | None = None):
    # Browser mode may explicitly select a direct API account. Codex is a
    # desktop-only transport, so unknown/desktop values fall back to ROUTING.
    # codex/claude — консольные аккаунты (cli_llm); всё остальное — Sol по ключу
    # или первый доступный CLI, если ключа нет (см. llm_client.chat_envelope).
    provider = req.provider if getattr(req, "provider", None) in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
    brief = req.brief.strip()
    if not brief:
        return err(422, "Пустой бриф: опишите, что нужно сгенерировать.")
    count = max(1, min(int(req.count or 1), 5))
    if req.rawOutputs is not None and len(req.rawOutputs) < count:
        return err(422, "Модель вернула меньше ответов, чем запрошено вариантов.")
    has_style = bool(req.styleHint and req.styleHint.strip())
    style = f"\n\n## Reference / style context\n{req.styleHint.strip()}" if has_style else ""
    memory_hint = project_store.build_prompt_memory_hint()
    memory = f"\n\n{memory_hint}" if memory_hint else ""
    mode = "edit" if has_style else "generate"
    policy_context = generator_policy.context(req.brief, surface=req.surface, style=req.designStyle,
        ds=req.designSystem, locked=bool(req.tokens), edit=mode == "edit")
    surface = policy_context["surface"]
    policy_block = generator_policy.prompt(policy_context)
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Генерация отменена")
    rules_block = project_rules.prompt_block("generation")
    reference_block = _reference_screens_block(req.referenceIrs)
    dna, complete_dna = _locked_generation_dna(req.tokens)
    preset = typography.PRESETS.get(req.preset or "")
    ptype, pinfo = designkb.detect_product(brief)
    # Шрифт из Style DNA — без подбора своей пары; иначе — библиотека typography.
    # Предпочтение: пресет → рекомендация design KB по типу продукта → настроение брифа.
    pair = None
    if not (dna and isinstance(dna.get("font"), dict)):
        pair = typography.pick_pair(
            set(preset["moods"]) if preset else typography.brief_moods(brief),
            prefer=(preset.get("font") if preset else None) or pinfo["fonts"][0])
    scale = typography.type_scale()
    if surface != "landing" and not dna:
        pair = None
    ds_doc = None

    # Design System: закрепляем ревизию на момент старта (§16.2) и строим
    # компактный контекст один раз; в промпт уходит prompt-block, не весь документ
    ds_context = None
    ds_prompt_block = ""
    ds_compiled = None
    ds_usage_mode = ""
    pinned_master_keys: list[str] = []
    ds_reference_instruction = ""
    ds_reference_candidates: list[dict] = []
    ds_reference_parts: list[dict] = []
    ds_reference_note = ""
    ds_min_font_size = 0
    ds_font_faces: list[dict] = []
    if isinstance(req.designSystem, dict) and req.designSystem.get("systemId"):
        from design_system import compiler as ds_compiler, reference_images as ds_reference_images
        from design_system import resolver as ds_resolver, store as ds_store
        ds_doc, ds_error = (resolved_document, None) if resolved_document is not None else ds_store.resolve_ref(req.designSystem)
        if ds_error:
            return err(422, f"Design System: {ds_error}")
        ds_usage_mode = str(req.designSystem.get("usageMode") or "strict")
        pinned_master_keys = _reference_pinned_component_keys(req.referenceIrs, ds_doc)
        ds_context = ds_resolver.resolve_context(
            ds_doc, brief, usage_mode=ds_usage_mode, pinned_keys=pinned_master_keys)
        if ds_usage_mode == "strict" and not ds_context.get("components"):
            return err(422, "Design System Strict: нет опубликованных мастеров для этой задачи. Используйте Extend или добавьте мастер.")
        # Strict обязан вместить exact master целой секции; extend/style-only —
        # сводки всех мастеров, ревью с DO/DON'T и декоративные сигнатуры
        # (на 1200 токенах всё это отрезалось, и модель рисовала общий шаблон).
        provider_budget = ds_compiler.default_budget(ds_usage_mode)
        ds_compiled = ds_resolver.compiled_context(
            ds_context, brief=brief,
            archetype_id=str(req.designSystem.get("archetypeId") or ""),
            token_budget=int(req.designSystem.get("tokenBudget") or provider_budget),
            pinned_keys=pinned_master_keys,
            surface=surface,
        )
        if ds_usage_mode == "strict" and not ds_compiled.get("strictReady"):
            # Пиннутый мастер (референс = мастер ДС) не влезает в бюджет промпта —
            # модель тут не нужна: отдаём точную копию мастера как вариант.
            primary = (ds_resolver.primary_component_for_brief(ds_context, brief, pinned_keys=pinned_master_keys)
                       if pinned_master_keys else None)
            recovered, recovered_check = (_materialize_exact_master(
                primary, ds_context, ds_compiled, "pinned-master-exceeds-context-budget")
                if primary is not None else (None, None))
            if recovered is None:
                return err(422, "Design System Strict: exact master не помещается в выбранный context budget. "
                                "Переключите режим ДС на Extend/Style-only или отключите ДС для этой ноды (× в строке «ДС» на ноде)")
            run_registry.stage(run_id, "design-system", "Материализую точный мастер ДС, модель переписывает контент")
            recovered = ensure_current_ir(recovered, source="generate")
            key = str(primary.get("componentKey") or "")
            # Тот же мастер — другой контент: точная копия референса как результат
            # бессмысленна, поэтому модель переписывает только текстовые слоты по брифу.
            slots = _content_slots(recovered)
            content_prompts = [_content_rewrite_messages(slots, brief, ds_doc, n + 1, count, rules_block)
                               for n in range(count)] if slots else []
            for messages in content_prompts:
                messages[0]["content"] += ("\nGenerator policy generator-design/1.0: rewrite only allowed text slots. "
                    "Do not invent ratings, customers, guarantees or prices. Preserve labels, units and the user's task. "
                    "Keep the slots output contract; masters and foundations are immutable.")
            if req.prepareOnly:
                return {
                    "variants": [recovered], "errors": [], "prompts": [{"messages": m} for m in content_prompts],
                    "contentRewrite": {"slots": len(slots), "componentKey": key},
                    "design": {"type": ptype, "label": pinfo["label"]},
                }
            variants_out, journal_lines, errors_out = [], [], []
            for n in range(count):
                if not slots:
                    variants_out.append(copy.deepcopy(recovered))
                    journal_lines.append(["у мастера нет текстовых слотов — отдана точная копия"])
                    continue
                if req.rawOutputs is not None:
                    raw = req.rawOutputs[n] if n < len(req.rawOutputs) else ""
                else:
                    run_registry.stage(run_id, "llm", f"Модель переписывает контент мастера ({n + 1}/{count})")
                    try:
                        raw = llm.chat(provider, content_prompts[n], 0.7, role="edit", reasoning_effort=effort)
                    except Exception as exc:  # noqa: BLE001
                        raw = ""
                        errors_out.append({"index": n + 1, "error": f"контент: {exc}"})
                variant, replaced, apply_error = _apply_content_answer(recovered, slots, raw)
                variant = ensure_current_ir(variant, source="generate")
                schema_errors = validate_ir(variant)
                ds_check = ds_resolver.validate_generation(variant, ds_context)
                if schema_errors or ds_check.get("errors"):
                    variant, replaced = copy.deepcopy(recovered), 0
                    apply_error = "Контент нарушил контракт мастера; сохранён исходник"
                if apply_error:
                    errors_out.append({"index": n + 1, "error": apply_error})
                variant.setdefault("meta", {})["contentRewrite"] = {"slots": len(slots), "replaced": replaced,
                                                                    **({"error": apply_error} if apply_error else {})}
                variants_out.append(variant)
                journal_lines.append([
                    f"strict: мастер «{key}» ≈{ds_compiled.get('estimatedTokens')} токенов не влезает в бюджет "
                    f"{ds_compiled.get('tokenBudget')} — точная копия мастера, модель переписала контент",
                    f"контент: заменено {replaced} из {len(slots)} слотов" + (f" ({apply_error})" if apply_error else ""),
                ])
            return {
                "variants": variants_out, "errors": errors_out, "prompts": [],
                "qa": [{"index": n + 1, "fixed": 0, "violations": generator_policy.lint(variants_out[n], "component"), "recovery": "exact-master-materialized"}
                       for n in range(len(variants_out))],
                "design": {"type": ptype, "label": pinfo["label"]},
                "generationLog": {
                    "contractVersion": agent_contract.version(),
                    "product": pinfo["label"], "mode": mode, "tokensLocked": True,
                    "projectRules": bool(rules_block),
                    "referenceScreens": len([x for x in (req.referenceIrs or []) if isinstance(x, dict)]),
                    "designSystem": {
                        "name": (ds_doc or {}).get("name") or "",
                        "systemId": (ds_context.get("systemRef") or {}).get("systemId"),
                        "revision": (ds_context.get("systemRef") or {}).get("revision"),
                        "usageMode": ds_usage_mode,
                        "componentsAvailable": len(ds_context.get("components") or []),
                        "mastersInContext": [key],
                        "strictReady": False,
                        "errors": 0, "warnings": len((recovered_check or {}).get("warnings") or []),
                        "recovered": {"componentKey": key, "reason": "pinned-master-exceeds-context-budget"},
                        "pinnedMaster": key,
                    },
                    "pinnedMaster": key,
                    "strictRecovery": "exact-master-materialized",
                    "contentRewrite": {"slots": len(slots)},
                    "variants": [{"index": n + 1, "autofixes": 0, "journal": journal_lines[n],
                                  "lint": [], "recovery": "exact-master-materialized"}
                                 for n in range(len(variants_out))],
                },
                "designSystem": {"ref": ds_context.get("systemRef"), "errors": [], "warnings": (recovered_check or {}).get("warnings") or [],
                                 "recovered": {"componentKey": key, "reason": "pinned-master-exceeds-context-budget"}},
            }
        ds_prompt_block = ds_compiled["promptBlock"]
        # ДС — источник истины и для токенов, и для атмосферы: если по порту
        # пришло что-то неполное (или ничего), лочим токены из foundations
        # документа и добавляем профиль стиля (тема, углы, плотность, голос копирайта).
        from design_system import style_review as ds_style_review
        ds_dna, ds_complete_dna = _locked_generation_dna(
            ds_style_review.ir_tokens(ds_doc.get("foundations") or {}))
        if ds_dna:
            dna, complete_dna = ds_dna, ds_complete_dna
        ds_min_font_size = ds_style_review.label_size_floor(ds_doc.get("foundations") or {})
        ds_font_faces = ds_style_review.font_faces(ds_doc)
        ds_prompt_block += "\n\n" + ds_style_review.profile_prompt(ds_doc)
        ds_prompt_block += _embed_mode_block(ds_usage_mode)
        # Визуальные референсы: блоки исходника, где живут релевантные мастера,
        # и кроп самого мастера. Кандидаты логируются всегда, картинки
        # декодируются только когда промпт действительно уходит модели.
        ds_reference_candidates = ds_reference_images.select_candidates(ds_doc, ds_context, surface=surface)
        if req.rawOutputs is None and ds_reference_candidates:
            ds_reference_parts = ds_reference_images.render(ds_doc, ds_reference_candidates)
            ds_reference_note = ds_reference_images.prompt_note(ds_reference_parts)
        if dna and dna.get("font"):
            pair = None
        if ds_usage_mode == "strict" and pinned_master_keys:
            pinned = next((component for component in ds_context.get("components") or []
                           if str(component.get("componentKey") or "") == pinned_master_keys[0]), None)
            if pinned is not None:
                from design_system import compiler as ds_compiler
                handle = ds_compiler.component_handle(pinned, ds_context.get("systemRef") or {})
                ds_reference_instruction = (
                    f"Референс — это мастер {pinned_master_keys[0]}; результат обязан быть копией этого мастера "
                    f"с componentRef {json.dumps(handle, ensure_ascii=False)}, меняй только контент."
                )

    directions: list[dict] = []
    art_direction_error = ""
    exemplars = ""
    if mode == "generate" and prepared is not None:
        directions = prepared.get("directions") or []
    elif mode == "generate" and (surface != "landing" or policy_context["foundationsLocked"]):
        directions = generator_policy.directions(policy_context)
    elif mode == "generate":
        run_registry.stage(run_id, "art-direction", "Формирую три арт-направления")
        try:
            import art_direction
            generated_directions = art_direction.create_design_brief(
                brief,
                ptype,
                style_dna={"tokens": dna, "designSystem": req.designSystem,
                           "policyHash": policy_context["policyHash"], "surface": surface, "style": req.designStyle},
                provider=provider,
                count=3,
                generate_if_missing=req.rawOutputs is None,
            )
            if isinstance(generated_directions, list):
                directions = generated_directions
        except Exception as exc:
            # Art direction raises the quality ceiling but is deliberately not
            # a dependency: provider/cache failures keep generation available.
            art_direction_error = str(exc)
    if mode == "generate" and surface == "landing" and not ds_context:
        exemplars = llm.load_exemplars(ptype, limit=2)

    public_directions = [
        {key: item[key] for key in ("id", "label", "motivation", "tradeoff")}
        for item in directions
    ]
    requested_direction = str(req.selectedDirection or "all")
    chosen_direction = next(
        (item for item in directions if str(item.get("id")) == requested_direction),
        None,
    )
    selected_direction = requested_direction if chosen_direction is not None else "all"

    def direction_for(n: int) -> dict | None:
        if chosen_direction is not None:
            return chosen_direction
        return directions[(n - 1) % len(directions)] if directions else None

    def call_context_llm(user_content, direction: dict | None):
        """user_content — строка или части OpenAI-формата (текст + image_url референсы ДС)."""
        pending_chars = 0

        def on_delta(delta: str) -> None:
            nonlocal pending_chars
            if run_registry.is_cancelled(run_id):
                raise RuntimeError("cancelled")
            pending_chars += len(delta)
            if pending_chars >= 512:
                run_registry.add_received_chars(run_id, pending_chars)
                pending_chars = 0

        try:
            raw = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt(
                    mode,
                    design_brief=(direction or {}).get("designBrief") or (direction or {}).get("plan") or "",
                    exemplars=exemplars,
                    policy=policy_block + "\n\n" + ds_prompt_block,
                )},
                {"role": "user", "content": user_content},
            ], 0.8 if mode == "generate" else 0.3,
                role="generator" if mode == "generate" else "edit",
                reasoning_effort=effort, on_delta=on_delta)
        except Exception as exc:
            return None, str(exc)
        finally:
            run_registry.add_received_chars(run_id, pending_chars)
        return parse_ir_response(raw)


    def gen_one(n: int):
        variant_direction = direction_for(n)
        variant_pair = pair
        if not dna and not ds_context:
            pair_name = ((variant_direction or {}).get("designBrief") or {}).get("typePair")
            variant_pair = typography.PAIRS_BY_NAME.get(pair_name, pair)
        if mode == "edit":
            user = (
                f"## Reference context\n{req.styleHint.strip()}\n\n"
                f"## Modification instruction\n{brief}\n\n"
                f"REPRODUCE the reference structure and content EXACTLY. "
                f"Apply ONLY the modification above. Do NOT add or remove sections/elements. "
                f"Do NOT invent content not present in the reference."
            )
        else:
            vary = ("своя композиция и раскладка в рамках токенов DNA; настроение, "
                    "тема и характер ИСХОДНИКА сохраняются" if dna
                    else "своя палитра, типографика, настроение и композиция")
            user = (
                f"## Brief\n{brief}\n\n"
                f"Вариант {n} из {count}: сделай визуально отличное решение №{n} — "
                f"{vary}, не повторяй другие варианты."
            )
        if mode == "generate" and variant_direction:
            user += (
                "\n\n## Assigned art direction\n"
                f"ID: {variant_direction['id']}\n"
                f"Label: {variant_direction['label']}\n"
                f"Motivation: {variant_direction['motivation']}\n"
                f"Tradeoff: {variant_direction['tradeoff']}\n"
                "Follow this direction consistently; do not substitute another direction."
            )
        if req.seedTag:
            user += f"\nseedTag: {req.seedTag}"
        if style and mode != "edit":
            user += style
        if memory:
            user += memory
        if dna:
            user += ("\n\n## Locked Style DNA\n" + json.dumps(dna, ensure_ascii=False)
                     + "\nUse these foundations exactly. Preserve the supplied theme, typography, radii and spacing. "
                       "Use semantic color roles according to their purpose. Component masters take precedence over "
                       "generic token application. Do not force alternating backgrounds, border widths or an accent "
                       "that the supplied system does not prescribe. Images need a concrete imagePrompt.")
        elif variant_pair and not ds_context:
            user += "\n\n" + typography.typography_guide(variant_pair, scale, preset)
        palette = None
        # The surface recipe replaces unconditional landing/palette/anti-font defaults.
        user += "\nApply the system's selected surface recipe and locked foundations."
        if mode == "generate":
            user += _TYPE_ROLE_RULE
        if reference_block:
            user += "\n\n" + reference_block
        if ds_prompt_block:
            user += "\n\n" + ds_prompt_block
        if ds_reference_instruction:
            user += "\n\n" + ds_reference_instruction
        if rules_block:
            user += "\n\n" + rules_block
        if ds_reference_note:
            user += "\n\n" + ds_reference_note
        content = ([{"type": "text", "text": user}, *(item["part"] for item in ds_reference_parts)]
                   if ds_reference_parts else user)
        if req.prepareOnly:
            return content, None, None
        if run_registry.is_cancelled(run_id):
            return None, "cancelled", None
        if req.rawOutputs is not None:
            run_registry.stage(run_id, "parse", "Разбираю ответ модели")
            ir, error = parse_ir_response(req.rawOutputs[n - 1])
        else:
            run_registry.stage(run_id, "llm", f"Модель генерирует IR ({count} вар.)" if count > 1 else "Модель генерирует IR")
            ir, error = call_context_llm(content, variant_direction)
            run_registry.stage(run_id, "validate", "Проверка схемы и автофиксы")
        qa = None
        if ir is not None:
            ir = sanitize_generated_ir(ir)
            if ds_font_faces:
                # Шрифты системы (включая моно для лейблов) — в meta.fontFaces:
                # DS-lint признаёт их своими, рендер и редактор грузят файлы.
                meta = ir.get("meta")
                if not isinstance(meta, dict):
                    meta = ir["meta"] = {}
                meta["fontFaces"] = ds_style_review.merge_font_faces(meta.get("fontFaces"), ds_font_faces)
            # A model can return a schema-valid refusal as empty composition frames.
            # It is not a generated design and must not enter previews or Quality Pass.
            def empty_composition(node):
                if not isinstance(node, dict) or node.get("type") not in {"composition", "frame"}:
                    return False
                props, style = node.get("props") or {}, node.get("style") or {}
                if any(props.get(key) for key in ("heading", "title", "text", "subheading")):
                    return False
                if any(style.get(key) not in (None, "", "none", "transparent") for key in ("background", "backgroundColor", "backgroundImage", "borderColor", "boxShadow")):
                    return False
                return all(empty_composition(child) for child in node.get("children", []))
            if not ir.get("tree") or all(empty_composition(root) for root in ir["tree"]):
                return None, "Модель вернула пустой макет. Проверьте промпт и приложенный референс и повторите запуск.", None
            if variant_direction:
                ir.setdefault("meta", {})["direction"] = {
                    "name": str(variant_direction["label"])[:60],
                    "motivation": str(variant_direction["motivation"])[:200],
                    "tradeoff": str(variant_direction["tradeoff"])[:200],
                }
            if dna:
                # Give QA the locked palette first; inline styles are applied
                # after autofix so QA cannot silently overwrite the DNA lock.
                ir["tokens"] = copy.deepcopy(complete_dna or dna)
            elif isinstance(ir.get("tokens"), dict):
                # без DNA: шрифтовая пара и кураторская палитра из design KB — лок
                if variant_pair:
                    ir["tokens"]["font"] = typography.font_tokens(variant_pair)
                if palette:
                    ir["tokens"]["color"] = dict(palette)
            # сгенерированный IR — responsive-документ: вьюпорты артборда, чтобы
            # Page/редактор переключали устройства и per-device правки имели куда писаться
            ir.setdefault("responsive", {"viewports": {
                "desktop": {"width": 1440, "height": 900},
                "tablet": {"width": 768, "height": 1024},
                "mobile": {"width": 390, "height": 844}}})
            # авто quality-gate: детерминированный autofix (контраст/сетка/overflow,
            # DS-lint: цвета/шрифты/роли — в strict ДС цвета снапятся к токенам всегда)
            protected_masters = ds_usage_mode == "strict" or generator_policy.has_masters(ir)
            if protected_masters:
                fixlog = []  # Exact masters are validated, never snapped/reflowed by generic fixes.
            else:
                fix_rules = [r for r in qualitygate.RULES
                             if r["id"] not in {"grid-8"} and not (surface == "component" and r["id"] in {"single-h1", "frame-overflow"})]
                if ds_min_font_size:
                    # Дизайн-система с 9–11px моно-лейблами: стандартный порог 12px
                    # ломал её labelStyle сразу после генерации.
                    fix_rules = [qualitygate.min_font_rule(ds_min_font_size) if r["id"] == "min-font-size" else r
                                 for r in fix_rules]
                ir, fixlog = qualitygate.autofix(ir, rules=fix_rules)
            if dna and not protected_masters:
                # Deterministically update model-provided inline styles. Without
                # this, a black button from the LLM overrides primary in renderer.
                ir = bind_ir_element_styles(ir, complete_dna or dna)
                ir = apply_ir_tokens(ir, complete_dna or dna)
            lint = generator_policy.lint(ir, surface, locked=bool(dna))
            qa = {"index": n, "fixed": len(fixlog),
                  "violations": [v["rule"] for v in lint],
                  "lint": [{"rule": v["rule"], "severity": v.get("severity"), "path": v.get("path"),
                            "message": v.get("message")} for v in lint][:24],
                  "journal": fixlog[:24]}
            ir = ensure_current_ir(ir, source="generate")
            schema_errors = validate_ir(ir)
            if schema_errors:
                return None, "Generated IR does not pass schema: " + "; ".join(schema_errors[:5]), qa
        return ir, error, qa

    if req.prepareOnly:
        prepared_directions = [direction_for(i + 1) for i in range(count)]
        return {
            "prompts": [
                {"messages": [
                    {"role": "system", "content": llm.build_system_prompt(
                        mode,
                        design_brief=(prepared_directions[i] or {}).get("designBrief") or (prepared_directions[i] or {}).get("plan") or "",
                        exemplars=exemplars,
                        policy=policy_block + "\n\n" + ds_prompt_block,
                    )},
                    {"role": "user", "content": gen_one(i + 1)[0]},
                ]}
                for i in range(count)
            ],
            "design": {"type": ptype, "label": pinfo["label"]},
            "directions": public_directions,
            "variantDirections": [item["label"] if item else "" for item in prepared_directions],
            "designBrief": ((prepared_directions[0] or {}).get("designBrief")
                            if prepared_directions else None),
            "designBriefs": [(item or {}).get("designBrief") for item in prepared_directions],
            "_directionRecords": directions,
            **({"designSystem": {"ref": ds_context.get("systemRef"), **ds_compiled}}
               if ds_context is not None and ds_compiled else {}),
        }

    # copy_context: contextvar-токен отмены десктопного воркера (cancel_token)
    # иначе не виден в потоках пула — LLM-вызовы дорабатывали бы после отмены.
    futures = [common.EXECUTOR.submit(contextvars.copy_context().run, gen_one, i + 1) for i in range(count)]
    variants, errors, qa = [], [], []
    for i, f in enumerate(futures):
        ir, error, q = f.result()
        if ir is not None:
            variants.append(ir)
            qa.append(q)
        else:
            errors.append({"index": i + 1, "error": error})
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Генерация отменена")
    if not variants and not (ds_usage_mode == "strict" and ds_context is not None):
        return err(502, f"Ни один вариант не сгенерирован. {errors[0]['error'] if errors else ''}")
    run_registry.stage(run_id, "design-system", "Проверка дизайн-системы и сборка ответа")
    design_system_report = None
    strict_fallback = ""
    if ds_context is not None:
        from design_system import resolver as ds_resolver
        design_system_report = {"errors": [], "warnings": []}
        accepted_variants = []
        strict_candidate_variants = list(variants)
        for variant_index, variant in enumerate(variants, start=1):
            check = ds_resolver.validate_generation(variant, ds_context)
            if check["errors"] or check["warnings"]:
                variant.setdefault("meta", {})
                if check["errors"]:
                    variant["meta"]["designSystemErrors"] = check["errors"]
                if check["warnings"]:
                    variant["meta"]["designSystemWarnings"] = check["warnings"]
            if ds_compiled:
                variant.setdefault("meta", {})
                variant["meta"].update({
                    "designSystemRef": ds_context.get("systemRef"),
                    "compiledContextHash": ds_compiled.get("compiledContextHash"),
                    "archetypeId": ds_compiled.get("archetypeId"),
                    "identityScore": (check.get("identity") or {}).get("score"),
                    "identityReport": check.get("identity"),
                })
            design_system_report["errors"].extend(check["errors"])
            design_system_report["warnings"].extend(check["warnings"])
            if ds_usage_mode == "strict" and check["errors"]:
                errors.append({
                    "index": variant_index,
                    "error": "Design System Strict: " + "; ".join(item["message"] for item in check["errors"][:4]),
                })
            else:
                accepted_variants.append(variant)
        design_system_report["ref"] = ds_context.get("systemRef")
        if ds_compiled:
            design_system_report.update({
                "compiledContextHash": ds_compiled.get("compiledContextHash"),
                "includedRuleIds": ds_compiled.get("includedRuleIds"),
                "omittedRuleIds": ds_compiled.get("omittedRuleIds"),
                "estimatedTokens": ds_compiled.get("estimatedTokens"),
                "archetypeId": ds_compiled.get("archetypeId"),
            })
        if ds_usage_mode == "strict":
            variants = accepted_variants
            if not variants:
                # A large observed master (for example a responsive service card
                # with lossless image evidence) may not fit the provider prompt
                # budget. The provider still interprets the brief, while the
                # application owns exact-master materialisation and verification.
                primary = ds_resolver.primary_component_for_brief(
                    ds_context, brief, pinned_keys=pinned_master_keys)
                if primary is not None:
                    recovered, recovered_check = _materialize_exact_master(
                        primary, ds_context, ds_compiled, "provider-output-failed-strict-exact-master-validation")
                    if recovered is not None:
                        variants = [recovered]
                        qa.append({"index": 1, "fixed": 1, "violations": [],
                                   "recovery": "exact-master-materialized"})
                        design_system_report["recovered"] = {
                            "componentKey": primary.get("componentKey"),
                            "reason": "provider-output-failed-strict-exact-master-validation",
                        }
                if not variants and strict_candidate_variants and req.allowStrictFallback:
                    strict_fallback = "extend"
                    fallback_warning = {
                        "code": "strict-fallback-extend",
                        "message": "Strict: мастера не использованы, результат принят в режиме extend",
                    }
                    for variant in strict_candidate_variants:
                        meta = variant.setdefault("meta", {})
                        meta.pop("designSystemErrors", None)
                        meta.setdefault("designSystemWarnings", []).append(fallback_warning)
                    variants = strict_candidate_variants
                    errors = [item for item in errors
                              if not str(item.get("error") or "").startswith("Design System Strict:")]
                    rejected = list(design_system_report["errors"])
                    design_system_report["errors"] = []
                    design_system_report["warnings"].extend(rejected)
                    design_system_report["warnings"].append(fallback_warning)
                if not variants:
                    first = design_system_report["errors"][0]["message"] if design_system_report["errors"] else "strict validation failed"
                    return err(422, f"Design System Strict отклонил все варианты: {first}")
    # Журнал решений: что агент получил и что проверил — вместо чёрного ящика.
    generation_log = {
        "contractVersion": agent_contract.version(),
        "product": pinfo["label"],
        "mode": mode,
        "tokensLocked": bool(dna),
        "projectRules": bool(rules_block),
        "referenceScreens": len([x for x in (req.referenceIrs or []) if isinstance(x, dict)]),
        **({"strictFallback": strict_fallback} if strict_fallback else {}),
        "direction": {
            "selected": selected_direction,
            "variants": [
                (variant.get("meta") or {}).get("direction", {}).get("name", "")
                for variant in variants
            ],
            "degraded": not bool(directions),
            **({"error": art_direction_error} if art_direction_error else {}),
        },
        "designSystem": ({
            "name": (ds_doc or {}).get("name") or "",
            "systemId": (ds_context.get("systemRef") or {}).get("systemId"),
            "revision": (ds_context.get("systemRef") or {}).get("revision"),
            "usageMode": ds_usage_mode,
            "componentsAvailable": len(ds_context.get("components") or []),
            "mastersInContext": list((ds_compiled or {}).get("includedMasterKeys") or []),
            "summariesInContext": list((ds_compiled or {}).get("summarizedMasterKeys") or []),
            "decorSignatures": list((ds_compiled or {}).get("decorSignatureIds") or []),
            "archetypeSelection": (ds_compiled or {}).get("archetypeSelection"),
            "archetypeIds": list((ds_compiled or {}).get("archetypeIds") or []),
            "estimatedTokens": (ds_compiled or {}).get("estimatedTokens"),
            "tokenBudget": (ds_compiled or {}).get("tokenBudget"),
            "referenceImages": ds_reference_images.describe(
                ds_reference_candidates, ds_reference_parts if req.rawOutputs is None else None),
            "pinnedMaster": pinned_master_keys[0] if pinned_master_keys else None,
            "strictReady": (ds_compiled or {}).get("strictReady"),
            "errors": len((design_system_report or {}).get("errors") or []),
            "warnings": len((design_system_report or {}).get("warnings") or []),
            "recovered": (design_system_report or {}).get("recovered"),
        } if ds_context is not None else None),
        "variants": [{
            "index": q.get("index"),
            "autofixes": q.get("fixed", 0),
            "journal": q.get("journal") or [],
            "lint": q.get("lint") or [],
            "recovery": q.get("recovery"),
        } for q in qa],
    }
    return {"variants": variants, "errors": errors, "qa": qa,
            "design": {"type": ptype, "label": pinfo["label"]},
            "directions": public_directions,
            "variantDirections": [
                (variant.get("meta") or {}).get("direction", {}).get("name", "")
                for variant in variants
            ],
            "generationLog": generation_log,
            **({"designSystem": design_system_report} if design_system_report else {})}


@router.post("/api/mix")
def mix(req: MixReq):
    irs, weights = req.irs, [float(w) for w in req.weights]
    if not irs:
        return err(422, "Нужен хотя бы один IR для микса.")
    if len(irs) != len(weights):
        return err(422, "Количество IR и весов не совпадает.")
    if any(w < 0 for w in weights):
        return err(422, "Веса должны быть >= 0.")

    dom = max(range(len(irs)), key=lambda i: weights[i])  # при всех нулях -> 0
    result = copy.deepcopy(irs[dom])
    if not isinstance(result, dict):
        return err(422, f"IR #{dom + 1} не является объектом.")
    result_colors = result.setdefault("tokens", {}).setdefault("color", {})

    # цвета — взвешенный микс в OKLCH
    for key in COLOR_TOKEN_KEYS:
        pairs = [(ir["tokens"]["color"][key], weights[i])
                 for i, ir in enumerate(irs)
                 if isinstance(ir, dict) and key in ir.get("tokens", {}).get("color", {})]
        if pairs:
            result_colors[key] = mix_hex_colors(pairs)

    meta = result.setdefault("meta", {})
    if "name" in meta:
        meta["name"] = f"{meta['name']} (mix)"
    meta["mixOf"] = [{"index": i, "weight": weights[i]} for i in range(len(irs))]
    return {"ir": ensure_current_ir(result, source="mix")}


@router.post("/api/clone")
def clone(req: CloneReq):
    """Клонирование компонента с внешнего сайта: fetch HTML → LLM → IR."""
    url = req.url.strip()
    component = req.component.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    if not component:
        return err(422, "Опишите, какой компонент клонировать.")
    provider = "auto"  # вся цепочка ROUTING подключённых аккаунтов

    # SSRF-гард: только публичные http/https URL
    try:
        validate_public_url(url)
    except ValueError as e:
        return err(422, str(e))

    # кэш: тот же сайт повторно — без траты токенов
    hit = cache_store.get("clone_url", cache_store.key_url(url))
    if hit:
        return {**hit, "cached": True}

    # fetch страницы: redirect-ы валидируются пошагово, body ограничен
    try:
        response = fetch_public_bytes(
            url,
            timeout=15,
            max_bytes=MAX_CLONE_HTML_BYTES,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,en;q=0.9",
            },
        )
        html = response.content.decode("utf-8", errors="replace")
    except Exception as e:
        return err(502, f"Не удалось загрузить {url}: {e}")

    # извлекаем стили и body (обрезаем до 12000 символов чтобы уложиться в контекст)
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))[:6000]
    body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)  # убираем скрипты
    body = re.sub(r"\s+", " ", body)[:12000]

    user = (
        "Ты — senior фронтенд-разработчик и дизайн-инженер. Тебе дали HTML+CSS реальной страницы.\n"
        f"Задача: выделить компонент «{component}» из этой страницы и представить его как Design IR (JSON).\n\n"
        "ПРАВИЛА:\n"
        "- Воспроизведи структуру компонента ТОЧНО: те же элементы, тот же порядок, тот же текст.\n"
        "- НЕ добавляй элементы, которых нет в HTML.\n"
        "- НЕ убирай элементы из HTML.\n"
        "- Тексты — verbatim из HTML (не перефразируй).\n"
        "- Цвета/шрифты/радиусы — извлеки из CSS и запиши в tokens.\n"
        "- Раскладку (flex/grid/позиции) — передай через frame (layout/direction/gap/padding).\n"
        "- Верни ОДИН JSON-объект по схеме Design IR. Без markdown.\n\n"
        f"## CSS стили\n{styles}\n\n## HTML страницы\n{body}"
    )
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.2, role="clone")
    except Exception as e:
        return err(502, str(e))
    ir, error = parse_ir_response(raw)
    if ir is None:
        return err(502, error)
    errors = validate_ir(ir)
    if errors:
        # repair
        repair = (
            "Следующий JSON не прошёл валидацию. Ошибки:\n- " + "\n- ".join(errors[:8]) +
            "\n\nИсправь минимально и верни только JSON:\n\n" + json.dumps(ir, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair", reasoning_effort=req.effort if req.effort in ("medium", "high", "max") else "medium")
            ir2, _ = parse_ir_response(raw2)
            if ir2 and not validate_ir(ir2):
                ir = ir2
        except Exception:
            pass
    cache_store.put("clone_url", cache_store.key_url(url), {"ir": ir})
    return {"ir": ensure_current_ir(ir, source="clone"), "cached": False}


# человекочитаемые категории маски для промпта Reskin
_MASK_LABELS = {
    "colors": "цвета (tokens.color, tokens.mode) и fill элементов",
    "fonts": "шрифты (tokens.font: family/weight/scale)",
    "radii": "радиусы (tokens.radius)",
    "shadows": "тени (tokens.shadow)",
    "texts": "тексты в props (заголовки, подписи, кнопки)",
    "images": "изображения (src/imagePrompt/alt/aspect)",
}


@router.post("/api/reskin")
def reskin(req: ReskinReq):
    """Reskin: AI-рестайл блока с локом структуры.

    LLM (Sol по ключу или консольный аккаунт Codex/Claude) → детерминированный merge-back
    (залоченные поля принудительно из входного IR) → валидация по схеме →
    один repair-вызов по существующему паттерну. Дрейф структуры невозможен.
    """
    errors = validate_ir(sanitize_font_face_weights(req.ir))
    if errors:
        return err(422, "Входной IR невалиден: " + "; ".join(errors[:5]))

    mask = mergeback.normalize_mask(req.mask)
    if not any(mask.values()):
        return {"ir": req.ir,
                "log": ["пустая маска: возвращён входной IR без LLM-вызова"]}

    allowed = "\n".join(f"- {label}" for key, label in _MASK_LABELS.items() if mask[key])
    user = (
        "Ты — дизайн-инженер. Ниже — Design IR блока и источник нового стиля.\n"
        "Верни ПОЛНЫЙ Design IR того же блока в новом стиле: один JSON по схеме, без markdown.\n\n"
        "ЖЁСТКИЕ ОГРАНИЧЕНИЯ (проверяются программой, нарушения будут отброшены):\n"
        "- структура дерева НЕ меняется: те же секции и элементы, id, типы, порядок, вложенность;\n"
        "- frame (геометрия и раскладка) НЕ меняется;\n"
        "- props-разметка (состав ключей, варианты, ссылки, иконки) НЕ меняется;\n"
        f"- менять разрешено ТОЛЬКО:\n{allowed}\n\n"
        f"## Входной Design IR\n{json.dumps(req.ir, ensure_ascii=False)}"
    )
    if req.tokens:
        user += f"\n\n## Design-токены нового стиля (источник)\n{json.dumps(req.tokens, ensure_ascii=False)}"
    if req.prompt.strip():
        user += f"\n\n## Пожелания по новому стилю\n{req.prompt.strip()}"

    ds_context = None
    ds_compiled = None
    ds_usage_mode = ""
    if isinstance(req.designSystem, dict) and req.designSystem.get("systemId"):
        from design_system import resolver as ds_resolver, store as ds_store
        ds_doc, ds_error = ds_store.resolve_ref(req.designSystem)
        if ds_error:
            return err(422, f"Design System: {ds_error}")
        ds_usage_mode = str(req.designSystem.get("usageMode") or "strict")
        ds_context = ds_resolver.resolve_context(
            ds_doc, req.prompt, usage_mode=ds_usage_mode)
        from design_system import compiler as ds_compiler
        ds_compiled = ds_resolver.compiled_context(
            ds_context, brief=req.prompt,
            archetype_id=str(req.designSystem.get("archetypeId") or ""),
            token_budget=int(req.designSystem.get("tokenBudget") or ds_compiler.default_budget(ds_usage_mode)),
        )
        if ds_usage_mode == "strict" and not ds_compiled.get("strictReady"):
            return err(422, "Design System Strict: exact master не помещается в выбранный context budget. Переключите режим ДС на Extend/Style-only или отключите ДС для этой ноды (× в строке «ДС» на ноде)")
        user += "\n\n" + ds_compiled["promptBlock"]

    # codex/claude — консольные аккаунты (cli_llm); всё остальное — Sol по ключу
    # или первый доступный CLI, если ключа нет (см. llm_client.chat_envelope).
    provider = req.provider if getattr(req, "provider", None) in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
    reskin_messages = [
        {"role": "system", "content": llm.build_system_prompt("edit")},
        {"role": "user", "content": user},
    ]
    # Desktop executes the prepared prompt through the fixed Sol route.
    if req.prepareOnly:
        return {"prompts": [{"messages": reskin_messages}]}
    try:
        raw = req.rawOutput if req.rawOutput else llm.chat(
            provider, reskin_messages, 0.7, role="reskin", reasoning_effort=effort)
    except Exception as e:
        return err(502, str(e))
    model_ir, parse_error = parse_ir_response(raw)
    if model_ir is None:
        return err(502, parse_error)

    # детерминированный merge-back: залоченные поля — из входа, попытки в журнал
    merged, journal = mergeback.merge_back(req.ir, model_ir, mask)
    errors = validate_ir(merged)
    if errors:
        # один repair-вызов; после repair — повторный merge-back
        repair = (
            "Следующий JSON не прошёл валидацию по схеме. Ошибки:\n- " + "\n- ".join(errors[:10]) +
            "\n\nИсправь минимально и верни только исправленный JSON:\n\n" +
            json.dumps(merged, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair")
            ir2, _ = parse_ir_response(raw2)
            if ir2 is not None:
                merged2, journal2 = mergeback.merge_back(req.ir, ir2, mask)
                if not validate_ir(merged2):
                    merged, journal, errors = merged2, journal + journal2, []
        except Exception:
            pass
    if errors:
        return err(502, "reskin не прошёл валидацию после repair: " + "; ".join(errors[:5]))
    current = ensure_current_ir(merged, source="reskin")
    design_system_report = None
    if ds_context is not None:
        from design_system import resolver as ds_resolver
        design_system_report = ds_resolver.validate_generation(current, ds_context)
        if ds_usage_mode == "strict" and design_system_report["errors"]:
            return err(
                422,
                "Design System Strict отклонил reskin: "
                + "; ".join(item["message"] for item in design_system_report["errors"][:4]),
            )
        current.setdefault("meta", {}).update({
            "designSystemRef": ds_context.get("systemRef"),
            "compiledContextHash": (ds_compiled or {}).get("compiledContextHash"),
            "archetypeId": (ds_compiled or {}).get("archetypeId"),
            "identityScore": (design_system_report.get("identity") or {}).get("score"),
            "identityReport": design_system_report.get("identity"),
        })
    return {"ir": current, "log": journal,
            **({"designSystem": design_system_report} if design_system_report else {})}
