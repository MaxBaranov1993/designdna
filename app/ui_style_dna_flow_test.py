"""Browser regression checks for exact Style DNA flow and Page ownership."""
from __future__ import annotations

import copy
import json
import sys
import time

from playwright.sync_api import sync_playwright

from ui_source_import_editor_test import SOURCE_IR


BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILS.append(name)


def styled_ir(name: str, primary: str) -> dict:
    value = copy.deepcopy(SOURCE_IR)
    value["meta"]["name"] = name
    value["tokens"]["color"].update({
        "primary": primary,
        "surface": "#f8fafc",
        "textMuted": "#64748b",
        "border": "#e2e8f0",
    })
    value["tree"][0]["id"] = name.lower()
    value["tree"][0]["children"][2]["style"]["background"] = primary
    return value


def main() -> None:
    header_ir = styled_ir("Header", "#dc2626")
    content_ir = styled_ir("Content", "#2563eb")
    extracted = copy.deepcopy(content_ir["tokens"])
    generate_requests: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        page.route(
            "**/api/style-dna/extract",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tokens": extracted})),
        )

        def generate(route) -> None:
            generate_requests.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"variants": [content_ir]}))

        page.route("**/api/generate", generate)
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")
        ids = page.evaluate("""() => ({
          source: window.GraphDev.add('sourceimport', 30, 30).id,
          dna: window.GraphDev.add('styledna', 450, 50).id,
          generator: window.GraphDev.add('generator', 820, 50).id,
          content: window.GraphDev.add('edit', 450, 500).id,
          page: window.GraphDev.add('page', 900, 500).id,
        })""")
        page.evaluate("""(v) => {
          window.GraphDev.patchData(v.ids.source, {
            tokens: v.header.tokens,
            blocks: [{name:'Header', selector:'header', ir:v.content, lit:true}],
          });
          window.GraphDev.patchData(v.ids.generator, {ownPrompt:'Build content', count:1});
          window.GraphDev.setIR(v.ids.content, v.content);
        }""", {"ids": ids, "header": header_ir, "content": content_ir})

        connected = page.evaluate("""(ids) => [
          window.GraphDev.connect(ids.source, 'tokens', ids.dna, 'tokens'),
          window.GraphDev.connect(ids.source, 'Header', ids.dna, 'ir'),
          window.GraphDev.connect(ids.dna, 'tokens', ids.generator, 'tokens'),
        ]""", ids)
        check("IR and tokens inputs connect to Style DNA", connected == [True, True, True], json.dumps(connected))
        page.evaluate("id => window.GraphDev.run(id)", ids["dna"])
        page.wait_for_function("id => window.GraphDev.node(id).data.tokens?.color?.primary === '#2563eb'", arg=ids["dna"])
        dna = page.evaluate("id => window.GraphDev.node(id).data.tokens", ids["dna"])
        check("connected IR wins over inherited Header tokens", dna["color"]["primary"] == "#2563eb", json.dumps(dna))

        page.evaluate("id => window.GraphDev.run(id)", ids["generator"])
        page.wait_for_function("id => window.GraphDev.node(id).data.variants.length === 1", arg=ids["generator"])
        check(
            "Generator receives the exact Style DNA output",
            bool(generate_requests) and generate_requests[-1].get("tokens", {}).get("color", {}).get("primary") == "#2563eb",
            json.dumps(generate_requests[-1] if generate_requests else {}),
        )

        page.evaluate("""(ids) => {
          window.GraphDev.connect(ids.source, 'Header', ids.page, 'a');
          window.GraphDev.connect(ids.content, 'ir', ids.page, 'b');
          window.GraphDev.run(ids.page);
        }""", ids)
        assembled = page.evaluate("id => window.GraphDev.node(id).data.ir", ids["page"])
        check(
            "Page fallback DNA comes from main content, not first Header input",
            assembled["tokens"]["color"]["primary"] == "#2563eb",
            json.dumps(assembled["tokens"]),
        )
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL STYLE DNA FLOW CHECKS PASSED")


if __name__ == "__main__":
    main()
