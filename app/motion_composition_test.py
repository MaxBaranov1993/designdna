"""Motion editor export must retain the user's composition, before queueing frames."""
import copy
import math

import pytest
from motion_render import validate_composition_layers


def layer():
    return {
        "id": "title", "name": "Title", "type": "text", "text": "Edited title", "sceneId": "scene-0",
        "size": 48, "weight": 700, "w": 200, "color": "#123456",
        "props": {"p": {"keys": [{"t": 0, "v": [100, 120]}]},
                  "s": {"keys": [{"t": 0, "v": 1}]},
                  "r": {"keys": [{"t": 0, "v": 0}]},
                  "o": {"keys": [{"t": 0, "v": 1}]}},
    }


def test_valid_composition_is_not_rewritten():
    layers = [layer()]
    before = copy.deepcopy(layers)
    validate_composition_layers(layers, {"scenes": [{"id": "scene-0"}]})
    assert layers == before


@pytest.mark.parametrize("change", [
    lambda value: value.update(sceneId="missing"),
    lambda value: value.update(w=math.nan),
    lambda value: value["props"]["p"].update(keys=[{"t": 0, "v": [1]}]),
    lambda value: value["props"]["o"].update(keys=[{"t": 0, "v": 2}]),
    lambda value: value["props"]["s"].update(keys=[{"t": 0, "v": -1}]),
    lambda value: value["props"]["r"].update(keys=[{"t": 1, "v": 0}, {"t": 1, "v": 90}]),
    lambda value: value["props"]["r"].update(keys=[{"t": math.inf, "v": 0}]),
])
def test_invalid_layer_fails_before_expensive_render(change):
    value = layer()
    change(value)
    with pytest.raises(ValueError):
        validate_composition_layers([value], {"scenes": [{"id": "scene-0"}]})


def test_export_endpoint_forwards_layers_to_render_worker(monkeypatch):
    import server
    from ir import build_interaction, build_motion, ensure_current
    from ui_style_dna_test import make_ir

    base = ensure_current(make_ir())
    interaction = build_interaction(base, {"kind": "design-ir"}, [{"id": "scene-0", "viewport": "desktop", "patch": []}], [])
    motion = build_motion(interaction, {"width": 320, "height": 240, "fps": 12})
    value = layer()
    value["sceneId"] = motion["scenes"][0]["id"]
    queued = []
    monkeypatch.setattr(server.FEATURE_FLAGS, "is_enabled", lambda name: True)
    monkeypatch.setattr(server.RENDER_EXECUTOR, "submit", lambda *args: queued.append(args))
    request = server.MotionRenderReq(base_ir=base, interaction=interaction, motion=motion, layers=[value])
    response = server.motion_render(request)
    try:
        assert response["status"] == "queued"
        assert queued[0][-1] == [value]
        assert queued[0][-1] is not request.layers
    finally:
        with server.RENDER_JOBS_LOCK:
            server.RENDER_JOBS.pop(response["id"], None)


def test_desktop_image_blob_is_materialized_for_export(tmp_path, monkeypatch):
    import hashlib
    from motion_render import prepare_composition_layers
    content = b'local-image-bytes'
    key = hashlib.sha256(content).hexdigest()
    (tmp_path / 'blobs').mkdir()
    (tmp_path / 'blobs' / f'{key}.png').write_bytes(content)
    monkeypatch.setenv('DESIGNDNA_DATA_DIR', str(tmp_path))
    image = layer()
    image.update(type='image', src=f'ddna://blobs/{key}.png')
    prepared = prepare_composition_layers([image])
    assert prepared[0]['src'].startswith('data:image/png;base64,')
    assert image['src'].startswith('ddna://')
    (tmp_path / 'blobs' / f'{key}.png').unlink()
    with pytest.raises(ValueError, match='не найден'):
        prepare_composition_layers([image])
