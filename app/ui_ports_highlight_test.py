"""Playwright regression for compatible-port highlighting and Generator edge migration."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def port_from_8441() -> int:
    for port in range(8441, 8541):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            pass
        finally:
            sock.close()
    raise RuntimeError("no free test port in 8441..8540")


def center(locator) -> tuple[float, float]:
    box = locator.bounding_box()
    assert box
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def main() -> None:
    temp = tempfile.TemporaryDirectory(prefix="ports-highlight-", ignore_cleanup_errors=True)
    port = port_from_8441()
    env = os.environ.copy()
    env["DESIGNDNA_DATA_DIR"] = temp.name
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            page.route("**/api/project/load", lambda r: r.fulfill(status=200, content_type="application/json", body='{"project":null}'))
            page.route("**/api/project/save", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok":true,"revision":"mock"}'))
            for _ in range(40):
                try:
                    page.goto(f"http://127.0.0.1:{port}/flow", timeout=1500)
                    break
                except Exception:
                    time.sleep(.25)
            page.evaluate("localStorage.clear()")
            page.reload()
            page.wait_for_function("window.GraphDev && window.__flowStore")
            page.evaluate("""() => {
              window.GraphDev.clear();
              const edit = window.GraphDev.add('edit', 80, 100);
              const gen = window.GraphDev.add('generator', 620, 100);
              window.GraphDev.patchData(edit.id, {ir:{version:'1.1', tree:[{type:'section'}], tokens:{}}});
            }""")
            page.wait_for_selector(".n-edit .pp-out-ir")
            sx, sy = center(page.locator(".n-edit .pp-out-ir"))
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(sx + 30, sy, steps=4)
            check("IR highlights Generator reference",
                  page.locator(".n-generator [data-port='reference'].port-can-drop").count() == 1)
            check("IR dims Generator prompt",
                  page.locator(".n-generator [data-port='prompt'].port-cannot-drop").count() == 1)
            page.mouse.up()
            check("drop classes are cleared",
                  page.locator(".port-can-drop, .port-cannot-drop").count() == 0)

            sx, sy = center(page.locator(".n-edit .pp-out-ir"))
            tx, ty = center(page.locator(".n-generator .pp-in-prompt"))
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(tx, ty, steps=12)
            page.mouse.up()
            page.wait_for_selector("#toasts .toast.error")
            check("incompatible connection is rejected with toast",
                  "Несовместимые порты" in page.locator("#toasts .toast.error").last.inner_text())

            legacy = {
                "version": "designai-pages-v1", "activePageId": "page-1", "pages": [{
                    "id": "page-1", "name": "Legacy", "graph": {
                        "nodes": [
                            {"id": 1, "type": "sourceimport", "x": 20, "y": 20, "data": {"blocks": [], "tokens": {"color": {"primary": "#000"}}}},
                            {"id": 2, "type": "reference", "x": 20, "y": 300, "data": {"brief": "minimal"}},
                            {"id": 3, "type": "generator", "x": 600, "y": 100, "data": {"provider": "openai", "effort": "medium", "count": 1, "variants": [], "active": 0}},
                        ],
                        "edges": [
                            {"from": {"node": 1, "port": "tokens"}, "to": {"node": 3, "port": "tokens"}},
                            {"from": {"node": 2, "port": "out"}, "to": {"node": 3, "port": "style"}},
                        ], "view": {"x": 0, "y": 0, "zoom": 1}, "nextId": 4,
                    },
                }], "channels": {},
            }
            page.unroute("**/api/project/load")
            page.route("**/api/project/load", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"project": legacy, "revision": "legacy-mock"}),
            ))
            page.evaluate("localStorage.removeItem('designai-flow-pages-v1')")
            page.reload()
            page.wait_for_function("window.GraphDev && window.GraphDev.state().edges.length === 2")
            migrated = page.evaluate("window.GraphDev.state().edges.map(e => e.to.port).sort()")
            check("legacy Generator ports migrate", migrated == ["designSystem", "reference"], str(migrated))
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        temp.cleanup()
    if FAILS:
        raise SystemExit(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))


if __name__ == "__main__":
    main()
