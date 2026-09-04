"""Генератор живого UI kit: структура, самодостаточность, честность.

Страница — документ для встраивания компонентов в существующий сайт, а не
отчёт о верификации. Главные гарантии, которые здесь фиксируются:
* пять секций в нужном порядке: стиль сайта, токены, компоненты, правила, код;
* верификационной обвязки по умолчанию нет — ни бейджей «нужна проверка», ни
  кропа оригинала, ни таблиц точности, ни секции «Методика»;
* мастера «на ревью» показаны как обычные готовые компоненты;
* точность доступна только по запросу (include_fidelity) и только процентами;
* страница не ссылается наружу — открывается двойным кликом без сети;
* шрифты источника встроены как data:, а наш блок объявлен ПОСЛЕ синглтона
  рендерера (иначе он выиграет по порядку и до последнего компонента доедут
  чужие шрифты);
* meta.fontFaces из встроенных IR снят — иначе рендерер затирает общий стиль;
* состояния не выдумываются.
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


SECTIONS = ("style", "tokens", "components", "rules", "code")


def test_page_is_five_sections_in_reading_order(built):
    _document, html_text, _report = built
    positions = []
    for anchor in SECTIONS:
        assert f'id="{anchor}"' in html_text, anchor
        positions.append(html_text.index(f'id="{anchor}"'))
    assert positions == sorted(positions), "секции идут не в порядке чтения"
    # Верификационная секция ушла: страница отвечает «как сделать», а не
    # «насколько точно мы скопировали».
    assert 'id="method"' not in html_text
    assert 'id="overview"' not in html_text


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


def test_page_carries_no_verification_chrome(built):
    """Кит для встраивания не обсуждает, насколько хорошо мы скопировали."""
    from design_system.document import MASTER_FIDELITY_THRESHOLDS as thresholds

    _document, html_text, _report = built
    page = _page_only(html_text)
    for forbidden in ("НУЖНА ПРОВЕРКА", "нужна проверка", "Needs review", "Оригинал сайта",
                      "Мастер из источника", "Методика", "ЭКЗЕМПЛЯРЫ НА РЕВЬЮ",
                      "Не прошёл проверку точности", "Порог публикации", "Точность",
                      "bbox", "Покрытие краски", "pixelSimilarity",
                      f'{thresholds["minPixelSimilarity"]}%'):
        assert forbidden not in page, forbidden


def _with_measured_fidelity(document: dict) -> dict:
    import copy as _copy

    clone = _copy.deepcopy(document)
    for pool in ("components", "reviewComponents"):
        for component in (clone.get(pool) or {}).values():
            component["fidelity"] = {"status": "verified", "viewports": {
                "desktop": {"pixelSimilarity": 93.375}}}
    return clone


def test_accuracy_is_a_debug_attribute_not_a_table(built):
    from design_system import styleguide

    document, _html, _report = built
    html_text, _ = styleguide.render_styleguide(_with_measured_fidelity(document))
    assert 'data-accuracy="desktop=93.38"' in html_text
    assert "Точность" not in _page_only(html_text)
    assert "<th>" not in _page_only(html_text), "таблиц точности на странице быть не должно"


def test_fidelity_footnote_appears_only_when_asked(built):
    from design_system import styleguide

    document, _html, _report = built
    measured = _with_measured_fidelity(document)
    default_html, _ = styleguide.render_styleguide(measured)
    assert "Точность:" not in default_html

    with_fidelity, _ = styleguide.render_styleguide(measured, include_fidelity=True)
    assert "Точность: desktop 93.4%" in with_fidelity
    # Только проценты: ни порогов, ни вердиктов, ни причин отклонения.
    assert "Порог публикации" not in with_fidelity
    assert "нужна проверка" not in with_fidelity


def test_review_masters_are_rendered_as_ordinary_components(built):
    """Мастер «на ревью» — такой же точный захват сайта, а не второй сорт."""
    document, html_text, report = built
    review_keys = set(document.get("reviewComponents") or {})
    assert review_keys, "фикстура должна давать хотя бы один мастер на ревью"
    for key in review_keys:
        assert f'id="c-{key}"' in html_text, key
    page = _page_only(html_text)
    assert 'class="comp review"' not in page
    assert 'class="badge' not in page
    assert report["componentCount"] == len(
        set(document.get("components") or {}) | review_keys)


def test_style_section_describes_the_site(built):
    document, html_text, _report = built
    style = html_text[html_text.index('id="style"'):html_text.index('id="tokens"')]
    assert "Стиль сайта" in html_text
    assert document["sourceRefs"][0]["url"] in style
    one_line = document["identity"]["soul"]["oneLine"]["value"]
    assert one_line[:40] in style
    assert "Дизайн-язык" in style
    # Голос копирайта показан цитатами, а не пересказом.
    assert "Голос копирайта" in style or "Слова сайта" in style
    assert "«" in style


def test_optional_site_brief_is_rendered_and_merged_into_rules(built):
    from design_system import styleguide

    document, _html, _report = built
    briefed = dict(document, siteBrief={
        "summary": "Маркетплейс бытовой техники для домашних покупателей.",
        "audience": "Розничные покупатели 25-45",
        "tone": "Дружелюбный, без канцелярита",
        "sections": ["Каталог", {"label": "Доставка", "summary": "условия и сроки"}],
        "doRules": ["Кнопку действия держать одну на экран"],
        "dontRules": ["Не вводить новые акцентные цвета"],
    })
    html_text, _ = styleguide.render_styleguide(briefed)
    assert "Маркетплейс бытовой техники" in html_text
    assert "Розничные покупатели 25-45" in html_text
    assert "Доставка — условия и сроки" in html_text
    rules = html_text[html_text.index('id="rules"'):html_text.index('id="code"')]
    assert "Кнопку действия держать одну на экран" in rules
    assert "Не вводить новые акцентные цвета" in rules


def test_page_survives_a_document_without_brief_profile_or_identity(built):
    """Все источники секции «Стиль сайта» опциональны."""
    from design_system import styleguide

    document, _html, _report = built
    bare = dict(document)
    bare.pop("identity", None)
    bare.pop("referenceContent", None)
    bare["styleGuide"] = {"tokens": (document.get("styleGuide") or {}).get("tokens") or {}}
    html_text, report = styleguide.render_styleguide(bare)
    assert 'id="style"' in html_text and report["componentCount"] >= 1


def test_every_card_offers_a_copyable_master_reference(built):
    document, html_text, _report = built
    keys = set(document.get("components") or {}) | set(document.get("reviewComponents") or {})
    for key in keys:
        assert f'id="snip-{key}"' in html_text, key
        assert f'data-target="snip-{key}"' in html_text, key
    assert "componentRef" in html_text and "masterHash" in html_text
    assert "× на сайте" in html_text


def test_viewport_switcher_survives(built):
    _document, html_text, _report = built
    for name in ("desktop", "tablet", "mobile"):
        assert f'data-vp="{name}"' in html_text, name
    assert 'aria-pressed="true"' in html_text
    assert "DDNA.setViewport" in html_text


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
