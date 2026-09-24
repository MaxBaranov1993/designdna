"""Хореография видео: шаблоны, камера, слияние кейфреймов, быстрый моушн-путь."""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import timeline_choreography as choreo
import timeline_director
from ir.timeline import CAMERA_LAYER_ID, PRESET_NAMES, apply_change_set, build, build_change_set, revert_change_set, validate
from server import app
from timeline_choreography import (
    TEMPLATE_NAMES,
    is_motion_request,
    layer_roles,
    normalize_steps,
    plan_operations,
    template_steps,
)
from timeline_director import _match_layers, direct
from video_story import build_pages

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 1440},
    "tree": [
        {
            "id": "hero-1", "sourceKey": "src-hero-1", "type": "hero", "variant": "center", "props": {"heading": "Product"},
            "children": [
                {"id": "hero-title", "sourceKey": "src-hero-title", "type": "heading", "text": "Launch"},
                {"id": "hero-text", "sourceKey": "src-hero-text", "type": "text", "text": "Lead paragraph"},
                {"id": "hero-media", "sourceKey": "src-hero-image", "type": "image", "alt": "Product shot"},
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Start"},
            ],
        },
        {"id": "features-1", "type": "feature-grid", "variant": "cards", "props": {}},
        {"id": "pricing-1", "type": "pricing", "variant": "tiers", "props": {}},
        {"id": "footer-1", "type": "footer", "variant": "simple", "props": {}},
    ],
}


def _timeline(duration: int = 8000) -> dict:
    return build(DESIGN_IR, {"duration": duration})


def test_layer_roles_follow_reading_order() -> None:
    roles = {item["id"]: item["role"] for item in layer_roles(_timeline())}
    assert roles["layer-hero-1"] == "section"
    assert roles["layer-hero-1-1"] == "heading"
    assert roles["layer-hero-1-2"] == "text"
    assert roles["layer-hero-1-3"] == "image"
    assert roles["layer-hero-1-4"] == "button"
    assert _match_layers(_timeline(), "role:button") == ["layer-hero-1-4"]
    assert _match_layers(_timeline(), "section:1") == ["layer-features-1"]


def test_every_template_yields_a_valid_reversible_timeline() -> None:
    for template in TEMPLATE_NAMES:
        timeline = _timeline()
        steps = template_steps(timeline, template)
        assert steps, template
        operations = plan_operations(timeline, steps, _match_layers)
        change_set = build_change_set(timeline, template, operations)
        applied = apply_change_set(timeline, change_set)
        assert validate(applied) == [], template
        hero = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1")
        assert hero["transform"]["properties"], f"{template}: hero must move"
        # финал ролика: все проявившиеся блоки видимы
        for layer in applied["layers"]:
            opacity = layer["transform"]["properties"].get("opacity", {}).get("keyframes") or []
            if opacity and layer["type"] == "component":
                assert opacity[-1]["value"] >= 0.35, f"{template}: {layer['id']} ends invisible"
        assert revert_change_set(applied, change_set) == timeline


def test_camera_presets_add_one_camera_layer_that_drives_the_frame() -> None:
    timeline = _timeline()
    steps = template_steps(timeline, "product-showcase")
    assert any(step["preset"] == "camera-push" and step["layers"] == [CAMERA_LAYER_ID] for step in steps)
    operations = plan_operations(timeline, steps, _match_layers)
    adds = [op for op in operations if op["kind"] == "add-layer"]
    assert len(adds) == 1 and adds[0]["value"]["type"] == "camera"
    applied = apply_change_set(timeline, build_change_set(timeline, "camera", operations))
    camera = next(layer for layer in applied["layers"] if layer["id"] == CAMERA_LAYER_ID)
    scale = camera["transform"]["properties"]["scale"]["keyframes"]
    assert scale[0]["value"] == 1 and scale[-1]["value"] > 1 and scale[0]["easing"] == "cubic-bezier"
    # повторный план по документу с камерой не добавляет второй слой
    again = plan_operations(applied, template_steps(applied, "cinematic-camera"), _match_layers)
    assert not [op for op in again if op["kind"] == "add-layer"]


