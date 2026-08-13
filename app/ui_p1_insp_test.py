"""P1: numeric math (Р вЂ™Р’В«100*2Р вЂ™Р’В») Р В РЎвЂ drag-scrub Р В Р’В»Р В Р’ВµР В РІвЂћвЂ“Р В Р’В±Р В Р’В»Р В РЎвЂўР В Р вЂ  Р В Р вЂ  Р В РЎвЂР В Р вЂ¦Р РЋР С“Р В РЎвЂ”Р В Р’ВµР В РЎвЂќР РЋРІР‚С™Р В РЎвЂўР РЋР вЂљР В Р’Вµ.
Р В Р’В Р В Р’ВµР РЋРІР‚С™Р В Р’В°Р РЋР вЂљР В РЎвЂ“Р В Р’ВµР РЋРІР‚С™Р В РЎвЂР В Р вЂ¦Р В РЎвЂ“ Р В РЎвЂ”Р В РЎвЂўР РЋР С“Р В Р’В»Р В Р’Вµ Р РЋР С“Р В Р вЂ¦Р РЋР РЏР РЋРІР‚С™Р В РЎвЂР РЋР РЏ legacy /nodes: edit-Р В Р вЂ¦Р В РЎвЂўР В РўвЂР В Р’В° Р В Р’В¶Р В РЎвЂР В Р вЂ Р РЋРІР‚ВР РЋРІР‚С™ Р В Р вЂ  Р В Р вЂ¦Р В РЎвЂўР В Р вЂ Р В РЎвЂўР В РЎВ React Flow UI Р В Р вЂ¦Р В Р’В° /flow.
Р В РЎСљР РЋРЎвЂњР В Р’В¶Р В Р’ВµР В Р вЂ¦ Р В Р’В·Р В Р’В°Р В РЎвЂ”Р РЋРЎвЂњР РЋРІР‚В°Р В Р’ВµР В Р вЂ¦Р В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р РЋР С“Р В Р’ВµР РЋР вЂљР В Р вЂ Р В Р’ВµР РЋР вЂљ: .venv/Scripts/python app/server.py
Р В РІР‚вЂќР В Р’В°Р В РЎвЂ”Р РЋРЎвЂњР РЋР С“Р В РЎвЂќ: .venv/Scripts/python app/ui_p1_insp_test.py
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

FRAME = ("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id))"
         ".data.ir.tree[0].children[0].frame")


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" Р Р†Р вЂљРІР‚Сњ {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def set_field(pg, pi, value):
    pg.fill(f'.fe-inspector input[data-pi="{pi}"]', value)
    pg.evaluate(f'document.querySelector(".fe-inspector input[data-pi=\\"{pi}\\"]")'
                ".dispatchEvent(new Event('change'))")
    pg.wait_for_timeout(300)


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
        pg.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        pg.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
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
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(600)

        # Р В РЎСљР В РЎвЂўР В Р вЂ Р РЋРІР‚в„–Р В РІвЂћвЂ“ UI: renderer.js Р В Р’В°Р РЋР С“Р В РЎвЂР В Р вЂ¦Р РЋРІР‚В¦Р РЋР вЂљР В РЎвЂўР В Р вЂ¦Р В Р вЂ¦Р В РЎвЂў Р В РЎвЂ”Р В РЎвЂўР В РўвЂР В РЎвЂ“Р РЋР вЂљР РЋРЎвЂњР В Р’В¶Р В Р’В°Р В Р’ВµР РЋРІР‚С™ Google-Р РЋРІвЂљВ¬Р РЋР вЂљР В РЎвЂР РЋРІР‚С›Р РЋРІР‚С™Р РЋРІР‚в„– IR Р В РЎвЂ Р В РўвЂР В Р’ВµР В Р’В»Р В Р’В°Р В Р’ВµР РЋРІР‚С™
        # reflow Р В РЎвЂ”Р РЋР вЂљР В Р’ВµР В Р вЂ Р РЋР Р‰Р РЋР вЂ№ (Р В Р вЂ  legacy Р РЋР С“Р В РЎвЂўР В Р’ВµР В РўвЂР В РЎвЂР В Р вЂ¦Р В Р’ВµР В Р вЂ¦Р В РЎвЂР В Р’Вµ Р В РЎвЂ“Р РЋР вЂљР В Р’ВµР В Р’В» page-Р РЋРІвЂљВ¬Р РЋР вЂљР В РЎвЂР РЋРІР‚С›Р РЋРІР‚С™ nodes.html). Р В РІР‚вЂњР В РўвЂР РЋРІР‚ВР В РЎВ
        # Р РЋР С“Р РЋРІР‚С™Р В Р’В°Р В Р’В±Р В РЎвЂР В Р’В»Р В РЎвЂР В Р’В·Р В Р’В°Р РЋРІР‚В Р В РЎвЂР В РЎвЂ Р В РўвЂР В РЎвЂў Р В РЎвЂўР РЋРІР‚С™Р В РЎвЂќР РЋР вЂљР РЋРІР‚в„–Р РЋРІР‚С™Р В РЎвЂР РЋР РЏ Р РЋР вЂљР В Р’ВµР В РўвЂР В Р’В°Р В РЎвЂќР РЋРІР‚С™Р В РЎвЂўР РЋР вЂљР В Р’В°: Р В Р вЂ  Р В Р вЂ¦Р В Р’ВµР В РЎвЂ“Р В РЎвЂў IR Р РЋРЎвЂњР РЋРІР‚В¦Р В РЎвЂўР В РўвЂР В РЎвЂР РЋРІР‚С™ Р РЋР С“ Р В РўвЂР В РЎвЂўР В РЎвЂ“Р РЋР вЂљР РЋРЎвЂњР В Р’В¶Р В Р’ВµР В Р вЂ¦Р В Р вЂ¦Р РЋРІР‚в„–Р В РЎВР В РЎвЂ Р РЋРІвЂљВ¬Р РЋР вЂљР В РЎвЂР РЋРІР‚С›Р РЋРІР‚С™Р В Р’В°Р В РЎВР В РЎвЂ.
        def wait_ir_ready(sel, polls=3, interval=150):
            hits = 0
            for _ in range(80):
                st = pg.evaluate("document.fonts ? document.fonts.status : 'loaded'")
                hits = hits + 1 if st == "loaded" else 0
                if hits >= polls:
                    break
                pg.wait_for_timeout(interval)
            last, geo_hits = None, 0
            for _ in range(50):
                r = pg.evaluate(
                    "(s) => { const el = document.querySelector(s); if (!el) return null;"
                    " const b = el.getBoundingClientRect();"
                    " return [b.left, b.top, b.width, b.height]; }", sel)
                if r is not None and r == last:
                    geo_hits += 1
                    if geo_hits >= polls:
                        return True
                else:
                    geo_hits = 0
                last = r
                pg.wait_for_timeout(interval)
            return False

        wait_ir_ready('.n-edit .edit-inner [class^="ir-"]')

        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        cb = card.bounding_box()
        # Р В РЎвЂќР В Р’В»Р В РЎвЂР В РЎвЂќ Р В Р вЂ  padding-Р В Р’В·Р В РЎвЂўР В Р вЂ¦Р РЋРЎвЂњ (Р В Р вЂ¦Р В РЎвЂР В Р’В¶Р В Р вЂ¦Р В РЎвЂР В РІвЂћвЂ“ Р В РЎвЂ”Р РЋР вЂљР В Р’В°Р В Р вЂ Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р РЋРЎвЂњР В РЎвЂ“Р В РЎвЂўР В Р’В») Р Р†Р вЂљРІР‚Сњ Р В Р вЂ Р РЋРІР‚в„–Р В РўвЂР В Р’ВµР В Р’В»Р В РЎвЂР РЋРІР‚С™Р РЋР С“Р РЋР РЏ Р РЋР С“Р В Р’В°Р В РЎВР В Р’В° Р В РЎвЂќР В Р’В°Р РЋР вЂљР РЋРІР‚С™Р В РЎвЂўР РЋРІР‚РЋР В РЎвЂќР В Р’В°, Р В Р вЂ¦Р В Р’Вµ Р РЋР вЂљР В Р’ВµР В Р’В±Р РЋРІР‚ВР В Р вЂ¦Р В РЎвЂўР В РЎвЂќ
        pg.mouse.click(cb["x"] + cb["width"] - 4, cb["y"] + cb["height"] - 4)
        pg.wait_for_timeout(400)

        # ---------- appearance: selected layer fill + radius ----------
        check("appearance: fill field exists",
              pg.locator('.fe-inspector input[data-style-text="background"]').count() == 1)
        check("appearance: radius field exists",
              pg.locator('.fe-inspector input[data-style-num="borderRadius"]').count() == 1)
        pg.fill('.fe-inspector input[data-style-text="background"]', "#123456")
        pg.evaluate('document.querySelector(".fe-inspector input[data-style-text=\\"background\\"]").dispatchEvent(new Event("change"))')
        pg.fill('.fe-inspector input[data-style-num="borderRadius"]', "22")
        pg.evaluate('document.querySelector(".fe-inspector input[data-style-num=\\"borderRadius\\"]").dispatchEvent(new Event("change"))')
        pg.wait_for_timeout(500)
        appearance = pg.evaluate("""() => {
            const ir = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir;
            const node = ir.tree[0].children[0];
            const el = document.querySelector('.fe-canvas [data-ir-path="children.0"]');
            const cs = getComputedStyle(el);
            return {
                bg: node.style && node.style.background,
                r: node.style && node.style.borderRadius,
                cssBg: cs.backgroundColor,
                cssRadius: cs.borderRadius,
            };
        }""")
        check("appearance: fill writes selected layer style",
              appearance["bg"] == "#123456" and "18, 52, 86" in appearance["cssBg"], str(appearance))
        check("appearance: radius writes selected layer style",
              appearance["r"] == 22 and appearance["cssRadius"].startswith("22px"), str(appearance))

        # ---------- numeric math ----------
        set_field(pg, "width", "100*2+40")
        w = pg.evaluate(FRAME + ".width")
        shown = pg.input_value('.fe-inspector input[data-pi="width"]')
        check("math: 100*2+40 Р Р†РІР‚В РІР‚в„ў width 240", w == 240, str(w))
        check("math: Р В РЎвЂ”Р В РЎвЂўР В Р’В»Р В Р’Вµ Р РЋР С“Р РЋРІР‚В¦Р В Р’В»Р В РЎвЂўР В РЎвЂ”Р В Р вЂ¦Р РЋРЎвЂњР В Р’В»Р В РЎвЂўР РЋР С“Р РЋР Р‰ Р В Р вЂ  Р РЋРІР‚РЋР В РЎвЂР РЋР С“Р В Р’В»Р В РЎвЂў", shown == "240", shown)

        set_field(pg, "gap", "16/2")
        g = pg.evaluate(FRAME + ".gap")
        check("math: 16/2 Р Р†РІР‚В РІР‚в„ў gap 8", g == 8, str(g))

        set_field(pg, "width", "abc")
        w2 = pg.evaluate(FRAME + ".width")
        check("Р В РЎВР РЋРЎвЂњР РЋР С“Р В РЎвЂўР РЋР вЂљ Р В Р вЂ¦Р В Р’Вµ Р В РЎвЂ”Р РЋР вЂљР В РЎвЂР В РЎВР В Р’ВµР В Р вЂ¦Р РЋР РЏР В Р’ВµР РЋРІР‚С™Р РЋР С“Р РЋР РЏ", w2 == 240, str(w2))

        # ---------- drag-scrub Р В Р’В»Р В Р’ВµР В РІвЂћвЂ“Р В Р’В±Р В Р’В»Р В Р’В° X ----------
        x0 = pg.evaluate(FRAME + ".x")
        if not isinstance(x0, (int, float)):
            x0 = float(pg.input_value('.fe-inspector input[data-pi="x"]') or 0)
        lab = pg.query_selector('.fe-inspector .pi-field:has(input[data-pi="x"]) label')
        lb = lab.bounding_box()
        pg.mouse.move(lb["x"] + lb["width"] / 2, lb["y"] + lb["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(lb["x"] + lb["width"] / 2 + 30, lb["y"] + lb["height"] / 2, steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(300)
        x1 = pg.evaluate(FRAME + ".x")
        check("scrub: X Р РЋР С“Р В РўвЂР В Р вЂ Р В РЎвЂР В Р вЂ¦Р РЋРЎвЂњР В Р’В»Р РЋР С“Р РЋР РЏ Р В Р вЂ¦Р В Р’В° +30", isinstance(x1, (int, float)) and abs(x1 - (x0 + 30)) <= 2,
              f"x0={x0} x1={x1}")


        # ---------- typography: selected text layer font + color ----------
        heading = pg.query_selector('.fe-canvas [data-ir-path="children.0.children.2"]')
        hb = heading.bounding_box()
        pg.keyboard.down("Control")
        pg.mouse.click(hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2)
        pg.keyboard.up("Control")
        pg.wait_for_timeout(400)
        check("typography: font selector exists",
              pg.locator('.fe-inspector select[data-style-select="fontFamily"]').count() == 1)
        check("typography: text color field exists",
              pg.locator('.fe-inspector input[data-style-text="color"]').count() == 1)
        pg.select_option('.fe-inspector select[data-style-select="fontFamily"]', "Sora")
        pg.fill('.fe-inspector input[data-style-num="fontSize"]', "28")
        pg.evaluate('document.querySelector(".fe-inspector input[data-style-num=\\"fontSize\\"]").dispatchEvent(new Event("change"))')
        pg.fill('.fe-inspector input[data-style-text="color"]', "#abcdef")
        pg.evaluate('document.querySelector(".fe-inspector input[data-style-text=\\"color\\"]").dispatchEvent(new Event("change"))')
        pg.wait_for_timeout(500)
        type_style = pg.evaluate("""() => {
            const ir = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir;
            const node = ir.tree[0].children[0].children[2];
            const el = document.querySelector('.fe-canvas [data-ir-path="children.0.children.2"]');
            const cs = getComputedStyle(el.querySelector('h3') || el);
            return {
                family: node.style && node.style.fontFamily,
                size: node.style && node.style.fontSize,
                color: node.style && node.style.color,
                cssFamily: cs.fontFamily,
                cssSize: cs.fontSize,
                cssColor: cs.color,
            };
        }""")
        check("typography: font family writes selected text style",
              type_style["family"] == "Sora" and "Sora" in type_style["cssFamily"], str(type_style))
        check("typography: size and color write selected text style",
              type_style["size"] == 28 and type_style["color"] == "#abcdef"
              and type_style["cssSize"].startswith("28px") and "171, 205, 239" in type_style["cssColor"],
              str(type_style))
        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL INSPECTOR CHECKS PASSED")


if __name__ == "__main__":
    main()
