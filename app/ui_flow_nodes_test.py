"""Playwright test for the current React Flow node set.

No real LLM calls: /api/generate, /api/mix, /api/block-parse and
/api/quality-pass are mocked in the browser context.
"""
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
PROMPT_TEXT = "Generate a marketplace header"
SOURCE_URL = "https://example.com/page"

SMALL_IR = {
    "frame": {"width": 960},
    "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
    "tree": [
        {
            "id": "cta",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": "Mock heading",
                "subheading": "Valid IR without LLM",
                "ctaPrimary": {"text": "Button", "variant": "primary"},
            },
        }
    ],
}

BP_TOKENS = {
    "color": {"primary": "#5b5bd6", "background": "#ffffff"},
    "font": {"family": "Inter"},
    "radius": {"m": "12px"},
}

BP_RESP = {
    "url": SOURCE_URL,
    "blocks": [
        {"name": "hero", "selector": "section#hero", "ir": SMALL_IR, "cached": False, "source": "dom", "layers": 3},
        {"name": "cta", "selector": "section#cta", "ir": SMALL_IR, "cached": True, "source": "dom", "layers": 2},
    ],
    "tokens": BP_TOKENS,
    "cached": False,
}

FAILS = []
CAPTURED = {}


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" - {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag_wire(pg, src_sel, dst_sel):
    src = pg.wait_for_selector(src_sel)
    dst = pg.wait_for_selector(dst_sel)
    sx, sy = center(src.bounding_box())
    dx, dy = center(dst.bounding_box())
    pg.mouse.move(sx, sy)
    pg.mouse.down()
    pg.mouse.move(dx, dy, steps=14)
    pg.mouse.up()
    pg.wait_for_timeout(250)


def drag_wire_to_node(pg, src_sel, node_sel):
    src = pg.wait_for_selector(src_sel)
    dst = pg.wait_for_selector(node_sel)
    sx, sy = center(src.bounding_box())
    dx, dy = center(dst.bounding_box())
    pg.mouse.move(sx, sy)
    pg.mouse.down()
    pg.mouse.move(dx, dy, steps=18)
    pg.mouse.up()
    pg.wait_for_timeout(300)


def run_node_type(pg, node_type):
    pg.evaluate(
        """(type) => {
            const n = window.GraphDev.state().nodes.find((x) => x.type === type);
            if (!n) throw new Error(`Node not found: ${type}`);
            window.GraphDev.run(n.id);
        }""",
        node_type,
    )


def connect_types(pg, from_type, from_port, to_type, to_port):
    return pg.evaluate(
        """([fromType, fromPort, toType, toPort]) => {
            const st = window.GraphDev.state();
            const src = st.nodes.find((x) => x.type === fromType);
            const dst = st.nodes.find((x) => x.type === toType);
            if (!src || !dst) throw new Error(`Missing nodes: ${fromType} -> ${toType}`);
            return window.GraphDev.connect(src.id, fromPort, dst.id, toPort);
        }""",
        [from_type, from_port, to_type, to_port],
    )


def route_generate(route):
    CAPTURED.setdefault("generate", []).append(route.request.post_data_json)
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "variants": [SMALL_IR], "errors": [],
            "qa": [{"index": 1, "score": 92, "verdict": "pass", "summary": "rendered pass", "issues": [], "fixed": 1}],
            "design": {"type": "marketplace", "label": "Marketplace", "skills": ["web-design-guidelines", "frontend-design"]},
        }),
    )


def route_mix(route):
    CAPTURED["mix"] = route.request.post_data_json
    route.fulfill(status=200, content_type="application/json", body=json.dumps({"ir": SMALL_IR}))


def route_block_parse(route):
    CAPTURED["block_parse"] = route.request.post_data_json
    route.fulfill(status=200, content_type="application/json", body=json.dumps(BP_RESP))


