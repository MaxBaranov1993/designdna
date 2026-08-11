"""Deterministic Source Import semantics regression checks."""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema

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
    check("source preview is embedded for downstream pixel reference",
          ir["sourcePreview"] == capture["preview"] and ir["tree"][0]["props"]["sourcePreview"] == capture["preview"],
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
            return_tokens=True, timeout_ms=5000,
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
    fidelity = responsive_ir["responsive"]["viewports"]["desktop"].get("fidelity")
    check("desktop fidelity is an honest 0-100 metric",
          fidelity is None or 0 <= fidelity <= 100, str(fidelity))
    check("fidelity is mirrored to the capture result",
          captured.get("fidelity") == fidelity, str(captured.get("fidelity")))

    print("ALL SOURCE IMPORT CHECKS PASSED")


if __name__ == "__main__":
    main()
