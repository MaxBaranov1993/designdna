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

import copy
import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

import timeline_render
from ir.timeline import build
from timeline_assets import MaterializedAsset, install_render_asset_guard, rewrite_local_asset_urls
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


def _store_font(data_dir: Path, source: Path = FIXTURE_FONT) -> str:
    """Кладёт шрифт под его скреперным именем: <первые 16 hex sha1(байтов)>.<ext>."""
    fonts = data_dir / "fonts"
    fonts.mkdir(exist_ok=True)
    data = source.read_bytes()
    name = hashlib.sha1(data).hexdigest()[:16] + source.suffix
    (fonts / name).write_bytes(data)
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
    ir = copy.deepcopy(DESIGN_IR)
    ir["tokens"] = {"font": {"display": {"family": "Bebas Neue", "weight": 400},
                              "body": {"family": "Bebas Neue", "weight": 400},
                              "scale": "default"}}
    with pytest.raises(ValueError, match="недоступен офлайн"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)


# --------------------------------------------------------------------------
# Fail closed на ЛЮБОМ заблокированном запросе — даже при чистой готовности


def test_real_render_fails_closed_on_blocked_request_with_clean_readiness(
        tmp_path: Path, monkeypatch) -> None:
    """Регрессия: безвредный внешний запрос попытался и был абортирован,
    шрифты/картинки при этом готовы — рендер всё равно обязан упасть закрытым."""
    monkeypatch.setattr(
        timeline_render, "RENDER_DOCUMENT_HTML",
        timeline_render.RENDER_DOCUMENT_HTML
        + '<link rel="stylesheet" href="https://harmless.example/reset.css">')
    ir = copy.deepcopy(DESIGN_IR)  # ни ассетов, ни шрифтов — readiness чистый
    with pytest.raises(ValueError, match="выйти в сеть"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)


# --------------------------------------------------------------------------
# Перепись ddna:// в CSS url(...) и локальный фон


def test_rewrite_covers_css_url_in_dict_and_string_styles() -> None:
    blob = f"ddna://blobs/{'a1' * 32}.png"
    font = "ddna://fonts/0123456789abcdef.woff2"
    ir = {
        "tree": [{
            "id": "s", "type": "hero",
            "style": f"background-image: url('{blob}'), linear-gradient(#111, #222)",
            "children": [
                {"id": "c1", "type": "rect",
                 "style": {"backgroundImage": f'url("{blob}")',
                            "background": "#ff0000"}},
                {"id": "c2", "type": "rect",
                 "style": {"maskImage": f"url({font})",
                            "boxShadow": "0 1px 2px rgba(0,0,0,.3)"}},
            ],
        }],
        "meta": {"fontFaces": [{"family": "F", "weight": "400", "style": "normal", "url": font}]},
    }
    rewritten = rewrite_local_asset_urls(ir)

    # строковая форма стиля: ddna-ссылка заменена, прочий CSS не тронут
    assert rewritten["tree"][0]["style"] == (
        "background-image: url('/blobs/" + "a1" * 32 + ".png'), linear-gradient(#111, #222)")
    # dict-форма: каждое строковое значение, соседние свойства целы
    assert rewritten["tree"][0]["children"][0]["style"]["backgroundImage"] == (
        'url("/blobs/' + "a1" * 32 + '.png")')
    assert rewritten["tree"][0]["children"][0]["style"]["background"] == "#ff0000"
    assert rewritten["tree"][0]["children"][1]["style"]["maskImage"] == "url(/fonts/0123456789abcdef.woff2)"
    assert rewritten["tree"][0]["children"][1]["style"]["boxShadow"] == "0 1px 2px rgba(0,0,0,.3)"
    # fontFaces — тоже канонический CSS url() источник
    assert rewritten["meta"]["fontFaces"][0]["url"] == "/fonts/0123456789abcdef.woff2"
    # исходный IR не мутирован
    assert ir["tree"][0]["children"][0]["style"]["backgroundImage"] == f'url("{blob}")'


def test_real_render_rewrites_background_styles_and_keeps_zero_blocked(tmp_path: Path) -> None:
    """Локальный фоновый ассет в стилях переписывается в /blobs/...,
    рендер проходит без единого заблокированного запроса."""
    ir = _with_assets(tmp_path)
    blob_url = ir["tree"][0]["children"][0]["src"]
    # фоновый ассет в dict-форме и строковой форме стиля
    ir["tree"][0]["children"][0]["style"] = {"backgroundImage": f"url('{blob_url}')"}
    ir["tree"][0]["style"] = f"background-image: url('{blob_url}')"

    rewritten = rewrite_local_asset_urls(ir)
    expected = "url('" + blob_url.replace("ddna://blobs/", "/blobs/") + "')"
    assert rewritten["tree"][0]["children"][0]["style"]["backgroundImage"] == expected
    assert rewritten["tree"][0]["style"] == f"background-image: {expected}"

    output = tmp_path / "out.mp4"
    result = render_timeline_video(_timeline(ir), ir, output, data_dir=tmp_path)
    assert output.is_file() and result["bytes"] > 0
    assert result["assets"]["blockedRequests"] == [], "ноль внешних запросов"
    assert result["assets"]["imagesLoaded"] >= 1


