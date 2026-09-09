"""Acceptance: contact-form fields are groups with independently editable parts."""
from __future__ import annotations

import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
SCREENSHOT = pathlib.Path(__file__).parent.parent / "artifacts" / "contact-form-fields-editable.png"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


IR = {
    "version": "1.0",
    "frame": {"width": 960, "height": 720},
    "tokens": {
        "mode": "light",
        "color": {"primary": "#7c3aed", "background": "#ffffff", "surface": "#f7f7f8", "text": "#111111", "textMuted": "#6b7280", "border": "#d4d4d8"},
        "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "md", "button": "md", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "none",
    },
    "tree": [{
        "type": "contact-form",
        "variant": "stacked",
        "props": {
            "heading": "Заполните карточку товара",
            "subheading": "Добавьте основные сведения",
            "fields": [
                {"label": "Название товара", "placeholder": "Например, беспроводные наушники", "inputType": "text", "required": True},
                {"label": "Категория", "placeholder": "Выберите категорию", "inputType": "text", "required": True},
                {"label": "Описание", "placeholder": "Расскажите о товаре", "inputType": "textarea", "required": True},
            ],
            "submitText": "Создать карточку товара",
        },
    }],
}


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1700, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: print("PAGE ERROR:", error))
        page.set_default_timeout(6000)
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'", timeout=15000)
        edit_id = page.evaluate("window.GraphDev.add('edit', 60, 40).id")
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": edit_id, "ir": IR})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor[style*="flex"]')
        page.wait_for_timeout(400)

        fields = page.locator(".fe-canvas [data-form-field]")
        assert fields.count() == 3
        assert page.locator('.fe-canvas [data-form-part="label"]').count() == 3
        assert page.locator('.fe-canvas [data-form-part="control"]').count() == 3
        assert page.locator('.fe-canvas [data-form-submit]').count() == 1
        for index in range(3):
            group_key = f"0:props.fields.{index}"
            label_key = f"{group_key}.parts.label"
            control_key = f"{group_key}.parts.control"
            assert page.locator(f'.fe-layer.depth-3[data-key="{label_key}"]').count() == 1
            assert page.locator(f'.fe-layer.depth-3[data-key="{control_key}"]').count() == 1

            label_box = fields.nth(index).locator('[data-form-part="label"]').bounding_box()
            page.mouse.click(label_box["x"] + label_box["width"] / 2, label_box["y"] + label_box["height"] / 2)
            page.wait_for_timeout(120)
            assert page.locator(f'.fe-layer.selected[data-key="{label_key}"]').count() == 1, index

            control_box = fields.nth(index).locator('[data-form-part="control"]').bounding_box()
            page.mouse.click(control_box["x"] + control_box["width"] / 2, control_box["y"] + control_box["height"] / 2)
            page.wait_for_timeout(120)
            assert page.locator(f'.fe-layer.selected[data-key="{control_key}"]').count() == 1, index
            assert page.locator("[data-ai-inspector]").count() == 1, index
            assert page.evaluate("!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)")

            page.locator(f'.fe-layer[data-key="{group_key}"]').dispatch_event("click")
            assert page.locator(f'.fe-layer.selected[data-key="{group_key}"]').count() == 1, index

        # Edit label and control independently through their nested layers.
        page.locator('.fe-layer[data-key="0:props.fields.0.parts.label"]').dispatch_event("click")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        page.locator('[data-el-prop="text"]').fill("Товар")
        page.locator('[data-el-prop="text"]').press("Tab")

        page.locator('.fe-layer[data-key="0:props.fields.0.parts.label"]').dispatch_event("click")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        page.locator('[data-style-num="fontSize"]').fill("19")
        page.locator('[data-style-num="fontSize"]').press("Tab")

        page.locator('.fe-layer[data-key="0:props.fields.0.parts.control"]').dispatch_event("click")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        page.locator('[data-el-prop="placeholder"]').fill("Введите название товара")
        page.locator('[data-el-prop="placeholder"]').press("Tab")

        page.locator('.fe-layer[data-key="0:props.fields.0.parts.control"]').dispatch_event("click")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        page.locator('[data-style-color="background"]').evaluate(
            "el => { el.value = '#eef2ff'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.wait_for_timeout(180)

        draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        field = draft["tree"][0]["props"]["fields"][0]
        assert field["parts"]["label"]["text"] == "Товар"
        assert field["parts"]["label"]["style"]["fontSize"] == 19
        assert field["parts"]["control"]["placeholder"] == "Введите название товара"
        assert field["parts"]["control"]["style"]["background"] == "#eef2ff"
        rendered = page.locator('.fe-canvas [data-form-field="0"]')
        assert rendered.locator('[data-form-part="label"]').inner_text() == "Товар *"
        assert rendered.locator('[data-form-part="control"]').get_attribute("placeholder") == "Введите название товара"
        assert rendered.locator('[data-form-part="label"]').evaluate("el => getComputedStyle(el).fontSize") == "19px"
        assert rendered.locator('[data-form-part="control"]').evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(238, 242, 255)"

        # The submit button is a first-class editable form element.
        submit = page.locator('.fe-canvas [data-form-submit]')
        submit_box = submit.bounding_box()
        page.mouse.click(submit_box["x"] + submit_box["width"] / 2, submit_box["y"] + submit_box["height"] / 2)
        page.wait_for_timeout(150)
        assert page.locator('.fe-layer.selected[data-key="0:props.submit"]').count() == 1
        assert page.evaluate("document.activeElement?.tagName !== 'A'")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        submit_text = page.locator('.field-content [data-el-prop="text"]')
        submit_text.fill("Опубликовать товар")
        submit_text.press("Tab")
        page.locator('.fe-layer[data-key="0:props.submit"]').dispatch_event("click")
        if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
            page.locator(".manual-controls summary").click()
        page.locator('[data-style-color="background"]').evaluate(
            "el => { el.value = '#2563eb'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.wait_for_timeout(180)
        draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        assert draft["tree"][0]["props"]["submit"]["text"] == "Опубликовать товар"
        assert draft["tree"][0]["props"]["submit"]["style"]["background"] == "#2563eb"
        assert submit.inner_text() == "Опубликовать товар"
        assert submit.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(37, 99, 235)"

        if not page.locator(".manual-controls").evaluate("el => el.open"):
            if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
                page.locator(".manual-controls summary").click()
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True, timeout=20000)
        page.locator('.dna-editor [data-act="close"]').click()
        page.close(run_before_unload=False)
        context.close()
        browser.close()
    print("ALL CONTACT FORM FIELD CHECKS PASSED")


if __name__ == "__main__":
    main()
