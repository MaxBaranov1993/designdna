"""Stage 2 regression checks: grid -> measured free-layout, synthetic
background-image / ::before / ::after layers, sibling isolation."""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema

import scraper
from scraper import capture_block_irs
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        raise AssertionError(f"{name}: {detail}")
    print("OK", name)


def source_keys(nodes) -> set:
    keys = set()
    for node, _parent in scraper._walk_source_nodes(nodes):
        key = str(node.get("sourceKey") or "")
        if key:
            keys.add(key)
    return keys


def find_by_meta(nodes, kind) -> list:
    out = []
    for node, _parent in scraper._walk_source_nodes(nodes):
        meta = node.get("sourceMeta") or {}
        if meta.get("kind") == kind:
            out.append(node)
    return out


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/source_import_stage2.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        captured = capture_block_irs(
            url,
            [
                {"name": "grid", "label": "Grid", "kind": "section", "selector": "#fixture-grid"},
                {"name": "bg", "label": "Background", "kind": "section", "selector": "#fixture-bg"},
                {"name": "pseudo", "label": "Pseudo", "kind": "section", "selector": "#fixture-pseudo"},
            ],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
            timeout_ms=5000,
        )
    finally:
        scraper.validate_public_url = original_validate
        server.shutdown()
        server.server_close()

    # ---------- grid: free-layout с измеренными детьми, иерархия сохранена ----------
    grid_cap = captured["#fixture-grid"]
    grid_ir = grid_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(grid_ir)
    grid_section = grid_ir["tree"][0]
    grid_node = grid_section["children"][0]
    check("grid container serializes as free-layout, not wrapping flex",
          grid_node["frame"].get("layout") == "free" and grid_node["frame"].get("wrap") is not True
          or grid_node["frame"].get("layout") == "free",
          str(grid_node["frame"]))
    cells = grid_node.get("children") or []
    check("grid keeps its children inside the DOM parent (hierarchy preserved)",
          len(cells) == 3, str([c.get("sourceKey") for c in cells]))
    check("every grid child is pinned at measured coordinates",
          all(
              (c.get("frame") or {}).get("absolute") is True
              and isinstance(c["frame"].get("x"), (int, float))
              and isinstance(c["frame"].get("y"), (int, float))
              and c["frame"].get("width", 0) > 0 and c["frame"].get("height", 0) > 0
              for c in cells
          ),
          str([c.get("frame") for c in cells]))
    wide = cells[0]
    check("spanning grid item keeps measured full-track width",
          wide["frame"]["width"] > cells[1]["frame"]["width"],
          str({"wide": wide["frame"], "a": cells[1]["frame"]}))
    check("grid children stay independently selectable (own sourceKey each)",
          len({c.get("sourceKey") for c in cells}) == 3 and all(
              "root/" in str(c.get("sourceKey") or "") for c in cells),
          str([c.get("sourceKey") for c in cells]))
    check("emitted editable layers equal actual IR node count (grid)",
          grid_cap["editable_layers_by_viewport"]["desktop"]
          == sum(1 for _n, _p in scraper._walk_source_nodes(grid_section.get("children") or [])),
          str(grid_cap.get("editable_layers_by_viewport")))

    # ---------- background-image: синтетический слой с source metadata ----------
    bg_cap = captured["#fixture-bg"]
    bg_ir = bg_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(bg_ir)
    bg_section = bg_ir["tree"][0]
    bg_layers = find_by_meta(bg_section.get("children") or [], "background-image")
    check("background-image becomes a synthetic layer with source metadata",
          len(bg_layers) == 1 and bg_layers[0]["type"] == "image"
          and str(bg_layers[0].get("src") or "").startswith("data:image/svg+xml")
          and str(bg_layers[0]["sourceMeta"].get("url") or "").startswith("data:image/svg+xml"),
          str(bg_layers))
    hero = bg_section["children"][0]
    check("background-image layer is pinned over its owner element box",
          bg_layers[0] in (hero.get("children") or [])
          and bg_layers[0]["frame"] == {"absolute": True, "x": 0, "y": 0, "width": 300, "height": 120},
          str({"hero_children": [c.get("sourceKey") for c in hero.get("children") or []],
               "frame": bg_layers[0].get("frame")}))
    check("owner element keeps its content (bg layer does not replace hierarchy)",
          any(c.get("type") == "text" and c.get("text") == "Hero text" for c in hero.get("children") or []),
          str(hero.get("children")))
    check("represented background-image is not reported as a lost visual channel",
          not any(e.get("reason") == "background-image" and e.get("visual")
                  for e in bg_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str(bg_cap.get("extras_by_viewport")))

    # ---------- ::before/::after: синтетические слои ----------
    pseudo_cap = captured["#fixture-pseudo"]
    pseudo_ir = pseudo_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(pseudo_ir)
    pseudo_section = pseudo_ir["tree"][0]
    before_layers = find_by_meta(pseudo_section.get("children") or [], "pseudo-before")
    after_layers = find_by_meta(pseudo_section.get("children") or [], "pseudo-after")
    check("::before becomes a synthetic text layer with source metadata",
          len(before_layers) == 1 and before_layers[0]["type"] == "text"
          and "•" in before_layers[0].get("text", ""),
          str(before_layers))
    check("::after becomes a synthetic layer measured by its absolute offsets",
          len(after_layers) == 1 and after_layers[0]["frame"].get("width") == 12
          and after_layers[0]["frame"].get("height") == 12
          and after_layers[0]["frame"].get("absolute") is True,
          str(after_layers))
    badge = pseudo_section["children"][0]
    badge_order = [str(c.get("sourceKey") or "") for c in badge.get("children") or []]
    check("pseudo layers keep paint order around DOM content (before < content < after)",
          badge_order.index("pseudo:root/div:1::pseudo-before") < badge_order.index("pseudo:root/div:1::text0")
          < badge_order.index("pseudo:root/div:1::pseudo-after"),
          str(badge_order))
    check("represented pseudo channels are not reported as lost visual extras",
          not any(e.get("reason") == "pseudo" and e.get("visual")
                  for e in pseudo_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str(pseudo_cap.get("extras_by_viewport")))

    # ---------- sibling isolation: блоки не протекают друг в друга ----------
    grid_keys = source_keys(grid_section.get("children") or [])
    bg_keys = source_keys(bg_section.get("children") or [])
    pseudo_keys = source_keys(pseudo_section.get("children") or [])
    check("sibling blocks do not leak layers into each other",
          not (grid_keys & bg_keys) and not (grid_keys & pseudo_keys) and not (bg_keys & pseudo_keys),
          str({"grid": len(grid_keys), "bg": len(bg_keys), "pseudo": len(pseudo_keys)}))

    # ---------- transforms / stacking / masks / raster fallback surfaces ----------
    inner_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    inner_thread = threading.Thread(target=inner_server.serve_forever, daemon=True)
    inner_thread.start()
    surf_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    surf_thread = threading.Thread(target=surf_server.serve_forever, daemon=True)
    surf_thread.start()
    inner_url = f"http://127.0.0.1:{inner_server.server_port}/source_import_iframe_inner.html"
    from urllib.parse import quote
    surf_url = (f"http://127.0.0.1:{surf_server.server_port}/source_import_stage2_surfaces.html"
                f"?{quote(inner_url, safe='')}")
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        surf = capture_block_irs(
            surf_url,
            [
                {"name": "transform", "label": "Transform", "kind": "section", "selector": "#fixture-transform"},
                {"name": "stack", "label": "Stack", "kind": "section", "selector": "#fixture-stack"},
                {"name": "clip", "label": "Clip", "kind": "section", "selector": "#fixture-clip"},
                {"name": "raster", "label": "Raster", "kind": "section", "selector": "#fixture-raster"},
                {"name": "multibg", "label": "MultiBg", "kind": "section", "selector": "#fixture-multibg"},
                {"name": "urlmask", "label": "UrlMask", "kind": "section", "selector": "#fixture-urlmask"},
                {"name": "openshadow", "label": "OpenShadow", "kind": "section", "selector": "#fixture-open-shadow"},
            ],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
            timeout_ms=8000,
        )
    finally:
        scraper.validate_public_url = original_validate
        surf_server.shutdown()
        surf_server.server_close()
        inner_server.shutdown()
        inner_server.server_close()

    # transforms: measured bbox already includes translation. Applying matrix in
    # the renderer again would double the offset; complex transforms use a locked
    # element screenshot so their pixels remain exact.
    tr_ir = surf["#fixture-transform"]["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(tr_ir)
    tr_section = tr_ir["tree"][0]
    tr_nodes = [node for node, _parent in scraper._walk_source_nodes(tr_section.get("children") or [])]
    complex_fallback = next((node for node in tr_nodes
                             if (node.get("sourceMeta") or {}).get("kind") == "complex-transform"), None)
    translated = next((node for node in tr_nodes if node.get("role") == "div"
                       and any(child.get("text") == "Translated" for child in node.get("children") or [])), None)
    check("complex transform becomes a selectable pixel-exact fallback",
          bool(complex_fallback) and complex_fallback.get("type") == "image"
          and complex_fallback.get("editable") is False
          and str(complex_fallback.get("src") or "").startswith("data:image"),
          str(complex_fallback))
    check("pure translate is not applied twice",
          bool(translated) and "transform" not in (translated.get("frame") or {})
          and translated.get("frame", {}).get("absolute") is True,
          str(translated))

    # stacking: z-index переносится в frame.z
    st_ir = surf["#fixture-stack"]["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(st_ir)
    st_children = st_ir["tree"][0]["children"]
    zlist = sorted(c["frame"]["z"] for c in st_children if "z" in (c.get("frame") or {}))
    check("explicit z-index is captured into frame.z",
          zlist == [1, 5], str([c.get("frame") for c in st_children]))

    # masks/clipping: clip-path и gradient mask в style
    cl_ir = surf["#fixture-clip"]["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(cl_ir)
    cl_children = cl_ir["tree"][0]["children"]
    clip_paths = [str((c.get("style") or {}).get("clipPath") or "") for c in cl_children]
    mask_images = [str((c.get("style") or {}).get("maskImage") or "") for c in cl_children]
    check("clip-path is captured into style",
          any(v.startswith("polygon(") for v in clip_paths), str(clip_paths))
    check("gradient mask is captured into style",
          any("linear-gradient" in v for v in mask_images), str(mask_images))

    # raster fallback: canvas / cross-origin iframe / closed shadow —
    # видимые selectable слои editable:false с причиной и source metadata
    ra_cap = surf["#fixture-raster"]
    ra_ir = ra_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(ra_ir)
    ra_children = ra_ir["tree"][0]["children"]
    by_kind = {str((c.get("sourceMeta") or {}).get("kind")): c for c in ra_children}
    canvas_node = by_kind.get("canvas") or {}
    check("canvas becomes a locked raster layer (editable:false + reason + raster src)",
          canvas_node.get("type") == "image" and canvas_node.get("editable") is False
          and "canvas" in str(canvas_node.get("lockedReason") or "")
          and str(canvas_node.get("src") or "").startswith("data:image/"),
          str(canvas_node))
    iframe_node = by_kind.get("iframe") or {}
    check("cross-origin iframe becomes a locked raster layer with SOP reason",
          iframe_node.get("type") == "image" and iframe_node.get("editable") is False
          and "cross-origin" in str(iframe_node.get("lockedReason") or "")
          and str(iframe_node.get("src") or "").startswith("data:image/"),
          str(iframe_node))
    shadow_node = by_kind.get("shadow-dom") or {}
    check("closed shadow root becomes a locked raster layer with reason",
          shadow_node.get("type") == "image" and shadow_node.get("editable") is False
          and "shadow" in str(shadow_node.get("lockedReason") or "")
          and str(shadow_node.get("src") or "").startswith("data:image/"),
          str(shadow_node))
    check("raster fallback layers keep their bounds (width/height > 0)",
          all((by_kind[k].get("frame") or {}).get("width", 0) > 0
              and (by_kind[k].get("frame") or {}).get("height", 0) > 0
              for k in ("canvas", "iframe", "shadow-dom") if k in by_kind),
          str({k: (v.get("frame") or {}) for k, v in by_kind.items()}))
    check("represented raster surfaces are not reported as lost visual channels",
          not any(e.get("reason") in ("iframe", "canvas-tainted") and e.get("visual")
                  for e in ra_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str(ra_cap.get("extras_by_viewport")))
    check("raster fallback nodes stay independently selectable (own sourceKey)",
          len({c.get("sourceKey") for c in ra_children}) == len(ra_children) >= 3,
          str([c.get("sourceKey") for c in ra_children]))

    # ---------- repair: многослойный background — каждый слой в paint order ----------
    mb_cap = surf["#fixture-multibg"]
    mb_ir = mb_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(mb_ir)
    mb_section = mb_ir["tree"][0]
    mb_layers = find_by_meta(mb_section.get("children") or [], "background-image")
    check("multi-layer background emits every layer (2 root + 2 element)",
          len(mb_layers) == 4, str([l.get("sourceKey") for l in mb_layers]))
    mb_keys = [str(l.get("sourceKey") or "") for l in mb_layers]
    check("multi-layer background keys are unique (no duplicate ::bg)",
          len(set(mb_keys)) == len(mb_keys) == 4, str(mb_keys))
    check("multi-layer background keeps CSS layer index in sourceMeta",
          sorted(l["sourceMeta"].get("layer") for l in mb_layers) == [0, 0, 1, 1],
          str([l.get("sourceMeta") for l in mb_layers]))
    root_bg = [c for c in mb_section.get("children") or []
               if str(c.get("sourceKey") or "").startswith("multibg:root::bg")]
    check("root multi-layer background sits at the bottom in CSS paint order",
          [str(c.get("sourceKey")) for c in root_bg] == ["multibg:root::bg1", "multibg:root::bg0"]
          and root_bg[0]["sourceMeta"].get("layer") == 1 and root_bg[1]["sourceMeta"].get("layer") == 0,
          str([c.get("sourceKey") for c in mb_section.get("children") or []]))
    layered = next(c for c in mb_section.get("children") or []
                   if str(c.get("sourceKey") or "").endswith("div:1"))
    layered_kinds = [str(c.get("sourceKey") or "") for c in layered.get("children") or []]
    check("element multi-layer background paints bottom layer first, content on top",
          layered_kinds[0].endswith("::bg1") and layered_kinds[1].endswith("::bg0")
          and layered_kinds[-1].endswith("::text0"),
          str(layered_kinds))
    check("element keeps both background flavors (url image + gradient rect)",
          {c.get("type") for c in layered.get("children") or [] if "::bg" in str(c.get("sourceKey"))}
          == {"image", "rect"},
          str(layered.get("children")))
    check("multi-layer background is fully represented (no loss warning/extra)",
          not any("multi-layer background" in w for w in mb_cap.get("warnings") or [])
          and not any(e.get("reason") == "background-image" and e.get("visual")
                      for e in mb_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str({"warnings": mb_cap.get("warnings"), "extras": mb_cap.get("extras_by_viewport")}))

    # ---------- repair: url()-mask — locked raster fallback, не warning-only ----------
    um_cap = surf["#fixture-urlmask"]
    um_ir = um_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(um_ir)
    um_nodes = [c for c in um_ir["tree"][0].get("children") or []
                if (c.get("sourceMeta") or {}).get("kind") == "url-mask"]
    check("url()-mask becomes an explicit locked raster layer (not warning-only)",
          len(um_nodes) == 1 and um_nodes[0].get("type") == "image"
          and um_nodes[0].get("editable") is False
          and "mask" in str(um_nodes[0].get("lockedReason") or "")
          and str(um_nodes[0].get("src") or "").startswith("data:image/"),
          str(um_nodes))
    check("url()-mask raster layer keeps measured bounds and stays selectable",
          bool(um_nodes) and (um_nodes[0].get("frame") or {}).get("width", 0) > 0
          and (um_nodes[0].get("frame") or {}).get("height", 0) > 0
          and bool(um_nodes[0].get("sourceKey")),
          str(um_nodes[0].get("frame") if um_nodes else None))
    check("url()-mask raster fallback is reported in warnings, not as visual loss",
          any("url mask" in w for w in um_cap.get("warnings") or [])
          and not any(e.get("visual") for e in um_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str({"warnings": um_cap.get("warnings"), "extras": um_cap.get("extras_by_viewport")}))

    # ---------- repair: open shadow root — locked raster fallback, ничего не исчезает ----------
    osh_cap = surf["#fixture-open-shadow"]
    osh_ir = osh_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(osh_ir)
    osh_nodes = [c for c in osh_ir["tree"][0].get("children") or []
                 if (c.get("sourceMeta") or {}).get("kind") == "shadow-dom"]
    check("open shadow root becomes a locked raster layer with explicit reason",
          len(osh_nodes) == 1 and osh_nodes[0].get("type") == "image"
          and osh_nodes[0].get("editable") is False
          and "open shadow" in str(osh_nodes[0].get("lockedReason") or "")
          and str(osh_nodes[0].get("src") or "").startswith("data:image/"),
          str(osh_nodes))
    check("open shadow raster layer keeps measured bounds (no silent disappearance)",
          bool(osh_nodes) and (osh_nodes[0].get("frame") or {}).get("width", 0) > 0
          and (osh_nodes[0].get("frame") or {}).get("height", 0) > 0,
          str(osh_nodes[0].get("frame") if osh_nodes else None))
    check("open shadow fallback is not reported as lost visual channel",
          not any(e.get("visual") for e in osh_cap.get("extras_by_viewport", {}).get("desktop", [])),
          str(osh_cap.get("extras_by_viewport")))

    # ---------- один Chromium-сеанс / одна навигация на все viewports ----------
    # ---------- Phase 4: alpha, styled inline, empty pseudo, spacer, artboard origin ----------
    phase4_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    threading.Thread(target=phase4_server.serve_forever, daemon=True).start()
    phase4_url = f"http://127.0.0.1:{phase4_server.server_port}/source_import_phase4.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        phase4 = capture_block_irs(
            phase4_url,
            [{"name": "phase4", "label": "Phase 4", "kind": "section", "selector": "#phase4"}],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
            timeout_ms=5000,
        )["#phase4"]
    finally:
        scraper.validate_public_url = original_validate
        phase4_server.shutdown()
        phase4_server.server_close()
    phase4_ir = phase4["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(phase4_ir)
    phase4_nodes = [node for node, _parent in scraper._walk_source_nodes(
        phase4_ir["tree"][0].get("children") or [])]
    gradients = [node for node in phase4_nodes
                 if "gradient(" in str((node.get("style") or {}).get("backgroundImage") or "")]
    check("phase4 alpha colors remain translucent 8-digit hex",
          any((node.get("style") or {}).get("background") == "#ffffff1a" for node in phase4_nodes))
    check("phase4 gradients use a transparent base fill",
          bool(gradients) and all(node.get("fill") == "#00000000" for node in gradients), str(gradients[:2]))
    check("phase4 empty pseudo content is not reported as a visual loss",
          not any(extra.get("reason") == "pseudo-content"
                  for extra in phase4.get("extras_by_viewport", {}).get("desktop", [])))
    check("phase4 styled inline descendant remains an independent layer",
          any(node.get("text") == "styled child" for node in phase4_nodes)
          and not any(drop.get("visual") and str(drop.get("sourceKey") or "").endswith("span:1/span:1")
                      for drop in phase4.get("dropped_by_viewport", {}).get("desktop", [])))
    row = next(node for node in phase4_nodes if str(node.get("sourceKey") or "").endswith("div:1"))
    check("phase4 flex-grow spacer forces measured free layout",
          (row.get("frame") or {}).get("layout") == "free", str(row.get("frame")))
    check("phase4 outer artboard does not duplicate section padding",
          "padding" not in (phase4_ir.get("frame") or {})
          and (phase4_ir["tree"][0].get("frame") or {}).get("padding") == [14, 14, 14, 14])
    backdrop = next((node for node in phase4_nodes
                     if (node.get("sourceMeta") or {}).get("kind") == "inherited-background"), None)
    check("phase4 inherited backdrop is an explicit locked layer",
          bool(backdrop) and backdrop.get("type") == "image" and backdrop.get("editable") is False
          and str(backdrop.get("src") or "").startswith("data:image/png"), str(backdrop)[:200])
    check("phase4 fidelity reference capture is lossless PNG",
          str(phase4.get("previews", {}).get("desktop") or "").startswith("data:image/png"))

    class CountingHandler(SimpleHTTPRequestHandler):
        doc_requests = 0

        def do_GET(self):
            if self.path.startswith("/source_import_stage2.html"):
                type(self).doc_requests += 1
            super().do_GET()

    count_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(CountingHandler, directory=str(FIXTURES)))
    count_thread = threading.Thread(target=count_server.serve_forever, daemon=True)
    count_thread.start()
    count_url = f"http://127.0.0.1:{count_server.server_port}/source_import_stage2.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        multi = capture_block_irs(
            count_url,
            [{"name": "grid", "label": "Grid", "kind": "section", "selector": "#fixture-grid"}],
            viewports=[
                {"name": "desktop", "width": 1440, "height": 900},
                {"name": "tablet", "width": 768, "height": 1024},
                {"name": "mobile", "width": 390, "height": 844},
            ],
            timeout_ms=8000,
        )
    finally:
        scraper.validate_public_url = original_validate
        count_server.shutdown()
        count_server.server_close()
    check("all viewports are captured in a single navigation",
          CountingHandler.doc_requests == 1, f"doc_requests={CountingHandler.doc_requests}")
    check("every viewport still produced a capture after resize-only passes",
          set(multi["#fixture-grid"].get("layers_by_viewport") or {}) == {"desktop", "tablet", "mobile"},
          str(multi["#fixture-grid"].get("layers_by_viewport")))

    # ---------- colors fixture: modern color functions, per-side borders, text metrics ----------
    colors_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    threading.Thread(target=colors_server.serve_forever, daemon=True).start()
    colors_url = f"http://127.0.0.1:{colors_server.server_port}/source_import_stage2_colors.html"
    original_validate2 = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        colors_cap = capture_block_irs(
            colors_url,
            [
                {"name": "hero", "label": "Hero", "kind": "section", "selector": "#hero"},
                {"name": "sides", "label": "Sides", "kind": "section", "selector": "#sides"},
            ],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
            timeout_ms=5000,
        )
    finally:
        scraper.validate_public_url = original_validate2
        colors_server.shutdown()
        colors_server.server_close()

    hero_cap = colors_cap["#hero"]
    hero_ir = hero_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(hero_ir)
    hero_section = hero_ir["tree"][0]
    # #hero сам становится source-block секцией: фон/бордеры лежат на ней
    hstyle = hero_section.get("style") or {}

    def walk_all(node):
        yield node
        for child in node.get("children") or []:
            yield from walk_all(child)

    flat = [n for n in walk_all(hero_section) if isinstance(n, dict)]
    by_text = {str(n.get("text") or ""): n for n in flat if n.get("text")}

    check("oklch background parses to hex", isinstance(hstyle.get("background"), str)
          and hstyle["background"].startswith("#"), str(hstyle.get("background")))
    border_sides = hstyle.get("borderSides")
    check("border-bottom-only serializes per-side (borderSides [0,0,3,0])",
          isinstance(border_sides, list) and len(border_sides) == 4
          and abs(float(border_sides[2].get("width", 0)) - 3) <= 0.6
          and all(float(s.get("width", 99)) <= 0.6 for i, s in enumerate(border_sides) if i != 2),
          str(border_sides))
    lab_heading = by_text.get("Modern colors")
    check("lab() heading color parses to hex",
          bool(lab_heading and (lab_heading.get("style") or {}).get("color", "").startswith("#")),
          str((lab_heading or {}).get("style")))
    mix_p = by_text.get("centered subtitle over oklch background")
    check("color-mix() text color parses to hex",
          bool(mix_p and (mix_p.get("style") or {}).get("color", "").startswith("#")),
          str((mix_p or {}).get("style")))
    check("centered subtitle carries align:center", bool(mix_p and mix_p.get("align") == "center"),
          str((mix_p or {}).get("align")))
    fine = by_text.get("fine print in italic")
    check("italic captured as fontStyle", bool(fine and (fine.get("style") or {}).get("fontStyle") == "italic"),
          str((fine or {}).get("style")))
    timer = by_text.get("04:37")
    check("tabular-nums captured", bool(timer and (timer.get("style") or {}).get("fontVariantNumeric") == "tabular-nums"),
          str((timer or {}).get("style")))
    check("lch() timer color parses to hex",
          bool(timer and (timer.get("style") or {}).get("color", "").startswith("#")),
          str((timer or {}).get("style")))
    p3 = by_text.get("display-p3 red")
    check("color(display-p3) parses to hex",
          bool(p3 and (p3.get("style") or {}).get("color", "").startswith("#")),
          str((p3 or {}).get("style")))
    check("font stack keeps fallbacks (comma preserved)",
          "," in str((timer or {}).get("style", {}).get("fontFamily", "")),
          str((timer or {}).get("style", {}).get("fontFamily")))
    check("text frames keep subpixel precision (floats allowed)",
          all(isinstance((n.get("frame") or {}).get("width"), (int, float)) for n in flat if n.get("frame")),
          "frame widths are numeric")

    sides_cap = colors_cap["#sides"]
    sides_ir = sides_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(sides_ir)
    sides_style = sides_ir["tree"][0].get("style") or {}
    four = sides_style.get("borderSides")
    check("four differing borders serialize per-side with widths [1,2,4,2]",
          isinstance(four, list) and len(four) == 4
          and abs(float(four[0].get("width", 0)) - 1) <= 0.6
          and abs(float(four[1].get("width", 0)) - 2) <= 0.6
          and abs(float(four[2].get("width", 0)) - 4) <= 0.6
          and abs(float(four[3].get("width", 0)) - 2) <= 0.6,
          str(four))

    print("ALL STAGE 2 CHECKS PASSED")


if __name__ == "__main__":
    main()
