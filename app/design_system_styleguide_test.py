"""Генератор живого UI kit: структура, самодостаточность, честность.

Главные гарантии, которые здесь фиксируются:
* страница не ссылается наружу — открывается двойным кликом без сети;
* шрифты источника встроены как data:, а наш блок объявлен ПОСЛЕ синглтона
  рендерера (иначе он выиграет по порядку и до последнего компонента доедут
  чужие шрифты);
* meta.fontFaces из встроенных IR снят — иначе рендерер затирает общий стиль;
* состояния не выдумываются, а мастера на ревью не прячутся.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Документ, собранный настоящим билдером, плюс реальный файл шрифта."""
    data_dir = tmp_path_factory.mktemp("sg-data")
    (data_dir / "fonts").mkdir()
    (data_dir / "fonts" / "kit.woff2").write_bytes(
        (ROOT / "app" / "fixtures" / "fixture-font.woff2").read_bytes())
    previous = os.environ.get("DESIGNDNA_DATA_DIR")
    os.environ["DESIGNDNA_DATA_DIR"] = str(data_dir)
    try:
        from design_system import builder, styleguide

        def card(index: int) -> dict:
            return {
                "type": "card", "sourceKey": f"card{index}",
                "style": {"background": "#101014", "borderRadius": 14, "color": "#f4f2ee",
                          "fontFamily": "KitFont"},
                "frame": {"x": index * 300, "y": 0, "width": 280, "height": 180},
                "sourceMeta": {"componentBoundary": True, "componentRole": "article",
                               "componentLabel": "Card", "repeatGroup": "cards"},
                "children": [{"type": "image", "sourceKey": f"card{index}i"},
                             {"type": "heading", "text": "Карточка", "sourceKey": f"card{index}h"}],
            }

        block = {
            "name": "hero", "label": "Hero", "kind": "product-grid", "selector": "body>section",
            "ir": {"version": "1.0",
                   "tokens": {"mode": "dark", "color": {"primary": "#5b6cff"}, "font": {}},
                   "meta": {"fontFaces": [{"family": "KitFont", "weight": "400",
                                           "style": "normal", "url": "/fonts/kit.woff2"}]},
                   "tree": [{"type": "source-block", "sourceKey": "root",
                             "frame": {"width": 1200, "height": 320},
                             "children": [card(i) for i in range(3)]}]},
            "fidelityReport": {"components": {}},
            "sizes": {"desktop": {"width": 1200, "height": 320}},
        }
        pack = builder.build_source_pack(
            {"blocks": [block], "tokens": {}, "url": "https://example.com"}, source_node_id=1)
        pack["_raw_blocks"] = [block]
        document = builder.build_draft(pack, name="UI Kit · test")
        html_text, report = styleguide.render_styleguide(document, generated_at="2026-01-01")
        yield document, html_text, report
    finally:
        if previous is None:
            os.environ.pop("DESIGNDNA_DATA_DIR", None)
        else:
            os.environ["DESIGNDNA_DATA_DIR"] = previous


def _page_only(html_text: str) -> str:
    """Разметка без встроенного движка: строки вроде fonts.googleapis.com живут
    в исходнике engine.js и запросами не являются (это доказывает живой тест)."""
    start = html_text.index('<script type="application/json"')
    return html_text[:start]


def test_page_has_every_section(built):
    _document, html_text, _report = built
    for anchor in ("overview", "foundations", "components", "rules", "code", "method"):
        assert f'id="{anchor}"' in html_text, anchor


def test_page_never_points_outside_itself(built):
    _document, html_text, _report = built
    page = _page_only(html_text)
    for forbidden in ("http://", "https://fonts.", "ddna://", 'src="/', 'href="/fonts/', "/static/"):
        assert forbidden not in page.replace("https://example.com", ""), forbidden