def test_presets_on_one_property_merge_instead_of_overwriting() -> None:
    timeline = _timeline()
    steps = [
        {"preset": "fade-in", "layers": ["layer-features-1"], "start": 0.0, "duration": 0.1},
        {"preset": "dim", "layers": ["layer-features-1"], "start": 0.6, "duration": 0.2},
    ]
    operations = plan_operations(timeline, normalize_steps(timeline, steps), _match_layers)
    opacity_ops = [op for op in operations if op["path"] == "/transform/properties/opacity"]
    assert len(opacity_ops) == 1
    values = [kf["value"] for kf in opacity_ops[0]["value"]["keyframes"]]
    assert values == [0, 1, 1, 0.35]
    # существующий трек тоже сохраняется при следующем плане
    applied = apply_change_set(timeline, build_change_set(timeline, "a", operations))
    more = plan_operations(applied, [{"preset": "fade-out", "layers": ["layer-features-1"], "start": 0.9, "duration": 0.1}], _match_layers)
    merged = next(op for op in more if op["path"] == "/transform/properties/opacity")
    assert [kf["value"] for kf in merged["value"]["keyframes"]] == [0, 1, 1, 0.35, 1, 0]


def test_normalize_keeps_reveals_within_product_rhythm() -> None:
    timeline = _timeline(10000)
    steps = normalize_steps(timeline, [
        {"preset": "fade-in-up", "layers": "*", "start": 0, "duration": 0.01, "staggerMs": 900},
        {"preset": "camera-pan", "layers": ["layer-hero-1"], "start": 0.1, "duration": 0.8},
        {"preset": "unknown", "layers": "*", "start": 0, "duration": 0.2},
        {"preset": "dim", "layers": ["missing-layer"], "start": 0, "duration": 0.2},
    ])
    assert sorted(step["preset"] for step in steps) == ["camera-pan", "fade-in-up"]
    steps = sorted(steps, key=lambda step: step["preset"] != "fade-in-up")
    assert steps[0]["duration"] * 10000 >= choreo.MIN_REVEAL_MS and steps[0]["staggerMs"] <= choreo.MAX_STAGGER_MS
    assert steps[1]["layers"] == [CAMERA_LAYER_ID] and abs(steps[1]["duration"] - 0.8) < 1e-6


def test_all_presets_are_known_to_normalizer_and_labels() -> None:
    from timeline_api import PRESET_LABELS
    assert set(PRESET_LABELS) == set(PRESET_NAMES)
    timeline = _timeline()
    for preset in PRESET_NAMES:
        assert normalize_steps(timeline, [{"preset": preset, "layers": ["layer-hero-1"], "start": 0, "duration": 0.2}])


def test_motion_requests_are_detected_without_interaction_words() -> None:
    assert is_motion_request("Make it cinematic: slow camera push, soft reveals")
    assert is_motion_request("Сделай плавную анимацию появления и наезд камеры")
    assert is_motion_request("Presentation: camera pans down, finish with a gentle focus on the contact form and its button")
    assert not is_motion_request("Type my email into the contact form and press send")
    assert not is_motion_request("Click the language menu and translate the page")
    assert not is_motion_request("Кликни по кнопке и открой меню")
    assert not is_motion_request("Диван")
    assert not is_motion_request("smooth motion", [{"role": "assistant", "content": "Which title should I type?"}])


