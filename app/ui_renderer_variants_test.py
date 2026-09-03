"""Композиционная свобода в рендерере: блок `composition`, примитив `frame`,
новые варианты hero/feature-grid и тон заглушки изображения.

Скрипт, а не pytest-тест: нужен поднятый сервер (см. BASE) и headless Chromium.
"""
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"
FAILS = []

TOKENS = {
    "mode": "light",
    "color": {"primary": "#0F5C4A", "secondary": "#123B47", "accent": "#E3552B",
              "background": "#F3F5F2", "surface": "#FFFFFF", "text": "#14181A",
              "textMuted": "#55635F", "border": "#D8DED8"},
    "font": {"display": {"family": "Space Grotesk", "weight": 700},
             "body": {"family": "Inter", "weight": 400}, "scale": "default"},
    "radius": {"card": "md", "button": "sm", "input": "sm"},
    "spacing": {"section": "lg", "container": "default"},
    "shadow": "none",
}


def _rows(prefix):
    return [{
        "type": "frame",
        "frame": {"layout": "auto", "direction": "column", "gap": 8},
        "children": [{"type": "heading", "level": 3, "text": f"{prefix} {i}"},
                     {"type": "text", "text": f"Пояснение к пункту {i}"}],
    } for i in range(1, 4)]


IR = {
    "version": "1.1",
    "meta": {"name": "renderer variants", "description": "regression fixture",
             "direction": {"name": "Диспетчерская", "motivation": "мотив", "tradeoff": "цена"}},
    "frame": {"width": 1440},
    "tokens": TOKENS,
    "tree": [
        # 0 — свободная композиция: auto-layout дерево из frame + примитивов
        {"id": "comp", "type": "composition", "variant": "offset-diptych",
         "props": {"background": "surface", "density": "airy", "heading": "Композиция"},
         "children": [{
             "type": "frame",
             "frame": {"layout": "auto", "direction": "row", "gap": 64, "align": "start"},
             "children": [
                 {"type": "frame",
                  "frame": {"layout": "auto", "direction": "column", "gap": 16, "width": 420},
                  "children": [{"type": "heading", "level": 2, "text": "Левая колонка"},
                               {"type": "text", "text": "Текст"},
                               {"type": "divider"}]},
                 {"type": "image", "alt": "запасной alt",
                  "imagePrompt": "Пересменка в цехе, холодный свет сверху"},
             ],
         }]},
        # 1 — композиция на свободном холсте: дети позиционируются по x/y
        {"id": "comp-free", "type": "composition", "variant": "poster-free", "props": {},
         "frame": {"width": "fill", "height": 320, "layout": "free", "padding": 0},
         "children": [{"type": "frame", "frame": {"x": 120, "y": 40, "width": 300, "height": 180},
                       "children": [{"type": "text", "text": "Свободный слой"}]}]},
        # 2..5 — новые варианты hero
        {"id": "hero-editorial", "type": "hero", "variant": "editorial-stack",
         "props": {"badge": "Надзаголовок", "heading": "Редакционная колонка",
                   "subheading": "Лид", "ctaPrimary": {"text": "Действие"},
                   "media": {"alt": "alt", "imagePrompt": "Широкая полоса цеха"}}},
        {"id": "hero-poster", "type": "hero", "variant": "poster",
         "props": {"badge": "Афиша", "heading": "Плакат", "subheading": "Подпись",
                   "ctaPrimary": {"text": "Смотреть"}}},
        {"id": "hero-offset", "type": "hero", "variant": "split-offset",
         "props": {"heading": "Сдвинутый сплит", "subheading": "Лид",
                   "ctaPrimary": {"text": "Действие"},
                   "media": {"alt": "alt", "imagePrompt": "Станок в цехе"}}},
        {"id": "hero-numbered", "type": "hero", "variant": "numbered",
         "props": {"heading": "Нумерованный вход", "ctaPrimary": {"text": "Действие"}},
         "children": _rows("Шаг")},
        # 6..8 — новые варианты feature-grid
        {"id": "fg-rail", "type": "feature-grid", "variant": "list-rail",
         "props": {"heading": "Рейка"}, "children": _rows("Пункт")},
        {"id": "fg-bento", "type": "feature-grid", "variant": "bento-asym",
         "props": {"heading": "Бенто"},
         "children": [{"type": "card", "title": f"Плитка {i}", "text": "Текст"} for i in range(1, 7)]},
        {"id": "fg-manifest", "type": "feature-grid", "variant": "two-col-manifest",
         "props": {"heading": "Манифест", "subheading": "Лид"}, "children": _rows("Правило")},
    ],
}


