"""Headless layout timing and fail-closed fidelity boundaries."""
import copy
import io
import os
from types import SimpleNamespace

import pytest
from PIL import Image

import fidelity_harness
import scraper
from design_system import api, polish, master_review, styleguide


def png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "#123456").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("viewport,width", [("desktop", 720), ("mobile", 390)])
def test_render_layout_does_not_depend_on_preview_animation_frame(viewport, width):
    from playwright.sync_api import sync_playwright
    ir = {"version": "1.1", "tokens": {}, "frame": {"width": width, "height": 80},
          "tree": [{"type": "source-block", "sourceKey": "header",
                    "frame": {"width": width, "height": 80}, "children": []}]}
    original = copy.deepcopy(ir)
    def trace(label):
        if os.environ.get('FIDELITY_TEST_TRACE'):
            print('render-boundary: ' + label, flush=True)
    trace('start playwright')
    with sync_playwright() as pw:
        trace('launch browser')
        browser = scraper.launch_chromium(pw)
        try:
            trace('new page')
            real = browser.new_page(device_scale_factor=1)

            class MeasurementPage:
                def __getattr__(self, name):
                    method = getattr(real, name)
                    if not callable(method):
                        return method
                    def call(*args, **kwargs):
                        trace(name)
                        return method(*args, **kwargs)
                    return call

                def evaluate(self, expression, arg=None):
                    trace('evaluate ' + expression[:50])
                    if "IRRenderer.renderIR" not in expression:
                        return real.evaluate(expression, arg)
                    real.evaluate("window.savedRAF=requestAnimationFrame; window.requestAnimationFrame=()=>0")
                    try:
                        value = real.evaluate(expression, arg)
                        assert real.evaluate("document.querySelector('#preview').style.height") == "80px"
                        return value
                    finally:
                        real.evaluate("window.requestAnimationFrame=window.savedRAF; delete window.savedRAF")

            image = fidelity_harness._render_block_png(MeasurementPage(), ir, viewport, width, 80)
            assert Image.open(io.BytesIO(image)).size == (width, 80)
        finally:
            trace('close browser')
            browser.close()
    assert ir == original


def test_timeout_preserves_component_viewport_and_retry_context():
    from playwright.sync_api import TimeoutError
    def fail(_size):
        raise TimeoutError("measurement deadline")
    with pytest.raises(fidelity_harness.FidelityRenderError) as caught:
        fidelity_harness._render_block_png(SimpleNamespace(set_viewport_size=fail),
            {"tree": [{"sourceKey": "hero"}]}, "tablet", 768, 100)
    assert caught.value.detail == {"code": "render-failed", "stage": "fidelity-render",
        "component": "hero", "path": "masterIr.tree[0]", "viewport": "tablet", "retryable": True}


def test_build_returns_structured_render_failure_without_saving(monkeypatch):
    def fail(*_args, **_kwargs):
        raise fidelity_harness.FidelityRenderError({"tree": [{"sourceKey": "hero"}]}, "mobile", RuntimeError("deadline"))
    monkeypatch.setattr(api.builder, "build_source_pack", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(api.builder, "build_draft", fail)
    monkeypatch.setattr(api.store, "save_draft", lambda *_args: pytest.fail("Failed build must not save"))
    result = api.build_design_system(api.BuildRequest(blocks=[{"ir": {"tree": [{"type": "source-block"}]}}]))
    import json
    detail = json.loads(result.body)
    assert result.status_code == 503
    assert detail["component"] == "hero" and detail["viewport"] == "mobile" and detail["retryable"]


def test_polish_rejects_size_mismatch_without_resizing_or_scoring(monkeypatch):
    import base64
    from playwright import sync_api
    page = object()
    browser = SimpleNamespace(new_page=lambda **_kwargs: page, close=lambda: None)
    pw = SimpleNamespace(stop=lambda: None)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: SimpleNamespace(start=lambda: pw))
    monkeypatch.setattr(scraper, "launch_chromium", lambda _pw: browser)
    reference = "data:image/png;base64," + base64.b64encode(png(100, 80)).decode()
    monkeypatch.setattr(styleguide, "proof_crop", lambda *_args, **_kwargs: (reference, (100, 80), ""))
    monkeypatch.setattr(master_review, "render_master_png", lambda *_args: png(200, 80))
    monkeypatch.setattr(fidelity_harness, "_image_metrics", lambda *_args: pytest.fail("Wrong-size render cannot be scored"))
    observed = []
    def check(comp, **kwargs):
        observed.append(kwargs["fidelity_check"](comp["masterIr"]))
        return {"changed": False}
    monkeypatch.setattr(polish, "polish_component", check)
    document = {"components": {"hero": {"masterIr": {"tree": [{"type": "frame"}]},
        "sourceRef": {"evidenceKey": "ev", "boundsByViewport": {"desktop": {}}},
        "fidelity": {"requiredViewports": ["desktop"]}}},
        "referenceAssets": {"ev": {"referencePreviews": {"desktop": reference}, "blockSizes": {"desktop": {}}}}}
    before = copy.deepcopy(document)
    polish.polish_document(document, headless=True)
    assert document == before
    assert observed[0]["passed"] is False and observed[0]["pixelSimilarity"] == {}
    assert "size-mismatch" in observed[0]["fidelityRejected"][0]


@pytest.mark.parametrize('wrong', ['before', 'candidate'])
def test_ai_repair_rejects_wrong_size_before_scoring(monkeypatch, wrong):
    import base64
    from design_system import master_repair
    reference = png(100, 80)
    monkeypatch.setattr(polish, 'lint_master', lambda *_args, **_kwargs: pytest.fail('Size mismatch must fail first'))
    monkeypatch.setattr(fidelity_harness, '_image_metrics', lambda *_args: pytest.fail('No rescaled scoring'))
    accepted, reasons = master_repair._layout_acceptance({}, {}, page=None, viewport='mobile',
        original='data:image/png;base64,' + base64.b64encode(reference).decode(),
        before_png=png(200, 80) if wrong == 'before' else reference,
        candidate_png=png(200, 80) if wrong == 'candidate' else reference)
    assert accepted is False and reasons == ['size-mismatch:' + wrong]