def test_local_font_via_ddna_css_url_renders_with_zero_blocked(tmp_path: Path) -> None:
    """CSS url() путь: лицо объявлено через ddna://fonts/..., перепись даёт
    /fonts/..., @font-face исполняется гардом — шрифт загружен, запросов нет."""
    font_url = _store_font(tmp_path)                       # /fonts/<sha1-префикс>.woff2
    ddna_font_url = font_url.replace("/fonts/", "ddna://fonts/")
    ir = copy.deepcopy(DESIGN_IR)
    ir["meta"] = {"fontFaces": [{"family": "FixtureFont", "weight": "400",
                                  "style": "normal", "url": ddna_font_url}]}
    ir["tree"][0]["children"].append({
        "id": "branded", "sourceKey": "src-branded", "type": "text", "text": "Бренд",
        "style": {"fontFamily": "FixtureFont, sans-serif"},
        "frame": {"x": 10, "y": 200, "width": 120, "height": 24},
    })
    output = tmp_path / "out.mp4"
    result = render_timeline_video(_timeline(ir), ir, output, data_dir=tmp_path)
    assert output.is_file()
    assert result["assets"]["blockedRequests"] == [], "ноль внешних запросов"
    assert "FixtureFont" in result["assets"]["fontsLoaded"], "CSS url() шрифт загружен локально"


# --------------------------------------------------------------------------
# Скреперный формат имён шрифтов: sha1(байты)[:16] == имя


def test_font_materialization_good_corrupt_missing(tmp_path: Path) -> None:
    from timeline_assets import materialize_render_assets

    fonts = tmp_path / "fonts"
    fonts.mkdir()
    good = FIXTURE_FONT.read_bytes()
    good_name = hashlib.sha1(good).hexdigest()[:16] + ".woff2"
    (fonts / good_name).write_bytes(good)

    # good: имя совпадает с sha1-префиксом содержимого
    ir_good = {"meta": {"fontFaces": [{"family": "F", "weight": "400", "style": "normal",
                                        "url": f"/fonts/{good_name}"}]}, "tree": []}
    assets, errors = materialize_render_assets(ir_good, tmp_path)
    assert errors == [] and assets[f"/fonts/{good_name}"].data == good

    # corrupt: ВАЛИДНЫЙ шрифт, но сохранён под чужим именем (подмена) —
    # отказ по sha1-префиксу ещё до Chromium
    other = bytes(reversed(good))
    alien_name = hashlib.sha1(other).hexdigest()[:16] + ".woff2"
    (fonts / alien_name).write_bytes(good)  # байты не совпадают с именем
    ir_bad = {"meta": {"fontFaces": [{"family": "F", "weight": "400", "style": "normal",
                                       "url": f"/fonts/{alien_name}"}]}, "tree": []}
    _assets, errors = materialize_render_assets(ir_bad, tmp_path)
    assert errors and "подменён" in errors[0] and "sha1" in errors[0]

    # missing: имя правильного формата, файла нет
    ir_missing = {"meta": {"fontFaces": [{"family": "F", "weight": "400", "style": "normal",
                                          "url": "/fonts/" + "e" * 16 + ".woff2"}]}, "tree": []}
    _assets, errors = materialize_render_assets(ir_missing, tmp_path)
    assert errors and "не найден" in errors[0]


def test_real_render_fails_closed_on_replaced_font(tmp_path: Path) -> None:
    """Валидный, но подменённый шрифт валит рендер до запуска кадров."""
    font_url = _store_font(tmp_path)
    name = font_url.rsplit("/", 1)[-1]
    # подменяем содержимое другим валидным woff2-подобным мусором
    (tmp_path / "fonts" / name).write_bytes(FIXTURE_FONT.read_bytes()[::-1])
    ir = copy.deepcopy(DESIGN_IR)
    ir["meta"] = {"fontFaces": [{"family": "FixtureFont", "weight": "400",
                                  "style": "normal", "url": font_url}]}
    with pytest.raises(ValueError, match="подменён"):
        render_timeline_video(_timeline(ir), ir, tmp_path / "out.mp4", data_dir=tmp_path)
