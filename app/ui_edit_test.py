"""UI-тест ноды «Редактор»: выделение, drag, инспектор (модель pen.dev).
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_edit_test.py
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "frame-example.json"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"

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
        import time
        for _ in range(30):
            try:
                pg.goto(BASE + "/nodes", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready"); sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector("#viewport")

        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(700)

        NODE = ".node.n-edit"

        # 1) оверлей GeoEdit живёт внутри .edit-inner после рендера
        check("оверлей GeoEdit внутри .edit-inner", pg.evaluate(
            "!!document.querySelector('.n-edit .edit-inner > .geo-overlay')"))

        # 2) клик по карточке (children.0) в зоне padding (нижний правый угол) → выделение
        card = pg.query_selector(f'{NODE} [data-ir-path="children.0"]')
        cb = card.bounding_box()
        px, py = cb["x"] + cb["width"] - 4, cb["y"] + cb["height"] - 4
        pg.mouse.click(px, py)
        pg.wait_for_timeout(300)
        check("выделение появилось", pg.evaluate(
            "document.querySelectorAll('.n-edit .geo-box.selected').length === 1"))

        # 3) рамка выделения совпадает с элементом (фикс масштаба оверлея)
        box = pg.query_selector(f'{NODE} .geo-box.selected')
        bb = box.bounding_box()
        cb2 = card.bounding_box()
        dx, dy = abs(bb["x"] - cb2["x"]), abs(bb["y"] - cb2["y"])
        dw, dh = abs(bb["width"] - cb2["width"]), abs(bb["height"] - cb2["height"])
        check("рамка выделения совпадает с элементом", dx < 4 and dy < 4 and dw < 6 and dh < 6,
              f"d=({dx:.1f},{dy:.1f},{dw:.1f},{dh:.1f})")

        # 4) инспектор показал секции для карточки-контейнера
        insp = f'{NODE} .edit-inspector'
        check("инспектор: Position", pg.query_selector(f'{insp} input[data-pi="x"]') is not None)
        check("инспектор: Flex Layout", pg.query_selector(f'{insp} [data-pi-dir="row"]') is not None)
        check("инспектор: Dimensions/Fill/Hug/Clip", pg.query_selector(f'{insp} [data-pi="fillw"]') is not None)
        check("инспектор: Absolute Position", pg.query_selector(f'{insp} [data-pi="absolute"]') is not None)

        # 5) drag карточки (точка на нижнем padding, вне resize-хендлов) → родитель free
        dx0 = cb["x"] + cb["width"] * 0.25
        dy0 = cb["y"] + cb["height"] - 4
        pg.mouse.move(dx0, dy0)
        pg.mouse.down()
        pg.mouse.move(dx0 + 40, dy0 + 28, steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        st = pg.evaluate("(() => { const n = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)); const sec = n.data.ir.tree[0]; const c = sec.children[0]; return { layout: sec.frame && sec.frame.layout, x: c.frame && c.frame.x, y: c.frame && c.frame.y, sel: document.querySelectorAll('.n-edit .geo-box.selected').length }; })()")
        check("drag: родитель стал free", st["layout"] == "free", str(st))
        check("drag: frame.x/y записаны", isinstance(st["x"], (int, float)) and isinstance(st["y"], (int, float)), str(st))
        check("drag: выделение сохранено после мутации", st["sel"] == 1)

        # 6) инспектор: X = 12
        xin = pg.query_selector(f'{insp} input[data-pi="x"]')
        xin.fill("12")
        pg.evaluate("document.querySelector('.n-edit .edit-inspector input[data-pi=\"x\"]').dispatchEvent(new Event('change'))")
        pg.wait_for_timeout(300)
        fx = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame.x")
        check("инспектор: X применяет frame.x", fx == 12, str(fx))

        # 7) Fill Width
        pg.click(f'{insp} [data-pi="fillw"]', force=True)
        pg.wait_for_timeout(300)
        fw = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame.width")
        check("инспектор: Fill Width → width:'fill'", fw == "fill", str(fw))
        pg.click(f'{insp} [data-pi="fillw"]', force=True)
        pg.wait_for_timeout(300)

        # 8) direction row
        pg.click(f'{insp} [data-pi-dir="row"]')
        pg.wait_for_timeout(300)
        fr = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame")
        check("инспектор: direction row → layout auto", fr.get("layout") == "auto" and fr.get("direction") == "row", str(fr))

        # 9) gap
        gin = pg.query_selector(f'{insp} input[data-pi="gap"]')
        gin.fill("16")
        pg.evaluate("document.querySelector('.n-edit .edit-inspector input[data-pi=\"gap\"]').dispatchEvent(new Event('change'))")
        pg.wait_for_timeout(300)
        gp = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame.gap")
        check("инспектор: gap=16", gp == 16, str(gp))

        # 10) clip
        pg.click(f'{insp} [data-pi="clip"]', force=True)
        pg.wait_for_timeout(300)
        cl = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame.clip")
        check("инспектор: Clip Content → clip:true", cl is True, str(cl))

        # 11) rotation
        rin = pg.query_selector(f'{insp} input[data-pi="rotation"]')
        rin.fill("15")
        pg.evaluate("document.querySelector('.n-edit .edit-inspector input[data-pi=\"rotation\"]').dispatchEvent(new Event('change'))")
        pg.wait_for_timeout(300)
        rot = pg.evaluate("(() => { const f = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame; const el = document.querySelector('.n-edit [data-ir-path=\"children.0\"]'); return { r: f.rotation, css: el.style.transform }; })()")
        check("инспектор: rotation=15 и CSS rotate", rot["r"] == 15 and "rotate(15deg)" in (rot["css"] or ""), str(rot))
        # сброс rotation чтобы не мешал drag-проверкам дальше
        rin = pg.query_selector(f'{insp} input[data-pi="rotation"]')
        rin.fill("0")
        pg.evaluate("document.querySelector('.n-edit .edit-inspector input[data-pi=\"rotation\"]').dispatchEvent(new Event('change'))")
        pg.wait_for_timeout(200)

        # 12) alignment: одиночное выравнивание по правому краю родителя
        pg.click(f'{insp} [data-act="align-right"]')
        pg.wait_for_timeout(300)
        ar = pg.evaluate("(() => { const f = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame; return f.x; })()")
        check("инспектор: align-right меняет x", isinstance(ar, (int, float)), str(ar))

        # 13) зум ноды
        zl_before = pg.text_content(f'{NODE} .geo-tools .zoom-label')
        pg.click(f'{NODE} .f-zoom-in')
        pg.wait_for_timeout(200)
        zl_after = pg.text_content(f'{NODE} .geo-tools .zoom-label')
        check("зум ноды работает", zl_before != zl_after, f"{zl_before} -> {zl_after}")

        # 14) absolute position
        pg.click(f'{insp} [data-pi="absolute"]', force=True)
        pg.wait_for_timeout(300)
        ab = pg.evaluate("(() => { const f = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree[0].children[0].frame; const el = document.querySelector('.n-edit [data-ir-path=\"children.0\"]'); return { a: f.absolute, x: typeof f.x, pos: el.style.position }; })()")
        check("инспектор: Absolute Position → absolute+x/y", ab["a"] is True and ab["x"] == "number" and ab["pos"] == "absolute", str(ab))

        # 15) панель инструментов: rect drag-создание
        NODESEL = NODE
        pg.click(f'{NODESEL} .rail-btn[data-tool="rect"]')
        pg.wait_for_timeout(200)
        check("rail: rect активен", pg.evaluate(
            "document.querySelector('.n-edit .rail-btn[data-tool=\"rect\"]').classList.contains('active')"))
        sec0 = pg.query_selector(f'{NODESEL} [data-ir-sec="0"]')
        sb = sec0.bounding_box()
        pg.mouse.move(sb["x"] + 60, sb["y"] + min(40, sb["height"] - 8))
        pg.mouse.down()
        pg.mouse.move(sb["x"] + 200, sb["y"] + min(120, sb["height"] - 4), steps=5)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        ALL_NODES = ("(() => { const out = []; const walk = (n) => (n.children || []).forEach(c => { out.push(c); walk(c); }); "
                     "(window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir.tree || []).forEach(s => walk(s)); return out; })()")
        rects = pg.evaluate(f"{ALL_NODES}.filter(c => c.type === 'rect').map(c => (c.frame || {{}}).width)")
        check("инструмент rect: создан rect с размером", len(rects) > 0 and rects[0] >= 100, str(rects))
        check("инструмент rect: новый элемент выделен", pg.evaluate(
            "document.querySelectorAll('.n-edit .geo-box.selected').length === 1"))

        # 16) text: клик создаёт текст (в контейнер под курсором — здесь card)
        pg.click(f'{NODESEL} .rail-btn[data-tool="text"]')
        pg.wait_for_timeout(150)
        pg.mouse.click(sb["x"] + 90, sb["y"] + min(60, sb["height"] - 8))
        pg.wait_for_timeout(400)
        nodes = pg.evaluate(ALL_NODES)
        check("инструмент text: создан text", any(
            c.get("type") == "text" and c.get("text") == "Новый текст" for c in nodes))

        # 17) frame: клик создаёт card-контейнер
        cards_before = len([c for c in nodes if c.get("type") == "card"])
        pg.click(f'{NODESEL} .rail-btn[data-tool="frame"]')
        pg.wait_for_timeout(150)
        pg.mouse.click(sb["x"] + 260, sb["y"] + min(80, sb["height"] - 8))
        pg.wait_for_timeout(400)
        nodes2 = pg.evaluate(ALL_NODES)
        cards_after = len([c for c in nodes2 if c.get("type") == "card"])
        check("инструмент frame: создан card", cards_after == cards_before + 1, f"{cards_before}->{cards_after}")

        # 18) hand: скролл превью (предварительно зумим, чтобы контент был выше окна)
        pg.click(f'{NODESEL} .f-zoom-in')
        pg.click(f'{NODESEL} .f-zoom-in')
        pg.wait_for_timeout(300)
        pg.click(f'{NODESEL} .rail-btn[data-tool="hand"]')
        pg.wait_for_timeout(150)
        st0 = pg.evaluate("document.querySelector('.n-edit .edit-preview').scrollTop")
        sb3 = pg.query_selector(f'{NODESEL} [data-ir-sec="0"]').bounding_box()
        pg.mouse.move(sb3["x"] + 100, sb3["y"] + 100)
        pg.mouse.down()
        pg.mouse.move(sb3["x"] + 100, sb3["y"] + 40, steps=4)
        pg.mouse.up()
        pg.wait_for_timeout(200)
        st1 = pg.evaluate("document.querySelector('.n-edit .edit-preview').scrollTop")
        check("инструмент hand: превью скроллится", st1 != st0, f"{st0}->{st1}")

        # 19) хоткей V возвращает select
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("v")
        pg.wait_for_timeout(200)
        check("хоткей V: select активен", pg.evaluate(
            "document.querySelector('.n-edit .rail-btn[data-tool=\"select\"]').classList.contains('active')"))

        SHOT_DIR.mkdir(exist_ok=True)
        pg.screenshot(path=str(SHOT_DIR / "ui_edit_node.png"), full_page=False)
        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL UI CHECKS PASSED")


if __name__ == "__main__":
    main()
