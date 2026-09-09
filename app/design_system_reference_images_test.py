"""Визуальные референсы ДС в промпте генератора: выбор, рендер, транспорт."""
import base64
import io
import json
from copy import deepcopy
from pathlib import Path

import art_direction
import server
from design_system import reference_images, resolver, store

ROOT = Path(__file__).resolve().parent.parent


def _png_data_url(width: int, height: int, color: tuple) -> str:
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (width, height), (10, 10, 14))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, width - 40, height - 30), outline=color, width=3)
    draw.rectangle((60, 50, 260, 110), fill=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _component(key: str, evidence_key: str, category: str = "surfaces") -> dict:
    return {
        "componentKey": key, "name": key.replace("-", " ").title(), "category": category,
        "origin": "user", "confirmed": True,
        "sourceRef": {"evidenceKey": evidence_key, "bounds": {"x": 50, "y": 40, "width": 300, "height": 90}},
        "masterIr": {"version": "1.1", "tree": [{
            "type": "card", "frame": {"width": 300, "height": 90},
            "style": {"background": "#13131a", "borderColor": "#1b1b1f", "borderWidth": 1, "borderRadius": 14},
            "children": [{"type": "text", "text": f"{key} label", "frame": {"width": 100, "height": 16},
                          "style": {"fontFamily": "JetBrains Mono", "fontSize": 10, "color": "#9d9aab"}}],
        }]},
    }


def _document() -> dict:
    return {
        "id": "ds-ref", "name": "Reference kit", "revision": 1, "contentHash": "published-hash",
        "foundations": {"colors": {"semantic": {"primary": "#5b6cff", "background": "#0a0a0e", "text": "#f2f0ea"}},
                        "typography": {"families": ["Hanken Grotesk", "JetBrains Mono"]}},
        "styleGuide": {},
        "components": {
            "search-field": _component("search-field", "evidence-cta", "forms"),
            "trust-card": _component("trust-card", "evidence-proof"),
            "text-link": {**_component("text-link", "evidence-missing", "actions"), "sourceRef": {}},
        },
        "referenceAssets": {
            "evidence-cta": {"sourceBlock": "cta", "selector": "#start",
                             "blockSizes": {"desktop": {"width": 600, "height": 220}},
                             "referencePreviews": {"desktop": _png_data_url(600, 220, (91, 108, 255))}},
            "evidence-proof": {"sourceBlock": "cta-2", "selector": "#result",
                               "blockSizes": {"desktop": {"width": 600, "height": 1800}},
                               "referencePreviews": {"desktop": _png_data_url(600, 1800, (168, 224, 194))}},
        },
    }


def _context(document: dict, brief: str = "лендинг с формой и доказательствами", mode: str = "extend") -> dict:
    return resolver.resolve_context(document, brief, usage_mode=mode)


def test_candidates_prefer_blocks_for_pages_and_crops_for_components() -> None:
    document = _document()
    landing = reference_images.select_candidates(document, _context(document), surface="landing")
    assert [(item["kind"], item["componentKey"]) for item in landing][:2] == [("block", landing[0]["componentKey"]), ("block", landing[1]["componentKey"])]
    assert landing[2]["kind"] == "crop" and len(landing) == 3
    assert {item["evidenceKey"] for item in landing if item["kind"] == "block"} == {"evidence-cta", "evidence-proof"}
    assert all(item["componentKey"] != "text-link" for item in landing)  # без evidence — без картинки
    component = reference_images.select_candidates(document, _context(document), surface="component")
    assert component[0]["kind"] == "crop" and component[1]["kind"] == "block"
    assert component[1]["evidenceKey"] == component[0]["evidenceKey"]
    assert reference_images.select_candidates(document, _context(document), surface="landing", limit=1) == landing[:1]
    assert reference_images.select_candidates({"components": {}}, {"components": []}) == []
    assert "блок «cta»" in next(item["label"] for item in landing if item["evidenceKey"] == "evidence-cta")


def test_render_produces_jpeg_parts_within_budget() -> None:
    document = _document()
    candidates = reference_images.select_candidates(document, _context(document), surface="landing")
    rendered = reference_images.render(document, candidates)
    assert len(rendered) == 3
    for item in rendered:
        url = item["part"]["image_url"]["url"]
        assert item["part"]["type"] == "image_url" and url.startswith("data:image/jpeg;base64,")
        assert item["bytes"] > 0 and item["label"]
        payload = base64.b64decode(url.split(",", 1)[1])
        assert payload[:3] == b"\xff\xd8\xff"
    from PIL import Image
    tall = next(item for item in rendered if item["kind"] == "block" and "cta-2" in item["label"])
    image = Image.open(io.BytesIO(base64.b64decode(tall["part"]["image_url"]["url"].split(",", 1)[1])))
    assert image.height <= reference_images.BLOCK_MAX_HEIGHT and image.width <= reference_images.BLOCK_MAX_WIDTH
    crop = next(item for item in rendered if item["kind"] == "crop")
    crop_image = Image.open(io.BytesIO(base64.b64decode(crop["part"]["image_url"]["url"].split(",", 1)[1])))
    assert crop_image.size == (300, 90)
    described = reference_images.describe(candidates, rendered)
    assert all(entry["attached"] for entry in described) and len(described) == 3
    # бюджет: ни одна картинка не влезает — все пропущены с причиной, промпт без картинок
    starved = reference_images.select_candidates(document, _context(document), surface="landing")
    assert reference_images.render(document, starved, max_total_bytes=10) == []
    assert all(item["skipped"] for item in starved)
    assert reference_images.prompt_note([]) == ""
    note = reference_images.prompt_note(rendered)
    assert note.startswith("## Визуальные референсы") and "1. " in note and "3. " in note


def test_generate_prepare_only_attaches_reference_images(monkeypatch) -> None:
    document = _document()
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    response = server.generate(server.GenerateReq(
        brief="Лендинг для сервиса автоматизации продаж", count=2, prepareOnly=True,
        designSystem={"systemId": "ds-ref", "revision": 1, "usageMode": "extend"},
    ))
    assert len(response["prompts"]) == 2
    for prompt in response["prompts"]:
        system, user = prompt["messages"]
        assert isinstance(system["content"], str) and "image_url" not in system["content"]
        content = user["content"]
        assert isinstance(content, list) and content[0]["type"] == "text"
        text = content[0]["text"]
        assert "## Визуальные референсы" in text and "Лендинг для сервиса" in text
        assert "Master trust-card" in text and "Decor signature" in text
        images = [part for part in content[1:] if part["type"] == "image_url"]
        assert len(images) == 3 and all(part["image_url"]["url"].startswith("data:image/jpeg;base64,") for part in images)
    compiled = response["designSystem"]
    assert set(compiled["summarizedMasterKeys"]) == {"search-field", "trust-card", "text-link"}
    assert compiled["archetypeSelection"] in ("page", "none")


def test_generate_without_evidence_keeps_plain_text_prompt(monkeypatch) -> None:
    document = _document()
    document.pop("referenceAssets")
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    response = server.generate(server.GenerateReq(
        brief="Карточка доказательства", count=1, prepareOnly=True,
        designSystem={"systemId": "ds-ref", "revision": 1, "usageMode": "style-only"},
    ))
    content = response["prompts"][0]["messages"][1]["content"]
    assert isinstance(content, str) and "Визуальные референсы" not in content and "Master trust-card" in content


def test_raw_outputs_pass_logs_candidates_without_rendering(monkeypatch) -> None:
    document = _document()
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    calls = []
    monkeypatch.setattr(reference_images, "render", lambda *args, **kwargs: calls.append(args) or [])
    master = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    response = server.generate(server.GenerateReq(
        brief="Лендинг для сервиса автоматизации продаж", count=1, rawOutputs=[json.dumps(master)],
        designSystem={"systemId": "ds-ref", "revision": 1, "usageMode": "extend"},
    ))
    assert calls == []  # ответ модели уже есть: картинки не декодируются
    log = response["generationLog"]["designSystem"]
    assert len(log["referenceImages"]) == 3 and all("attached" not in entry for entry in log["referenceImages"])
    assert set(log["summariesInContext"]) == {"search-field", "trust-card", "text-link"}
    assert log["tokenBudget"] == 8000 and log["estimatedTokens"] <= 8000
    assert "sig-mono-labels" in log["decorSignatures"]
