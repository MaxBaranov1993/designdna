"""Browser UI actions: TimelineWorkspace undo/coalesce, AI preview apply/cancel,
persistence on close, keyboard access (Playwright against a running server).

Сценарии (редактор видео поверх ноды Timeline в графе):
1. клавиатурный скраб линейки (role=slider, стрелки двигают плейхед);
2. Undo возвращает документ ДО мутации (не после);
3. драг кейфрейма собирается в ОДНУ запись истории (один Undo откатывает весь жест);
4. ИИ-режиссёр: превью с Применить/Отменить, канон ноды не мутируется до Применить;
5. закрытие редактора сбрасывает несособранный дебаунс — последняя валидная
   правка сохраняется в ноде.

Запуск: python app/ui_timeline_workspace_test.py (сервер на :8420, как в ui_smoke).
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8420")
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def design_ir() -> dict:
    return {
        "version": "1.1",
        "frame": {"width": 1440},
        "tree": [
            {
                "id": "hero-1",
                "sourceKey": "src-hero-1",
                "type": "hero",
                "variant": "center",
                "props": {"heading": "Продукт"},
                "children": [
                    {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
                ],
            },
            {"id": "footer-1", "type": "footer", "variant": "simple", "props": {}},
        ],
    }


def node_timeline(page, node_id: int) -> dict | None:
    return page.evaluate("id => window.GraphDev.node(id)?.data?.timeline ?? null", node_id)


def layer_props(timeline: dict | None, layer_id: str) -> dict:
    if not timeline:
        return {}
    layer = next((l for l in timeline.get("layers", []) if l.get("id") == layer_id), None)
    return (layer or {}).get("transform", {}).get("properties", {})


def layer_timing(page, node_id: int, layer_id: str) -> dict | None:
    return page.evaluate("""(v) => {
      const tl = window.GraphDev.node(v.id)?.data?.timeline;
      const layer = (tl?.layers || []).find((l) => l.id === v.layer);
      return layer ? { in: layer.in, out: layer.out, duration: tl.composition.duration } : null;
    }""", {"id": node_id, "layer": layer_id})


def timing_valid(t: dict | None) -> bool:
    return bool(t) and 0 <= t["in"] < t["out"] <= t["duration"]


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")

        # --- нода Video Editor с входным Design IR ---
        timeline_id = page.evaluate("window.GraphDev.add('timeline', 200, 120).id")
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {ir: v.ir})",
                      {"id": timeline_id, "ir": design_ir()})
        page.evaluate("id => window.GraphDev.run(id)", timeline_id)
        page.wait_for_function(
            "id => Boolean(window.GraphDev.node(id)?.data?.timeline)",
            arg=timeline_id, timeout=15000)
        baseline = node_timeline(page, timeline_id)
        check("timeline собран из входного Design IR", bool(baseline and baseline.get("layers")))

        page.click(f'.svelte-flow__node[data-id="{timeline_id}"] button:has-text("Открыть редактор")')
        page.wait_for_selector('.tlw-root [data-act="ruler"]')

        # --- 1. клавиатурный скраб линейки ---
        ruler = page.locator('.tlw-root [data-act="ruler"]')
        check("линейка доступна с клавиатуры (role=slider)",
              ruler.get_attribute("role") == "slider" and ruler.get_attribute("tabindex") == "0")
        ruler.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(50)
        check("стрелка вправо двигает плейхед",
              page.evaluate("Number(document.querySelector('.tlw-root [data-act=\"ruler\"]').getAttribute('aria-valuenow'))") > 0)

        # --- 2. Undo возвращает документ ДО мутации ---
        page.click('.tlw-root [data-act="layer"] >> nth=0')
        page.click('.tlw-root [data-act="add-keyframe"]')
        page.wait_for_timeout(800)  # дебаунс 400мс + валидация
        mutated = node_timeline(page, timeline_id)
        mutated_props = layer_props(mutated, "layer-hero-1")
        check("кейфрейм добавлен и досинхронизирован в ноду", bool(mutated_props.get("opacity")))

        page.click('.tlw-root [data-act="undo"]')
        page.wait_for_timeout(200)
        undone = node_timeline(page, timeline_id)
        check("Undo вернул документ ДО мутации",
              layer_props(undone, "layer-hero-1") == layer_props(baseline, "layer-hero-1"))

        # --- 3. драг кейфрейма — одна запись истории ---
        page.locator('.tlw-root [data-act="ruler"]').focus()
        for _ in range(30):
            page.keyboard.press("ArrowRight")
        page.click('.tlw-root [data-act="add-keyframe"]')
        page.wait_for_timeout(800)
        before_drag = node_timeline(page, timeline_id)
        kf_before = layer_props(before_drag, "layer-hero-1").get("opacity", {}).get("keyframes", [])
        check("кейфрейм для драга создан", len(kf_before) == 1)

        key = page.locator(".tlw-key >> nth=0")
        box = key.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            for step in range(1, 9):  # 8 движений — без коалесции это 8 записей истории
                page.mouse.move(box["x"] + box["width"] / 2 + step * 12, box["y"] + box["height"] / 2)
                page.wait_for_timeout(16)
            page.mouse.up()
            page.wait_for_timeout(800)
            dragged = node_timeline(page, timeline_id)
            kf_after = layer_props(dragged, "layer-hero-1").get("opacity", {}).get("keyframes", [])
            check("драг сдвинул кейфрейм", bool(kf_after) and kf_after[0]["t"] != kf_before[0]["t"])

            page.click('.tlw-root [data-act="undo"]')  # ОДИН клик — откатывает весь жест
            page.wait_for_timeout(200)
            rolled_back = node_timeline(page, timeline_id)
            kf_rolled = layer_props(rolled_back, "layer-hero-1").get("opacity", {}).get("keyframes", [])
            check("один Undo откатывает весь драг (коалесция жестов)",
                  bool(kf_rolled) and kf_rolled[0]["t"] == kf_before[0]["t"],
                  f"ожидали t={kf_before[0]['t'] if kf_before else '?'}, получили {kf_rolled}")
        else:
            check("драг кейфрейма: элемент найден", False, ".tlw-key не виден")

        # --- 4. ИИ-превью: Применить/Отменить, канон не мутируется до Применить ---
        canonical_before = json.dumps(node_timeline(page, timeline_id), sort_keys=True)
        page.fill('.tlw-root [data-act="ai-prompt"]', "интро снизу, наезд на последней")
        page.click('.tlw-root [data-act="ai-run"]')
        page.wait_for_selector('.tlw-root [data-act="ai-preview"]')
        preview_visible = page.locator('.tlw-root [data-act="ai-preview"]').is_visible()
        apply_btn = page.locator('.tlw-root [data-act="ai-apply"]')
        cancel_btn = page.locator('.tlw-root [data-act="ai-cancel"]')
        check("превью ИИ показывает Применить и Отменить",
              preview_visible and apply_btn.is_visible() and cancel_btn.is_visible())
        check("канонический таймлайн ноды не мутирован до Применить",
              json.dumps(node_timeline(page, timeline_id), sort_keys=True) == canonical_before)

        cancel_btn.click()
        page.wait_for_timeout(150)
        check("Отменить убирает превью без правок",
              not page.locator('.tlw-root [data-act="ai-preview"]').is_visible()
              and json.dumps(node_timeline(page, timeline_id), sort_keys=True) == canonical_before)

        page.click('.tlw-root [data-act="ai-run"]')
        page.wait_for_selector('.tlw-root [data-act="ai-preview"]')
        page.click('.tlw-root [data-act="ai-apply"]')
        page.wait_for_selector('.tlw-root [data-act="ai-preview"]', state="detached")
        page.wait_for_timeout(800)
        applied = node_timeline(page, timeline_id)
        check("Применить записывает ИИ-монтаж в ноду",
              bool(layer_props(applied, "layer-hero-1").get("opacity"))
              and json.dumps(applied, sort_keys=True) != canonical_before)
        check("после Применить доступен откат ИИ-патча",
              page.locator('.tlw-root [data-act="ai-revert"]').is_visible())

        # --- 5. границы трима: 0 <= in < out <= duration при любом вводе ---
        page.click('.tlw-root [data-act="layer"] >> nth=0')
        page.wait_for_timeout(150)
        pre_timing = layer_timing(page, timeline_id, "layer-hero-1")
        check("исходный тайминг слоя валиден", timing_valid(pre_timing), str(pre_timing))

        def undo_times(n: int) -> None:
            for _ in range(n):
                page.click('.tlw-root [data-act="undo"]')
                page.wait_for_timeout(120)

        # числовой ввод за верхнюю границу: in не может стать >= out
        in_input = page.locator("label:has-text('in, с') input")
        in_input.fill("999")
        in_input.press("Tab")
        page.wait_for_timeout(800)
        t = layer_timing(page, timeline_id, "layer-hero-1")
        check("числовой in=999с зажат в 0 <= in < out <= duration", timing_valid(t), str(t))
        undo_times(1)
        check("Undo вернул тайминг до числовой правки",
              layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)

        # числовой ввод ниже нуля: out не может стать <= in
        out_input = page.locator("label:has-text('out, с') input")
        out_input.fill("0")
        out_input.press("Tab")
        page.wait_for_timeout(800)
        t = layer_timing(page, timeline_id, "layer-hero-1")
        check("числовой out=0 зажат в 0 <= in < out <= duration", timing_valid(t), str(t))
        undo_times(1)
        check("Undo вернул тайминг после числового out=0",
              layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)

        # клавиатура на границе 0: ещё шаг влево не даёт in=-1
        in_input.fill("0")
        in_input.press("Tab")
        page.wait_for_timeout(800)
        first_track = page.locator('.tlw-track').nth(0)
        first_track.locator('.tlw-trim:not(.right)').focus()
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(800)
        t = layer_timing(page, timeline_id, "layer-hero-1")
        check("клавиша влево на границе не даёт in=-1", timing_valid(t) and t["in"] == 0, str(t))
        undo_times(2)
        check("Undo вернул тайминг после клавиатурной границы",
              layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)

        # клавиатура на границе duration: ещё шаг вправо не даёт out=duration+1
        out_input.fill(str(pre_timing["duration"] / 1000))
        out_input.press("Tab")
        page.wait_for_timeout(800)
        first_track.locator('.tlw-trim.right').focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(800)
        t = layer_timing(page, timeline_id, "layer-hero-1")
        check("клавиша вправо на границе не даёт out=duration+1",
              timing_valid(t) and t["out"] == t["duration"], str(t))
        undo_times(2)
        check("Undo вернул тайминг после клавиатурной границы duration",
              layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)

        # мышь: драг начала клипа далеко влево — коалесция в одну запись, in >= 0
        trim_in = first_track.locator('.tlw-trim:not(.right)')
        box = trim_in.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            for step in range(1, 7):
                page.mouse.move(box["x"] + box["width"] / 2 - step * 500, box["y"] + box["height"] / 2)
                page.wait_for_timeout(16)
            page.mouse.up()
            page.wait_for_timeout(800)
            t = layer_timing(page, timeline_id, "layer-hero-1")
            check("драг трима влево держит 0 <= in < out", timing_valid(t) and t["in"] == 0, str(t))
            undo_times(1)  # весь драг — одна запись истории
            check("один Undo откатывает весь драг трима",
                  layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)
        else:
            check("драг трима: элемент найден", False, ".tlw-trim не виден")

        # мышь: драг конца клипа далеко вправо — out <= duration
        trim_out = first_track.locator('.tlw-trim.right')
        box = trim_out.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            for step in range(1, 7):
                page.mouse.move(box["x"] + box["width"] / 2 + step * 500, box["y"] + box["height"] / 2)
                page.wait_for_timeout(16)
            page.mouse.up()
            page.wait_for_timeout(800)
            t = layer_timing(page, timeline_id, "layer-hero-1")
            check("драг трима вправо держит out <= duration",
                  timing_valid(t) and t["out"] == t["duration"], str(t))
            undo_times(1)
            check("один Undo откатывает весь драг конца клипа",
                  layer_timing(page, timeline_id, "layer-hero-1") == pre_timing)
        else:
            check("драг трима вправо: элемент найден", False, ".tlw-trim.right не виден")

        # --- 6. закрытие сбрасывает несособранный дебаунс ---
        duration_input = page.locator("label:has-text('Длительность, с') input")
        duration_input.fill("8")
        duration_input.press("Tab")  # change ушёл, дебаунс ещё не собрался
        page.click('.tlw-root [data-act="close"]')
        page.wait_for_timeout(900)  # фоновая валидация досинхронизирует
        closed_timeline = node_timeline(page, timeline_id)
        check("закрытие сохранило последнюю валидную правку",
              int((closed_timeline or {}).get("composition", {}).get("duration") or 0) == 8000,
              f"duration={(closed_timeline or {}).get('composition', {}).get('duration')}")

        browser.close()


if __name__ == "__main__":
    main()
    if FAILS:
        print(f"\n{len(FAILS)} FAIL: {', '.join(FAILS)}")
        sys.exit(1)
    print("\nALL OK")
    sys.exit(0)
