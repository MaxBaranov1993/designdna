"""Проверка, что кнопки из Source Import можно выделить в DNA Editor.

Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_button_select_test.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8420"

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/source_import_header.html"

    sys.path.insert(0, str(ROOT / "app"))
    import scraper

    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        captured, _tokens = scraper.capture_block_irs(
            url,
            [{"name": "header", "label": "Header", "kind": "header", "selector": "#fixture-header"}],
            return_tokens=True,
            timeout_ms=5000,
        )
    finally:
        scraper.validate_public_url = original_validate

    ir = captured["#fixture-header"]["ir"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 800})
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
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(600)
        check("редактор открыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))

        # find the "Publish listing" layer label
        labels = pg.evaluate("Array.from(document.querySelectorAll('.fe-layer .fe-ln')).map(e => e.textContent)")
        publish_layer = [l for l in labels if "publish" in l.lower() or "размест" in l.lower()]
        check("слой publish найден", bool(publish_layer), str(labels))

        # try to click the publish button on canvas
        bbox = pg.evaluate(
            """() => {
              const el = document.querySelector('.fe-canvas [data-ir-path="children.6"]');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
            }"""
        )
        check("publish button rendered", bbox is not None)
        if bbox:
            pg.mouse.click(bbox["x"], bbox["y"])
            pg.wait_for_timeout(400)
            selected = pg.evaluate(
                """() => {
                  const box = document.querySelector('.fe-canvas .geo-box.selected:last-child');
                  if (!box) return null;
                  const t = box.querySelector('.geo-chip');
                  return t ? t.textContent : '';
                }"""
            )
            check("publish button selected", bool(selected) and "button" in (selected or "").lower(), str(selected))

        # also test the Find button (path children.2.children.2 from fixture IR)
        bbox_find = pg.evaluate(
            """() => {
              const el = document.querySelector('.fe-canvas [data-ir-path="children.2.children.2"]');
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
            }"""
        )
        check("find button rendered", bbox_find is not None)
        if bbox_find:
            pg.mouse.click(bbox_find["x"], bbox_find["y"])
            pg.wait_for_timeout(400)
            selected = pg.evaluate(
                """() => {
                  const box = document.querySelector('.fe-canvas .geo-box.selected:last-child');
                  if (!box) return null;
                  const t = box.querySelector('.geo-chip');
                  return t ? t.textContent : '';
                }"""
            )
            check("find button selected", bool(selected) and "button" in (selected or "").lower(), str(selected))

        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL BUTTON SELECT CHECKS PASSED")


if __name__ == "__main__":
    main()
