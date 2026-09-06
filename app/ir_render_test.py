"""Small contracts for the server-side Design IR renderer."""
from __future__ import annotations

import pytest

import ir_render


def test_render_png_rejects_invalid_width_before_starting_browser():
    with pytest.raises(ValueError, match="between 320 and 4096"):
        ir_render.render_png({}, width=200)
    with pytest.raises(ValueError, match="integer"):
        ir_render.render_png({}, width="wide")


def test_render_png_reports_missing_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(ir_render, "RENDERER_JS", tmp_path / "missing-engine.js")
    with pytest.raises(RuntimeError, match="frontend build"):
        ir_render.render_png({}, width=1440)


def test_mobile_render_passes_viewport_and_changes_only_private_artboard(monkeypatch, tmp_path):
    import copy
    engine = tmp_path / "engine.js"
    engine.write_text("", encoding="utf-8")
    monkeypatch.setattr(ir_render, "RENDERER_JS", engine)
    monkeypatch.setattr(ir_render, "materialize_render_assets", lambda ir: ({}, []))
    monkeypatch.setattr(ir_render, "rewrite_local_asset_urls", copy.deepcopy)
    monkeypatch.setattr(ir_render, "_install_deterministic_font_fallbacks", lambda *_a, **_k: None)
    seen = []
    monkeypatch.setattr(ir_render, "_render_document", lambda ir, assets, width, fonts, fallback, viewport:
        (seen.append((ir, width, viewport)) or b"png", set()))
    source = {"frame": {"width": 1440, "height": "hug"}, "tree": []}
    assert ir_render.render_png(source, width=390, viewport="mobile") == b"png"
    assert source["frame"]["width"] == 1440
    assert seen[0][0]["frame"]["width"] == 390
    assert seen[0][1:] == (390, "mobile")
    with pytest.raises(ValueError, match="viewport"):
        ir_render.render_png(source, viewport="phone")



def test_render_neutralizes_non_asset_hrefs_before_asset_guard():
    """mailto/якоря/внешние ссылки — не ассеты: гард не должен ронять рендер."""
    from ir_render import _neutralize_links

    ir = {"tree": [{"type": "navbar", "props": {"links": [{"label": "Почта", "href": "mailto:a@b.c"},
                                                          {"label": "Секция", "href": "#pricing"},
                                                          {"label": "Сайт", "href": "https://example.com"}],
                                                "cta": {"text": "Заказать", "href": "<якорь>"}}},
                   {"type": "image", "src": "ddna://blobs/abc.png", "href": "ddna://blobs/abc.png"}]}
    out = _neutralize_links(ir)
    links = out["tree"][0]["props"]["links"]
    assert all("href" not in l for l in links)
    assert "href" not in out["tree"][0]["props"]["cta"]
    assert out["tree"][1]["href"] == "ddna://blobs/abc.png"
    # исходник не мутирован
    assert ir["tree"][0]["props"]["links"][0]["href"] == "mailto:a@b.c"
