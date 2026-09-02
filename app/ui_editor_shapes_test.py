"""UI-тест новых инструментов GeoEdit: ellipse (O), line (L), image (I),
буфер обмена (Ctrl+A/C/X/V) и undo после этих операций.
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Инструменты драйвятся хоткеями (o/l/i), а не кнопками rail — так тест проходит
и на legacy chrome, и на React-порте редактора.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_shapes_test.py
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
            print("server not ready"); sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        pg.evaluate("window.GraphDev.clear()")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        # как в ui_editor_test: ждём шрифты и стабильную геометрию до открытия редактора
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
        check("редактор открыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))

        ir_js = "(() => { const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data; return d._editorDraft?.ir || d.ir; })()"
        kids_js = ir_js + ".tree[0].children"

        def blur():
            pg.evaluate("document.activeElement && document.activeElement.blur()")

        def tool():
            return pg.evaluate("document.querySelector('.fe-canvas .geo-overlay').dataset.tool")

        def sec_box():
            return pg.query_selector('.fe-canvas [data-ir-sec="0"]').bounding_box()

        def drag(fx, fy, tx, ty):
            pg.mouse.move(fx, fy)
            pg.mouse.down()
            pg.mouse.move(tx, ty, steps=6)
            pg.mouse.up()
            pg.wait_for_timeout(400)

        def sel_count():
            return pg.evaluate("document.querySelectorAll('.fe-canvas .geo-box.selected:not(.geo-union)').length")

        layers0 = pg.evaluate("document.querySelectorAll('.fe-layer').length")
        kids0 = pg.evaluate("len = " + kids_js + ".length")

        # ---------- ellipse (O): drag создаёт rect с radius 9999 ----------
        blur(); pg.keyboard.press("o")
        pg.wait_for_timeout(200)
        check("хоткей O активирует ellipse", tool() == "ellipse", tool())
        sb = sec_box()
        drag(sb["x"] + sb["width"] * 0.72, sb["y"] + 40,
             sb["x"] + sb["width"] * 0.88, sb["y"] + 140)
        ell = pg.evaluate(
            kids_js + ".find(c => c.type === 'rect' && c.radius === 9999) || null")
        check("ellipse создана (rect, radius 9999)", bool(ell), str(ell))
        check("ellipse получила уникальный sourceKey", bool(ell and str(ell.get("sourceKey", "")).startswith("geo-")),
              str(ell and ell.get("sourceKey")))
        check("ellipse выделена после создания", sel_count() == 1, str(sel_count()))

        # ---------- line (L): горизонтальный drag -> height 2, вертикальный -> width 2 ----------
        blur(); pg.keyboard.press("l")
        pg.wait_for_timeout(200)
        check("хоткей L активирует line", tool() == "line", tool())
        sb = sec_box()
        drag(sb["x"] + sb["width"] * 0.72, sb["y"] + 180,
             sb["x"] + sb["width"] * 0.90, sb["y"] + 186)
        line_h = pg.evaluate(
            kids_js + ".find(c => c.type === 'rect' && c.frame && c.frame.height === 2) || null")
        check("line: горизонтальный drag -> height 2", bool(line_h), str(line_h))
        check("line: fill по умолчанию #6b7280", bool(line_h and line_h.get("fill") == "#6b7280"),
              str(line_h and line_h.get("fill")))
        sb = sec_box()
        drag(sb["x"] + sb["width"] * 0.94, sb["y"] + 40,
             sb["x"] + sb["width"] * 0.94 + 4, sb["y"] + 150)
        line_v = pg.evaluate(
            kids_js + ".find(c => c.type === 'rect' && c.frame && c.frame.width === 2) || null")
        check("line: вертикальный drag -> width 2", bool(line_v), str(line_v))

        # ---------- image (I): click создаёт 240x160 с плейсхолдером ----------
        imgs0 = pg.evaluate(kids_js + ".filter(c => c.type === 'image').length")
        blur(); pg.keyboard.press("i")
        pg.wait_for_timeout(200)
        check("хоткей I активирует image", tool() == "image", tool())
        sb = sec_box()
        pg.mouse.click(sb["x"] + sb["width"] * 0.80, sb["y"] + sb["height"] * 0.62)
        pg.wait_for_timeout(400)
        img = pg.evaluate(
            kids_js + ".filter(c => c.type === 'image').pop() || null")
        check("image создана по click", bool(img), str(img))
        check("image: alt и размер 240x160",
              bool(img and img.get("alt") == "изображение"
                   and img["frame"]["width"] == 240 and img["frame"]["height"] == 160),
              str(img))
        check("image: плейсхолдер .img-ph отрендерен",
              pg.evaluate("document.querySelectorAll('.fe-canvas .img-ph').length >= 1"))
        check("image: новых image-узлов +1",
              pg.evaluate(kids_js + ".filter(c => c.type === 'image').length") == imgs0 + 1)

        # ---------- слои: новые узлы видны в дереве ----------
        layers1 = pg.evaluate("document.querySelectorAll('.fe-layer').length")
        check("дерево слоёв пополнилось", layers1 > layers0, f"{layers0} -> {layers1}")

        # ---------- clipboard: copy/paste эллипса со сдвигом +16/+16 ----------
        blur(); pg.keyboard.press("v")
        pg.wait_for_timeout(200)
        eb = pg.query_selector('.fe-canvas [data-ir-path="children.1"]').bounding_box()
        pg.mouse.click(eb["x"] + eb["width"] / 2, eb["y"] + eb["height"] / 2)
        pg.wait_for_timeout(400)
        check("эллипс кликом выделяется", sel_count() == 1, str(sel_count()))
        src = pg.evaluate(kids_js + "[1].frame")
        n_before = pg.evaluate(kids_js + ".length")
        pg.keyboard.press("Control+c")
        pg.wait_for_timeout(150)
        pg.keyboard.press("Control+v")
        pg.wait_for_timeout(400)
        n_after = pg.evaluate(kids_js + ".length")
        check("Ctrl+V: children +1", n_after == n_before + 1, f"{n_before} -> {n_after}")
        pasted = pg.evaluate(kids_js + "[" + str(n_after - 1) + "]")
        check("paste: сдвиг +16/+16",
              bool(pasted and pasted["frame"]["x"] == src["x"] + 16 and pasted["frame"]["y"] == src["y"] + 16),
              str(pasted and pasted["frame"]))
        check("paste: свежий уникальный sourceKey",
              bool(pasted and pasted.get("sourceKey", "").startswith("geo-") and pasted["sourceKey"] != ell.get("sourceKey")),
              str(pasted and pasted.get("sourceKey")))
        check("paste: копия выделена", sel_count() == 1, str(sel_count()))

        # ---------- Ctrl+A: все top-level children секции ----------
        pg.keyboard.press("Control+a")
        pg.wait_for_timeout(400)
        n_kids = pg.evaluate(kids_js + ".length")
        check("Ctrl+A выделяет все top-level children", sel_count() == n_kids,
              f"sel={sel_count()} kids={n_kids}")
        check("Ctrl+A: объединяющая рамка с ручками",
              pg.evaluate("document.querySelectorAll('.fe-canvas .geo-box.geo-union .geo-h').length === 8"))

        # ---------- Ctrl+C/Ctrl+V: дублирование всего выделения ----------
        pg.keyboard.press("Control+c")
        pg.wait_for_timeout(150)
        pg.keyboard.press("Control+v")
        pg.wait_for_timeout(500)
        n_dbl = pg.evaluate(kids_js + ".length")
        check("Ctrl+V дублирует всё выделение", n_dbl == n_kids * 2, f"{n_kids} -> {n_dbl}")
        check("paste-all: копии выделены", sel_count() == n_kids, str(sel_count()))

        # уникальность sourceKey по всему IR
        ids = pg.evaluate(
            "(() => { const out = []; const walk = n => { if (n.sourceKey) out.push(n.sourceKey);"
            " (n.children || []).forEach(walk); };"
            " (" + ir_js + ".tree || []).forEach(walk); return out; })()")
        check("sourceKey уникальны по всему IR", len(ids) == len(set(ids)),
              f"{len(set(ids))}/{len(ids)}")

        # ---------- Ctrl+X: вырезать выделенное ----------
        pg.keyboard.press("Control+a")
        pg.wait_for_timeout(300)
        pg.keyboard.press("Control+x")
        pg.wait_for_timeout(400)
        n_cut = pg.evaluate(kids_js + ".length")
        check("Ctrl+X удаляет выделенное", n_cut == 0, str(n_cut))
        check("Ctrl+X: выделение снято", sel_count() == 0, str(sel_count()))

        # ---------- undo после всех операций ----------
        blur()
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(400)
        check("undo откатывает Ctrl+X", pg.evaluate(kids_js + ".length") == n_dbl,
              str(pg.evaluate(kids_js + ".length")))
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(400)
        check("undo откатывает paste-all", pg.evaluate(kids_js + ".length") == n_kids,
              str(pg.evaluate(kids_js + ".length")))

        # ---------- регрессия: IR со созданными фигурами проходит схему ----------
        # (style-dna/extract валидирует IR; раньше id на дочерних узлах давал 422)
        resp = pg.evaluate(
            "(ir) => fetch('/api/style-dna/extract', {method:'POST',"
            " headers:{'Content-Type':'application/json'}, body: JSON.stringify({ir})})"
            ".then(r => r.status)", pg.evaluate(ir_js))
        check("IR с фигурами проходит схему (style-dna/extract)", resp == 200, str(resp))

        pg.click('.fe-toolbar [data-act="close"]')
        # защита черновика: редактор с правками спрашивает — закрываем без сохранения
        try:
            pg.wait_for_selector('[data-act="close-discard"]', timeout=1000).click()
        except Exception:
            pass
        pg.wait_for_timeout(300)
        check("редактор закрыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'none'"))
        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL SHAPES/CLIPBOARD CHECKS PASSED")


if __name__ == "__main__":
    main()
