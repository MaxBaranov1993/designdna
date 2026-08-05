"""Галерея рендерит все IR живым renderer.js (без собственной копии).
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_gallery_test.py
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for _ in range(30):
            try:
                pg.goto(BASE + "/static/gallery.html", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        pg.wait_for_timeout(2000)

        st = pg.evaluate("""(() => ({
            artboards: document.querySelectorAll('.prev [class^="ir-"]').length,
            total: Object.keys(DATA).length,
            broken: Array.from(document.querySelectorAll('.prev'))
                .filter(x => x.textContent.includes('render error')).length,
            renderer: typeof window.IRRenderer,
        }))()""")
        check("renderer.js подключён внешним скриптом", st["renderer"] == "object", str(st))
        check("все IR отрендерены", st["artboards"] == st["total"] and st["total"] >= 40, str(st))
        check("нет render error", st["broken"] == 0, str(st))
        check("нет page-ошибок", not errs, str(errs[:2]))

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL GALLERY CHECKS PASSED")


if __name__ == "__main__":
    main()
