"""Проверка: text-ноды в source-block не рендерят background/border/shadow."""
from __future__ import annotations

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

IR = {
    "version": "1.0",
    "frame": {"width": 960, "height": 600, "layout": "free", "clip": True},
    "tokens": {
        "color": {"primary": "#5b5bd6", "background": "#ffffff", "text": "#111111"},
        "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "md", "button": "md", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "none",
    },
    "tree": [{
        "id": "test-block",
        "type": "source-block",
        "variant": "dom-capture",
        "frame": {"width": 960, "height": 600, "layout": "free", "clip": True},
        "children": [
            {
                "type": "button",
                "text": "Find",
                "frame": {"absolute": True, "x": 100, "y": 100, "width": 120, "height": 40},
                "style": {"background": "#ff691d", "color": "#ffffff", "borderRadius": 8},
                "children": [
                    {
                        "type": "text",
                        "text": "Найти",
                        "frame": {"absolute": True, "x": 10, "y": 10, "width": 100, "height": 20},
                        "style": {
                            "background": "#ff691d",
                            "color": "#ffffff",
                            "fontSize": 14,
                            "borderColor": "#000000",
                            "borderWidth": 2,
                            "borderRadius": 4,
                            "boxShadow": "0 2px 4px rgba(0,0,0,.2)",
                        },
                    }
                ],
            }
        ],
    }],
}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:8420/flow")
        page.wait_for_timeout(1500)
        # Вставляем IR в flow-хранилище и перезагружаем
        saved = page.evaluate("localStorage.getItem('designai-flow-saved')") or "{}"
        try:
            state = json.loads(saved)
        except Exception:
            state = {}
        state["ir"] = IR
        state["viewport"] = state.get("viewport", {"x": 0, "y": 0, "zoom": 1})
        page.evaluate(f"localStorage.setItem('designai-flow-saved', {json.dumps(json.dumps(state))})")
        page.reload()
        page.wait_for_timeout(1500)
        # Рендерим IR через глобальный IRRenderer
        page.evaluate(f"""
            const ir = JSON.parse({json.dumps(json.dumps(IR))});
            const div = document.createElement('div');
            div.style.width = '960px';
            document.body.appendChild(div);
            window.IRRenderer.renderIR(div, ir, {{fit: false}});
        """)
        page.wait_for_timeout(300)
        assert page.locator("p").count() > 0, "renderer did not emit text"
        page.wait_for_timeout(200)
        p_el = page.locator("p").first
        style = p_el.evaluate("el => window.getComputedStyle(el)")
        inline = p_el.evaluate("el => el.getAttribute('style') || ''")
        print(f"inline style: {inline}")
        bg = style.get("backgroundColor", "")
        border = style.get("borderColor", "")
        border_width = style.get("borderWidth", "")
        shadow = style.get("boxShadow", "")
        print(f"border-width: {border_width}")
        print(f"text background: {bg}")
        print(f"text border: {border}")
        print(f"text shadow: {shadow}")
        ok = (bg in ("rgba(0, 0, 0, 0)", "transparent") or "rgba(0" in bg)
        ok = ok and border_width == "0px"
        ok = ok and (shadow == "none" or shadow == "")
        if not ok:
            raise AssertionError(f"text node leaked visual container styles: bg={bg}, border={border}, shadow={shadow}")
        print("OK text node has no background/border/shadow")

        # Проверяем Inspector: transparent-кнопка и opacity slider
        insp_html = page.evaluate("""(ir) => {
            const sec = ir.tree && ir.tree[0];
            const btn = sec && sec.children && sec.children[0];
            const node = btn && btn.children && btn.children[0];
            if (!node) throw new Error('node not found: sec=' + JSON.stringify(sec) + ' btn=' + JSON.stringify(btn));
            const container = document.createElement('div');
            document.body.appendChild(container);
            window.Inspector.render(container, {
                ir: ir,
                selections: [{ref: {secIdx: 0, path: 'children.0.children.0'}, label: 'text', node: node}],
                geo: {frameOf: () => node.frame, posOf: () => ({x:0,y:0}), sizeOf: () => ({w:100,h:20}), setNodeStyle: () => {}}
            });
            return container.innerHTML;
        }""", IR)
        assert "data-clear-style=\"background\"" in insp_html, "missing transparent button for Fill"
        assert "data-clear-style=\"color\"" in insp_html, "missing transparent button for Text"
        assert "data-style-range=\"opacity\"" in insp_html, "missing opacity slider"
        assert "transparent" in insp_html.lower(), "missing transparent placeholder/label"
        print("OK inspector has transparent buttons and opacity slider")

        # Проверяем, что button без children и generic CTA имеют data-ir-path на кликабельном элементе
        sel_ir = {
            "version": "1.0",
            "frame": {"width": 960, "height": 200, "layout": "free", "clip": True},
            "tokens": IR["tokens"],
            "tree": [
                {
                    "id": "navbar",
                    "type": "navbar",
                    "variant": "default",
                    "frame": {"width": 960, "height": 80},
                    "props": {"cta": {"text": "Разместить", "variant": "primary"}},
                    "children": [
                        {"type": "button", "text": "Войти", "variant": "secondary",
                         "frame": {"absolute": True, "x": 700, "y": 20, "width": 100, "height": 40}}
                    ]
                }
            ]
        }
        page.evaluate("""(ir) => {
            const div = document.createElement('div');
            div.style.width = '960px';
            document.body.appendChild(div);
            window.IRRenderer.renderIR(div, ir, {fit: false});
        }""", sel_ir)
        page.wait_for_timeout(300)
        cta_a = page.locator("a.btn:has-text('Разместить')")
        login_a = page.locator("a.btn:has-text('Войти')")
        assert cta_a.count() == 1, "CTA not rendered"
        assert login_a.count() == 1, "login button not rendered"
        assert cta_a.get_attribute("data-ir-path") == "props.cta", f"CTA path mismatch: {cta_a.get_attribute('data-ir-path')}"
        assert login_a.get_attribute("data-ir-path") == "children.0", f"login button path mismatch: {login_a.get_attribute('data-ir-path')}"
        print("OK buttons are selectable (have data-ir-path)")
        browser.close()


if __name__ == "__main__":
    main()