def test_fonts_are_inlined_after_the_renderer_singleton(built):
    _document, html_text, report = built
    assert report["fontFaceCount"] >= 1, report["warnings"]
    assert "@font-face" in html_text and "url('data:font/woff2;base64," in html_text
    assert "font-display:block" in html_text
    # Оба синглтона рендерера созданы заранее, наш блок — ПОСЛЕ них.
    assert html_text.index('id="ir-fonts"') < html_text.index('id="ir-fontfaces"')
    assert html_text.index('id="ir-fontfaces"') < html_text.index('id="ddna-fonts"')


def test_embedded_irs_carry_no_font_faces(built):
    """Иначе renderIR затрёт общий стиль и до последнего компонента доедут чужие."""
    _document, html_text, _report = built
    payload = re.search(r'<script type="application/json" id="ddna-payload">(.*?)</script>',
                        html_text, re.S).group(1)
    data = json.loads(payload.replace("<\\/", "</"))
    assert data["irs"], "в payload нет ни одного IR"
    for ir in data["irs"].values():
        assert "fontFaces" not in (ir.get("meta") or {})
    assert data["fontSpecs"], "без спецификаций bootstrap не предзагрузит шрифты"


def test_every_master_is_present_and_renderable(built):
    document, html_text, report = built
    keys = set(document.get("components") or {}) | set(document.get("reviewComponents") or {})
    assert keys
    for key in keys:
        assert f'id="c-{key}"' in html_text, key
    assert html_text.count("data-ddna-render") >= len(keys)
    assert report["componentCount"] == len(keys)


def test_states_are_reported_as_unobserved_not_drawn(built):
    _document, html_text, _report = built
    assert "не наблюдались в источнике" in html_text
    assert "DesignDNA не рисует то, чего не измерил" in html_text


def test_fidelity_thresholds_come_from_the_shared_constant(built):
    from design_system.document import MASTER_FIDELITY_THRESHOLDS as thresholds

    _document, html_text, _report = built
    assert f'{thresholds["minPixelSimilarity"]}%' in html_text
    assert f'{thresholds["maxBboxP95"]}px' in html_text


def test_live_code_blocks_are_usable(built):
    document, html_text, _report = built
    from design_system import styleguide

    css = styleguide.tokens_css(document)
    assert "--ddna-primary" in css and ":root {" in css
    theme = styleguide.tailwind_theme(document)
    assert theme["extend"]["colors"], "тема Tailwind без цветов бесполезна"
    assert all(value.startswith("var(--ddna-") for value in theme["extend"]["colors"].values())
    tokens = styleguide.figma_tokens(document)
    for group in tokens.values():
        for entry in group.values():
            assert "$type" in entry and "$value" in entry
    assert 'id="code-tokens"' in html_text and 'button class="copy"' in html_text


def test_generation_does_not_mutate_the_document(built):
    from design_system import styleguide
    from design_system.document import canonical_json

    document, _html, _report = built
    before = canonical_json(document)
    styleguide.render_styleguide(document, generated_at="2026-01-01")
    assert canonical_json(document) == before


def test_output_is_stable_between_runs(built):
    """Побайтовая стабильность делает выгрузку сравнимой в git."""
    from design_system import styleguide

    document, html_text, _report = built
    again, _ = styleguide.render_styleguide(document, generated_at="2026-01-01")
    assert again == html_text


def test_report_counts_real_bytes_and_survives_a_tiny_budget(built):
    from design_system import styleguide

    document, html_text, report = built
    assert report["bytes"] == len(html_text.encode("utf-8"))
    with pytest.raises(ValueError):
        styleguide.render_styleguide(document, max_bytes=1_000)


def test_documents_without_masters_produce_no_cards():
    from design_system import styleguide

    empty = {"name": "Пустой", "components": {}, "reviewComponents": {},
             "foundations": {}, "styleGuide": {}, "catalog": {}}
    cards, _warnings, _bytes = styleguide.component_cards(empty)
    assert cards == []
