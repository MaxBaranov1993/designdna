"""Playwright-тест UI-нод Source Import и Reskin (см. docs/NODES.md).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_houdini_test.py

БЕЗ реальных LLM-вызовов: POST /api/block-parse и /api/reskin перехватываются
через page.route и возвращают маленькие валидные IR.

Проверяет: создание обеих нод из контекстного меню (в меню 14 типов); BlockParse —
без галки «мой сайт» запуск заблокирован, payload {url}, список блоков с превью,
порты только у зажжённых, блок с ошибкой показан с ошибкой, бейдж «из кэша»;
провода: зажжённый блок → Reskin.ir, tokens → Reskin.tokens, несовместимый
провод (ir → tokens) отклоняется; Reskin — payload {ir, prompt, tokens, mask},
результат в data.ir + превью, журнал merge-back отображается, пустая маска не
запускает запрос; после перезагрузки ноды/провода/зажжённые блоки/маска сохранены.
"""
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
BP_URL = "https://mysite.example/landing"
RS_PROMPT = "Сделай стиль теплее: песочные оттенки, скругления мягче"

# Маленький валидный IR: секция cta — рендерится renderer.js без LLM
SMALL_IR = {
    "frame": {"width": 960},
    "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
    "tree": [
        {
            "id": "cta",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": "Мок-заголовок",
                "subheading": "Тестовый IR без LLM",
                "ctaPrimary": {"text": "Кнопка", "variant": "primary"},
            },
        }
    ],
}

# Результат Reskin — тот же блок в «новом стиле» (структура не меняется)
RESKIN_IR = json.loads(json.dumps(SMALL_IR))
RESKIN_IR["tree"][0]["props"]["heading"] = "Рестайл-заголовок"

BP_TOKENS = {
    "color": {"primary": "#5b5bd6", "background": "#ffffff"},
    "font": {"family": "Inter", "scale": [12, 14, 16, 24]},
    "radius": {"m": "12px"},
}

# Ответ /api/block-parse: 2 блока с IR (второй из кэша) + блок с ошибкой
BP_RESP = {
    "url": BP_URL,
    "blocks": [
        {"name": "hero", "selector": "section#hero", "ir": SMALL_IR, "cached": False},
        {"name": "cta", "selector": "section#cta", "ir": SMALL_IR, "cached": True},
        {"name": "broken", "selector": "section#broken",
         "error": "блок не найден по селектору 'section#broken'"},
    ],
    "tokens": BP_TOKENS,
    "cached": False,
}

# Ответ /api/reskin: новый IR + журнал merge-back
RS_RESP = {
    "ir": RESKIN_IR,
    "log": [
        "merge-back: топология дерева сохранена (1 узлов)",
        "отклонено: попытка модели изменить frame (поле залочено)",
        "валидация по схеме: ок",
    ],
}

FAILS = []
CAPTURED = {}


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag_wire(pg, src_sel, dst_sel):
    """Протянуть провод мышью: pointerdown на handle-источнике, drop на приёмнике."""
    src = pg.wait_for_selector(src_sel)
    dst = pg.wait_for_selector(dst_sel)
    sx, sy = center(src.bounding_box())
    dx, dy = center(dst.bounding_box())
    pg.mouse.move(sx, sy)
    pg.mouse.down()
    pg.mouse.move(dx, dy, steps=14)
    pg.mouse.up()
    pg.wait_for_timeout(300)


# ---------- перехват API: никаких реальных LLM-вызовов ----------

def route_block_parse(route):
    CAPTURED.setdefault("block_parse", []).append(route.request.post_data_json)
    route.fulfill(status=200, content_type="application/json", body=json.dumps(BP_RESP))


