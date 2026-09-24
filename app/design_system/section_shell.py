"""Section shell: the page grid every section of a captured site sits in.

A new section fits an existing page only when it lands in the same column,
keeps the same vertical rhythm and reuses the same eyebrow, heading, body,
surface and button styles. Colour and font tokens alone do not carry that:
a generator given only hex values and families builds a generic white card.
This module measures the shell deterministically from Source block IRs
captured by the snapshot engine (``meta.pageRect`` holds the section box in
page coordinates) and never invents values: a field without evidence is
omitted.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

_CHROME_KINDS = {"header", "footer", "nav", "navbar"}
_TEXT_TYPES = {"text", "heading"}


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _tidy(value: float) -> int | float:
    rounded = round(float(value), 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _padding(frame: dict) -> list[float]:
    raw = frame.get("padding")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return [float(raw)] * 4
    if isinstance(raw, list) and raw:
        values = [_num(item) or 0.0 for item in raw]
        if len(values) == 1:
            return values * 4
        if len(values) == 2:
            return [values[0], values[1], values[0], values[1]]
        if len(values) == 3:
            return [values[0], values[1], values[2], values[1]]
        return values[:4]
    return [0.0, 0.0, 0.0, 0.0]


def _mode(values: Iterable[float], *, prefer_larger: bool = True) -> float | None:
    counts = Counter(round(value) for value in values)
    if not counts:
        return None
    return max(counts.items(), key=lambda pair: (pair[1], pair[0] if prefer_larger else -pair[0]))[0]


def _family(style: dict) -> str:
    return str(style.get("fontFamily") or "").split(",")[0].strip().strip("'\"")[:60]


def _text_of(node: dict) -> str:
    text = str(node.get("text") or "").strip()
    if text:
        return text
    return " ".join(_text_of(child) for child in node.get("children") or [] if isinstance(child, dict)).strip()


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)


def _text_style(node: dict) -> dict:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    out: dict[str, Any] = {}
    family = _family(style)
    if family:
        out["fontFamily"] = family
    for key in ("fontSize", "fontWeight", "letterSpacing", "lineHeight"):
        value = _num(style.get(key))
        if value is not None and (value or key == "fontSize"):
            out[key] = _tidy(value)
    for key in ("color", "textTransform", "fontStyle"):
        value = style.get(key)
        if isinstance(value, str) and value and value not in ("none", "normal"):
            out[key] = value
    return out


def _box_style(node: dict) -> dict:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("background", "borderColor", "boxShadow", "color"):
        value = style.get(key)
        if isinstance(value, str) and value and value != "none":
            out[key] = value[:160]
    for key in ("borderWidth", "borderRadius"):
        value = _num(style.get(key))
        if value:
            out[key] = _tidy(value)
    if not out.get("borderWidth"):
        out.pop("borderColor", None)
    if not out.get("background"):
        # gradients are captured as a "::bg" layer child
        for child in node.get("children") or []:
            if isinstance(child, dict) and str(child.get("sourceKey") or "").endswith("::bg"):
                layer = child.get("style") if isinstance(child.get("style"), dict) else {}
                image = layer.get("backgroundImage")
                if isinstance(image, str) and "gradient" in image:
                    out["background"] = image[:160]
                    break
    return out


def _is_eyebrow(node: dict) -> bool:
    if node.get("type") not in _TEXT_TYPES:
        return False
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    size = _num(style.get("fontSize")) or 0
    text = _text_of(node)
    if not text or size <= 0 or size > 18 or len(text) > 48:
        return False
    family = _family(style).lower()
    return (style.get("textTransform") == "uppercase" or (_num(style.get("letterSpacing")) or 0) >= 0.5
            or "mono" in family or text.upper() == text and any(ch.isalpha() for ch in text))


def _top_styles(counter: Counter, styles: dict, limit: int) -> list[dict]:
    return [{**styles[key], "count": count} for key, count in counter.most_common(limit)]


def measure_section_shell(blocks: list) -> dict:
    """Measured page grid and section anatomy of a captured site; {} without evidence."""
    entries = []
    for index, block in enumerate(blocks or []):
        ir = block.get("ir") if isinstance(block, dict) else None
        if not isinstance(ir, dict):
            continue
        meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
        rect = meta.get("pageRect") if isinstance(meta.get("pageRect"), dict) else None
        tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
        root = tree[0] if tree and isinstance(tree[0], dict) else None
        if not rect or root is None or not all(_num(rect.get(key)) is not None for key in ("x", "y", "width", "height")):
            continue
        kind = str(block.get("kind") or "").lower()
        entries.append({"index": index, "kind": kind, "rect": {k: float(rect[k]) for k in ("x", "y", "width", "height")},
                        "root": root, "meta": meta,
                        "chrome": kind in _CHROME_KINDS})
    if not entries:
        return {}

    # Column: the (x, width) that covers the most page height.
    column_weight: Counter = Counter()
    for entry in entries:
        rect = entry["rect"]
        column_weight[(round(rect["x"]), round(rect["width"]))] += rect["height"]
    (column_x, column_w), _ = column_weight.most_common(1)[0]
    in_column = [entry for entry in entries if (round(entry["rect"]["x"]), round(entry["rect"]["width"])) == (column_x, column_w)]
    content = [entry for entry in in_column if not entry["chrome"]] or in_column
    # Captured sections are centred on the viewport far more often than not:
    # 2·x + width recovers the capture width without a separate field.
    page_width = _mode([2 * entry["rect"]["x"] + entry["rect"]["width"] for entry in entries])

    pads = [_padding(entry["root"].get("frame") if isinstance(entry["root"].get("frame"), dict) else {}) for entry in content]
    inset = _mode([pad[3] for pad in pads if pad[3] > 0] + [pad[1] for pad in pads if pad[1] > 0])
    pad_top = _mode([pad[0] for pad in pads if pad[0] > 0])
    pad_bottom = _mode([pad[2] for pad in pads if pad[2] > 0])

    shell: dict[str, Any] = {"basis": "source-ir", "sections": len(entries)}
    if page_width:
        shell["pageWidth"] = int(page_width)
    shell["column"] = {"x": column_x, "width": column_w, "sections": len(in_column)}
    if inset:
        shell["contentInset"] = inset
        shell["content"] = {"x": column_x + inset, "width": column_w - 2 * inset}
    if pad_top or pad_bottom:
        shell["sectionPadding"] = {"top": pad_top or 0, "bottom": pad_bottom or 0}

    backgrounds = Counter(str(entry["meta"].get("pageBackground"))[:240] for entry in entries
                          if isinstance(entry["meta"].get("pageBackground"), str) and entry["meta"].get("pageBackground"))
    if backgrounds:
        shell["pageBackground"] = backgrounds.most_common(1)[0][0]
    painted = sum(1 for entry in content if isinstance((entry["root"].get("style") or {}).get("background"), str))
    shell["sectionRoot"] = ("transparent: the page background shows through" if painted * 2 < len(content)
                            else "painted: sections carry their own surface")

    # Eyebrow: a short uppercase/mono/tracked label that opens several sections.
    eyebrow_styles: dict[str, dict] = {}
    eyebrow_counts: Counter = Counter()
    eyebrow_gaps: list[float] = []
    for entry in content:
        children = [child for child in entry["root"].get("children") or [] if isinstance(child, dict)
                    and isinstance(child.get("frame"), dict) and child.get("type") not in ("image", "rect")]
        children.sort(key=lambda child: (_num(child["frame"].get("y")) or 0, _num(child["frame"].get("x")) or 0))
        if not children or not _is_eyebrow(children[0]):
            continue
        style = _text_style(children[0])
        key = repr(sorted(style.items()))
        eyebrow_styles[key] = style
        eyebrow_counts[key] += 1
        if len(children) > 1:
            first = children[0]["frame"]
            gap = (_num(children[1]["frame"].get("y")) or 0) - (_num(first.get("y")) or 0) - (_num(first.get("height")) or 0)
            if gap >= 0:
                eyebrow_gaps.append(gap)
    if eyebrow_counts:
        key, count = eyebrow_counts.most_common(1)[0]
        if count >= 2 or len(content) <= 2:
            shell["eyebrow"] = {**eyebrow_styles[key], "sections": count}
            gap = _mode(eyebrow_gaps, prefer_larger=False)
            if gap is not None:
                shell["eyebrow"]["gapBelow"] = gap

    # Headings, body, surfaces, buttons across all captured sections.
    heading_styles: dict[str, dict] = {}
    heading_counts: Counter = Counter()
    body_styles: dict[str, dict] = {}
    body_counts: Counter = Counter()
    surface_styles: dict[str, dict] = {}
    surface_counts: Counter = Counter()
    button_styles: dict[str, dict] = {}
    button_counts: Counter = Counter()
    for entry in entries:
        for node in _walk(entry["root"]):
            if node is entry["root"]:
                continue
            node_type = node.get("type")
            frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
            if node_type in _TEXT_TYPES and str(node.get("text") or "").strip():
                style = _text_style(node)
                size = float(style.get("fontSize") or 0)
                if _is_eyebrow(node) or size <= 0:
                    continue
                key = repr(sorted(style.items()))
                if not any(ch.isalpha() for ch in str(node.get("text") or "")):
                    continue
                if node_type == "heading" or float(style.get("fontWeight") or 400) >= 600 and size >= 17:
                    heading_styles[key] = style
                    heading_counts[key] += 1
                elif 13 <= size <= 20:
                    body_styles[key] = style
                    body_counts[key] += min(8, 1 + len(str(node.get("text") or "")) // 40)
            elif node_type == "button":
                style = {**_box_style(node), **{k: v for k, v in _text_style(node).items() if k in ("fontFamily", "fontSize", "fontWeight", "textTransform")}}
                height = _num(frame.get("height"))
                if height:
                    style["height"] = _tidy(height)
                if style:
                    key = repr(sorted(style.items()))
                    button_styles[key] = style
                    button_counts[key] += 1
            elif node_type in ("card", "section", "container", "box", "frame"):
                style = _box_style(node)
                style.pop("color", None)
                width, height = _num(frame.get("width")) or 0, _num(frame.get("height")) or 0
                if style.get("background") and (style.get("borderWidth") or style.get("boxShadow") or style.get("borderRadius")) \
                        and width >= 120 and height >= 64:
                    key = repr(sorted(style.items()))
                    surface_styles[key] = style
                    surface_counts[key] += 1
    if heading_counts:
        # the display heading (largest) plus the most frequent levels, largest first
        largest = max(heading_styles, key=lambda key: float(heading_styles[key].get("fontSize") or 0))
        keep = [largest] + [key for key, _ in heading_counts.most_common(4) if key != largest][:3]
        keep.sort(key=lambda key: -float(heading_styles[key].get("fontSize") or 0))
        shell["headings"] = [{**heading_styles[key], "count": heading_counts[key]} for key in keep]
    if body_counts:
        shell["body"] = _top_styles(body_counts, body_styles, 2)
    if surface_counts:
        shell["surfaces"] = _top_styles(surface_counts, surface_styles, 3)
    if button_counts:
        shell["buttons"] = _top_styles(button_counts, button_styles, 3)
    return shell


def shell_prompt_payload(shell: dict) -> dict:
    """Compact shell for the generator prompt plus the derived root frame of a new section."""
    if not shell or not shell.get("column"):
        return {}
    payload = {key: shell[key] for key in ("pageWidth", "column", "content", "sectionPadding", "sectionRoot",
                                           "eyebrow", "headings", "body", "surfaces", "buttons") if shell.get(key)}
    content = shell.get("content") or {"x": shell["column"]["x"], "width": shell["column"]["width"]}
    page_width = shell.get("pageWidth")
    padding = shell.get("sectionPadding") or {}
    if page_width:
        side = content["x"]
        payload["newSectionRoot"] = {
            "width": page_width,
            "padding": [padding.get("top", 0), max(0, page_width - side - content["width"]), padding.get("bottom", 0), side],
            "background": "none" if str(shell.get("sectionRoot") or "").startswith("transparent") else "surface",
        }
    return payload