def test_motion_request_on_story_timeline_uses_one_call_and_no_page_screenshots() -> None:
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}]
    timeline = build_pages(pages, {"duration": 8000})
    plan = {"template": "product-showcase", "steps": [{"preset": "cta-pulse", "layers": "role:button", "start": 0.8, "duration": 0.1}], "summary": "Product film"}
    with TestClient(app) as client, patch("video_context.prepare_context") as context, \
            patch("timeline_director.llm.chat", return_value=json.dumps(plan)) as chat:
        response = client.post("/api/timeline/assist", json={
            "timeline": timeline, "prompt": "Make a smooth product showcase with a slow camera push",
            "provider": "claude", "model": "fable", "effort": "high", "require_llm": True})
    assert response.status_code == 200, response.text
    context.assert_not_called()
    assert chat.call_count == 1
    assert chat.call_args.args[0] == "claude" and chat.call_args.kwargs["model"] == "fable"
    body = response.json()
    assert body["planSource"] == "llm" and body["steps"] >= 2
    applied = body["timeline"]
    assert applied["story"] == timeline["story"], "motion path never rewrites the scenario"
    assert any(layer["id"] == CAMERA_LAYER_ID for layer in applied["layers"])
    cta = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1-4")
    assert "scale" in cta["transform"]["properties"]
    assert validate(applied) == []


def test_story_director_accepts_templates_and_camera_effects() -> None:
    from video_story import direct_story
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}]
    timeline = build_pages(pages, {"duration": 8000})
    plan = {"summary": "Cinematic", "edits": [], "animations": [{"template": "cinematic-camera"}, {"preset": "camera-pull", "start": 4000, "duration": 3000}]}
    with patch("video_story.llm.chat", return_value=json.dumps(plan)):
        applied, changes, _ = direct_story(timeline, "Click nothing, just cinematic camera", "codex", "medium")
    assert validate(applied) == []
    camera = next(layer for layer in applied["layers"] if layer["id"] == CAMERA_LAYER_ID)
    scale = camera["transform"]["properties"]["scale"]["keyframes"]
    assert scale[0]["value"] == 1 and scale[-1]["value"] == 1 and max(kf["value"] for kf in scale) > 1
    assert revert_change_set(applied, changes) == timeline


def test_deterministic_prompt_picks_templates(monkeypatch) -> None:
    timeline = _timeline()
    applied, _, meta = direct(timeline, "презентация продукта", allow_llm=False)
    assert meta["planSource"] == "deterministic" and validate(applied) == []
    assert any(layer["id"] == CAMERA_LAYER_ID for layer in applied["layers"])
    assert timeline_director.template_for_prompt("cinematic launch video") == "cinematic-camera"
    assert timeline_director.template_for_prompt("наезд камеры на кнопку") is None


def test_blur_presets_and_page_transitions_validate() -> None:
    from ir.timeline import preset_operations
    timeline = _timeline()
    operations = preset_operations("focus-pull", ["layer-hero-1-3"], {"start": 0, "duration": 700})
    operations += preset_operations("defocus", ["layer-footer-1"], {"start": 3000, "duration": 1000})
    applied = apply_change_set(timeline, build_change_set(timeline, "blur", operations))
    assert validate(applied) == []
    media = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1-3")
    blur = media["transform"]["properties"]["blur"]["keyframes"]
    assert blur[0]["value"] == 14 and blur[-1]["value"] == 0
    broken = json.loads(json.dumps(applied))
    broken["layers"][0]["transform"]["properties"]["blur"] = {"keyframes": [{"t": 0, "value": -1}]}
    assert any("blur" in error for error in validate(broken))
    from timeline_render import export_css, export_waapi, solve_layer
    assert solve_layer(media, 0)["blur"] == 14 and solve_layer(media, 700)["blur"] == 0
    assert "filter: blur(" in export_css(applied)
    waapi = export_waapi(applied)
    assert any("filter" in kf for layer in waapi["layers"] for kf in layer["keyframes"])
    # new story transitions pass schema and scenario validation
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}, {"id": "second", "name": "Pricing", "ir": DESIGN_IR}]
    story_timeline = build_pages(pages, {"duration": 8000})
    from video_story import edit_actions, validate_story
    for transition in ("slide", "zoom"):
        story = edit_actions(story_timeline["story"], [{"op": "insert", "afterId": None, "actions": [
            {"id": f"go-{transition}", "type": "navigate", "pageId": "ir", "toPageId": "second", "transition": transition}]}])
        assert validate_story(story, 8000) == []
        candidate = json.loads(json.dumps(story_timeline)); candidate["story"] = story
        assert validate(candidate) == []


