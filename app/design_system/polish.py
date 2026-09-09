"""Deterministic layout polish for Design System component masters.

The module has a pure fallback linter (useful for tests and imports) and a
browser linter which uses the production renderer through fidelity_harness.
Only geometry is changed; text, styles and the node tree remain immutable.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable

VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 900), "mobile": (390, 844)}
TEXT_TYPES = {"text", "heading", "button", "badge", "link"}
BUFFER_PX = 2.0
MAX_WIDTH_GROWTH = .30
# A proven hidden/clip truncation may recover up to 2x its damaged width; the
# existing parent-bound, sibling-displacement, defect, and fidelity gates still apply.
MAX_CLIPPED_WIDTH_GROWTH = 1.0
SIMILARITY_DROP_PCT = 1.5

# Browser text metrics routinely drift by 1--3 px because glyph ink, integer
# scroll metrics, and captured frame bounds use different rounding.  A normal
# overflow must clear both the absolute and proportional thresholds.  Actual
# clipping may skip the proportional threshold, but never the absolute one.
TEXT_OVERFLOW_MIN_PX = 4.0
TEXT_OVERFLOW_MIN_RATIO = .15
NODE_ESCAPE_MIN_PX = 4.0


def _walk(nodes: Any, prefix: str = "tree"):
    if not isinstance(nodes, list):
        return
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        path = str(node.get("sourceKey") or f"{prefix}.{index}")
        yield path, node
        yield from _walk(node.get("children"), path + ".children")


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rect(node: dict) -> tuple[float, float, float, float] | None:
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    values = tuple(_num(frame.get(k)) for k in ("x", "y", "width", "height"))
    return values if all(v is not None for v in values) else None  # type: ignore[return-value]


def _viewport_node(node: dict, viewport: str) -> tuple[bool, dict]:
    """Return visibility and effective frame for a viewport."""
    override = ((node.get("responsive") or {}).get(viewport) or {})
    visible = node.get("visible") is not False
    if isinstance(override, dict) and override.get("visible") is False:
        visible = False
    base = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    extra = override.get("frame") if isinstance(override, dict) and isinstance(override.get("frame"), dict) else {}
    return visible, {**base, **extra}


def _walk_viewport(nodes: Any, viewport: str, prefix: str = "tree", ancestor_visible: bool = True):
    if not isinstance(nodes, list):
        return
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        path = str(node.get("sourceKey") or f"{prefix}.{index}")
        own_visible, frame = _viewport_node(node, viewport)
        visible = ancestor_visible and own_visible
        yield path, node, frame, visible
        yield from _walk_viewport(node.get("children"), viewport, path + ".children", visible)


def _source_line_count(node: dict) -> int | None:
    meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
    for owner in (node, meta):
        for key in ("sourceLineCount", "measuredLineCount", "textLineCount", "lineCount"):
            value = owner.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1:
                return int(value)
    return None


def _minimum_source_gap(node: dict, current: float) -> float:
    meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
    for key in ("sourceMinGap", "measuredMinGap", "minimumGap", "minGap"):
        value = _num(meta.get(key))
        if value is not None:
            return max(0.0, min(current, value))
    gaps = meta.get("measuredGaps")
    if isinstance(gaps, list):
        values = [_num(value) for value in gaps]
        if any(value is not None for value in values):
            return max(0.0, min(current, min(value for value in values if value is not None)))
    return current


def _dedupe(defects: list[dict]) -> list[dict]:
    """One actionable defect per captured node and kind (viewport clones collapse)."""
    found: dict[tuple[str, str], dict] = {}
    for defect in defects:
        key = (str(defect.get("path") or ""), str(defect.get("kind") or ""))
        current = found.get(key)
        if current is None or float(defect.get("px") or 0) > float(current.get("px") or 0):
            found[key] = defect
    return list(found.values())


def _text_width(node: dict) -> float:
    text = str(node.get("text") or "")
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    size = _num(style.get("fontSize")) or 16.0
    spacing = _num(style.get("letterSpacing")) or 0.0
    # Conservative deterministic fallback. Browser measurements replace this
    # when headless=True; overestimating is safer than shipping clipped copy.
    return max(0.0, len(text) * size * 0.58 + max(0, len(text) - 1) * spacing)


def _clips_content(node: dict, frame: dict) -> bool:
    """Whether *node* really clips descendants/text in the effective frame."""
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    values = (node.get("clipsContent"), frame.get("clipsContent"), style.get("overflow"),
              style.get("overflowX"), style.get("overflowY"), frame.get("overflow"))
    return any(value is True or str(value).lower() in {"hidden", "clip"} for value in values)


def _actionable_text_overflow(excess: float, width: float, actually_clipped: bool) -> bool:
    """Filter sub-pixel/font-rounding noise while retaining genuine clipping."""
    return (excess >= TEXT_OVERFLOW_MIN_PX
            and (actually_clipped or excess / max(width, 1.0) >= TEXT_OVERFLOW_MIN_RATIO))


def _captured_line_fragment(path: str) -> bool:
    """Captured ``::text0l47`` layers are intentional per-line clip masks."""
    tail = path.rsplit("::text", 1)[-1] if "::text" in path else ""
    line = tail.rsplit("l", 1)
    return len(line) == 2 and all(part.isdigit() for part in line)


def _root_escape_defects(master_ir: dict, viewport: str) -> list[dict]:
    """Find any visible descendant crossing its component-root boundary.

    Root escape is always actionable, even below the normal parent-noise
    threshold, because it can paint into the neighbouring component.
    """
    defects: list[dict] = []
    for root_index, root in enumerate((master_ir or {}).get("tree") or []):
        if not isinstance(root, dict):
            continue
        root_path = str(root.get("sourceKey") or f"tree.{root_index}")
        root_visible, root_frame = _viewport_node(root, viewport)
        root_width, root_height = _num(root_frame.get("width")), _num(root_frame.get("height"))
        if not root_visible or root_width is None or root_height is None:
            continue

        def visit(children: Any, offset_x: float, offset_y: float, prefix: str) -> None:
            if not isinstance(children, list):
                return
            for index, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                path = str(child.get("sourceKey") or f"{prefix}.{index}")
                visible, child_frame = _viewport_node(child, viewport)
                if not visible:
                    continue
                x, y = _num(child_frame.get("x")) or 0.0, _num(child_frame.get("y")) or 0.0
                width, height = _num(child_frame.get("width")), _num(child_frame.get("height"))
                absolute_x, absolute_y = offset_x + x, offset_y + y
                if width is not None and height is not None:
                    escape = max(0.0, -absolute_x, -absolute_y,
                                 absolute_x + width - root_width,
                                 absolute_y + height - root_height)
                    if escape > .5:
                        defects.append({"path": path, "kind": "escape", "px": round(escape, 2),
                                        "viewport": viewport})
                visit(child.get("children"), absolute_x, absolute_y, path + ".children")

        visit(root.get("children"), 0.0, 0.0, root_path + ".children")
    return defects


def static_lint(master_ir: dict, viewport: str = "desktop") -> list[dict]:
    defects: list[dict] = _root_escape_defects(master_ir, viewport)
    for path, node, frame, visible in _walk_viewport((master_ir or {}).get("tree") or [], viewport):
        if not visible:
            continue
        width = _num(frame.get("width"))
        if str(node.get("text") or "") and width is not None and not _captured_line_fragment(path):
            excess = _text_width(node) - width
            clipped = _clips_content(node, frame)
            if _actionable_text_overflow(excess, width, clipped):
                defects.append({"path": path, "kind": "overflow", "px": round(excess, 2),
                                "viewport": viewport})
                if clipped:
                    defects.append({"path": path, "kind": "clip", "px": round(excess, 2),
                                    "viewport": viewport})
        expected_lines = _source_line_count(node)
        height = _num(frame.get("height"))
        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        font_size = _num(style.get("fontSize")) or 16
        line_height = _num(style.get("lineHeight")) or font_size * 1.2
        if line_height <= 4:  # captured CSS unitless line-height multiplier
            line_height *= font_size
        if str(node.get("text") or "") and expected_lines is not None and height is not None:
            actual_lines = max(1, int(round(height / max(1.0, line_height))))
            if actual_lines > expected_lines:
                defects.append({"path": path, "kind": "wrap", "px": actual_lines - expected_lines,
                                "viewport": viewport})
        children = [c for c in (node.get("children") or []) if isinstance(c, dict)
                    and _viewport_node(c, viewport)[0]]
        parent_width, parent_height = _num(frame.get("width")), _num(frame.get("height"))
        parent_clips = _clips_content(node, frame)
        for child in children:
            child_path = str(child.get("sourceKey") or "")
            _child_visible, child_frame = _viewport_node(child, viewport)
            rect = tuple(_num(child_frame.get(k)) for k in ("x", "y", "width", "height"))
            if parent_width is not None and parent_height is not None and all(v is not None for v in rect):
                x, y, w, h = rect  # type: ignore[misc]
                escape = max(0.0, -x, -y, x + w - parent_width, y + h - parent_height)
                if escape >= NODE_ESCAPE_MIN_PX or (parent_clips and escape > .5):
                    defects.append({"path": child_path, "kind": "escape", "px": round(escape, 2),
                                    "viewport": viewport})
        if frame.get("layout") == "free":
            rects = [(str(child.get("sourceKey") or f"{path}.children.{i}"),
                      tuple(_num(_viewport_node(child, viewport)[1].get(k))
                            for k in ("x", "y", "width", "height")))
                     for i, child in enumerate(children)]
            for i, (a_path, a) in enumerate(rects):
                if a is None:
                    continue
                if not all(v is not None for v in a):
                    continue
                ax, ay, aw, ah = a
                for b_path, b in rects[i + 1:]:
                    if b is None or not all(v is not None for v in b):
                        continue
                    if a_path.split("::", 1)[0] == b_path.split("::", 1)[0]:
                        continue
                    bx, by, bw, bh = b
                    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
                    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
                    if ix > .5 and iy > .5:
                        defects.append({"path": b_path, "kind": "overlap",
                                        "px": round(min(ix, iy), 2), "otherPath": a_path,
                                        "viewport": viewport})
    return _dedupe(defects)


def lint_master(master_ir: dict, *, page: Any = None,
                viewports: tuple[str, ...] = ("desktop", "tablet", "mobile")) -> list[dict]:
    """Return ``{path, kind, px, viewport}`` defects on three viewports."""
    if page is None:
        return _dedupe([d for viewport in viewports for d in static_lint(master_ir, viewport)])
    import fidelity_harness
    import scraper
    from .document import preview_ir_for_master
    preview = preview_ir_for_master(master_ir)
    render_preview, asset_errors = scraper.resolve_ir_blobs(preview)
    if asset_errors:
        root = (master_ir.get("tree") or [{}])[0]
        raise scraper.CanonicalRasterAssetError(
            "blob-resolve-failed", "; ".join(asset_errors[:3]), stage="ds-polish-render",
            component=str(root.get("sourceKey") or ""), path="masterIr")
    defects: list[dict] = []
    for viewport in viewports:
        if _master_hidden(master_ir, viewport):
            continue  # Explicit Source state; acceptance still requires proof.
        width, height = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])
        root = (preview.get("tree") or [{}])[0]
        frame = root.get("frame") if isinstance(root, dict) and isinstance(root.get("frame"), dict) else {}
        width = max(240, int(_num(frame.get("width")) or width))
        height = max(320, int(_num(frame.get("height")) or height))
        line_counts = {path: count for path, node in _walk((master_ir or {}).get("tree") or [])
                       if (count := _source_line_count(node)) is not None}
        measured = fidelity_harness.measure_layout(page, render_preview, viewport, width, height,
                                                   source_line_counts=line_counts,
                                                   thresholds={
                                                       "overflowMinPx": TEXT_OVERFLOW_MIN_PX,
                                                       "overflowMinRatio": TEXT_OVERFLOW_MIN_RATIO,
                                                       "escapeMinPx": NODE_ESCAPE_MIN_PX,
                                                   })
        for defect in measured.get("defects") or []:
            defects.append({**defect, "viewport": viewport})
    return _dedupe(defects)


def _find(master_ir: dict, path: str) -> tuple[dict | None, dict | None, int]:
    def visit(nodes: list, parent: dict | None):
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            if str(node.get("sourceKey") or "") == path:
                return node, parent, index
            found = visit(node.get("children") or [], node)
            if found[0] is not None:
                return found
        return None, None, -1
    return visit((master_ir or {}).get("tree") or [], None)


def autofix(master_ir: dict, defects: list[dict]) -> tuple[dict, list[dict]]:
    """Apply unambiguous width expansion and minimum sibling displacement."""
    fixed = copy.deepcopy(master_ir)
    journal: list[dict] = []
    # Clip is normally the visible consequence of the same overflow. Collapse
    # both into one width change per concrete (base/responsive) frame.
    width_jobs: dict[tuple[str, str], tuple[float, bool]] = {}
    overlap_jobs: dict[tuple[str, str], float] = {}
    for defect in defects:
        path, viewport = str(defect.get("path") or ""), str(defect.get("viewport") or "desktop")
        if defect.get("kind") in {"overflow", "clip"}:
            key = (path, viewport)
            previous_px, was_clipped = width_jobs.get(key, (0.0, False))
            width_jobs[key] = (max(previous_px, float(defect.get("px") or 0)),
                               was_clipped or defect.get("kind") == "clip")
            continue
        elif defect.get("kind") == "overlap":
            jobs = overlap_jobs
        else:
            continue
        jobs[(path, viewport)] = max(jobs.get((path, viewport), 0.0), float(defect.get("px") or 0))
    changed_frames: set[int] = set()
    for (path, viewport), (px, actually_clipped) in width_jobs.items():
        node, parent, index = _find(fixed, path)
        if node is None or px <= .5:
            continue
        base_frame = node.get("frame") if isinstance(node.get("frame"), dict) else None
        override = (node.get("responsive") or {}).get(viewport)
        responsive_frame = override.get("frame") if isinstance(override, dict) and isinstance(override.get("frame"), dict) else None
        frame = responsive_frame if responsive_frame is not None and frame_has_width(responsive_frame) else base_frame
        if frame is None:
            continue
        if id(frame) in changed_frames:
            continue
        old = _num(frame.get("width"))
        if old is None:
            continue
        desired = old + math.ceil(px + BUFFER_PX)
        growth_cap = MAX_CLIPPED_WIDTH_GROWTH if actually_clipped else MAX_WIDTH_GROWTH
        new_width = min(desired, old * (1 + growth_cap))
        delta = new_width - old
        if delta <= .5:
            continue
        # A free-layout expansion is atomic: every displaced sibling and the
        # expanded text must remain within the parent's local bounds.
        siblings_to_shift: list[tuple[dict, dict, float]] = []
        gap_change: tuple[dict, float, float] | None = None
        if parent is not None:
            _pv, pframe = _viewport_node(parent, viewport)
            parent_width = _num(pframe.get("width"))
            children = parent.get("children") or []
            if pframe.get("layout") == "free":
                node_x = _num(frame.get("x")) or 0.0
                if parent_width is not None and node_x + new_width > parent_width + .5:
                    continue
                safe = True
                cursor = node_x + new_width
                node_y, node_h = _num(frame.get("y")) or 0.0, _num(frame.get("height")) or 0.0
                for sibling in children[index + 1:]:
                    if not isinstance(sibling, dict) or not _viewport_node(sibling, viewport)[0]:
                        continue
                    _sv, sf = _viewport_node(sibling, viewport)
                    sibling_override = ((sibling.get("responsive") or {}).get(viewport) or {})
                    target = sibling_override.get("frame") if isinstance(sibling_override, dict) and isinstance(sibling_override.get("frame"), dict) else sibling.get("frame")
                    sx, sw = _num(sf.get("x")), _num(sf.get("width"))
                    sy, sh = _num(sf.get("y")) or 0.0, _num(sf.get("height")) or 0.0
                    same_band = min(node_y + node_h, sy + sh) - max(node_y, sy) > .5
                    shift = max(0.0, cursor - sx) if sx is not None and same_band else 0.0
                    if sx is not None and sw is not None and parent_width is not None and sx + shift + sw > parent_width + .5:
                        safe = False; break
                    if isinstance(target, dict) and sx is not None and shift > .5:
                        siblings_to_shift.append((sibling, target, shift))
                    if sx is not None and sw is not None and same_band:
                        cursor = sx + shift + sw
                if not safe:
                    continue
            elif pframe.get("layout") == "row" and parent_width is not None:
                visible_children = [child for child in children
                                    if isinstance(child, dict) and _viewport_node(child, viewport)[0]]
                widths = [_num(_viewport_node(child, viewport)[1].get("width"))
                          for child in visible_children]
                if any(value is None for value in widths):
                    continue
                padding = pframe.get("padding") if isinstance(pframe.get("padding"), list) else [0, 0, 0, 0]
                horizontal_padding = float(padding[1] or 0) + float(padding[3] or 0) if len(padding) == 4 else 0.0
                old_gap = _num(pframe.get("gap")) or 0.0
                slots = max(0, len(widths) - 1)
                occupied = sum(float(value) for value in widths if value is not None) + horizontal_padding + old_gap * slots
                if occupied + delta > parent_width + .5:
                    min_gap = _minimum_source_gap(parent, old_gap)
                    new_gap = max(min_gap, old_gap - (occupied + delta - parent_width) / max(1, slots))
                    if not slots or occupied + delta - (old_gap - new_gap) * slots > parent_width + .5:
                        continue
                    parent_override = ((parent.get("responsive") or {}).get(viewport) or {})
                    gap_target = (parent_override.get("frame")
                                  if isinstance(parent_override, dict) and isinstance(parent_override.get("frame"), dict)
                                  else parent.get("frame"))
                    if not isinstance(gap_target, dict):
                        continue
                    gap_change = (gap_target, old_gap, round(new_gap, 3))
            elif parent_width is not None:
                node_x = _num(frame.get("x")) or 0.0
                if node_x + new_width > parent_width + .5:
                    continue
        frame["width"] = round(new_width, 3)
        changed_frames.add(id(frame))
        journal.append({"path": path, "viewport": viewport, "property": "width", "before": old,
                        "after": frame["width"], "reason": "overflow"})
        for sibling, sf, shift in siblings_to_shift:
            before = float(sf["x"]); sf["x"] = round(before + shift, 3)
            journal.append({"path": sibling.get("sourceKey") or "", "viewport": viewport,
                            "property": "x", "before": before, "after": sf["x"],
                            "reason": "make-room"})
        if gap_change is not None:
            target, before, after = gap_change; target["gap"] = after
            journal.append({"path": parent.get("sourceKey") or "", "viewport": viewport,
                            "property": "gap", "before": before, "after": after,
                            "reason": "source-min-gap"})
    for (path, _viewport), px in overlap_jobs.items():
        node, parent, _index = _find(fixed, path)
        if node is not None and parent is not None and px > .5:
            frame = node.get("frame") if isinstance(node.get("frame"), dict) else None
            if frame is None:
                continue
            pframe = parent.get("frame") if isinstance(parent.get("frame"), dict) else {}
            axis = "y" if pframe.get("layout") == "column" else "x"
            before = _num(frame.get(axis))
            if before is not None:
                delta = math.ceil(px + BUFFER_PX); frame[axis] = before + delta
                journal.append({"path": path, "property": axis, "before": before,
                                "after": frame[axis], "reason": "overlap"})
            elif pframe.get("layout") in {"row", "column"}:
                old_gap = _num(pframe.get("gap")) or 0.0
                pframe["gap"] = old_gap + math.ceil(px + BUFFER_PX)
                journal.append({"path": parent.get("sourceKey") or "", "property": "gap",
                                "before": old_gap, "after": pframe["gap"], "reason": "overlap"})
    return fixed, journal


def frame_has_width(frame: dict) -> bool:
    return _num(frame.get("width")) is not None


def _master_hidden(master: dict, viewport: str) -> bool:
    roots = master.get("tree") or []
    return bool(roots) and all(isinstance(root, dict) and not _viewport_node(root, viewport)[0]
                               for root in roots)


def _fidelity_passed(component: dict) -> bool:
    fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
    gate = fidelity.get("gate") if isinstance(fidelity.get("gate"), dict) else {}
    if "passed" in gate:
        return bool(gate["passed"])
    viewports = fidelity.get("viewports") if isinstance(fidelity.get("viewports"), dict) else {}
    return not viewports or all(bool((m or {}).get("sourceGatePassed", True)) for m in viewports.values())


def polish_component(component: dict, *, page: Any = None,
                     fidelity_check: Callable[[dict], bool | dict] | None = None) -> dict:
    master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else None
    if master is None:
        return {"changed": False, "defectsBefore": [], "defectsAfter": [], "rounds": 0}
    before_defects = lint_master(master, page=page)
    candidate, journal = autofix(master, before_defects)
    if journal:
        from .builder import normalize_new_master_numbers
        candidate = normalize_new_master_numbers(candidate)
    after_defects = lint_master(candidate, page=page) if journal else list(before_defects)
    gate_result = fidelity_check(candidate) if fidelity_check else _fidelity_passed(component)
    gate_ok = bool(gate_result.get("passed")) if isinstance(gate_result, dict) else bool(gate_result)
    before_set = {(str(d.get("path")), str(d.get("kind"))) for d in before_defects}
    after_set = {(str(d.get("path")), str(d.get("kind"))) for d in after_defects}
    reasons = []
    if not after_set.issubset(before_set): reasons.append("new-defect")
    if any(d.get("kind") == "escape" for d in after_defects): reasons.append("escape")
    if not gate_ok: reasons.append("fidelity")
    if not journal and before_defects: reasons.append("no-safe-fix")
    accepted = bool(journal and gate_ok and after_set.issubset(before_set)
                    and not any(d.get("kind") == "escape" for d in after_defects))
    if accepted:
        component["polish"] = {"before": copy.deepcopy(master), "journal": journal}
        component["masterIr"] = candidate
        component.pop("templateIr", None)
        source_ref = component.get("sourceRef") if isinstance(component.get("sourceRef"), dict) else {}
        if source_ref:
            from .document import content_hash
            source_ref["masterHash"] = content_hash(candidate)
    fidelity = component.setdefault("fidelity", {})
    if isinstance(fidelity, dict):
        remaining_defects = after_defects if accepted else before_defects
        fidelity["polish"] = {"defectsBefore": before_defects,
                              "defectsAfter": remaining_defects,
                              "rounds": 1 if journal else 0, "accepted": accepted,
                              "status": ("needs-polish" if remaining_defects else
                                         "ready" if gate_ok else "needs-review")}
        if isinstance(gate_result, dict):
            fidelity["polish"].update({k: v for k, v in gate_result.items() if k != "passed"})
        if accepted or (not remaining_defects and gate_ok):
            fidelity["polish"].pop("rejected", None)
        else:
            fidelity["polish"]["rejected"] = reasons
    return {"changed": accepted, "defectsBefore": before_defects,
            "defectsAfter": after_defects if accepted else before_defects,
            "rounds": 1 if journal else 0, "journal": journal if accepted else []}


def rollback_component(component: dict) -> bool:
    polish = component.get("polish") if isinstance(component.get("polish"), dict) else {}
    before = polish.get("before") if isinstance(polish.get("before"), dict) else None
    if before is None:
        return False
    component["masterIr"] = copy.deepcopy(before)
    component.pop("polish", None)
    fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
    fidelity.pop("polish", None)
    source_ref = component.get("sourceRef") if isinstance(component.get("sourceRef"), dict) else {}
    if source_ref:
        from .document import content_hash
        source_ref["masterHash"] = content_hash(before)
    return True


def polish_document(document: dict, *, headless: bool = False) -> tuple[dict, list[dict]]:
    updated = copy.deepcopy(document)
    results: list[dict] = []
    page = browser = playwright = None
    try:
        if headless:
            import scraper
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            browser = scraper.launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        for pool in ("components", "reviewComponents"):
            for key, component in (updated.get(pool) or {}).items():
                if isinstance(component, dict):
                    measured_fidelity: dict[str, Any] = {}
                    fidelity_check = None
                    if page is not None:
                        def check_candidate(candidate: dict, component=component) -> dict:
                            import fidelity_harness
                            from . import master_review, styleguide
                            import io
                            from PIL import Image
                            threshold = float(fidelity_harness.GATE_THRESHOLDS["min_pixel_similarity"])
                            fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
                            stored = fidelity.get("viewports") if isinstance(fidelity.get("viewports"), dict) else {}
                            required = fidelity.get("requiredViewports") if isinstance(fidelity.get("requiredViewports"), list) else []
                            viewports = list(dict.fromkeys([*required, *stored.keys()])) or ["desktop"]
                            similarities: dict[str, dict[str, float]] = {}
                            hidden_viewports: list[str] = []
                            rejected: list[str] = []
                            for candidate_viewport in viewports:
                                before_hidden = _master_hidden(component["masterIr"], candidate_viewport)
                                after_hidden = _master_hidden(candidate, candidate_viewport)
                                if before_hidden != after_hidden:
                                    rejected.append(f"{candidate_viewport}: visibility-changed")
                                    continue
                                if before_hidden:
                                    from .desktop_ai import _hidden_evidence
                                    if _hidden_evidence(updated, component, candidate_viewport):
                                        hidden_viewports.append(candidate_viewport)
                                    else:
                                        rejected.append(f"{candidate_viewport}: hidden-without-source-proof")
                                    continue
                                ref = component.get("sourceRef") or {}
                                evidence = (updated.get("referenceAssets") or {}).get(ref.get("evidenceKey")) or {}
                                if (not (evidence.get("referencePreviews") or {}).get(candidate_viewport)
                                        or candidate_viewport not in (ref.get("boundsByViewport") or {})
                                        or candidate_viewport not in (evidence.get("blockSizes") or {})):
                                    rejected.append(f"{candidate_viewport}: no-source-proof")
                                    continue
                                source, _size, note = styleguide.proof_crop(
                                    updated, component, candidate_viewport, budget_left=4_000_000)
                                if not source or note:
                                    rejected.append(f"{candidate_viewport}: no-source-proof ({note or 'missing'})")
                                    continue
                                render_comp = {**component, "masterIr": candidate}
                                rendered = master_review.render_master_png(page, master_review.with_source_context(updated, render_comp), candidate_viewport)
                                reference = fidelity_harness._decode_data_url(source)
                                ref_image = Image.open(io.BytesIO(reference))
                                rendered_image = Image.open(io.BytesIO(rendered)).convert("RGB")
                                if rendered_image.size != ref_image.size:
                                    rejected.append(
                                        f"{candidate_viewport}: size-mismatch "
                                        f"{rendered_image.size} != {ref_image.size}")
                                    continue  # Never rescale a candidate to manufacture fidelity.
                                similarity = fidelity_harness._image_metrics(reference, rendered).get("pixel_similarity")
                                if similarity is None:
                                    rejected.append(f"{candidate_viewport}: similarity-unavailable")
                                    continue
                                after = float(similarity)
                                before_raw = (stored.get(candidate_viewport) or {}).get("pixelSimilarity")
                                before = float(before_raw) if isinstance(before_raw, (int, float)) else after
                                similarities[candidate_viewport] = {"before": before, "after": after}
                                floor = max(threshold, before - SIMILARITY_DROP_PCT)
                                if after + 1e-6 < floor:
                                    rejected.append(f"{candidate_viewport}: {after:.2f} < {floor:.2f}")
                            measured_fidelity["pixelSimilarity"] = similarities
                            return {"passed": not rejected and bool(similarities),
                                    "pixelSimilarity": similarities,
                                    "sourceHiddenViewports": hidden_viewports,
                                    "fidelityRejected": rejected}
                        fidelity_check = check_candidate
                    results.append({"componentKey": key, "pool": pool,
                                    **polish_component(component, page=page,
                                                       fidelity_check=fidelity_check)})
                    fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
                    trace = fidelity.get("polish") if isinstance(fidelity.get("polish"), dict) else {}
                    trace.update(measured_fidelity)
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
    return updated, results
