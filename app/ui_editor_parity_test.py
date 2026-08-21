"""UI-тест паритета React DNA Editor: непокрытые уголки порта.
1) линейки канваса нарисованы; 2) зум тулбара; 3) переключение вьюпортов
(desktop/tablet/mobile + кастомная ширина, meta.activeViewport);
4) flyout-группа фигур в rail (hover открывает, клик выбирает, хоткеи
синхронизируют лидера); 5) Style DNA: Preview Normalize и Exact Tailwind.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_parity_test.py
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
    # фикстура без responsive — добавляем, чтобы вьюпорт-бар редактора появился
    # (схема требует width И height на вьюпорт)
    ir["responsive"] = {"viewports": {
        "desktop": {"width": 1440, "height": 900},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 390, "height": 844}}}
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
        pg.wait_for_timeout(500)

        def wait_ir_ready(sel, polls=3, interval=150):
            hits = 0
            for _ in range(80):
                st = pg.evaluate("document.fonts ? document.fonts.status : 'loaded'")
                hits = hits + 1 if st == "loaded" else 0
                if hits >= polls:
                    break
                pg.wait_for_timeout(interval)
            last, stable = None, 0
            for _ in range(50):
                r = pg.evaluate(
                    "(s) => { const el = document.querySelector(s); if (!el) return null;"
                    " const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }",
                    sel)
                if r is not None and r == last:
                    stable += 1
                    if stable >= polls:
                        return
                else:
                    stable = 0
                last = r
                pg.wait_for_timeout(interval)

        wait_ir_ready('.n-edit .edit-inner [class^="ir-"]')
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_selector('.dna-editor[style*="flex"]')
        pg.wait_for_timeout(600)

        # ---------- 1. линейки ----------
        def ruler_drawn(sel):
            return pg.evaluate("""(sel) => {
                const c = document.querySelector(sel);
                if (!c || c.width === 0 || c.height === 0) return false;
                const ctx = c.getContext('2d');
                if (!ctx) return false;
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;
                return false;
            }""", sel)

        check("линейка H нарисована", ruler_drawn(".dna-editor .fe-ruler-h canvas"))
        check("линейка V нарисована", ruler_drawn(".dna-editor .fe-ruler-v canvas"))

        # ---------- 2. зум тулбара ----------
        def zoom_label():
            return pg.evaluate("document.querySelector('.dna-editor .fe-zoom').textContent.trim()")

        z0 = zoom_label()
        pg.click('.dna-editor [data-act="zoom-in"]')
        pg.wait_for_timeout(250)
        z1 = zoom_label()
        check("zoom-in меняет масштаб", z1 != z0, f"{z0} -> {z1}")
        pg.click('.dna-editor [data-act="zoom-fit"]')
        pg.wait_for_timeout(250)
        z2 = zoom_label()
        check("zoom-fit вписывает", z2.endswith("%"), f"{z2}")

        # ---------- 3. вьюпорты ----------
        check("вьюпорт-бар виден (responsive IR)",
              pg.evaluate("document.querySelector('.dna-editor .fe-viewports').hidden === false"))
        WIDTH = ("(() => { const d = window.GraphDev.node(%d).data;"
                 " const ir = d._editorDraft?.ir || d.ir;"
                 " return ir.meta && ir.meta.activeViewport; })()" % nid)
        WIDTH_INPUT = "document.querySelector('.dna-editor .fe-viewport-width').value"

        pg.click('.dna-editor .fe-viewports [data-viewport="tablet"]')
        pg.wait_for_timeout(350)
        check("tablet: ширина 768", pg.evaluate(WIDTH_INPUT) == "768", pg.evaluate(WIDTH_INPUT))
        check("tablet: meta.activeViewport", pg.evaluate(WIDTH) == "tablet", str(pg.evaluate(WIDTH)))
        check("tablet: кнопка active", pg.evaluate(
            "document.querySelector('.dna-editor [data-viewport=\"tablet\"]').classList.contains('active')"))

        pg.click('.dna-editor .fe-viewports [data-viewport="mobile"]')
        pg.wait_for_timeout(350)
        check("mobile: ширина 390", pg.evaluate(WIDTH_INPUT) == "390", pg.evaluate(WIDTH_INPUT))

        pg.fill(".dna-editor .fe-viewport-width", "500")
        pg.wait_for_timeout(350)
        check("кастом 500: активен mobile (<640)", pg.evaluate(
            "document.querySelector('.dna-editor [data-viewport=\"mobile\"]').classList.contains('active')"))
        pg.fill(".dna-editor .fe-viewport-width", "1200")
        pg.wait_for_timeout(350)
        check("кастом 1200: активен desktop", pg.evaluate(
            "document.querySelector('.dna-editor [data-viewport=\"desktop\"]').classList.contains('active')"))
        check("кастом 1200: meta.activeViewport", pg.evaluate(WIDTH) == "desktop", str(pg.evaluate(WIDTH)))

        # ---------- 4. flyout-группа фигур ----------
        check("rail: 5 кнопок", pg.evaluate(
            "document.querySelectorAll('.dna-editor .fe-rail [data-tool]').length === 5"))
        check("лидер flyout — стабильный data-tool=rect", pg.evaluate(
            "document.querySelector('.dna-editor .fe-rail [data-flyout=\"shapes\"]').dataset.tool === 'rect'"))
        pg.hover('.dna-editor .fe-rail [data-flyout="shapes"]')
        pg.wait_for_timeout(450)  # hover-таймер 200 мс
        check("flyout открылся по hover", pg.query_selector(".dna-editor .fe-rail-flyout") is not None)
        check("flyout: 4 фигуры", pg.evaluate(
            "document.querySelectorAll('.dna-editor .fe-rail-flyout [data-fly-item]').length === 4"))
        pg.click('.dna-editor .fe-rail-flyout [data-fly-item="ellipse"]')
        pg.wait_for_timeout(250)
        check("клик по ellipse во flyout активировал инструмент", pg.evaluate(
            "document.querySelector('.dna-editor .fe-rail [data-flyout=\"shapes\"]').classList.contains('active')"))
        check("flyout закрылся после выбора", pg.query_selector(".dna-editor .fe-rail-flyout") is None)

        pg.keyboard.press("r")  # хоткей rect — синхронизация лидера группы
        pg.wait_for_timeout(200)
        pg.hover('.dna-editor .fe-rail [data-flyout="shapes"]')
        pg.wait_for_timeout(450)
        check("хоткей R: leader снова rect", pg.evaluate(
            "document.querySelector('.dna-editor .fe-rail-flyout [data-fly-item=\"rect\"]')"
            ".classList.contains('active')"))
        pg.keyboard.press("v")  # вернуть select
        pg.wait_for_timeout(200)

        # ---------- 5. Style DNA: normalize + tailwind ----------
        pg.click('.dna-editor [data-act="style-dna"]')
        pg.wait_for_selector(".dna-editor .fe-dna-section", timeout=5000)
        check("DNA: кнопки workflow на месте", pg.evaluate(
            "!!document.querySelector('[data-dna-action=\"preview-normalize\"]')"
            " && !!document.querySelector('[data-dna-action=\"tailwind-exact\"]')"))

        pg.click('[data-dna-action="preview-normalize"]')
        # дождаться финального результата (не промежуточного «Building preview…»)
        pg.wait_for_function("""() => {
            const err = document.querySelector('#feDnaWorkflowResult .fe-dna-err');
            if (err) return true;
            const m = document.querySelector('#feDnaWorkflowResult .fe-dna-meta');
            return m && /properties/.test(m.textContent);
        }""", timeout=10000)
        meta = pg.evaluate(
            "(document.querySelector('#feDnaWorkflowResult .fe-dna-meta') || {}).textContent || ''")
        check("Preview Normalize: результат с properties/risk", "properties" in meta, meta)

        pg.click('[data-dna-action="tailwind-exact"]')
        pg.wait_for_selector("#feDnaWorkflowResult .fe-dna-code", timeout=10000)
        code = pg.evaluate("document.querySelector('#feDnaWorkflowResult .fe-dna-code').textContent")
        check("Exact Tailwind: классы не пустые", len(code.strip()) > 0, code[:60])
        check("Copy classes активен", pg.evaluate(
            "document.querySelector('[data-dna-action=\"copy-tailwind\"]').disabled === false"))

        pg.click('.dna-editor [data-act="close-style-dna"]')
        pg.wait_for_timeout(300)
        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_timeout(400)
        browser.close()

    if FAILS:
        print("\nFAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("\nALL PARITY CHECKS PASSED")


if __name__ == "__main__":
    main()