def test_camera_travel_uses_real_section_heights() -> None:
    tall = json.loads(json.dumps(DESIGN_IR))
    for section in tall["tree"]:
        section["frame"] = {"width": 1440, "height": 1200}
    short = json.loads(json.dumps(DESIGN_IR))
    for section in short["tree"]:
        section["frame"] = {"width": 1440, "height": 200}
    travel_tall = choreo._page_travel(build_pages([{"id": "ir", "name": "p", "ir": tall}], {"duration": 8000}), [1, 2, 3, 4])
    travel_short = choreo._page_travel(build_pages([{"id": "ir", "name": "p", "ir": short}], {"duration": 8000}), [1, 2, 3, 4])
    assert travel_short == 0 and travel_tall > 0
    assert travel_tall == min(int(4 * 1200 * (1920 / 1440) - 1080), int(1080 * 2.5))
    unknown = choreo._page_travel(_timeline(), [1, 2, 3, 4])
    assert 0 < unknown <= int(1080 * 1.2), "unmeasured pages get a conservative pan"


def test_clip_presets_mask_from_the_bottom_and_export() -> None:
    from ir.timeline import preset_operations
    from timeline_render import export_css, export_waapi, solve_layer
    timeline = _timeline()
    operations = preset_operations("wipe-reveal", ["layer-hero-1"], {"start": 0, "duration": 800})
    operations += preset_operations("wipe-out", ["layer-footer-1"], {"start": 6000, "duration": 1000})
    applied = apply_change_set(timeline, build_change_set(timeline, "clip", operations))
    assert validate(applied) == []
    hero = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1")
    assert solve_layer(hero, 0)["clip"] == 100 and solve_layer(hero, 800)["clip"] == 0
    assert "clip-path: inset(0 0 " in export_css(applied)
    assert any("clipPath" in kf for layer in export_waapi(applied)["layers"] for kf in layer["keyframes"])
    broken = json.loads(json.dumps(applied))
    broken["layers"][0]["transform"]["properties"]["clip"] = {"keyframes": [{"t": 0, "value": 120}]}
    assert any("clip" in error for error in validate(broken))


def test_measured_page_heights_drive_camera_pan() -> None:
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}]
    timeline = build_pages(pages, {"duration": 8000})
    estimated = choreo._page_travel(timeline, [1, 2, 3, 4])
    measured_tall = choreo._page_travel(timeline, [1, 2, 3, 4], {"ir": 5000})
    measured_short = choreo._page_travel(timeline, [1, 2, 3, 4], {"ir": 700})
    assert measured_short == 0
    assert measured_tall == min(int(5000 * (1920 / 1440) - 1080), int(1080 * 2.5)) > estimated
    steps = template_steps(timeline, "presentation", page_heights={"ir": 5000})
    pan = next(step for step in steps if step["preset"] == "camera-pan")
    # a 6 s pan may travel up to MAX_PAN_SPEED px/s: the bottom of a long page reaches the frame
    assert pan["travel"] == min(int(5000 * (1920 / 1440) - 1080), choreo.MAX_PAN_SPEED * 6) > measured_tall
    # through the API: measured heights reach the deterministic director
    with TestClient(app) as client:
        response = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "presentation", "provider": "codex",
                                                              "require_llm": False, "pageHeights": {"ir": 5000}})
    assert response.status_code == 200, response.text
    camera = next(layer for layer in response.json()["timeline"]["layers"] if layer["id"] == CAMERA_LAYER_ID)
    # an 8 s clip cannot show a 5000 px page at MAX_PAN_SPEED: the director lengthens it
    full = int(5000 * (1920 / 1440) - 1080)
    applied = response.json()["timeline"]
    assert applied["composition"]["duration"] == 11000
    assert camera["transform"]["properties"]["y"]["keyframes"][-1]["value"] == -full, "the camera reaches the page end"
    assert all(layer["out"] == 11000 for layer in applied["layers"]), "every layer lasts the whole clip"


