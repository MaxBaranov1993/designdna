"""AI-починка мастеров, отклонённых ревью: цикл диагноз → правка → пересуд.

`master_review` находит РЕАЛЬНЫЕ дефекты реконструкции («яркая рамка там, где в
оригинале она почти не видна», «фон компонента темнее — потеряна полупрозрачная
поверхность», «фрагмент текста белый жирный вместо серого обычного»). Раньше
такой мастер оставался на ревью и ждал человека. Здесь его чинит второй агент:
он видит те же две картинки, список узлов мастера с их текущими визуальными
стилями и дефекты судьи — и предлагает точечные правки визуальных каналов.

Границы намеренно узкие и совпадают с `fidelity_repair`: только
``restore-style`` по СУЩЕСТВУЮЩЕМУ ``sourceKey``, только визуальные каналы
(цвета с альфой, рамки, тени, вес, трекинг, прозрачность). Геометрия измерена
браузером и не обсуждается; текст и состав узлов не меняются вообще — иначе это
уже не точная копия источника, а рисунок по мотивам.

Каждый раунд замкнут на того же судью, что вынес отказ: правка применяется к
КОПИИ masterIr, копия рендерится и снова оценивается vision-ревью. Мастер
переезжает в реестр только после одобрения; ухудшившая оценку правка
откатывается.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
from typing import Any, Callable

from .document import canonical_json, content_hash

REPAIR_SYSTEM = (
    "You repair a reconstructed design-system component so that it matches the ORIGINAL website "
    "component pixel for pixel. You are given the original crop, the current render and the list of "
    "the master's nodes with their current visual styles. Fix ONLY the defects the reviewer listed, "
    "by restoring visual channels: colors (hex, 8 digits when the original is translucent), border "
    "color and width, shadows, font weight, letter spacing, opacity. Never touch text, sizes, "
    "the set of nodes. Layout defects may use restore-layout for width, height, x, y, gap or padding, "
    "within 20 percent of the measured value and inside the component bounds. Return ONE JSON object "
    "with an \"operations\" array and no prose."
)

# Каналы поверх набора fidelity_repair: поверхность и рамка компонента — ровно
# те места, где теряется полупрозрачность источника (бледная рамка становится
# яркой, тёмная стеклянная подложка — плоской).
EXTRA_STYLE_PROPS = {"background", "borderColor", "borderWidth"}
COLOR_PROPS = {"color", "background", "borderColor"}
# Стилевой срез узла в промпте: то, что агент вправе менять и что объясняет
# типичные дефекты ревью.
STYLE_SUMMARY_PROPS = ("color", "background", "borderColor", "borderWidth", "boxShadow",
                       "fontWeight", "letterSpacing", "opacity")
# Диапазоны из schema/design-ir.schema.json (elementStyle): правка не должна
# делать IR невалидным.
NUMERIC_LIMITS = {
    "opacity": (0.0, 1.0),
    "fontWeight": (100.0, 900.0),
    "letterSpacing": (-20.0, 100.0),
    "borderRadius": (0.0, 1000.0),
    "borderWidth": (0.0, 64.0),
}
# 6 или 8 hex-цифр: альфа обязательна, иначе полупрозрачные поверхности и рамки
# источника невозможно восстановить.
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
MAX_OPERATIONS = 12
MAX_PROMPT_NODES = 40
LAYOUT_PROPS = {"width", "height", "x", "y", "gap", "padding"}


def _fidelity_repair():
    """`fidelity_repair` лежит в корне app/ — импорт ленивый, как у остального пакета."""
    import fidelity_repair

    return fidelity_repair


def repairable_props() -> set[str]:
    """Словарь правок: набор fidelity_repair плюс поверхность/рамка компонента."""
    return set(_fidelity_repair().REPAIRABLE_STYLE_PROPS) | EXTRA_STYLE_PROPS


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def describe_nodes(master_ir: dict, limit: int = MAX_PROMPT_NODES) -> list[dict]:
    """Компактный список узлов мастера: адрес правки + текущие визуальные каналы."""
    nodes: list[dict] = []
    for node in _walk((master_ir or {}).get("tree") or []):
        source_key = str(node.get("sourceKey") or "")
        if not source_key:
            continue
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        entry: dict[str, Any] = {"sourceKey": source_key, "type": str(node.get("type") or "")}
        text = " ".join(str(node.get("text") or "").split())
        if text:
            entry["text"] = text[:240]
        entry["style"] = {prop: style[prop] for prop in STYLE_SUMMARY_PROPS if style.get(prop) is not None}
        entry["size"] = {
            "width": round(float(frame.get("width") or 0), 1),
            "height": round(float(frame.get("height") or 0), 1),
        }
        # Layout repairs are bounded against these measured values. The model
        # must not guess x/y/gap/padding from a screenshot or confuse viewports.
        entry["frame"] = {prop: copy.deepcopy(frame[prop]) for prop in
                          ("x", "y", "width", "height", "layout", "gap", "padding") if prop in frame}
        entry["responsive"] = {vp: copy.deepcopy(value) for vp, value in
                               (node.get("responsive") or {}).items()
                               if vp in ("desktop", "tablet", "mobile") and isinstance(value, dict)}
        nodes.append(entry)
        if len(nodes) >= max(1, int(limit)):
            break
    return nodes


def build_repair_prompt(comp: dict, verdict: dict, viewport: str, nodes: list[dict]) -> str:
    """Промпт починки: дефекты судьи, обе картинки и адресуемые узлы мастера."""
    defects = [
        f"{d.get('severity') or 'minor'}: {d.get('what')}" + (f" ({d['where']})" if d.get("where") else "")
        for d in (verdict.get("defects") or []) if isinstance(d, dict) and d.get("what")
    ] or [" ".join(str(verdict.get("summary") or "the render differs from the original").split())]
    payload = {
        "nodes": nodes,
        "allowedProperties": sorted(repairable_props()),
        "previousRepairRejections": ((comp.get("fidelity") or {}).get("aiReview") or {}).get("previousRepairRejections", []),
        "output": {"operations": [{
            "op": "restore-style",
            "sourceKey": "<sourceKey from nodes above>",
            "property": "<one of allowedProperties>",
            "value": "#rrggbb or #rrggbbaa for colors, a CSS string for shadows, a number for "
                     "borderWidth/fontWeight/letterSpacing/opacity",
        }]},
    }
    payload["output"]["layoutOperation"] = {
        "op": "restore-layout", "sourceKey": "<sourceKey from nodes above>",
        "property": "width|height|x|y|gap|padding", "value": "number or four-number padding",
    }
    return (
        f"Component: {comp.get('name') or comp.get('componentKey')} "
        f"({comp.get('category') or 'component'}), viewport {viewport}.\n"
        "Image 1 = ORIGINAL crop from the site screenshot. Image 2 = current RENDER of the "
        "reconstructed master.\n"
        "Defects found by the reviewer:\n- " + "\n- ".join(defects) + "\n"
        "Hard rules: change visual channels, or use restore-layout only for a listed layout defect. "
        "Layout values stay within +/-20% and inside component bounds; never change sizes or positions "
        "except through a validated restore-layout operation. Never change text, never add "
        "or remove nodes, never invent a sourceKey. Use an 8-digit hex when the "
        "original channel is translucent. Emit only the operations needed to fix the listed defects.\n"
        f"Master nodes and their current styles:\n{json.dumps(payload, ensure_ascii=False)}\n"
        "If previousRepairRejections are supplied, address those validation failures; do not repeat the rejected repair. "
        "Answer with ONE JSON object and nothing else."
    )


def _clean_value(prop: str, value: Any) -> Any:
    if prop in NUMERIC_LIMITS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        low, high = NUMERIC_LIMITS[prop]
        number = max(low, min(high, float(value)))
        return int(round(number)) if prop == "fontWeight" else number
    text = str(value or "").strip()
    if not text:
        return None
    if prop in COLOR_PROPS:
        # Цвет — только hex (6 или 8 цифр): ровно то, что принимает elementStyle.
        return text.lower() if HEX_COLOR.match(text) else None
    if not _fidelity_repair()._SAFE_CSS_VALUE.match(text):
        return None
    return text


def validate_operations(parsed: Any, ir: dict) -> list[dict]:
    """Строгая валидация ответа: restore-style по существующим узлам, без геометрии.

    Расширяет валидатор `fidelity_repair`: цвета принимают альфу (8 hex-цифр),
    borderWidth — число. Всё остальное (неизвестный sourceKey, свойства кадра,
    операции над структурой) молча отбрасывается.
    """
    if not isinstance(parsed, dict):
        raise ValueError("repair response must be a JSON object")
    raw_ops = parsed.get("operations")
    if not isinstance(raw_ops, list):
        raise ValueError("operations must be a list")
    allowed = repairable_props()
    known_nodes: dict[str, dict] = {}
    parents: dict[str, dict | None] = {}
    def index_nodes(nodes: Any, parent: dict | None = None) -> None:
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            source_key = str(node.get("sourceKey") or "")
            if source_key:
                known_nodes[source_key] = node; parents[source_key] = parent
            index_nodes(node.get("children"), node)
    index_nodes((ir or {}).get("tree") or [])
    known = set(known_nodes)
    root = next(iter(_walk((ir or {}).get("tree") or [])), {})
    root_frame = root.get("frame") if isinstance(root, dict) and isinstance(root.get("frame"), dict) else {}
    root_w, root_h = float(root_frame.get("width") or 0), float(root_frame.get("height") or 0)
    clean: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_ops[:MAX_OPERATIONS]:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "restore-style")
        source_key = str(raw.get("sourceKey") or "")
        prop = str(raw.get("property") or "")
        if source_key not in known:
            continue
        if op == "restore-layout":
            if prop not in LAYOUT_PROPS or (source_key, prop) in seen:
                continue
            frame = known_nodes[source_key].get("frame")
            if not isinstance(frame, dict):
                continue
            old, value = frame.get(prop), raw.get("value")
            if prop == "padding":
                old_values = old if isinstance(old, list) and len(old) == 4 else [old] * 4
                new_values = value if isinstance(value, list) and len(value) == 4 else [value] * 4
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in new_values):
                    continue
                limits = [max(2.0, abs(float(v or 0)) * .2) for v in old_values]
                if any(abs(float(n) - float(o or 0)) > limit + 1e-6
                       for n, o, limit in zip(new_values, old_values, limits)):
                    continue
                clean_value: Any = [max(0.0, float(v)) for v in new_values]
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                old_num = float(old or 0)
                base = root_w if prop in {"x", "width", "gap"} else root_h
                limit = max(2.0, abs(old_num) * .2,
                            base * .2 if prop in {"x", "y"} and old_num == 0 else 0)
                clean_value = float(value)
                if abs(clean_value - old_num) > limit + 1e-6 or clean_value < 0:
                    continue
                candidate = dict(frame); candidate[prop] = clean_value
                x, y = float(candidate.get("x") or 0), float(candidate.get("y") or 0)
                width, height = float(candidate.get("width") or 0), float(candidate.get("height") or 0)
                parent = parents.get(source_key)
                parent_frame = parent.get("frame") if isinstance(parent, dict) and isinstance(parent.get("frame"), dict) else {}
                bound_w = float(parent_frame.get("width") or root_w)
                bound_h = float(parent_frame.get("height") or root_h)
                if (x < -.5 or y < -.5
                        or (bound_w and x + width > bound_w + .5)
                        or (bound_h and y + height > bound_h + .5)):
                    continue
            seen.add((source_key, prop))
            clean.append({"op": op, "sourceKey": source_key, "property": prop, "value": clean_value})
            continue
        if op != "restore-style" or prop not in allowed:
            continue
        value = _clean_value(prop, raw.get("value"))
        if value is None or (source_key, prop) in seen:
            continue
        seen.add((source_key, prop))
        clean.append({"op": "restore-style", "sourceKey": source_key, "property": prop, "value": value})
    return clean


def parse_operations(raw: str, ir: dict) -> list[dict]:
    """Ответ модели → валидные операции; мусор и не-JSON дают пустой список."""
    match = re.search(r"\{.*\}", str(raw or ""), re.S)
    if not match:
        return []
    try:
        return validate_operations(json.loads(match.group(0)), ir)
    except (ValueError, json.JSONDecodeError):
        return []


def apply_operations(ir: dict, operations: list[dict]) -> dict:
    """Apply validated style/layout operations to a copy of the master."""
    style_ops = [op for op in operations if op.get("op") == "restore-style"]
    fixed = _fidelity_repair().apply_operations(ir, style_ops)
    by_key = {str(node.get("sourceKey") or ""): node for node in _walk(fixed.get("tree") or [])}
    for op in operations:
        if op.get("op") != "restore-layout":
            continue
        node = by_key.get(str(op.get("sourceKey") or ""))
        if isinstance(node, dict) and isinstance(node.get("frame"), dict):
            node["frame"][str(op.get("property"))] = copy.deepcopy(op.get("value"))
    return fixed


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _with_master(comp: dict, master_ir: dict) -> dict:
    return {**comp, "masterIr": master_ir}


def pin_master(comp: dict, master_ir: dict) -> None:
    """Закрепить починенный мастер: IR, его hash в sourceRef и превью.

    ``templateIr`` — производная копия мастера; после правки она устаревает, и
    валидация справедливо ругается ``observed-master-mutated``. Пересобирать её
    нельзя вслепую (превью нормализует x/y корня), поэтому производную просто
    убираем — `document.migrate_draft` и так удаляет её, когда она равна мастеру.
    """
    from .builder import normalize_new_master_numbers
    master_ir = normalize_new_master_numbers(master_ir)
    comp["masterIr"] = master_ir
    source_ref = comp.get("sourceRef")
    if not isinstance(source_ref, dict):
        source_ref = {}
        comp["sourceRef"] = source_ref
    source_ref["masterHash"] = content_hash(master_ir)
    comp.pop("templateIr", None)


def annotate_review(comp: dict, result: dict) -> None:
    """Дописать след починки в ``fidelity.aiReview`` (после `apply_verdict`)."""
    if not isinstance(comp, dict):
        return
    fidelity = comp.setdefault("fidelity", {})
    if not isinstance(fidelity, dict):
        return
    review = fidelity.setdefault("aiReview", {})
    if not isinstance(review, dict):
        return
    review["repaired"] = bool(result.get("repaired"))
    review["rounds"] = int(result.get("rounds") or 0)
    if result.get("repaired"):
        review["operations"] = list(result.get("operations") or [])
        review.pop("repairAttempts", None)
    else:
        review["repairAttempts"] = int(result.get("rounds") or 0)
        if result.get("rejected"):
            review["rejected"] = list(result["rejected"])


def _layout_acceptance(before: dict, candidate: dict, *, page: Any, viewport: str,
                       original: str, before_png: bytes, candidate_png: bytes) -> tuple[bool, list[str]]:
    """Objective guard shared with deterministic polish, independent of AI verdict."""
    from . import polish
    import fidelity_harness
    from PIL import Image

    reference = fidelity_harness._decode_data_url(original)
    reference_size = Image.open(io.BytesIO(reference)).size
    wrong_sizes = [label for label, png in (("before", before_png), ("candidate", candidate_png))
                   if Image.open(io.BytesIO(png)).size != reference_size]
    if wrong_sizes:
        return False, ["size-mismatch:" + label for label in wrong_sizes]
    before_defects = polish.lint_master(before, page=page, viewports=(viewport,))
    after_defects = polish.lint_master(candidate, page=page, viewports=(viewport,))
    before_set = {(str(d.get("path")), str(d.get("kind"))) for d in before_defects}
    after_set = {(str(d.get("path")), str(d.get("kind"))) for d in after_defects}
    reasons: list[str] = []
    if not after_set.issubset(before_set): reasons.append("new-defect")
    if any(d.get("kind") == "escape" for d in after_defects): reasons.append("escape")
    before_similarity = fidelity_harness._image_metrics(reference, before_png).get("pixel_similarity")
    after_similarity = fidelity_harness._image_metrics(reference, candidate_png).get("pixel_similarity")
    threshold = float(fidelity_harness.GATE_THRESHOLDS["min_pixel_similarity"])
    if before_similarity is None or after_similarity is None:
        reasons.append("similarity-unavailable")
    elif float(after_similarity) + 1e-6 < max(threshold, float(before_similarity) - 1.5):
        reasons.append(f"similarity:{float(after_similarity):.2f}")
    return not reasons, reasons


def repair_master(document: dict, key: str, comp: dict | None, verdict: dict, *,
                  chat_repair: Callable[[list[str], str], str],
                  chat_vision: Callable[[list[str], str], str],
                  render: Callable[[Any, dict, str], bytes],
                  viewport: str = "desktop",
                  max_rounds: int = 3,
                  page: Any = None,
                  original: str | None = None) -> dict:
    """Цикл починки одного мастера: предложить → применить → перерендерить → пересудить.

    Возвращает ``{"repaired", "rounds", "operations", "verdict"}``. При одобрении
    компонент уже несёт починенный ``masterIr`` с обновлённым ``sourceRef.masterHash``
    и запись ``fidelity.aiReview``; переносит его в реестр вызывающий код через
    `master_review.apply_verdict`.
    """
    from . import master_review, styleguide

    if comp is None:
        comp = (document.get("reviewComponents") or {}).get(key)
    result: dict[str, Any] = {"repaired": False, "rounds": 0, "operations": [], "verdict": verdict,
                             "rejected": []}
    if not isinstance(comp, dict) or not isinstance(comp.get("masterIr"), dict):
        return result
    if original is None:
        original, _bytes, note = styleguide.proof_crop(document, comp, viewport, budget_left=4_000_000)
        if not original:
            raise RuntimeError(note or "no original crop")

    current_master = copy.deepcopy(comp["masterIr"])
    current_verdict = dict(verdict)
    operations_log: list[dict] = []
    rounds = 0

    for _round in range(max(1, int(max_rounds))):
        current_comp = _with_master(comp, current_master)
        current_png = render(page, current_comp, viewport)
        nodes = describe_nodes(current_master)
        if not nodes:
            break
        raw = chat_repair([original, _data_url(current_png)],
                          build_repair_prompt(current_comp, current_verdict, viewport, nodes))
        operations = parse_operations(raw, current_master)
        if not operations:
            break
        candidate_master = apply_operations(current_master, operations)
        if canonical_json(candidate_master) == canonical_json(current_master):
            break  # правка ничего не меняет — следующий раунд предложит то же самое
        rounds += 1
        candidate_comp = _with_master(comp, candidate_master)
        candidate_png = render(page, candidate_comp, viewport)
        safe, rejected = _layout_acceptance(current_master, candidate_master, page=page,
                                            viewport=viewport, original=original,
                                            before_png=current_png, candidate_png=candidate_png)
        if not safe:
            result["rejected"].extend(rejected)
            continue
        new_verdict = master_review.parse_verdict(
            chat_vision([original, _data_url(candidate_png)],
                        master_review.build_prompt(candidate_comp, viewport)))
        if not new_verdict["approved"] and new_verdict["score"] < current_verdict.get("score", 0):
            # Стало хуже по мнению того же судьи — откат, дефекты прежние.
            continue
        current_master = candidate_master
        current_verdict = new_verdict
        operations_log.extend(operations)
        if new_verdict["approved"]:
            break

    approved = bool(current_verdict.get("approved"))
    result.update({"repaired": approved, "rounds": rounds, "operations": operations_log,
                   "verdict": current_verdict})
    if approved:
        pin_master(comp, current_master)
        fidelity = comp.setdefault("fidelity", {})
        if isinstance(fidelity, dict):
            fidelity["aiReview"] = {
                "verdict": "approved",
                "repaired": True,
                "rounds": rounds,
                "operations": list(operations_log),
                "score": current_verdict.get("score"),
                "summary": current_verdict.get("summary"),
                "defects": [],
            }
    else:
        annotate_review(comp, result)
    return result
