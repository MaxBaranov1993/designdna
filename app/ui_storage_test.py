"""localStorage: quota-fallback (СЃРѕС…СЂР°РЅРµРЅРёРµ Р±РµР· СЃРєСЂРёРЅС€РѕС‚РѕРІ) + SQLite-primary save.
Р РµС‚Р°СЂРіРµС‚РёРЅРі РїРѕСЃР»Рµ СЃРЅСЏС‚РёСЏ legacy /nodes: edit-РЅРѕРґР° Р¶РёРІС‘С‚ РІ РЅРѕРІРѕРј React Flow UI РЅР° /flow,
СЃРµР№РІ РёРґС‘С‚ РІ РєР»СЋС‡ designai-flow-v1 (serialize.ts); РїРѕРІРµРґРµРЅРёРµ stripHeavy/С„Р»Р°С€ вЂ” parity
СЃ legacy nodes.js (serialize.ts: stripHeavy Р·РµСЂРєР°Р»РёС‚ nodes.js). РџРѕР»РЅР°СЏ РєРІРѕС‚Р°
localStorage Р±РѕР»СЊС€Рµ РЅРµ Р±Р»РѕРєРёСЂСѓРµС‚ Р·Р°РєСЂС‹С‚РёРµ, РїРѕС‚РѕРјСѓ С‡С‚Рѕ pages-РїСЂРѕРµРєС‚ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ РІ SQLite.
РќСѓР¶РµРЅ Р·Р°РїСѓС‰РµРЅРЅС‹Р№ СЃРµСЂРІРµСЂ: .venv/Scripts/python app/server.py
Р—Р°РїСѓСЃРє: .venv/Scripts/python app/ui_storage_test.py
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
    print(f"[{tag}] {name}" + (f" вЂ” {extra}" if extra and not cond else ""))
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
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        # С‚СЏР¶С‘Р»С‹Р№ base64 РІ РґР°РЅРЅС‹С… РЅРѕРґС‹ (РєР°Рє СЃРєСЂРёРЅС€РѕС‚ Reproduce)
        pg.evaluate("window.GraphDev.node(%d).data.shot = 'data:image/png;base64,' + 'A'.repeat(300000)" % nid)

        # ---------- СЃС†РµРЅР°СЂРёР№ 1: РєРІРѕС‚Р° в†’ retry Р±РµР· СЃРєСЂРёРЅС€РѕС‚РѕРІ ----------
        pg.evaluate("""(() => {
            const orig = Storage.prototype.setItem;
            window.__quotaHits = 0;
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-flow-v1' && window.__quotaHits === 0) {
                    window.__quotaHits++;
                    throw new DOMException('quota exceeded', 'QuotaExceededError');
                }
                return orig.call(this, k, v);
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)  # С‚СЂРёРіРіРµСЂРёС‚ save()
        pg.wait_for_timeout(700)
        toast1 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("РєРІРѕС‚Р°: С‚РѕСЃС‚ Рѕ СЃРѕС…СЂР°РЅРµРЅРёРё Р±РµР· СЃРєСЂРёРЅС€РѕС‚РѕРІ", "Р±РµР· СЃРєСЂРёРЅС€РѕС‚РѕРІ" in toast1, toast1)
        saved = pg.evaluate("localStorage.getItem('designai-flow-v1') || ''")
        check("РєРІРѕС‚Р°: РіСЂР°С„ СЃРѕС…СЂР°РЅС‘РЅ", len(saved) > 100, str(len(saved)))
        check("РєРІРѕС‚Р°: base64 РІС‹СЂРµР·Р°РЅ РёР· СЃРµР№РІР°", "data:image" not in saved)
        check("РєРІРѕС‚Р°: IR РЅР° РјРµСЃС‚Рµ", '"tree"' in saved)

        # ---------- СЃС†РµРЅР°СЂРёР№ 2: РєРІРѕС‚Р° РІСЃРµРіРґР° в†’ SQLite РѕСЃС‚Р°С‘С‚СЃСЏ РѕСЃРЅРѕРІРЅС‹Рј СЃРµР№РІРѕРј ----------
        pg.evaluate("""(() => {
            Storage.prototype.setItem = function (k, v) {
                if (k === 'designai-flow-v1' || k === 'designai-flow-pages-v1') throw new DOMException('quota exceeded', 'QuotaExceededError');
            };
        })()""")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(700)
        toast2 = pg.evaluate("Array.from(document.querySelectorAll('#toasts .toast')).map(t => t.textContent).join('|')")
        check("РїРѕР»РЅР°СЏ РєРІРѕС‚Р°: Р±РµР· РїСѓРіР°СЋС‰РµРіРѕ РїСЂРёР·С‹РІР° СЌРєСЃРїРѕСЂС‚РёСЂРѕРІР°С‚СЊ", "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕС…СЂР°РЅРёС‚СЊ" not in toast2, toast2)
        check("РїРѕР»РЅР°СЏ РєРІРѕС‚Р°: РїРѕРєР°Р·Р°РЅ SQLite fallback", "SQLite" in toast2, toast2)
        prevented = pg.evaluate("(() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; })()")
        check("РїРѕР»РЅР°СЏ РєРІРѕС‚Р°: beforeunload РЅРµ Р±Р»РѕРєРёСЂСѓРµС‚СЃСЏ", prevented is False, str(prevented))

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
