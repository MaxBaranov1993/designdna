"""Plans, permissions, raster validation and durable image identity."""
import base64
import copy
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import asset_plan
from design_system.compiler import component_shape_hash


@pytest.fixture(autouse=True)
def isolated_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    return tmp_path


def png(alpha=False):
    image = Image.new("RGBA", (96, 64), (30, 90, 180, 255))
    if alpha:
        image.putpixel((0, 0), (0, 0, 0, 0))
    output = io.BytesIO()
    image.save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def ir():
    return {"version": "1.1", "tokens": {"color": {"primary": "#abcdef"}}, "tree": [
        {"type": "composition", "children": [
            {"type": "text", "text": "Точный текст и цена 1490 ₽"},
            {"type": "image", "imagePrompt": "Blue ceramic cup", "sourceKey": "cup"},
            {"type": "image", "imagePrompt": "Blue plate", "sourceKey": "plate"},
        ]},
    ]}


def test_plan_is_deterministic_versioned_and_does_not_modify_ir():
    original = ir()
    saved = copy.deepcopy(original)
    plan = asset_plan.prepare([original], {"brief": "Kitchen"})
    assert plan == asset_plan.prepare([original], {"brief": "Kitchen"})
    assert plan["schemaVersion"] == "design-assets/1.0"
    assert len(plan["slots"]) == 2
    assert len({slot["id"] for slot in plan["slots"]}) == 2
    assert plan["slots"][0]["sourceKey"] == "cup"
    assert "#abcdef" in plan["slots"][0]["prompt"]
    assert original == saved


def test_explicit_replacement_is_local_stale_guarded_and_never_replaces_a_master():
    original = ir()
    node = original['tree'][0]['children'][1]
    node['src'] = 'data:image/png;base64,original'
    before = copy.deepcopy(original)
    assert len(asset_plan.prepare([original])['slots']) == 1
    plan = asset_plan.prepare([original], {'replaceImages': True})
    slot = plan['slots'][0]
    assert slot['operation'] == 'replace'
    applied = asset_plan.apply(original, slot, png())['ir']
    expected = copy.deepcopy(original)
    expected['tree'][0]['children'][1]['src'] = applied['tree'][0]['children'][1]['src']
    assert applied == expected and original == before
    node['src'] = 'manually-changed.png'
    with pytest.raises(ValueError, match='план ресурсов'):
        asset_plan.apply(original, slot, png())
    node['componentRef'] = {'masterHash': 'exact'}
    assert len(asset_plan.prepare([original], {'replaceImages': True})['slots']) == 1
    original['tree'][0]['type'] = 'source-block'
    assert not asset_plan.prepare([original], {'replaceImages': True})['slots']


def test_partial_apply_preserves_text_geometry_other_slots_and_restart(isolated_assets):
    original = ir()
    plan = asset_plan.prepare([original])
    first = asset_plan.apply(original, plan["slots"][0], png())
    assert original["tree"][0]["children"][1].get("src") is None
    assert first["ir"]["tree"][0]["children"][0] == original["tree"][0]["children"][0]
    assert first["ir"]["tokens"] == original["tokens"]
    assert first["ir"]["tree"][0]["children"][2] == original["tree"][0]["children"][2]
    second = asset_plan.apply(first["ir"], plan["slots"][1], png())
    assert second["result"] == first["result"]
    assert len(list((isolated_assets / "blobs").glob("*.png"))) == 1
    with Image.open(isolated_assets / "blobs" / (first["result"]["sha256"] + ".png")) as image:
        assert image.size == (96, 64)


@pytest.mark.parametrize("protected", [
    {"editable": False}, {"constraints": {"intentLocks": ["content"]}},
    {"constraints": {"intentLocks": ["brand"]}}, {"type": "source-block"},
])
def test_protected_ancestors_are_not_planned_and_cannot_be_forged(protected):
    original = ir()
    slot = asset_plan.prepare([original])["slots"][0]
    original["tree"][0].update(protected)
    assert asset_plan.prepare([original])["slots"] == []
    with pytest.raises(ValueError, match="защищено"):
        asset_plan.apply(original, slot, png())


