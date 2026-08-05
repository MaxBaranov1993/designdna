"""localStorage: quota-fallback (сохранение без скриншотов) + beforeunload-флаш.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_storage_test.py
"""
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "frame-example.json"
FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
        for _ in range(30):
            try:
                pg.goto(BASE + "/nodes", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector("#viewport")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        # тяжёлый base64 в данных ноды (как скриншот Reproduce)
        pg.evaluate("window.GraphDev.node(%d).data.shot = 'data:image/png;base64,' + 'A'.repeat(300000)" % nid)

        # ---------- сценарий 1: квота → retry без скриншотов ----------
        pg.evaluate("""(() => {
            const orig = Storage.prototype.setItem;
            window.__quotaHits = 0;
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-graph-v1' && window.__quotaHits === 0) {
                    window.__quotaHits++;
                    throw new DOMException('quota exceeded', 'QuotaExceededError');
                }
                return orig.call(this, k, v);
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)  # триггерит save()
        pg.wait_for_timeout(700)
        toast1 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("квота: тост о сохранении без скриншотов", "без скриншотов" in toast1, toast1)
        saved = pg.evaluate("localStorage.getItem('designai-graph-v1') || ''")
        check("квота: граф сохранён", len(saved) > 100, str(len(saved)))
        check("квота: base64 вырезан из сейва", "data:image" not in saved)
        check("квота: IR на месте", '"tree"' in saved)

        # ---------- сценарий 2: квота всегда → тост + beforeunload ----------
        pg.evaluate("""(() => {
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-graph-v1') throw new DOMException('quota exceeded', 'QuotaExceededError');
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(700)
        toast2 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("полная квота: тост с призывом экспортировать", "Не удалось сохранить" in toast2, toast2)
        prevented = pg.evaluate("(() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; })()")
        check("полная квота: beforeunload блокируется", prevented is True, str(prevented))

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL STORAGE CHECKS PASSED")


if __name__ == "__main__":
    main()