def test_llm_accents_without_template_inherit_the_requested_choreography(monkeypatch) -> None:
    """Astra answered a "presentation … camera pans" request with three reveals and no camera."""
    import timeline_director as director
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}]
    timeline = build_pages(pages, {"duration": 12000})
    plan = {"template": None, "steps": [
        {"preset": "fade-in-up", "layers": ["layer-hero-1"], "start": 0, "duration": 0.08},
        {"preset": "fade-in-up", "layers": ["layer-features-1"], "start": 0.3, "duration": 0.08},
        {"preset": "cta-pulse", "layers": "role:button", "start": 0.85, "duration": 0.08}], "summary": "reveals"}
    monkeypatch.setattr(director.llm, "chat", lambda *a, **k: json.dumps(plan))
    steps = director.plan_from_llm(timeline, "Presentation of this website: the camera pans down the page while sections reveal",
                                   provider="codex", model="gpt-6-astra", page_heights={"ir": 6000})
    presets = [step["preset"] for step in steps]
    assert "camera-pan" in presets, presets
    assert presets.count("cta-pulse") >= 1, "model accents stay on top of the template"
    # an explicit template from the model still wins
    plan["template"] = "clean-reveal"
    steps = director.plan_from_llm(timeline, "Presentation with camera pan", provider="codex")
    assert "camera-pan" not in [step["preset"] for step in steps]


def test_long_pages_keep_camera_and_finale_when_steps_are_capped() -> None:
    """glebkudr.com: 11 sections → the presentation template must not lose camera-pan."""
    ir = json.loads(json.dumps(DESIGN_IR))
    for index in range(8):
        ir["tree"].append({"id": f"extra-{index}", "type": "feature-grid", "variant": "cards", "props": {},
                           "children": [{"id": f"extra-{index}-h", "type": "heading", "text": f"Block {index}"}]})
    timeline = build_pages([{"id": "ir", "name": "Landing", "ir": ir}], {"duration": 12000})
    steps = template_steps(timeline, "presentation", page_heights={"ir": 3872})
    presets = [step["preset"] for step in steps]
    assert "camera-pan" in presets and "hero-focus" in presets, presets
    assert len(steps) <= choreo.MAX_STEPS
    capped = normalize_steps(timeline, steps + [{"preset": "fade-in", "layers": ["layer-hero-1"], "start": 0.5, "duration": 0.1}] * 40)
    assert "camera-pan" in [step["preset"] for step in capped]


def test_reveals_never_lag_behind_the_camera_and_one_pan_survives() -> None:
    pages = [{"id": "ir", "name": "Landing", "ir": DESIGN_IR}]
    timeline = build_pages(pages, {"duration": 8000})
    steps = template_steps(timeline, "presentation", page_heights={"ir": 5000})
    # the model adds its own, conflicting pan on top of the template
    steps = normalize_steps(timeline, steps + [{"preset": "camera-pan", "layers": ["camera"], "start": 0.16,
                                                "duration": 0.7, "travel": 4000}])
    pans = [step for step in steps if step["preset"] == "camera-pan"]
    assert len(pans) == 1 and pans[0]["travel"] != 4000, "the measured template pan is kept"
    sections = [item["id"] for item in choreo.layer_roles(timeline) if item["role"] == "section"]
    pan = pans[0]
    for step in steps:
        if step["preset"] not in choreo.ENTRANCE_PRESETS or not set(step["layers"]) & set(sections):
            continue
        index = min(sections.index(layer) for layer in step["layers"] if layer in sections)
        top = index / len(sections) * (pan["travel"] + 1080)
        start_ms = step["start"] * 8000
        if top <= 1080 * 0.6:
            assert start_ms <= 120 * index + 1, "first-screen sections reveal right away"
            continue
        # camera position when the reveal starts must not yet show the section
        progress = max(0.0, min(1.0, (start_ms - pan["start"] * 8000) / (pan["duration"] * 8000)))
        camera = choreo._bezier_progress(choreo.NAMED_CURVES["cinematic"], progress) * pan["travel"]
        assert camera + 1080 <= top + 1080 * 0.15 + 1, (index, start_ms, camera, top)