def test_exact_master_only_allows_existing_empty_string_content_slot():
    original = ir()
    master = original["tree"][0]
    master["sourceMeta"] = {"componentRef": {"componentKey": "cup", "masterHash": "exact"}}
    assert asset_plan.prepare([original])["slots"] == []
    master["children"][1]["src"] = ""
    before_hash = component_shape_hash(master)
    plan = asset_plan.prepare([original])
    assert len(plan["slots"]) == 1
    changed = asset_plan.apply(original, plan["slots"][0], png())["ir"]
    assert component_shape_hash(changed["tree"][0]) == before_hash
    assert changed["tree"][0]["sourceMeta"] == master["sourceMeta"]


def test_existing_source_and_changed_target_cannot_be_overwritten():
    original = ir()
    slot = asset_plan.prepare([original])["slots"][0]
    original["tree"][0]["children"][1]["src"] = "https://example.test/product.png"
    with pytest.raises(ValueError):
        asset_plan.apply(original, slot, png())
    original["tree"][0]["children"][1].pop("src")
    original["tree"][0]["children"][1]["imagePrompt"] = "New subject"
    with pytest.raises(ValueError):
        asset_plan.apply(original, slot, png())


def test_real_alpha_is_required_and_invalid_raster_cannot_be_applied():
    original = ir()
    original["tree"][0]["children"][1]["imagePrompt"] = "Чашка на прозрачном фоне"
    slot = asset_plan.prepare([original])["slots"][0]
    assert slot["requiresAlpha"]
    with pytest.raises(ValueError, match="прозрачном"):
        asset_plan.apply(original, slot, png())
    with pytest.raises(ValueError):
        asset_plan.apply(original, slot, "data:image/png;base64,AAAA")
    assert asset_plan.apply(original, slot, png(True))["result"]["transparent"] is True


def test_actual_consumers_hero_gallery_and_alternating_are_planned():
    original = {"tree": [
        {"type": "hero", "props": {"heading": "Title", "media": {"imagePrompt": "Hero", "aspect": "16:9"}}},
        {"type": "gallery", "children": [{"type": "image", "imagePrompt": "Gallery"}]},
        {"type": "feature-alternating", "children": [{"type": "card", "imagePrompt": "Feature", "title": "Feature"}]},
    ]}
    plan = asset_plan.prepare([original])
    assert len(plan["slots"]) == 3
    assert plan["slots"][0]["height"] == 576
    result = asset_plan.apply(original, plan["slots"][0], png())
    assert result["ir"]["tree"][0]["props"]["media"]["src"].startswith("ddna://blobs/")
    assert "type" not in result["ir"]["tree"][0]["props"]["media"]


def test_reconcile_restores_blob_after_transport_and_detects_lost_output():
    original = ir()
    slot = asset_plan.prepare([original])["slots"][0]
    applied = asset_plan.apply(original, slot, png())
    slot["result"] = applied["result"]
    expanded = copy.deepcopy(applied["ir"])
    expanded["tree"][0]["children"][1]["src"] = png()
    result = asset_plan.reconcile(expanded, [slot])
    assert not result["missing"]
    assert result["ir"] == applied["ir"]
    expanded["tree"][0]["children"][1].pop("src")
    assert asset_plan.reconcile(expanded, [slot])["missing"] == [slot["id"]]


def test_endpoints_validate_apply_and_roundtrip():
    import server
    client = TestClient(server.app)
    original = ir()
    response = client.post("/api/generate/assets/prepare", json={"variants": [original]})
    assert response.status_code == 200
    slot = response.json()["slots"][0]
    response = client.post("/api/generate/assets/apply", json={"ir": original, "slot": slot, "image": png()})
    assert response.status_code == 200
    assert client.post("/api/generate/assets/apply", json={"ir": response.json()["ir"], "slot": slot, "image": png()}).status_code == 409


def test_corrupt_blob_does_not_pass_validation_and_new_delivery_repairs_it(isolated_assets):
    original = ir()
    slot = asset_plan.prepare([original])["slots"][0]
    applied = asset_plan.apply(original, slot, png())
    slot["result"] = applied["result"]
    blob = isolated_assets / "blobs" / (slot["result"]["sha256"] + ".png")
    blob.write_bytes(b"corrupt")
    assert asset_plan.reconcile(applied["ir"], [slot])["missing"] == [slot["id"]]
    asset_plan.apply(original, slot, png())
    assert asset_plan.reconcile(applied["ir"], [slot])["missing"] == []
