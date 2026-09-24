"""Page assembly keeps captured Source sections where they were on the site."""
from __future__ import annotations

from ir.validate import validate_ir
from source_page_layout import compose_source_page

SOURCE = "https://example.test/"


def source_block(name: str, x: float, y: float, width: float, height: float, *, clip: bool = True,
                 extra_meta: dict | None = None) -> dict:
    section = {
        "id": name, "type": "source-block", "variant": "dom-capture", "sourceKey": "root", "props": {},
        "style": {"background": "#fbf6ea", "borderRadius": 12},
        "frame": {"width": width, "height": height, "layout": "free", "clip": clip, "padding": [0, 0, 0, 0]},
        "children": [{"type": "text", "text": name, "sourceKey": f"root/{name}",
                      "frame": {"absolute": True, "x": 10, "y": 10, "width": 200, "height": 20}}],
    }
    meta = {"name": name, "pageRect": {"x": x, "y": y, "width": width, "height": height, "source": SOURCE},
            "pageBackground": "#ffffff", **(extra_meta or {})}
    return {"name": name, "ir": {"version": "1.1", "meta": meta, "tokens": {}, "tree": [section]}}


def generated_block() -> dict:
    return {"name": "form", "ir": {"version": "1.1", "meta": {"name": "form"}, "tokens": {}, "tree": [
        {"id": "form", "type": "contact-form", "variant": "default", "props": {"heading": "Contact", "fields": [{"label": "Email", "inputType": "email"}], "submitText": "Send"},
         "frame": {"width": "fill", "height": "hug"}}]}}


def test_sections_become_bands_at_their_page_position() -> None:
    page = compose_source_page([source_block("header", 0, 0, 1440, 80), source_block("hero", 130, 80, 1180, 600)])
    header, hero = page["tree"]
    box = hero["children"][0]
    assert hero["frame"]["width"] == "fill" and hero["frame"]["layout"] == "free"
    assert hero["style"] == {}, "bands are transparent"
    assert page["meta"]["pageBackground"] == "#ffffff", "the page background is painted once on the page root"
    assert box["sourceKey"] == "root::box" and box["frame"]["x"] == 130 and box["frame"]["width"] == 1180
    assert box["role"] == "section", "drawn as the captured box, not a generated card with shadow"
    assert box["style"]["background"] == "#fbf6ea" and box["frame"]["clip"] is True, "section box keeps its own style and clip"
    assert box["children"][0]["text"] == "hero"
    assert header["frame"]["height"] == 80


def test_gaps_and_overlaps_between_neighbours_are_preserved() -> None:
    page = compose_source_page([
        source_block("hero", 130, 80, 1180, 600),
        source_block("features", 130, 700, 1180, 300),      # 20 px gap after hero
        source_block("media", 0, 990, 1440, 400),            # overlaps features by 10 px
    ])
    hero, features, media = page["tree"]
    assert hero["frame"]["height"] == 620
    assert features["frame"]["height"] == 290 and features["frame"]["clip"] is False
    assert media["frame"]["height"] == 400


def test_generated_block_between_bands_flows_and_breaks_the_gap_chain() -> None:
    page = compose_source_page([source_block("hero", 130, 80, 1180, 600), generated_block(),
                                source_block("footer", 0, 700, 1440, 200)])
    hero, form, footer = page["tree"]
    assert form["type"] == "contact-form" and form["frame"]["width"] == "fill"
    assert hero["frame"]["height"] == 600, "no distance-based height across a foreign section"
    assert footer["children"][0]["frame"]["x"] == 0


def test_non_bandable_blocks_keep_the_stacked_layout() -> None:
    legacy = source_block("legacy", 0, 0, 1440, 300)
    legacy["ir"]["tree"][0]["frame"]["layout"] = "auto"
    page = compose_source_page([legacy])
    assert page["tree"][0]["frame"]["width"] == "fill" and page["tree"][0]["children"][0]["text"] == "legacy"


def test_composed_page_validates() -> None:
    page = compose_source_page([source_block("hero", 130, 80, 1180, 600), generated_block(),
                                source_block("footer", 0, 700, 1440, 200)])
    errors = [f"{getattr(error, 'path', '')}: {getattr(error, 'message', error)}" for error in validate_ir(page)
              if not str(getattr(error, "path", "")).startswith("tokens")]
    assert errors == [], errors


def test_transparent_generated_section_between_bands_shows_the_page_background() -> None:
    gradient = "linear-gradient(rgb(251, 248, 240) 0%, rgb(247, 242, 232) 46%, rgb(251, 248, 240) 100%)"
    blocks = [source_block("hero", 130, 80, 1180, 600, extra_meta={"pageBackground": gradient}), generated_block(),
              source_block("footer", 0, 700, 1440, 200, extra_meta={"pageBackground": gradient})]
    page = compose_source_page(blocks)
    assert page["meta"]["pageBackground"] == gradient, "one page-wide gradient, not a copy per band"
    assert not (page["tree"][1].get("style") or {}).get("background"), "the generated section stays transparent"
    painted = generated_block()
    painted["ir"]["tree"][0]["style"] = {"background": "#101010"}
    page = compose_source_page([source_block("hero", 130, 80, 1180, 600), painted])
    assert page["tree"][1]["style"]["background"] == "#101010", "an own surface is kept"