def check(name, condition, extra=""):
    print(f"[{'OK' if condition else 'FAIL'}] {name}" + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.clear()")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("([id, ir]) => window.GraphDev.setIR(id, ir)", [node_id, IR])
        page.wait_for_timeout(700)
        page.click(".n-edit .f-open-editor")
        page.wait_for_selector('.dna-editor .fe-canvas-inner [class^="ir-"]')
        page.wait_for_timeout(300)

        def sec(index):
            return f'.dna-editor [data-ir-sec="{index}"]'

        for index, name in enumerate([
            "composition", "composition/free", "hero/editorial-stack", "hero/poster",
            "hero/split-offset", "hero/numbered", "feature-grid/list-rail",
            "feature-grid/bento-asym", "feature-grid/two-col-manifest",
        ]):
            box = page.evaluate(
                "s => { const el = document.querySelector(s); if (!el) return null;"
                " const b = el.getBoundingClientRect(); return {w: b.width, h: b.height}; }",
                sec(index))
            check(f"{name}: секция отрисована с ненулевой площадью",
                  bool(box) and box["w"] > 100 and box["h"] > 40, str(box))

        # композиция редактируется как обычные frame-дети: путь до листа дерева
        leaf = page.query_selector(f'{sec(0)} [data-ir-path="children.0.children.0.children.0"]')
        check("composition: у листа дерева есть data-ir-path", leaf is not None)
        nested = page.evaluate(
            "s => { const el = document.querySelector(s); const cs = getComputedStyle(el);"
            " return {display: cs.display, direction: cs.flexDirection, gap: cs.gap}; }",
            f'{sec(0)} [data-ir-path="children.0"]')
        check("composition: auto-layout фрейма доезжает до CSS",
              nested["display"] == "flex" and nested["direction"] == "row", str(nested))

        free_child = page.evaluate(
            "s => { const el = document.querySelector(s); const p = el.closest('[data-ir-sec]');"
            " const b = el.getBoundingClientRect(), pb = p.getBoundingClientRect();"
            " const scale = pb.width / p.offsetWidth;"
            " return {position: getComputedStyle(el).position,"
            "         x: (b.left - pb.left) / scale, y: (b.top - pb.top) / scale}; }",
            f'{sec(1)} [data-ir-path="children.0"]')
        check("composition/free: ребёнок абсолютный и держит x/y",
              free_child["position"] == "absolute"
              and abs(free_child["x"] - 120) <= 2 and abs(free_child["y"] - 40) <= 2,
              str(free_child))

        surface = page.evaluate(
            "s => { const el = document.querySelector(s);"
            " return {cls: el.className, bg: getComputedStyle(el).backgroundColor}; }", sec(0))
        check("composition: фон берётся из токена surface",
              "sec-composition" in surface["cls"] and surface["bg"] == "rgb(255, 255, 255)",
              str(surface))

        # заглушка изображения: тон из палитры + текст из imagePrompt
        placeholder = page.evaluate(
            "s => { const el = document.querySelector(s); const cs = getComputedStyle(el);"
            " return {text: el.textContent.trim(), bg: cs.backgroundColor,"
            "         image: cs.backgroundImage, border: cs.borderTopColor}; }",
            f'{sec(0)} .img-ph')
        check("img-ph: текст заглушки — imagePrompt, а не alt",
              placeholder["text"].startswith("Пересменка в цехе"), placeholder["text"])
        check("img-ph: фон — поверхность палитры, а не серый градиент",
              placeholder["bg"] == "rgb(255, 255, 255)"
              and "gradient" in placeholder["image"]
              and "128, 128, 128" not in placeholder["image"], str(placeholder))
        check("img-ph: рамка из токена border", placeholder["border"] == "rgb(216, 222, 216)",
              placeholder["border"])

        # нумерация в hero/numbered и feature-grid/list-rail несёт порядок
        numbers = page.evaluate(
            "s => Array.from(document.querySelectorAll(s + ' span'))"
            ".map(e => e.textContent.trim()).filter(t => /^0\\d$/.test(t))", sec(5))
        check("hero/numbered: индексы 01/02/03", numbers[:3] == ["01", "02", "03"], str(numbers))
        rail = page.evaluate(
            "s => Array.from(document.querySelectorAll(s + ' span'))"
            ".map(e => e.textContent.trim()).filter(t => /^0\\d$/.test(t))", sec(6))
        check("feature-grid/list-rail: индексы 01/02/03", rail[:3] == ["01", "02", "03"], str(rail))

        # бенто асимметрично: ширины плиток в первом ряду различаются
        widths = page.evaluate(
            "s => Array.from(document.querySelectorAll(s + ' .wrap > div > div'))"
            ".slice(0, 2).map(e => Math.round(e.getBoundingClientRect().width))", sec(7))
        check("feature-grid/bento-asym: соседние плитки разной ширины",
              len(widths) == 2 and abs(widths[0] - widths[1]) > 40, str(widths))

        # split-offset намеренно уводит медиа за правый край рейки, но обрезает
        # вылет секцией: горизонтальной прокрутки у страницы появиться не должно
        offset = page.evaluate(
            # холст редактора отмасштабирован — переводим в единицы макета
            "s => { const section = document.querySelector(s);"
            " const wrap = section.querySelector('.wrap'), media = section.querySelector('.img-ph');"
            " const scale = section.getBoundingClientRect().width / section.offsetWidth;"
            " return {over: (media.getBoundingClientRect().right - wrap.getBoundingClientRect().right) / scale,"
            "         clipped: getComputedStyle(section).overflowX}; }", sec(4))
        check("hero/split-offset: медиа выходит за рейку и обрезано секцией",
              offset["over"] > 40 and offset["clipped"] == "hidden", str(offset))

        overflow = page.evaluate("""() => {
            const root = document.querySelector('.dna-editor .fe-canvas-inner [class^="ir-"]');
            return root.scrollWidth - root.offsetWidth;
        }""")
        check("новые варианты не создают горизонтальный overflow страницы",
              overflow <= 2, str(overflow))

        SHOT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / "ui_renderer_variants.png"), full_page=True)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS))
        for failure in FAILS:
            print(" -", failure)
        raise SystemExit(1)
    print("ALL RENDERER-VARIANTS CHECKS PASSED")


if __name__ == "__main__":
    main()
