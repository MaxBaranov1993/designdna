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


def _text_width(node: dict) -> float:
    text = str(node.get("text") or "")
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    size = _num(style.get("fontSize")) or 16.0
    spacing = _num(style.get("letterSpacing")) or 0.0
    # Conservative deterministic fallback. Browser measurements replace this
    # when headless=True; overestimating is safer than shipping clipped copy.
    return max(0.0, len(text) * size * 0.58 + max(0, len(text) - 1) * spacing)


def static_lint(master_ir: dict, viewport: str = "desktop") -> list[dict]:
    defects: list[dict] = []
    for path, node in _walk((master_ir or {}).get("tree") or []):
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        width = _num(frame.get("width"))
        if str(node.get("text") or "") and width is not None:
            excess = _text_width(node) - width
            if excess > .5:
                defects.append({"path": path, "kind": "overflow", "px": round(excess, 2),
                                "viewport": viewport})
                style = node.get("style") if isinstance(node.get("style"), dict) else {}
                if str(style.get("overflow") or frame.get("overflow") or "") in {"hidden", "clip"}:
                    defects.append({"path": path, "kind": "clip", "px": round(excess, 2),
                                    "viewport": viewport})
        children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
        if frame.get("layout") == "free":
            rects = [(str(child.get("sourceKey") or f"{path}.children.{i}"), _rect(child))
                     for i, child in enumerate(children)]
            for i, (a_path, a) in enumerate(rects):
                if a is None:
                    continue
                ax, ay, aw, ah = a
                for b_path, b in rects[i + 1:]:
                    if b is None:
                        continue
                    bx, by, bw, bh = b
                    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
                    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
                    if ix > .5 and iy > .5:
                        defects.append({"path": b_path, "kind": "overlap",
                                        "px": round(min(ix, iy), 2), "otherPath": a_path,
                                        "viewport": viewport})
    return defects


def lint_master(master_ir: dict, *, page: Any = None,
                viewports: tuple[str, ...] = ("desktop", "tablet", "mobile")) -> list[dict]:
    """Return ``{path, kind, px, viewport}`` defects on three viewports."""
    if page is None:
        return [d for viewport in viewports for d in static_lint(master_ir, viewport)]
    import fidelity_harness
    from .document import preview_ir_for_master
    preview = preview_ir_for_master(master_ir)
    defects: list[dict] = []
    for viewport in viewports:
        width, height = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])
        root = (preview.get("tree") or [{}])[0]
        frame = root.get("frame") if isinstance(root, dict) and isinstance(root.get("frame"), dict) else {}
        width = max(240, int(_num(frame.get("width")) or width))
        height = max(320, int(_num(frame.get("height")) or height))
        measured = fidelity_harness.measure_layout(page, preview, viewport, width, height)
        for defect in measured.get("defects") or []:
            defects.append({**defect, "viewport": viewport})
    return defects


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
    width_jobs: dict[tuple[str, str], float] = {}
    overlap_jobs: dict[tuple[str, str], float] = {}
    for defect in defects:
        path, viewport = str(defect.get("path") or ""), str(defect.get("viewport") or "desktop")
        jobs = width_jobs if defect.get("kind") in {"overflow", "clip"} else overlap_jobs
        jobs[(path, viewport)] = max(jobs.get((path, viewport), 0.0), float(defect.get("px") or 0))
    changed_frames: set[int] = set()
    for (path, viewport), px in width_jobs.items():
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
        changed_frames.add(id(frame))
        old = _num(frame.get("width"))
        if old is None:
            continue
        delta = math.ceil(px + BUFFER_PX)
        frame["width"] = old + delta
        journal.append({"path": path, "viewport": viewport, "property": "width", "before": old,
                        "after": frame["width"], "reason": "overflow"})
        if parent is not None:
            pframe = parent.get("frame") if isinstance(parent.get("frame"), dict) else {}
            children = parent.get("children") or []
            if pframe.get("layout") == "free":
                for sibling in children[index + 1:]:
                    sf = sibling.get("frame") if isinstance(sibling, dict) and isinstance(sibling.get("frame"), dict) else None
                    sibling_override = ((sibling.get("responsive") or {}).get(viewport)
                                        if isinstance(sibling, dict) else None)
                    if isinstance(sibling_override, dict) and isinstance(sibling_override.get("frame"), dict):
                        sf = sibling_override["frame"]
                    if sf is not None and _num(sf.get("x")) is not None:
                        before = float(sf["x"]); sf["x"] = before + delta
                        journal.append({"path": sibling.get("sourceKey") or "", "viewport": viewport,
                                        "property": "x", "before": before, "after": sf["x"],
                                        "reason": "make-room"})
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


def _fidelity_passed(component: dict) -> bool:
    fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
    gate = fidelity.get("gate") if isinstance(fidelity.get("gate"), dict) else {}
    if "passed" in gate:
        return bool(gate["passed"])
    viewports = fidelity.get("viewports") if isinstance(fidelity.get("viewports"), dict) else {}
    return not viewports or all(bool((m or {}).get("sourceGatePassed", True)) for m in viewports.values())


def polish_component(component: dict, *, page: Any = None,
                     fidelity_check: Callable[[dict], bool] | None = None) -> dict:
    master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else None
    if master is None:
        return {"changed": False, "defectsBefore": [], "defectsAfter": [], "rounds": 0}
    before_defects = lint_master(master, page=page)
    candidate, journal = autofix(master, before_defects)
    after_defects = lint_master(candidate, page=page) if journal else list(before_defects)
    gate_ok = fidelity_check(candidate) if fidelity_check else _fidelity_passed(component)
    accepted = bool(journal and gate_ok and len(after_defects) < len(before_defects))
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
        fidelity["polish"] = {"defectsBefore": before_defects,
                              "defectsAfter": after_defects if accepted else before_defects,
                              "rounds": 1 if journal else 0, "accepted": accepted}
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
                    measured_fidelity: dict[str, float] = {}
                    fidelity_check = None
                    if page is not None:
                        def check_candidate(candidate: dict, component=component) -> bool:
                            import fidelity_harness
                            from . import master_review, styleguide
                            source, _size, _note = styleguide.proof_crop(
                                updated, component, "desktop", budget_left=4_000_000)
                            if not source:
                                return _fidelity_passed(component)
                            render_comp = {**component, "masterIr": candidate}
                            rendered = master_review.render_master_png(page, render_comp, "desktop")
                            # Source crops may be stored at capture DPR/scale.
                            # Compare like-sized rasters, matching the crop's
                            # measured pixel grid instead of failing by shape.
                            import io
                            from PIL import Image
                            reference = fidelity_harness._decode_data_url(source)
                            ref_image = Image.open(io.BytesIO(reference))
                            rendered_image = Image.open(io.BytesIO(rendered)).convert("RGB")
                            if rendered_image.size != ref_image.size:
                                rendered_image = rendered_image.resize(ref_image.size)
                                buffer = io.BytesIO()
                                rendered_image.save(buffer, format="PNG")
                                rendered = buffer.getvalue()
                            metrics = fidelity_harness._image_metrics(
                                reference, rendered)
                            similarity = metrics.get("pixel_similarity")
                            if similarity is None:
                                return False
                            measured_fidelity["pixelSimilarityAfter"] = float(similarity)
                            threshold = float(fidelity_harness.GATE_THRESHOLDS["min_pixel_similarity"])
                            return float(similarity) >= threshold
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
