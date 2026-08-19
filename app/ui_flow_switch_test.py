"""Canonical route test after removing legacy entrypoints.

Run:
    .venv/Scripts/python app/ui_flow_switch_test.py

Checks:
    - /flow is the only route that renders the React Flow app directly;
    - / redirects to /flow;
    - /nodes redirects to /flow;
    - legacy localStorage key designai-graph-v1 is not created.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def wait_flow_ready(pg):
    pg.wait_for_selector(".svelte-flow__pane")
    pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")


def no_legacy_markers(pg):
    return pg.evaluate(
        "!document.querySelector('#viewport') && !document.querySelector('#wires') && "
        "!document.querySelector('script[src*=\"nodes.js\"]')"
    )


def main():
    with sync_playwright() as p:
        api = p.request.new_context()
        for path in ("/", "/nodes"):
            try:
                r = api.get(BASE + path, max_redirects=0)
                check(f"GET {path} -> 307", r.status == 307, str(r.status))
                check(f"GET {path}: Location /flow", r.headers.get("location") == "/flow", str(r.headers))
            except Exception as e:
                check(f"GET {path} -> 307", False, str(e))
        try:
            r = api.get(BASE + "/flow")
            check("GET /flow -> 200", r.status == 200, str(r.status))
        except Exception as e:
            check("GET /flow -> 200", False, str(e))
        api.dispose()

        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
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
        wait_flow_ready(pg)
        check("/flow renders React Flow", pg.is_visible(".svelte-flow__pane"))
        check("/flow has GraphDev shim", pg.evaluate("typeof window.GraphDev.add === 'function'"))
        check("/flow has no legacy nodes.html markers", no_legacy_markers(pg))

        pg.goto(BASE + "/")
        wait_flow_ready(pg)
        check("/ redirects browser to /flow", pg.url.rstrip("/") == BASE + "/flow", pg.url)

        pg.goto(BASE + "/nodes")
        wait_flow_ready(pg)
        check("/nodes redirects browser to /flow", pg.url.rstrip("/") == BASE + "/flow", pg.url)
        check("legacy storage key is not created", pg.evaluate("localStorage.getItem('designai-graph-v1') === null"))

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nAll canonical route checks passed.")


if __name__ == "__main__":
    main()
