"""Эндпоинты Timeline IR: build/commit/apply/revert поверх TestClient."""
from __future__ import annotations

from fastapi.testclient import TestClient

from server import app

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 1440},
    "tree": [
        {
            "id": "hero-1",
            "sourceKey": "src-hero-1",
            "type": "hero",
            "variant": "center",
            "props": {"heading": "Продукт"},
            "children": [
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
            ],
        },
        {
            "id": "footer-1",
            "type": "footer",
            "variant": "simple",
            "props": {},
        },
    ],
}


def test_timeline_endpoints_roundtrip() -> None:
    with TestClient(app) as client:
        built = client.post("/api/timeline/build", json={"ir": DESIGN_IR, "settings": {"duration": 6000}})
        assert built.status_code == 200, built.text
        timeline = built.json()["timeline"]
        assert timeline["composition"]["duration"] == 6000
        assert {g["id"] for g in timeline["groups"]} == {"grp-hero-1", "grp-footer-1"}

        presets = client.get("/api/timeline/presets")
        assert presets.status_code == 200
        preset_ids = {p["id"] for p in presets.json()["presets"]}
        assert "fade-in-up" in preset_ids and "cta-pulse" in preset_ids

        committed = client.post("/api/timeline/commit", json={
            "timeline": timeline,
            "intent": "интро героя",
            "operations": [{
                "kind": "set-keyframes",
                "target": "layer-hero-1",
                "path": "/transform/properties/opacity",
                "value": {"keyframes": [
                    {"t": 0, "value": 0, "easing": "ease-out"},
                    {"t": 800, "value": 1},
                ]},
            }],
        })
        assert committed.status_code == 200, committed.text
        applied = committed.json()["timeline"]
        change_set = committed.json()["changeSet"]
        hero = next(l for l in applied["layers"] if l["id"] == "layer-hero-1")
        assert hero["transform"]["properties"]["opacity"]["keyframes"][0]["value"] == 0

        valid = client.post("/api/timeline/validate", json={"timeline": applied})
        assert valid.json()["errors"] == []

        reverted = client.post("/api/timeline/revert", json={"timeline": applied, "changeSet": change_set})
        assert reverted.status_code == 200, reverted.text
        hero_after = next(l for l in reverted.json()["timeline"]["layers"] if l["id"] == "layer-hero-1")
        assert hero_after["transform"]["properties"] == {}


def test_timeline_build_rejects_empty_tree() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/timeline/build", json={"ir": {"version": "1.1", "tree": []}})
        assert resp.status_code == 422


def test_timeline_commit_rejects_unknown_layer() -> None:
    with TestClient(app) as client:
        built = client.post("/api/timeline/build", json={"ir": DESIGN_IR})
        timeline = built.json()["timeline"]
        resp = client.post("/api/timeline/commit", json={
            "timeline": timeline,
            "intent": "битая цель",
            "operations": [{
                "kind": "set-keyframes",
                "target": "layer-unknown",
                "path": "/transform/properties/x",
                "value": {"keyframes": [{"t": 0, "value": 0}]},
            }],
        })
        assert resp.status_code == 422


def test_completed_download_survives_render_worker_restart(tmp_path, monkeypatch):
    import timeline_api
    from timeline_render import JOBS
    render_id = "e" * 32
    monkeypatch.setattr(timeline_api, "TIMELINE_RENDER_DIR", tmp_path)
    assert render_id not in JOBS
    output = tmp_path / f"{render_id}.mp4"
    output.write_bytes(b"saved-video-artifact")
    with TestClient(app) as client:
        status = client.get(f"/api/timeline/render/{render_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "done"
        download = client.get(status.json()["downloadUrl"])
        assert download.status_code == 200
        assert download.content == b"saved-video-artifact"
        assert client.get("/api/timeline/render/invalid-id").status_code == 404
    output.unlink()
    with TestClient(app) as client:
        assert client.get(f"/api/timeline/render/{render_id}/download").status_code == 404


def test_timeline_built_from_expanded_images_matches_the_same_ir_with_blob_refs(tmp_path, monkeypatch) -> None:
    """Timelines built before 2026-09-24 hashed the IR with images expanded to data URLs."""
    import base64
    import hashlib

    import scraper
    import timeline_api
    from ir.hash import content_hash

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    digest = hashlib.sha256(png).hexdigest()
    (tmp_path / f"{digest}.png").write_bytes(png)
    monkeypatch.setattr(scraper, "blobs_dir", lambda: tmp_path)
    with_ref = {**DESIGN_IR, "tree": [{"id": "img", "type": "image", "src": f"ddna://blobs/{digest}.png"}]}
    expanded = {**DESIGN_IR, "tree": [{"id": "img", "type": "image",
                                       "src": "data:image/png;base64," + base64.b64encode(png).decode()}]}
    assert timeline_api._same_design_ir(content_hash(expanded), with_ref)
    assert timeline_api._same_design_ir(content_hash(with_ref), with_ref)
    assert not timeline_api._same_design_ir(content_hash(DESIGN_IR), with_ref), "another design is still rejected"
