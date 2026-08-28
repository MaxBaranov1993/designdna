"""Deterministic Source Import semantics regression checks."""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema

import blockparse
import scraper
from scraper import _captured_ir, _merge_responsive_irs, capture_block_irs, detect_blocks
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        raise AssertionError(f"{name}: {detail}")
    print("OK", name)


def main() -> None:
    original_cookie_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        cookies = scraper._normalize_source_cookies([
            {"name": "session", "value": "secret", "domain": ".example.com", "path": "/", "secure": True},
            {"name": "foreign", "value": "drop", "domain": ".evil.test", "path": "/"},
            {"name": "bad name", "value": "drop", "domain": ".example.com", "path": "/"},
        ], "https://app.example.com/private")
    finally:
        scraper.validate_public_url = original_cookie_validate
    check("authenticated cookies are host-scoped and sanitized",
          [cookie["name"] for cookie in cookies] == ["session"], str(cookies))

    html = """
    <html><body>
      <header><nav><a>Catalog</a><a>Journal</a></nav></header>
      <main>
        <div class="carousel-wrapper"><article class="slide active">A</article><article class="slide">B</article></div>
        <nav class="category-grid"><a>Cars</a><a>Homes</a></nav>
        <section id="products" class="listing-section product-grid">
          <h2>New products</h2><div class="grid">
            <article class="card">One</article><article class="card">Two</article><article class="card">Three</article>
          </div>
        </section>
        <section class="journal-section"><section class="journal-panel"><h2>Journal</h2></section></section>
        <section class="how"><h2>How it works</h2></section>
        <section class="faq"><h2>Frequently asked questions</h2></section>
      </main>
      <footer><div class="seller-cta">Nested CTA</div></footer>
    </body></html>
    """
    blocks = detect_blocks(html)
    kinds = [b["kind"] for b in blocks]
    check("semantic order", kinds == ["header", "carousel", "categories", "product-grid", "journal", "how-it-works", "faq", "footer"], str(kinds))
    check("repeated articles are not outputs", all("article" not in b["selector"] for b in blocks), str(blocks))
    check("nested journal and footer CTA deduplicated", kinds.count("journal") == 1 and kinds.count("cta") == 0, str(kinds))

    shell_html = """
    <html><body><div id="shell" class="shell">
      <nav id="rail" class="shell-rail"><button>Hub</button><button>Archive</button></nav>
      <section id="content"><h2>Arena</h2><p>Main content remains separate.</p></section>
      <div id="act" class="shell-act"><div role="status">Connection stable</div></div>
    </div></body></html>
    """
    shell_blocks = detect_blocks(shell_html)
    shell_by_selector = {b["selector"]: b for b in shell_blocks}
    check("top-level nav becomes an independent navigation block",
          shell_by_selector['[id="rail"]']["kind"] == "navigation", str(shell_blocks))
    check("stable shell action bar becomes an independent status block",
          shell_by_selector['[id="act"]']["kind"] == "status", str(shell_blocks))
    check("nested status landmark is deduplicated under its shell action bar",
          sum(1 for b in shell_blocks if b["kind"] == "status") == 1, str(shell_blocks))
    shell_capture = {
        "root": {"width": 320, "height": 64, "style": {"background": "#101014"}},
        "nodes": [{"type": "text", "text": "Shell", "sourceKey": "root/span:1",
                   "frame": {"width": 50, "height": 18}}],
    }
    for selector in ('[id="rail"]', '[id="act"]'):
        jsonschema.Draft7Validator(SCHEMA).validate(_captured_ir(shell_by_selector[selector], shell_capture))
    check("navigation and status roles are valid Source IR semantics", True)

    block = {"name": "product-grid", "label": "New products", "kind": "product-grid", "selector": "#products"}
    capture = {
        "root": {"width": 1200, "height": 400, "style": {"background": "#ffffff", "color": "#111111"}},
        "layers": [{"kind": "text", "x": 20, "y": 20, "width": 200, "height": 30, "text": "New products", "style": {"color": "#111111"}}],
        "repeat": {"count": 3, "kind": "card"},
        "preview": "data:image/jpeg;base64,source-preview",
    }
    ir = _captured_ir(block, capture)
    jsonschema.Draft7Validator(SCHEMA).validate(ir)
    frame = ir["frame"]
    check("legacy source block keeps its measured free artboard",
          frame["width"] == 1200 and frame["height"] == 400 and frame["layout"] == "free" and frame["clip"],
          str(frame))
    semantic = ir["tree"][0]["semantic"]
    check("source-block semantic metadata", semantic["role"] == "product-grid" and semantic["repeatCount"] == 3, str(semantic))
    check("source preview stays outside canonical IR and is attached by the Source output",
          "sourcePreview" not in ir and "sourcePreview" not in ir["tree"][0]["props"],
          str(ir.get("sourcePreview")))

    button_capture = {
        "root": {"width": 300, "height": 80, "style": {"background": "#ffffff", "color": "#111111"}},
        "layers": [
            {"kind": "container", "id": "btn1", "role": "button", "x": 40, "y": 20,
             "width": 90, "height": 36, "text": "Find",
             "style": {"background": "#f97316", "color": "#ffffff", "fontSize": 13}},
            {"kind": "text", "parentId": "btn1", "x": 58, "y": 32,
             "width": 40, "height": 16, "text": "Find",
             "style": {"color": "#ffffff", "fontSize": 13}},
        ],
        "preview": "data:image/jpeg;base64,source-preview",
    }
    button_ir = _captured_ir(block, button_capture)
    jsonschema.Draft7Validator(SCHEMA).validate(button_ir)
    button = button_ir["tree"][0]["children"][1]
    check("captured button is a parent layer", button["type"] == "button" and len(button["children"]) == 1, str(button))
    check("captured button text is nested relative to parent",
          button["children"][0]["frame"]["x"] == 18 and button["children"][0]["frame"]["y"] == 12,
          str(button["children"][0]["frame"]))

    structured_capture = {
        "root": {"width": 900, "height": 72, "style": {"background": "#ffffff"}},
        "sourceKey": "root", "direction": "row", "gap": 12, "padding": [8, 16, 8, 16],
        "nodes": [{
            "type": "card", "role": "form", "sourceKey": "root/form:1",
            "frame": {"width": 520, "height": 48, "layout": "auto", "direction": "row", "gap": 8},
            "children": [{
                "type": "button", "text": "Find", "sourceKey": "root/form:1/button:1",
                "frame": {"width": 90, "height": 40, "layout": "auto", "direction": "row", "gap": 0},
                "children": [{"type": "text", "text": "Find", "sourceKey": "root/form:1/button:1::text0",
                              "frame": {"width": 32, "height": 16}}],
            }],
        }],
    }
    structured_ir = _captured_ir(block, structured_capture)
    jsonschema.Draft7Validator(SCHEMA).validate(structured_ir)
    structured_section = structured_ir["tree"][0]
    nested_button = structured_section["children"][0]["children"][0]
    check("structured capture keeps compact auto-layout",
          structured_ir["frame"]["layout"] == "auto" and structured_section["frame"]["direction"] == "row",
          str(structured_section["frame"]))
    check("structured button owns its text",
          nested_button["type"] == "button" and nested_button["children"][0]["text"] == "Find",
          str(nested_button))

    mobile_variant = json.loads(json.dumps(structured_ir))
    mobile_variant["frame"]["width"] = 390
    mobile_variant["tree"][0]["frame"]["width"] = 390
    mobile_variant["tree"][0]["children"][0]["frame"]["direction"] = "column"
    mobile_variant["tree"][0]["children"].append({
        "type": "button", "text": "Menu", "sourceKey": "root/button:mobile",
        "frame": {"width": 44, "height": 40, "layout": "auto", "direction": "row"},
        "children": [{"type": "text", "text": "Menu", "sourceKey": "root/button:mobile::text0",
                      "frame": {"width": 34, "height": 16}}],
    })
    merged = _merge_responsive_irs(
        {"desktop": structured_ir, "mobile": mobile_variant},
        {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}},
    )
    jsonschema.Draft7Validator(SCHEMA).validate(merged)
    mobile_only = merged["tree"][0]["children"][-1]
    check("responsive merge keeps one shared tree",
          mobile_only["responsive"]["desktop"]["visible"] is False and
          mobile_only["responsive"]["mobile"]["visible"] is True,
          str(mobile_only.get("responsive")))

    # Раньше слияние viewport-only веток давало дубли sourceKey: потомок
    # клонируемой ветки перекрывал существующий ключ базового дерева.
    def mini_ir(children):
        return {
            "version": "1.0",
            "tokens": {"mode": "light",
                       "color": {"primary": "#111111", "background": "#ffffff", "surface": "#ffffff",
                                 "text": "#111111", "textMuted": "#666666", "border": "#dddddd"},
                       "font": {"display": {"family": "Inter", "weight": 700},
                                "body": {"family": "Inter", "weight": 400}, "scale": "default"},
                       "radius": {"card": "md", "button": "md", "input": "md"},
                       "spacing": {"section": "md", "container": "default"}, "shadow": "none"},
            "tree": [{"id": "blk", "type": "source-block", "variant": "dom-capture",
                      "props": {}, "sourceKey": "root", "children": children}],
        }

    shared_card = {"type": "card", "role": "div", "sourceKey": "root/div:1",
                   "frame": {"width": 400, "height": 100, "layout": "auto", "direction": "column"},
                   "children": [{"type": "text", "text": "shared", "sourceKey": "root/div:1/span:1",
                                 "frame": {"width": 60, "height": 16}}]}
    dup_desktop = mini_ir([shared_card])
    dup_mobile = mini_ir([json.loads(json.dumps(shared_card)), {
        "type": "card", "role": "div", "sourceKey": "root/div:2",
        "frame": {"width": 300, "height": 80, "layout": "auto", "direction": "column"},
        # ключ-призрак из другого viewport: совпадает с потомком базового дерева
        "children": [{"type": "text", "text": "bleed", "sourceKey": "root/div:1/span:1",
                      "frame": {"width": 40, "height": 16}}],
    }])
    dup_merged = _merge_responsive_irs(
        {"desktop": dup_desktop, "mobile": dup_mobile},
        {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}},
    )
    jsonschema.Draft7Validator(SCHEMA).validate(dup_merged)
    dup_keys = [key for key in (str(node.get("sourceKey") or "")
                                for node, _parent in scraper._walk_source_nodes(dup_merged["tree"])) if key]
    check("merge enforces unique sourceKey after viewport bleed",
          len(dup_keys) == len(set(dup_keys)), str(dup_keys))
    check("merge renames duplicate instead of dropping content",
          any(node.get("text") == "bleed" for node, _p in scraper._walk_source_nodes(dup_merged["tree"]))
          and any(key.endswith("#001") for key in dup_keys),
          str(dup_keys))

    # Private captures must never read or write shared Source Import caches.
    auth_ir = mini_ir([{"type": "text", "text": "Private", "sourceKey": "root/span:1",
                        "frame": {"width": 80, "height": 20}}])
    original_capture = blockparse.capture_block_irs
    original_cache_get = blockparse.cache_store.get
    original_cache_put = blockparse.cache_store.put_gated
    observed_auth_cookies = []
    def fake_auth_capture(_url, _blocks, **kwargs):
        observed_auth_cookies.extend(kwargs.get("cookies") or [])
        return ({"#private": {"ir": auth_ir, "width": 80, "height": 20,
                               "layer_count": 1, "layers_by_viewport": {"desktop": 1},
                               "editable_layers_by_viewport": {"desktop": 1},
                               "component_boundaries_by_viewport": {"desktop": 0},
                               "coverage": {"desktop": 100}, "paint_coverage": {"desktop": 100}}},
                auth_ir["tokens"])
    blockparse.capture_block_irs = fake_auth_capture
    blockparse.cache_store.get = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auth cache read"))
    blockparse.cache_store.put_gated = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auth cache write"))
    try:
        auth_result = blockparse.parse_blocks(
            "https://example.com/private",
            blocks=[{"name": "private", "selector": "#private"}],
            auth_cookies=[{"name": "session", "value": "secret", "domain": "example.com", "path": "/"}],
        )
    finally:
        blockparse.capture_block_irs = original_capture
        blockparse.cache_store.get = original_cache_get
        blockparse.cache_store.put_gated = original_cache_put
    check("authenticated capture bypasses caches and forwards cookies only to Chromium",
          auth_result.get("authenticated") is True and observed_auth_cookies[0]["name"] == "session",
          str(auth_result))

    # Маппинг сырых сигналов страницы в закрытый enum-контракт токенов схемы.
    tokens = scraper._page_tokens_from_signals({
        "bodyBg": "#0b0e14", "bodyColor": "#e6e6e6",
        "buttonBg": "#ff6b20", "linkColor": "#4f8cff", "borderColor": "#2a2f3a",
        "mutedColor": "#8a8f99",
        "displayFont": {"family": "'Sora', sans-serif", "weight": 745},
        "bodyFont": {"family": "Arial, sans-serif", "weight": 400},
        "buttonRadius": [9999, 9999, 8], "cardRadius": [12, 16, 10], "inputRadius": [6],
        "cardShadowBlur": [12, 18], "sectionPadding": [160, 140], "containerWidth": [1280, 1200],
    })
    check("page tokens follow the schema contract",
          tokens["mode"] == "dark" and tokens["color"]["primary"] == "#ff6b20" and
          tokens["color"]["accent"] == "#4f8cff" and tokens["font"]["display"] == {"family": "Sora", "weight": 700} and
          tokens["font"]["body"] == {"family": "Arial", "weight": 400} and
          tokens["radius"] == {"card": "lg", "button": "full", "input": "md"} and
          tokens["spacing"] == {"section": "xl", "container": "wide"} and tokens["shadow"] == "md",
          str(tokens))
    probe = {"version": "1.0", "tokens": tokens, "tree": [
        {"id": "t", "type": "source-block", "variant": "dom-capture", "props": {}}]}
    jsonschema.Draft7Validator(SCHEMA).validate(probe)
    check("page tokens failures fall back to defaults",
          scraper._page_tokens_from_signals(None) is None and
          scraper._page_tokens_from_signals({"bodyBg": "not-a-color"})["color"]["background"] == "#ffffff",
          "")
    branded = scraper._page_tokens_from_signals({
        "bodyBg": "#ffffff", "bodyColor": "#171717", "buttonBg": "#2b2b2b",
        "linkColor": "#2b2b2b", "brandColors": ["#ff691d", "#7018e6"],
    })
    check("saturated reference colors beat neutral header controls",
          branded["color"]["primary"] == "#ff691d" and branded["color"]["accent"] == "#7018e6",
          str(branded["color"]))

    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        live, _tokens = capture_block_irs(
            f"http://127.0.0.1:{server.server_port}/source_import_header.html",
            [{"name": "header", "label": "Header", "kind": "header", "selector": "#fixture-header"}],
            return_tokens=True, timeout_ms=30000,
        )
    finally:
        scraper.validate_public_url = original_validate
        server.shutdown()
        server.server_close()
    captured = live["#fixture-header"]
    check("fixture capture succeeds", "ir" in captured, str(captured.get("error")))
    responsive_ir = captured["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(responsive_ir)
    nodes = [node for node, _parent in scraper._walk_source_nodes(responsive_ir["tree"][0]["children"])]
    source_keys = [node.get("sourceKey") for node in nodes if node.get("sourceKey")]
    auto_nodes = [node for node in nodes if isinstance(node.get("frame"), dict) and node["frame"].get("layout") == "auto"]
    buttons = [node for node in nodes if node.get("type") == "button"]
    images = [node for node in nodes if node.get("type") == "image"]
    find_button = next((node for node in buttons if node.get("text") == "Find"), None)
    check("real DOM capture is compact", len(nodes) < 45, str(len(nodes)))
    check("real DOM capture produces auto-layout containers", len(auto_nodes) >= 4,
          str([(node.get("type"), node.get("sourceKey")) for node in auto_nodes]))
    component_nodes = [node for node in nodes if node.get("sourceMeta", {}).get("componentBoundary")]
    check("semantic component boundaries survive as editable hierarchy",
          0 < captured.get("component_boundaries_by_viewport", {}).get("desktop", 0) <= len(component_nodes) and
          any(node.get("sourceMeta", {}).get("componentRole") == "form" for node in component_nodes) and
          any(node.get("sourceMeta", {}).get("componentRole") == "nav" for node in component_nodes),
          str([(node.get("sourceKey"), node.get("sourceMeta")) for node in component_nodes]))
    check("responsive source keys are unique",
          len(source_keys) == len(set(source_keys)),
          str([key for key in source_keys if source_keys.count(key) > 1][:10]))
    check("real button text cannot escape its button",
          bool(find_button) and any(c.get("type") == "text" and c.get("text") == "Find" for c in find_button.get("children", [])),
          str(find_button))
    check("input and select remain editable containers",
          sum(1 for node in nodes if node.get("type") == "input") >= 2,
          str([node.get("sourceKey") for node in nodes if node.get("type") == "input"]))
    check("visible SVG icons remain editable nested image layers",
          len(images) >= 5 and all(str(node.get("src", "")).startswith("data:image/svg+xml") for node in images),
          str([(node.get("sourceKey"), bool(node.get("src"))) for node in images]))
    input_value = next((node for node in nodes if str(node.get("sourceKey", "")).endswith("input:1::value")), None)
    check("native input value stays on one clipped line",
          bool(input_value) and input_value.get("style", {}).get("whiteSpace") == "nowrap" and
          input_value.get("frame", {}).get("absolute") is True,
          str(input_value))
    check("three linked source viewports are captured",
          set(responsive_ir["responsive"]["viewports"]) == {"desktop", "tablet", "mobile"},
          str(responsive_ir["responsive"]["viewports"]))
    check("source diagnostics include per-viewport layers and coverage",
          set(captured["layers_by_viewport"]) == {"desktop", "tablet", "mobile"} and
          all(0 <= score <= 100 for score in captured["coverage"].values()),
          str({"layers": captured.get("layers_by_viewport"), "coverage": captured.get("coverage")}))

    # Токены теперь замеряются на живой странице, а не hardcode: фикстура даёт
    # оранжевую/фиолетовую кнопку и Arial как body-шрифт.
    check("rendered tokens come from the live page",
          isinstance(_tokens, dict) and _tokens.get("mode") == "light" and
          _tokens["color"]["primary"] in ("#ff6b20", "#7715ed") and
          _tokens["font"]["body"]["family"] == "Arial",
          str(_tokens))
    check("capture defers fidelity to the single certified harness pass",
          "fidelity" not in captured and "p95_layout_error" not in captured,
          str({"fidelity": captured.get("fidelity"), "p95": captured.get("p95_layout_error")}))
    # Honest metrics: coverage is never 100 when a visual layer was dropped, and
    # the new capture contract carries visited/emitted/dropped/extras/paint coverage.
    check("coverage is reported per viewport",
          isinstance(captured.get("coverage"), dict) and set(captured["coverage"]) == {"desktop", "tablet", "mobile"},
          str(captured.get("coverage")))
    check("paint coverage is reported separately from structural coverage",
          isinstance(captured.get("paint_coverage"), dict) and all(0 <= v <= 100 for v in captured["paint_coverage"].values()),
          str(captured.get("paint_coverage")))
    check("editable layer count uses emitted nodes only",
          isinstance(captured.get("editable_layers_by_viewport"), dict) and
          all(v <= captured["layers_by_viewport"][vp] for vp, v in captured["editable_layers_by_viewport"].items()),
          str(captured.get("editable_layers_by_viewport")))
    dropped_visual = [d for d in captured.get("dropped_by_viewport", {}).get("desktop", []) if d.get("visual")]
    check("coverage never reads 100% when a visual layer is dropped",
          len(dropped_visual) == 0 or all(v < 100 for v in captured["coverage"].values()),
          f"dropped_visual={len(dropped_visual)}, coverage={captured.get('coverage')}")
    # Hidden blocks (display:none / zero box) are omitted, not surfaced as import errors.
    hidden_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    hidden_thread = threading.Thread(target=hidden_server.serve_forever, daemon=True)
    hidden_thread.start()
    hidden_url = f"http://127.0.0.1:{hidden_server.server_port}/source_import_hidden_aside.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        parsed = blockparse.parse_blocks(
            hidden_url,
            blocks=[
                {"name": "visible", "label": "Visible", "kind": "section", "selector": "#fixture-visible"},
                {"name": "hidden", "label": "Hidden", "kind": "section", "selector": "#fixture-hidden"},
            ],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
        )
    finally:
        scraper.validate_public_url = original_validate
        hidden_server.shutdown()
        hidden_server.server_close()
    names = [b["name"] for b in parsed.get("blocks", []) if not b.get("error")]
    errors = [b.get("error", "") for b in parsed.get("blocks", []) if b.get("error")]
    check("hidden aside is omitted from Source Import outputs",
          "hidden" not in names and "hidden" not in " ".join(errors).lower(),
          str(parsed.get("blocks")))
    check("visible block is still imported when a sibling aside is hidden",
          "visible" in names, str(names))

    # ---------- reviewer invariants: честные метрики emitted/coverage ----------
    # Regression: emitted/editableLayers обязан равняться числу реально
    # присутствующих IR-слоёв после collapse/flatten, а потерянные визуальные
    # каналы (extras visual:true) запрещают coverage/paintCoverage = 100.
    inv_server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    inv_thread = threading.Thread(target=inv_server.serve_forever, daemon=True)
    inv_thread.start()
    inv_url = f"http://127.0.0.1:{inv_server.server_port}/source_import_visual_extras.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        inv = capture_block_irs(
            inv_url,
            [
                {"name": "extras", "label": "Extras", "kind": "section", "selector": "#fixture-extras"},
                {"name": "collapse", "label": "Collapse", "kind": "section", "selector": "#fixture-collapse"},
                {"name": "flatten", "label": "Flatten", "kind": "section", "selector": "#fixture-flatten"},
            ],
            viewports=[{"name": "desktop", "width": 1440, "height": 900}],
            timeout_ms=30000,
        )
    finally:
        scraper.validate_public_url = original_validate
        inv_server.shutdown()
        inv_server.server_close()

    extras_cap = inv["#fixture-extras"]
    visual_extras = [e for e in extras_cap.get("extras_by_viewport", {}).get("desktop", []) if e.get("visual")]
    check("visual extras: pseudo channel is reported as a lost visual layer",
          any(e.get("reason") == "pseudo" for e in visual_extras),
          str(extras_cap.get("extras_by_viewport")))
    check("visual extras forbid 100% paint coverage and coverage",
          extras_cap["paint_coverage"]["desktop"] < 100 and extras_cap["coverage"]["desktop"] < 100,
          str({"paint": extras_cap.get("paint_coverage"), "coverage": extras_cap.get("coverage")}))

    collapse_cap = inv["#fixture-collapse"]
    check("collapsed-neutral wrappers do not inflate emitted",
          collapse_cap["editable_layers_by_viewport"]["desktop"] == 0,
          str(collapse_cap.get("editable_layers_by_viewport")))
    check("collapsed-neutral wrappers are reported as dropped",
          sum(1 for d in collapse_cap["dropped_by_viewport"]["desktop"]
              if d.get("reason") == "collapsed-neutral") == 2,
          str(collapse_cap.get("dropped_by_viewport")))

    flatten_cap = inv["#fixture-flatten"]
    flatten_ir = flatten_cap["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(flatten_ir)
    flatten_nodes = [n for n, _p in scraper._walk_source_nodes(flatten_ir["tree"][0].get("children") or [])]
    check("flattened wrapper does not inflate emitted (emitted == IR nodes)",
          flatten_cap["editable_layers_by_viewport"]["desktop"] == len(flatten_nodes) == 1,
          str({"emitted": flatten_cap.get("editable_layers_by_viewport"), "irNodes": len(flatten_nodes)}))
    check("flattened wrapper is reported as dropped",
          any(d.get("reason") == "flattened" for d in flatten_cap["dropped_by_viewport"]["desktop"]),
          str(flatten_cap.get("dropped_by_viewport")))
    print("ALL SOURCE IMPORT CHECKS PASSED")


if __name__ == "__main__":
    main()