def route_quality_pass(route):
    CAPTURED["quality_pass"] = route.request.post_data_json
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "ir": SMALL_IR,
            "passed": True,
            "min_score": 85,
            "scorecard": {"score": 92, "verdict": "pass", "summary": "mock pass", "issues": []},
            "initial_scorecard": {"score": 92},
            "deterministic": {"before": [], "after": []},
            "repair": {"attempted": True, "applied": True, "error": None},
        }),
    )


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        pg.route("**/api/generate", route_generate)
        pg.route("**/api/mix", route_mix)
        pg.route("**/api/block-parse", route_block_parse)
        pg.route("**/api/quality-pass", route_quality_pass)

        for _ in range(30):
            try:
                pg.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")

        pg.click(".react-flow__pane", button="right", position={"x": 520, "y": 100})
        pg.wait_for_selector("#ctx-menu")
        check("menu has 14 current node types", pg.evaluate("document.querySelectorAll('#ctx-menu .ctx-item').length === 14"))
        check("old nodes are removed from menu", pg.locator("#ctx-menu .ctx-item[data-type='clone']").count() == 0
              and pg.locator("#ctx-menu .ctx-item[data-type='reproduce']").count() == 0
              and pg.locator("#ctx-menu .ctx-item[data-type='blockparse']").count() == 0)
        pg.click("#ctx-menu .ctx-item[data-type='generator']")
        pg.wait_for_selector(".n-generator")

        pg.evaluate("""(() => {
            window.GraphDev.add('prompt', 80, 60);
            window.GraphDev.add('sourceimport', 80, 360);
            window.GraphDev.add('styledna', 500, 360);
            window.GraphDev.add('derive', 900, 360);
            window.GraphDev.add('edit', 830, 60);
            window.GraphDev.add('mix', 500, 690);
            window.GraphDev.add('qualitypass', 1240, 60);
        })()""")
        for sel in (".n-prompt", ".n-sourceimport", ".n-styledna", ".n-derive", ".n-edit", ".n-mix", ".n-qualitypass"):
            pg.wait_for_selector(sel)
        check("created 8 nodes", pg.evaluate("window.GraphDev.state().nodes.length === 8"))
        check("Generator shows GPT Codex route", pg.locator(".n-generator .generator-model-row").inner_text().strip() == "GPT Codex")
        check("Generator exposes Taste Memory controls", pg.locator(".n-generator .generator-taste-toggle").count() == 1)

        old_add_rejected = pg.evaluate("""(() => {
            const before = window.GraphDev.state().nodes.length;
            try { window.GraphDev.add('clone', 100, 100); } catch {}
            return window.GraphDev.state().nodes.length === before;
        })()""")
        check("GraphDev cannot add old clone node", bool(old_add_rejected))

        pg.fill(".n-prompt .f-text", PROMPT_TEXT)
        pg.fill(".n-sourceimport .f-url", SOURCE_URL)
        pg.check(".n-sourceimport .f-mine")
        pg.click(".n-sourceimport .f-run")
        pg.wait_for_selector(".n-sourceimport .bp-block[data-block='hero']", timeout=8000)
        pg.check(".n-sourceimport .bp-block[data-block='hero'] .f-lit")
        pg.wait_for_selector(".n-sourceimport .pp-out-hero")
        source_payload = CAPTURED.get("block_parse") or {}
        check("Source Import requests the three responsive viewports",
              source_payload.get("url") == SOURCE_URL and
              [v.get("name") for v in source_payload.get("viewports", [])] == ["desktop", "tablet", "mobile"])
        check("Source Import exposes block + DNA ports", pg.locator(".n-sourceimport .port-row.out").count() == 2)

        check("connect prompt → generator", connect_types(pg, "prompt", "out", "generator", "prompt"))
        check("connect generator → edit", connect_types(pg, "generator", "ir", "edit", "ir"))
        check("connect Source Import tokens → Style DNA", connect_types(pg, "sourceimport", "tokens", "styledna", "tokens"))
        check("connect Style DNA → Derive", connect_types(pg, "styledna", "tokens", "derive", "tokens"))
        check("connect prompt → Derive", connect_types(pg, "prompt", "out", "derive", "prompt"))
        drag_wire_to_node(pg, ".n-sourceimport .pp-out-hero", ".n-derive")
        check("snap-to-node connects hero to Derive.reference", pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const si = st.nodes.find(n => n.type === 'sourceimport');
            const de = st.nodes.find(n => n.type === 'derive');
            return st.edges.some(e => e.from.node === si.id && e.from.port === 'hero'
                && e.to.node === de.id && e.to.port === 'reference');
        })()"""))

        run_node_type(pg, "generator")
        pg.wait_for_selector('.n-generator .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Generator uses Codex role", CAPTURED.get("generate", [{}])[0].get("provider") == "codex")
        generate_payload = CAPTURED.get("generate", [{}])[0]
        check("Generator sends scoped Taste Memory settings", generate_payload.get("tasteEnabled") is True
              and generate_payload.get("tasteWeight") == 0.35 and generate_payload.get("tasteScope") == "project")
        check("Generator displays rendered QA score and skills", "92/100" in pg.locator(".n-generator .generator-quality").inner_text()
              and "web-design-guidelines" in pg.locator(".n-generator .generator-quality").inner_text())
        pg.wait_for_selector('.n-edit .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000)

        run_node_type(pg, "styledna")
        check("Style DNA extracts tokens", pg.evaluate("""(() => {
            const n = window.GraphDev.state().nodes.find(x => x.type === 'styledna');
            return !!window.GraphDev.node(n.id).data.tokens.color;
        })()"""))

        run_node_type(pg, "derive")
        pg.wait_for_selector('.n-derive .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        derive_payload = CAPTURED.get("generate", [{}, {}])[-1]
        check("Derive passes reference DNA in styleHint", "Style DNA" in derive_payload.get("styleHint", "")
              and "Reference IR" in derive_payload.get("styleHint", ""))

        check("connect Source Import hero → Mix.a", connect_types(pg, "sourceimport", "hero", "mix", "a"))
        check("connect Generator → Mix.b", connect_types(pg, "generator", "ir", "mix", "b"))
        run_node_type(pg, "mix")
        pg.wait_for_selector('.n-mix .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Mix receives two IR inputs", len(CAPTURED.get("mix", {}).get("irs", [])) == 2)

        generator_id = pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'generator').id")
        quality_id = pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'qualitypass').id")
        pg.evaluate("([g, q]) => window.GraphDev.connect(g, 'ir', q, 'ir')", [generator_id, quality_id])
        run_node_type(pg, "qualitypass")
        pg.wait_for_selector(".n-qualitypass .qp-score", timeout=8000)
        check("Quality Pass scorecard rendered", "92/100" in pg.locator(".n-qualitypass .qp-score").inner_text())

        pg.wait_for_timeout(700)
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        check("after reload: current graph persists", pg.evaluate("window.GraphDev.state().nodes.length === 8"))
        check("after reload: old node types absent", pg.evaluate("""(() => {
            return window.GraphDev.state().nodes.every(n => !['clone','reproduce','blockparse'].includes(n.type));
        })()"""))

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} - {', '.join(FAILS)}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
