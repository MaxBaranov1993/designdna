"""Загрузка своей картинки в image-элемент (заглушку генератора) в DNA-редакторе.

Проверяет: группа «Изображение» в инспекторе для выделенной картинки, загрузка
файла через инспектор пишет data:-URL в src черновика (с даунскейлом до 1600px),
двойной клик по заглушке открывает выбор файла, «Убрать» снимает src,
undo (Ctrl+Z) откатывает вставку.

Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_editor_image_upload_test.py
"""
from __future__ import annotations

import base64
import io
import struct
import sys
import time
import zlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK ] " if ok else "[FAIL] ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def png_bytes(width: int, height: int, rgb=(220, 40, 40)) -> bytes:
    """Минимальный валидный PNG без зависимостей: сплошной цвет."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def document() -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1200, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": "hero", "type": "hero", "variant": "default",
            "frame": {"width": "fill", "layout": "free", "height": 420},
            "children": [
                {"type": "text", "text": "Панель Sendline", "frame": {"x": 40, "y": 40, "width": 300, "height": 40}},
                {"type": "image", "imagePrompt": "Панель управления рассылками", "frame": {"x": 400, "y": 60, "width": 320, "height": 220}},
            ],
        }],
    }


def open_manual(pg) -> None:
    """Ручные настройки инспектора свёрнуты в <details>; раскрыть, если закрыты."""
    pg.wait_for_selector(".manual-controls", state="attached", timeout=5000)
    if not pg.evaluate("!!document.querySelector('.manual-controls')?.open"):
        pg.locator(".manual-controls summary").click()
        pg.wait_for_timeout(150)


DRAFT_SRC = "id => { const d = window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].children[1].src || null; }"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
        pg.route("**/api/project/load", lambda r: r.fulfill(status=200, content_type="application/json", body='{"project":null,"revision":"r1"}'))
        pg.route("**/api/project/save", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok":true,"revision":"r2"}'))
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
        pg.wait_for_function("window.GraphDev && window.DNAEditor")
        pg.evaluate("window.GraphDev.clear()")
        edit_id = pg.evaluate("window.GraphDev.add('edit', 200, 120).id")
        pg.wait_for_timeout(200)
        pg.evaluate("(v) => window.GraphDev.patchData(v.id, {ir: v.ir})", {"id": edit_id, "ir": document()})
        pg.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        pg.wait_for_function("window.DNAEditor.isOpen()")
        pg.wait_for_selector('.fe-canvas [data-ir-path="children.1"]')

        # заглушка на холсте видна и несёт подсказку
        ph = pg.locator('.fe-canvas [data-ir-path="children.1"] .img-ph')
        check("заглушка генератора отрисована", ph.count() == 1)
        hint = pg.evaluate("getComputedStyle(document.querySelector('.fe-canvas .img-ph'), '::after').content")
        check("на заглушке подсказка о загрузке", "загрузить" in hint.lower(), hint)

        # выделяем картинку кликом → инспектор показывает группу «Изображение»
        box = pg.locator('.fe-canvas [data-ir-path="children.1"]').bounding_box()
        pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.wait_for_selector("[data-pi-image]", state="attached", timeout=5000)
        open_manual(pg)
        check("инспектор показывает группу «Изображение»", pg.locator("[data-pi-image]").count() == 1)
        check("без src показана заглушка и кнопка «Загрузить…»",
              "Загрузить" in pg.locator("[data-pi-image] .pi-image-upload").inner_text())

        # загрузка большого PNG через инспектор → src с даунскейлом до 1600px
        big = png_bytes(2400, 1200)
        pg.locator('[data-pi-image] input[data-act="upload-image"]').set_input_files(
            files=[{"name": "hero.png", "mimeType": "image/png", "buffer": big}])
        pg.wait_for_function(f"({DRAFT_SRC})(" + str(edit_id) + ") !== null", timeout=15000)
        src = pg.evaluate(DRAFT_SRC, edit_id)
        check("src записан как data:-URL", isinstance(src, str) and src.startswith("data:image/"), str(src)[:40])
        check("непрозрачный PNG перекодирован в JPEG", src.startswith("data:image/jpeg"), src[:30])
        dims = pg.evaluate("""src => new Promise(res => { const i = new Image(); i.onload = () => res([i.naturalWidth, i.naturalHeight]); i.onerror = () => res(null); i.src = src; })""", src)
        check("картинка ужата до 1600px по большей стороне", dims == [1600, 800], str(dims))
        check("на холсте вместо заглушки <img>", pg.locator('.fe-canvas [data-ir-path="children.1"] img').count() == 1)
        open_manual(pg)
        check("в инспекторе превью и кнопка «Заменить…»",
              pg.locator("[data-pi-image] .pi-image-preview").count() == 1
              and "Заменить" in pg.locator("[data-pi-image] .pi-image-upload").inner_text())
        check("тост о вставке", pg.locator("#toasts .toast", has_text="Картинка вставлена").count() == 1)

        # «Убрать» снимает src
        open_manual(pg)
        pg.click('[data-pi-image] [data-act="clear-image"]')
        pg.wait_for_function(f"({DRAFT_SRC})(" + str(edit_id) + ") === null", timeout=5000)
        check("«Убрать» снял src", pg.evaluate(DRAFT_SRC, edit_id) is None)
        check("заглушка вернулась на холст", pg.locator('.fe-canvas [data-ir-path="children.1"] .img-ph').count() == 1)

        # двойной клик по заглушке открывает выбор файла
        box = pg.locator('.fe-canvas [data-ir-path="children.1"]').bounding_box()
        with pg.expect_file_chooser(timeout=5000) as chooser_info:
            pg.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        chooser = chooser_info.value
        chooser.set_files(files=[{"name": "small.png", "mimeType": "image/png", "buffer": png_bytes(64, 48, (30, 120, 220))}])
        pg.wait_for_function(f"({DRAFT_SRC})(" + str(edit_id) + ") !== null", timeout=15000)
        src2 = pg.evaluate(DRAFT_SRC, edit_id)
        dims2 = pg.evaluate("""src => new Promise(res => { const i = new Image(); i.onload = () => res([i.naturalWidth, i.naturalHeight]); i.onerror = () => res(null); i.src = src; })""", src2)
        check("двойной клик по заглушке загрузил файл", src2 is not None and dims2 == [64, 48], str(dims2))

        # undo откатывает вставку
        pg.locator("body").focus()
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        check("Ctrl+Z откатил вставку картинки", pg.evaluate(DRAFT_SRC, edit_id) is None)

        pg.click('.dna-editor [data-act="close"]')
        try:
            pg.wait_for_selector('[data-act="close-discard"]', timeout=1000).click()
        except Exception:
            pass
        browser.close()

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("ALL IMAGE UPLOAD CHECKS PASSED")


if __name__ == "__main__":
    main()