def route_reskin(route):
    CAPTURED.setdefault("reskin", []).append(route.request.post_data_json)
    route.fulfill(status=200, content_type="application/json", body=json.dumps(RS_RESP))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        pg.route("**/api/block-parse", route_block_parse)
        pg.route("**/api/reskin", route_reskin)

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

        # ---------- создание нод из контекстного меню (14 типов, с Recorder, Motion и Page Bridge) ----------
        pg.click(".react-flow__pane", button="right", position={"x": 300, "y": 120})
        pg.wait_for_selector("#ctx-menu")
        check(
            "контекстное меню: 14 типов нод",
            pg.evaluate("document.querySelectorAll('#ctx-menu .ctx-item').length === 14"),
        )
        pg.click("#ctx-menu .ctx-item[data-type='sourceimport']")
        pg.wait_for_selector(".n-sourceimport")
        check("BlockParse создан из меню",
              pg.evaluate("window.GraphDev.state().nodes.some(n => n.type === 'sourceimport')"))

        pg.click(".react-flow__pane", button="right", position={"x": 900, "y": 120})
        pg.click("#ctx-menu .ctx-item[data-type='reskin']")
        pg.wait_for_selector(".n-reskin")
        check("Reskin создан из меню",
              pg.evaluate("window.GraphDev.state().nodes.some(n => n.type === 'reskin')"))

        # ---------- BlockParse: юридика и запуск ----------
        check("BlockParse: без галки «мой сайт» запуск заблокирован",
              pg.evaluate("document.querySelector('.n-sourceimport .f-run').disabled === true"))
        check("BlockParse: подсказка про «мой сайт» видна",
              bool(pg.locator(".n-sourceimport .bp-hint").count()))

        pg.fill(".n-sourceimport .f-url", BP_URL)
        pg.check(".n-sourceimport .f-mine")
        check("BlockParse: с галкой запуск разрешён",
              pg.evaluate("document.querySelector('.n-sourceimport .f-run').disabled === false"))

        pg.click(".n-sourceimport .f-run")
        pg.wait_for_selector(".n-sourceimport .bp-block", timeout=8000)
        check("BlockParse: список блоков получен (3 шт.)",
              pg.evaluate("document.querySelectorAll('.n-sourceimport .bp-block').length === 3"))
        check(
            "BlockParse: payload {url} без поля blocks (v1 парсит всё)",
            len(CAPTURED.get("block_parse", [])) == 1
            and CAPTURED["block_parse"][0].get("url") == BP_URL
            and "blocks" not in CAPTURED["block_parse"][0],
        )
        check(
            "BlockParse: статус «N блоков (M ошибок)»",
            "3 блоков" in pg.inner_text(".n-sourceimport .n-status")
            and "1 ошибок" in pg.inner_text(".n-sourceimport .n-status"),
        )

        # превью у блоков с IR; блок с ошибкой — текст ошибки, чекбокс недоступен.
        # В SourceImport-ноде превью по умолчанию — «Reference» (скриншот, у моков его нет);
        # миниатюра IR рендерится в режиме «IR» — переключаем.
        pg.click(".n-sourceimport .bp-block[data-block='hero'] .source-preview-mode button:text-is('IR')")
        pg.wait_for_selector(
            ".n-sourceimport .bp-block[data-block='hero'] .bp-preview .ir-preview-inner div[class^='ir-']",
            timeout=5000,
        )
        check("BlockParse: миниатюра IR у блока hero", True)
        check(
            "BlockParse: блок broken показан с ошибкой",
            "блок не найден" in pg.inner_text(".n-sourceimport .bp-block[data-block='broken'] .bp-error"),
        )
        check("BlockParse: у блока с ошибкой чекбокс недоступен",
              pg.evaluate("document.querySelector(\".bp-block[data-block='broken'] .f-lit\").disabled === true"))
        check("BlockParse: бейдж «из кэша» у блока cta",
              bool(pg.locator(".n-sourceimport .bp-block[data-block='cta'] .bp-cached").count()))

        # ---------- порты: только у зажжённых + постоянный tokens ----------
        check("BlockParse: до зажжения только порт tokens",
              pg.evaluate(
                  "(() => { const rows = document.querySelectorAll('.n-sourceimport .port-row.out');"
                  " return rows.length === 1 && rows[0].dataset.port === 'tokens' && rows[0].dataset.kind === 'tokens'; })()"
              ))

        pg.check(".n-sourceimport .bp-block[data-block='hero'] .f-lit")
        pg.check(".n-sourceimport .bp-block[data-block='cta'] .f-lit")
        pg.wait_for_timeout(200)
        check("BlockParse: у зажжённых блоков появились порты (hero+cta+tokens = 3)",
              pg.evaluate("document.querySelectorAll('.n-sourceimport .port-row.out').length === 3"))
        check("BlockParse: handle id = имя блока",
              bool(pg.locator(".n-sourceimport .pp-out-hero").count()))

        # ---------- провода ----------
        drag_wire(pg, ".n-sourceimport .pp-out-hero", ".n-reskin .pp-in-ir")
        check("провод: hero → Reskin.ir",
              pg.evaluate(
                  "(() => { const st = window.GraphDev.state();"
                  " const bp = st.nodes.find(n => n.type === 'sourceimport');"
                  " const rs = st.nodes.find(n => n.type === 'reskin');"
                  " return st.edges.some(e => e.from.node === bp.id && e.from.port === 'hero'"
                  " && e.to.node === rs.id && e.to.port === 'ir'); })()"
              ))

        drag_wire(pg, ".n-sourceimport .pp-out-tokens", ".n-reskin .pp-in-tokens")
        check("провод: tokens → Reskin.tokens",
              pg.evaluate(
                  "(() => { const st = window.GraphDev.state();"
                  " const bp = st.nodes.find(n => n.type === 'sourceimport');"
                  " const rs = st.nodes.find(n => n.type === 'reskin');"
                  " return st.edges.some(e => e.from.node === bp.id && e.from.port === 'tokens'"
                  " && e.to.node === rs.id && e.to.port === 'tokens'); })()"
              ))
        check("протянуты 2 провода", pg.evaluate("window.GraphDev.state().edges.length === 2"))
        check("провод tokens — янтарный (новый kind)",
              pg.evaluate(
                  "Array.from(document.querySelectorAll('.react-flow__edge-path'))"
                  ".some(p => p.style.stroke === '#d6a13b' || p.style.stroke === 'rgb(214, 161, 59)')"
              ))

        # несовместимый провод: ir → tokens отклоняется
        drag_wire(pg, ".n-sourceimport .pp-out-hero", ".n-reskin .pp-in-tokens")
        check("несовместимый провод (ir → tokens) отклонён",
              pg.evaluate("window.GraphDev.state().edges.length === 2"))

        # ---------- Reskin: запуск и результат ----------
        pg.fill(".n-reskin .f-prompt", RS_PROMPT)
        pg.click(".n-reskin .f-run")
        pg.wait_for_selector('.n-reskin .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Reskin: превью результата появилось", True)

        rs_payload = CAPTURED.get("reskin", [{}])[0] if CAPTURED.get("reskin") else {}
        check(
            "Reskin: payload ir — IR зажжённого блока hero",
            rs_payload.get("ir") == SMALL_IR,
        )
        check("Reskin: payload prompt", rs_payload.get("prompt") == RS_PROMPT)
        check("Reskin: payload tokens — из провода", rs_payload.get("tokens") == BP_TOKENS)
        check(
            "Reskin: payload mask — по умолчанию (4 вкл, texts/images выкл)",
            rs_payload.get("mask") == {
                "colors": True, "fonts": True, "radii": True,
                "shadows": True, "texts": False, "images": False,
            },
        )
        check(
            "Reskin: результат в data.ir (heading заменён моделью)",
            pg.evaluate(
                "(() => { const rs = window.GraphDev.state().nodes.find(n => n.type === 'reskin');"
                " const d = window.GraphDev.node(rs.id).data;"
                " return !!d.ir && d.ir.tree[0].props.heading === 'Рестайл-заголовок'; })()"
            ),
        )

        # журнал merge-back: свёрнутый блок, счётчик, содержимое видно после раскрытия
        check("Reskin: журнал merge-back со счётчиком",
              "журнал merge-back" in pg.inner_text(".n-reskin .rs-log summary")
              and "3" in pg.inner_text(".n-reskin .rs-log summary"))
        pg.click(".n-reskin .rs-log summary")
        check("Reskin: записи журнала отображаются",
              "поле залочено" in pg.inner_text(".n-reskin .rs-log"))

        # пустая маска: снимаем все чекбоксы — запуск блокируется, запрос не уходит
        for k in ("colors", "fonts", "radii", "shadows"):
            pg.uncheck(f".n-reskin .f-mask-{k}")
        check("Reskin: пустая маска — запуск заблокирован",
              pg.evaluate("document.querySelector('.n-reskin .f-run').disabled === true"))
        check("Reskin: подсказка про пустую маску видна",
              bool(pg.locator(".n-reskin .rs-hint").count()))
        pg.evaluate("document.querySelector('.n-reskin .f-run').click()")
        pg.wait_for_timeout(300)
        check("Reskin: пустая маска не отправила запрос",
              len(CAPTURED.get("reskin", [])) == 1)

        # включим texts — проверим сохранение маски после перезагрузки
        pg.check(".n-reskin .f-mask-texts")

        # ---------- автосейв (debounce 300 мс) и перезагрузка ----------
        pg.wait_for_timeout(700)
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.wait_for_selector(".n-sourceimport")
        pg.wait_for_selector(".n-reskin")
        check("после перезагрузки: 2 ноды",
              pg.evaluate("window.GraphDev.state().nodes.length === 2"))
        check("после перезагрузки: 2 провода",
              pg.evaluate("window.GraphDev.state().edges.length === 2"))
        check(
            "после перезагрузки: провода hero→ir и tokens→tokens на месте",
            pg.evaluate(
                "(() => { const st = window.GraphDev.state();"
                " const bp = st.nodes.find(n => n.type === 'sourceimport');"
                " const rs = st.nodes.find(n => n.type === 'reskin');"
                " const has = (fp, tp) => st.edges.some(e => e.from.node === bp.id"
                " && e.from.port === fp && e.to.node === rs.id && e.to.port === tp);"
                " return has('hero', 'ir') && has('tokens', 'tokens'); })()"
            ),
        )
        check(
            "после перезагрузки: зажжённые блоки сохранены (hero, cta)",
            pg.evaluate(
                "(() => { const bp = window.GraphDev.state().nodes.find(n => n.type === 'sourceimport');"
                " const d = window.GraphDev.node(bp.id).data;"
                " const by = (n) => d.blocks.find(b => b.name === n);"
                " return by('hero').lit === true && by('cta').lit === true"
                " && by('broken').lit === false && !!by('broken').error; })()"
            ),
        )
        check("после перезагрузки: порты только у зажжённых (3 шт.)",
              pg.evaluate("document.querySelectorAll('.n-sourceimport .port-row.out').length === 3"))
        check(
            "после перезагрузки: маска сохранена (texts вкл, colors/images выкл)",
            pg.evaluate(
                "(() => { const rs = window.GraphDev.state().nodes.find(n => n.type === 'reskin');"
                " const m = window.GraphDev.node(rs.id).data.mask;"
                " return m.texts === true && m.images === false && m.colors === false; })()"
            ),
        )
        check(
            "после перезагрузки: журнал merge-back сохранён",
            pg.evaluate(
                "(() => { const rs = window.GraphDev.state().nodes.find(n => n.type === 'reskin');"
                " return window.GraphDev.node(rs.id).data.log.length === 3; })()"
            ),
        )

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
