"""Офлайн-детерминизм видео-рендера: ноль внешних запросов.

Проверяется весь контракт ремонтного блока:
* рендер принимает только локальные контент-адресные ассеты;
* полный SHA-256 и размер блоба проверяются ДО использования;
* отсутствующий/битый объект — отказ (fail closed), не тихий фолбэк;
* локальный шрифт действительно загружается в страницу (не дрейф);
* любые внешние запросы (включая Google Fonts самого движка) блокируются,
  а дрейф на фолбэк-шрифт валит рендер с человекочитаемой причиной;
* готовность картинок/шрифтов проверяется до нулевого кадра.
"""
from __future__ import annotations

import hashlib
import io
import shutil
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from ir.timeline import build
from timeline_assets import MaterializedAsset, install_render_asset_guard
from timeline_render import RENDER_DOCUMENT_URL, render_timeline_video

FIXTURE_FONT = Path(__file__).resolve().parent / "fixtures" / "fixture-font.woff2"

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 320, "height": 240},
    "tree": [
        {
            "id": "hero-1",
            "sourceKey": "src-hero-1",
            "type": "hero",
            "variant": "center",
            "props": {"heading": "Продукт"},
            "frame": {"width": 320, "height": 240, "layout": "free"},
            "children": [
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
            ],
        },
    ],
}


def _png_bytes(color=(200, 40, 40)) -> bytes:
    image = Image.new("RGB", (8, 8), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _timeline(design_ir: dict, duration: int = 500, fps: int = 12) -> dict:
    return build(design_ir, {"width": 320, "height": 240, "fps": fps, "duration": duration})


def _store_blob(data_dir: Path, payload: bytes, ext: str = "png") -> str:
    blobs = data_dir / "blobs"
    blobs.mkdir(exist_ok=True)
    sha = hashlib.sha256(payload).hexdigest()
    (blobs / f"{sha}.{ext}").write_bytes(payload)
    return f"ddna://blobs/{sha}.{ext}"


def _store_font(data_dir: Path, source: Path = FIXTURE_FONT, name: str = "0011223344556677.woff2") -> str:
    fonts = data_dir / "fonts"
    fonts.mkdir(exist_ok=True)
    shutil.copyfile(source, fonts / name)
    return f"/fonts/{name}"


# --------------------------------------------------------------------------
# Гард: локальные байты — да, всё остальное — нет


def test_guard_fulfills_local_assets_and_blocks_external() -> None:
    payload = _png_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    url = f"ddna://blobs/{sha}.png"
    origin = RENDER_DOCUMENT_URL.rsplit("/", 1)[0]
    assets = {url: MaterializedAsset(url=url, data=payload, mime="image/png", source="<test>")}
    blocked: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            install_render_asset_guard(context, assets, blocked,
                                       RENDER_DOCUMENT_URL, "<div id='host'>offline</div>")
            page = context.new_page()
            page.goto(RENDER_DOCUMENT_URL)
            assert "offline" in page.content(), "документ рендера исполняется гардом"

            loaded = page.evaluate(
                """(src) => new Promise((resolve) => {
                     const img = new Image();
                     img.onload = () => resolve(img.naturalWidth > 0);
                     img.onerror = () => resolve(false);
                     img.src = src;
                   })""",
                f"{origin}/blobs/{sha}.png")
            assert loaded is True, "локальный контент-адресный блоб отдаётся через fulfill"

            with pytest.raises(Exception):
                page.goto("https://example.com/", timeout=5000)
            assert any("example.com" in item for item in blocked), "внешний запрос заблокирован и учтён"
        finally:
            browser.close()


# --------------------------------------------------------------------------
# Настоящие рендеры: офлайн-ассеты, шрифты, fail closed


def test_real_render_loads_local_font_and_blob(tmp_path: Path) -> None:
    ir = _with_assets(tmp_path)
    output = tmp_path / "out.mp4"
    result = render_timeline_video(_timeline(ir), ir, output, data_dir=tmp_path)
    assert output.is_file() and result["bytes"] > 0
    assets = result["assets"]
    assert assets["blockedRequests"] == [], "ноль внешних запросов"
    assert "FixtureFont" in assets["fontsLoaded"], "локальный шрифт действительно загружен"
    assert "Inter" in assets["fontsLoaded"], "дефолтный Inter материализован из ассетов приложения"
    assert assets["imagesLoaded"] >= 1, "блоб-картинка загружена до нулевого кадра"


def _with_assets(data_dir: Path) -> dict:
    import copy
    ir = copy.deepcopy(DESIGN_IR)
    blob_url = _store_blob(data_dir, _png_bytes())
    font_url = _store_font(data_dir)
    ir["tree"][0]["children"][0]["src"] = blob_url
    ir["meta"] = {"fontFaces": [{"family": "FixtureFont", "weight": "400", "style": "normal", "url": font_url}]}
    ir["tree"][0]["children"].append({
        "id": "hero-img", "sourceKey": "src-hero-img", "type": "image", "src": blob_url, "alt": "блоб",
        "frame": {"x": 10, "y": 150, "width": 40, "height": 40},
    })
    ir["tree"][0]["children"].append({
        "id": "branded", "sourceKey": "src-branded", "type": "text", "text": "Бренд",
        "style": {"fontFamily": "FixtureFont, sans-serif"},
        "frame": {"x": 10, "y": 200, "width": 120, "height": 24},
    })
    return ir


def test_real_render_fails_closed_on_corrupt_blob(tmp_path: Path) -> None:
    ir = _with_assets(tmp_path)
    blob_url = ir["tree"][0]["children"][0]["src"]
    # портим содержимое: имя (хэш) остаётся, байты подменяются
    sha = blob_url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    (tmp_path / "blobs" / f"{sha}.png").write_bytes(b"corrupted payload")
    with pytest.raises(ValueError, match="sha256"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)


def test_real_render_fails_closed_on_missing_blob(tmp_path: Path) -> None:
    ir = _with_assets(tmp_path)
    ir["tree"][0]["children"][0]["src"] = f"ddna://blobs/{'c' * 64}.png"
    with pytest.raises(ValueError, match="не найден"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)


def test_real_render_surfaces_font_drift_instead_of_silent_fallback(tmp_path: Path) -> None:
    """Семейство только из внешнего каталога (без локального лица) — явный отказ."""
    import copy
    ir = copy.deepcopy(DESIGN_IR)
    ir["tokens"] = {"font": {"display": {"family": "Bebas Neue", "weight": 400},
                              "body": {"family": "Bebas Neue", "weight": 400},
                              "scale": "default"}}
    with pytest.raises(ValueError, match="недоступен офлайн"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)
