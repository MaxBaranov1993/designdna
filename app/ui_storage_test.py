"""localStorage: quota-fallback (сохранение без тяжёлых данных) + SQLite-primary save.

Автосейв пишет один компакт-payload в designai-flow-pages-v1 (legacy-ключ
designai-flow-v1 больше не пишется), сериализация уезжает в idle-слот, поэтому
после изменения графа тест ждёт дебаунс 300 мс + idle до ~1.2 с.
Полная квота localStorage больше не блокирует закрытие, потому что проект
сохраняется в SQLite.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_storage_test.py
"""
import json
import pathlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "fixtures" / "frame-example.json"
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
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        pg.evaluate("window.GraphDev.clear()")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(2000)

        # тяжёлый base64 в данных ноды (как скриншот Reproduce)
        pg.evaluate("window.GraphDev.node(%d).data.shot = 'data:image/png;base64,' + 'A'.repeat(300000)" % nid)

        # ---------- сценарий 1: квота → retry без тяжёлых данных ----------
        pg.evaluate("""(() => {
            const orig = Storage.prototype.setItem;
            window.__quotaHits = 0;
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-flow-pages-v1' && window.__quotaHits === 0) {
                    window.__quotaHits++;
                    throw new DOMException('quota exceeded', 'QuotaExceededError');
                }
                return orig.call(this, k, v);
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)  # триггерит сейв
        pg.wait_for_timeout(2000)
        toast1 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("квота: тост о сохранении без тяжёлых данных", "без тяжёлых данных" in toast1, toast1)
        saved = pg.evaluate("localStorage.getItem('designai-flow-pages-v1') || ''")
        check("квота: проект сохранён", len(saved) > 100, str(len(saved)))
        check("квота: base64 вырезан из сейва", "data:image" not in saved)
        check("квота: IR на месте", '"tree"' in saved)
        legacy = pg.evaluate("localStorage.getItem('designai-flow-v1') || ''")
        check("legacy-ключ designai-flow-v1 больше не пишется", len(legacy) == 0, str(len(legacy)))

        # ---------- сценарий 2: квота всегда → SQLite остаётся основным сейвом ----------
        pg.evaluate("""(() => {
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-flow-pages-v1') throw new DOMException('quota exceeded', 'QuotaExceededError');
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(2000)
        toast2 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("полная квота: без пугающего призыва экспортировать", "Не удалось сохранить" not in toast2, toast2)
        check("полная квота: показан SQLite fallback", "SQLite" in toast2, toast2)
        prevented = pg.evaluate("(() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; })()")
        check("полная квота: beforeunload не блокируется", prevented is False, str(prevented))

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
