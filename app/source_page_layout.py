"""Source-faithful page assembly (Python mirror of frontend/src/flow/source-layout.ts).

A captured Source section keeps its document rectangle in ``meta.pageRect``.
For the Page node every such section becomes a full-width *band*:

* the band is a transparent ``free`` section as wide as the page; the source
  page background (often a body gradient) is painted once on the page root
  (``meta.pageBackground``), so bands and foreign sections share it;
* inside it one container (``card``) carries the original section box —
  style, clip, padding, children, responsive overrides — at its original ``x``;
* consecutive bands from the same capture keep the original vertical gaps and
  overlaps: a band is exactly as tall as the distance to the next captured
  section (the container may overflow into the next band);
* any foreign section (Generator, Mix, ...) inserted between bands flows
  normally and pushes the following bands down.

The algorithm is deliberately identical in both languages; the tests in
``source_page_layout_test.py`` and ``frontend/tests/source-layout.test.mjs``
use the same fixture.
"""
from __future__ import annotations

import copy

DESKTOP_WIDTH = 1440


def _rect(ir: dict, viewport: str | None = None) -> dict | None:
    meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
    if viewport:
        by_viewport = meta.get("pageRectByViewport") if isinstance(meta.get("pageRectByViewport"), dict) else {}
        rect = by_viewport.get(viewport)
        if isinstance(rect, dict):
            return rect
    rect = meta.get("pageRect")
    return rect if isinstance(rect, dict) else None


def bandable(ir: dict) -> bool:
    tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
    if len(tree) != 1 or not isinstance(tree[0], dict) or not _rect(ir):
        return False
    return (tree[0].get("frame") or {}).get("layout") == "free"


def band_section(section: dict, ir: dict) -> dict:
    """Wrap one captured section into a full-width band (heights fixed later)."""
    rect = _rect(ir) or {}
    frame = dict(section.get("frame") or {})
    box_frame = {**frame, "absolute": True, "x": round(float(rect.get("x") or 0), 2), "y": 0,
                 "width": round(float(rect.get("width") or frame.get("width") or DESKTOP_WIDTH), 2)}
    if not isinstance(box_frame.get("height"), (int, float)):
        box_frame["height"] = round(float(rect.get("height") or 0), 2)
    box = {
        "type": "card",
        # role marks a captured DOM box: the renderer draws it exactly as styled,
        # without the generated-card surface, border, padding and shadow
        "role": "section",
        "sourceKey": f"{section.get('sourceKey') or 'root'}::box",
        "sourceMeta": {"kind": "dom", "reason": "source section box placed at its page position"},
        "style": copy.deepcopy(section.get("style") or {}),
        "frame": box_frame,
        "children": section.get("children") or [],
    }
    responsive = copy.deepcopy(section.get("responsive")) if isinstance(section.get("responsive"), dict) else {}
    meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
    for viewport, vp_rect in (meta.get("pageRectByViewport") or {}).items():
        if not isinstance(vp_rect, dict) or viewport == "desktop":
            continue
        override = responsive.setdefault(viewport, {})
        override["frame"] = {**(override.get("frame") or {}), "x": round(float(vp_rect.get("x") or 0), 2), "y": 0,
                             "absolute": True}
    if responsive:
        box["responsive"] = responsive
    band = {key: copy.deepcopy(value) for key, value in section.items()
            if key not in ("style", "frame", "children", "responsive")}
    band["style"] = {}  # transparent: the page background is painted once on the page root
    band["frame"] = {"width": "fill", "height": box_frame["height"], "layout": "free", "direction": "column",
                     "gap": 0, "padding": 0, "justify": "start", "align": "start"}
    band["children"] = [box]
    return band


def settle_band_heights(entries: list[dict]) -> None:
    """entries: [{"section": band-or-foreign, "ir": ir, "band": bool}] in page order.

    A band's height becomes the distance to the next band of the same capture
    (per viewport), so gaps and overlaps of the source page are preserved.
    """
    for index, entry in enumerate(entries):
        if not entry["band"]:
            continue
        following = entries[index + 1] if index + 1 < len(entries) else None
        if not following or not following["band"]:
            continue
        here, there = _rect(entry["ir"]) or {}, _rect(following["ir"]) or {}
        if not here.get("source") or here.get("source") != there.get("source"):
            continue
        band = entry["section"]
        distance = float(there.get("y") or 0) - float(here.get("y") or 0)
        box_height = float(band["children"][0]["frame"].get("height") or 0)
        band["frame"]["height"] = round(max(1.0, distance), 2)
        if distance < box_height:
            band["frame"]["clip"] = False
        by_viewport = (entry["ir"].get("meta") or {}).get("pageRectByViewport") or {}
        next_by_viewport = (following["ir"].get("meta") or {}).get("pageRectByViewport") or {}
        for viewport, vp_rect in by_viewport.items():
            if viewport == "desktop" or not isinstance(vp_rect, dict) or not isinstance(next_by_viewport.get(viewport), dict):
                continue
            vp_distance = float(next_by_viewport[viewport].get("y") or 0) - float(vp_rect.get("y") or 0)
            band.setdefault("responsive", {}).setdefault(viewport, {})["frame"] = {"height": round(max(1.0, vp_distance), 2)}


def page_background_of(entries: list[dict]) -> str | None:
    """The site's page background, painted once on the page root (meta.pageBackground)."""
    for entry in entries:
        meta = entry["ir"].get("meta") if entry["band"] and isinstance(entry["ir"].get("meta"), dict) else {}
        value = meta.get("pageBackground")
        if isinstance(value, str) and value.strip():
            return value
    return None


def compose_source_page(blocks: list[dict], tokens: dict | None = None, width: int = DESKTOP_WIDTH) -> dict:
    """Blocks as returned by Source Import (``{"name", "ir"}``) → one page IR."""
    tree: list[dict] = []
    faces: dict[str, dict] = {}
    entries: list[dict] = []
    for block in blocks:
        ir = block.get("ir") if isinstance(block.get("ir"), dict) else None
        if not ir:
            continue
        meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
        for face in meta.get("fontFaces") or []:
            if isinstance(face, dict):
                faces[repr(sorted(face.items()))] = face
        if bandable(ir):
            band = band_section(ir["tree"][0], ir)
            entries.append({"section": band, "ir": ir, "band": True})
            tree.append(band)
            continue
        for section in ir.get("tree") or []:
            if not isinstance(section, dict):
                continue
            s = copy.deepcopy(section)
            frame = dict(s.get("frame") or {})
            for key in ("x", "y", "absolute"):
                frame.pop(key, None)
            frame["width"] = "fill"
            s["frame"] = frame
            entries.append({"section": s, "ir": ir, "band": False})
            tree.append(s)
    settle_band_heights(entries)
    page_background = page_background_of(entries)
    return {
        "version": "1.1",
        "meta": {"name": "Page", **({"fontFaces": list(faces.values())} if faces else {}),
                 **({"pageBackground": page_background} if page_background else {})},
        "frame": {"width": width, "height": "hug", "layout": "auto", "direction": "column"},
        "tokens": copy.deepcopy(tokens or {}),
        "tree": tree,
    }
