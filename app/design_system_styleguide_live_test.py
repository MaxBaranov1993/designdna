"""Сгенерированный UI kit в настоящем браузере.

Юнит-тест проверяет структуру строки. Здесь проверяется то, что строкой не
проверить: страница действительно отрисовывает компоненты, применяет шрифты
сайта и НЕ ХОДИТ НАРУЖУ НИ ОДНИМ ЗАПРОСОМ — это и есть смысл «самодостаточного
файла, который открывается двойным кликом».

Шрифт проверяется у ПОСЛЕДНЕГО отрисованного компонента: рендерер перезаписывает
общий на документ <style> при каждом вызове, и регрессию обхода поймает только
последний, а не первый.
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="sg-live-")
os.environ["DESIGNDNA_DATA_DIR"] = _TMP
sys.path.insert(0, str(ROOT / "app"))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK " if ok else "FAIL ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def _fixture_document() -> dict:
    from design_system import builder

    fonts_dir = Path(_TMP) / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    source_font = ROOT / "app" / "fixtures" / "fixture-font.woff2"
    (fonts_dir / "kitfont.woff2").write_bytes(source_font.read_bytes())

    def card(index: int) -> dict:
        return {
            "type": "card", "sourceKey": f"card{index}",
            "style": {"background": "#101014", "borderRadius": 14, "color": "#f4f2ee",
                      "fontFamily": "FixtureFont", "fontSize": 20},
            "frame": {"x": index * 300, "y": 0, "width": 280, "height": 180},
            "sourceMeta": {"componentBoundary": True, "componentRole": "article",
                           "componentLabel": "Card", "repeatGroup": "cards"},
            "children": [
                {"type": "heading", "text": f"Карточка {index}", "sourceKey": f"card{index}h",
                 "style": {"fontFamily": "FixtureFont", "fontSize": 22, "color": "#f4f2ee"},
                 "frame": {"x": 16, "y": 16, "width": 240, "height": 30}},
            ],
        }

    def button(index: int) -> dict:
        return {
            "type": "button", "text": f"Кнопка {index}", "sourceKey": f"btn{index}",
            "style": {"background": "#5b6cff", "color": "#ffffff", "borderRadius": 999,
                      "fontFamily": "FixtureFont", "fontSize": 15},
            "frame": {"x": index * 140, "y": 220, "width": 120, "height": 44},
            "sourceMeta": {"componentBoundary": True, "componentRole": "button",
                           "componentLabel": "Button", "repeatGroup": "buttons"},
            "children": [],
        }

    block = {
        "name": "hero", "label": "Hero", "kind": "product-grid", "selector": "body>section",
        "ir": {
            "version": "1.0",
            "tokens": {"mode": "dark", "color": {"primary": "#5b6cff", "background": "#0b0d12",
                                                 "text": "#f4f2ee"}, "font": {}},
            "meta": {"fontFaces": [{"family": "FixtureFont", "weight": "400", "style": "normal",
                                    "url": "/fonts/kitfont.woff2"}]},
            "tree": [{"type": "source-block", "sourceKey": "root",
                      "frame": {"width": 1200, "height": 320},
                      "children": [card(i) for i in range(3)] + [button(i) for i in range(3)]}],
        },
        "fidelityReport": {"components": {}},
        "sizes": {"desktop": {"width": 1200, "height": 320}},
    }
    pack = builder.build_source_pack(
        {"blocks": [block], "tokens": {}, "url": "https://example.com"}, source_node_id=1)
    pack["_raw_blocks"] = [block]
    return builder.build_draft(pack, name="UI Kit · live")


def main() -> None:
    from design_system import styleguide

    document = _fixture_document()
    html_text, report = styleguide.render_styleguide(document, generated_at="2026-01-01")
    check("страница собралась", report["bytes"] > 10_000, str(report["bytes"]))
    check("шрифт источника встроен", report["fontFaceCount"] >= 1,
          str(report["warnings"][:3]))

    page_path = Path(_TMP) / "kit.html"
    page_path.write_text(html_text, encoding="utf-8")

    from playwright.sync_api import sync_playwright

    external: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("request", lambda request: (
                external.append(request.url)
                if not request.url.startswith(("file://", "data:")) else None))
            page.on("console", lambda message: (
                console_errors.append(message.text) if message.type == "error" else None))
            page.on("pageerror", lambda error: console_errors.append(str(error)))

            url = "file:///" + urllib.parse.quote(str(page_path).replace("\\", "/")) + "#all"
            page.goto(url, wait_until="load")
            page.wait_for_function("() => document.documentElement.dataset.ddnaReady === '1'",
                                   timeout=20_000)
            page.wait_for_timeout(1500)

            check("страница не делает внешних запросов", not external,
                  ", ".join(external[:3]))
            check("консоль без ошибок", not console_errors, "; ".join(console_errors[:3]))

            total = page.evaluate("document.querySelectorAll('[data-ddna-render]').length")
            empty = page.evaluate("document.querySelectorAll('[data-ddna-render]:empty').length")
            check("контейнеры компонентов есть", total > 0, str(total))
            check("все контейнеры отрисованы", empty == 0, f"{empty} из {total} пустых")

            faces = page.evaluate("""() => {
              const out = [];
              for (const face of document.fonts) out.push({ family: face.family, status: face.status });
              return out;
            }""")
            loaded = {face["family"] for face in faces if face["status"] == "loaded"}
            check("шрифт источника загружен", "FixtureFont" in loaded,
                  str(faces[:4]))
            check("нет шрифтов в ошибке",
                  not [face for face in faces if face["status"] == "error"], str(faces[:4]))

            # Последний контейнер — тот, на котором ломается обход синглтона.
            applied = page.evaluate("""() => {
              const nodes = document.querySelectorAll('[data-ddna-render]');
              const last = nodes[nodes.length - 1];
              const el = last.querySelector('h1,h2,h3,h4,p,span,a,button') || last;
              return getComputedStyle(el).fontFamily;
            }""")
            check("шрифт применён к ПОСЛЕДНЕМУ компоненту", "FixtureFont" in applied, applied)

            check("живой код доступен",
                  page.evaluate("typeof window.DDNA === 'object' && !!window.DDNA.renderAll"))
            check("кнопки копирования есть",
                  page.evaluate("document.querySelectorAll('button.copy').length") >= 3)
        finally:
            browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL STYLEGUIDE LIVE CHECKS PASSED")


if __name__ == "__main__":
    main()
