"""Canonical Source -> DS asset boundaries; all persistence is temporary."""
from __future__ import annotations

import base64
import copy
import io
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PIL import Image

import scraper
from design_system import api, builder, document as dsdoc, master_review, store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path / "data"))


def raster(fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (20, 12), (14, 68, 151)).save(buf, format=fmt)
    raw = buf.getvalue()
    return raw, f"data:image/{fmt.lower()};base64," + base64.b64encode(raw).decode()


def block(src=None):
    _, png = raster()
    return {
        "name": "Products", "selector": "#products", "preview": png,
        "previews": {"desktop": png}, "sizes": {"desktop": {"width": 20, "height": 12}},
        "ir": {"version": "1.1", "tokens": builder._tokens_for_ir(builder.normalize_dna({})),
               "tree": [{"type": "source-block", "sourceKey": "root",
                         "frame": {"width": 20, "height": 12}, "children": [{
                             "type": "image", "sourceKey": "product-image", "src": src or png,
                             "frame": {"width": 20, "height": 12},
                             "sourceMeta": {"kind": "dom", "componentBoundary": True,
                                            "componentRole": "article", "url": src or png},
                             "responsive": {"mobile": {"src": src or png}},
                         }]}]},
    }


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_copy_pixels_responsive_idempotence_and_strict_render(fmt):
    raw, src = raster(fmt)
    original = block(src)
    before = copy.deepcopy(original)
    canonical = scraper.canonicalize_source_blocks([original])[0]
    assert original == before
    node = canonical["ir"]["tree"][0]["children"][0]
    assert node["src"] == node["responsive"]["mobile"]["src"]
    png = scraper.read_png_blob(scraper.parse_blob_ref(node["src"]))
    if fmt == "PNG":
        assert png == raw
    with Image.open(io.BytesIO(raw)) as source, Image.open(io.BytesIO(png)) as stored:
        assert source.size == stored.size
        assert source.convert("RGBA").tobytes() == stored.convert("RGBA").tobytes()
    assert node["sourceMeta"] == {**before["ir"]["tree"][0]["children"][0]["sourceMeta"],
                                  "url": node["src"]}
    assert canonical["preview"] == before["preview"]
    assert scraper.canonicalize_source_blocks([canonical]) == [canonical]
    assert len(list(scraper.blobs_dir().glob("*.png"))) == 1
    assert scraper.resolve_ir_blobs(original["ir"])[1]  # still fail closed
    rendered, errors = scraper.resolve_ir_blobs(canonical["ir"])
    assert errors == []
    assert rendered["tree"][0]["children"][0]["src"].startswith("data:image/png")
    assert node["src"].startswith("ddna://blobs/")


def test_svg_remote_urls_fonts_and_slot_previews():
    _, png = raster()
    ir = {"tree": [{"src": "https://example.com/image.png", "props": {"sourcePreview": png},
                    "children": [{"src": "data:image/svg+xml,%3Csvg/%3E"}]}],
          "meta": {"fontFaces": [{"src": "data:font/woff2;base64,AAAA"}]}}
    result = scraper.canonicalize_ir_raster_assets(ir)
    assert result["tree"][0]["props"]["sourcePreview"].startswith("ddna://blobs/")
    assert result["meta"] == ir["meta"]
    assert result["tree"][0]["src"] == ir["tree"][0]["src"]
    assert result["tree"][0]["children"] == ir["tree"][0]["children"]


@pytest.mark.parametrize("src,code", [
    ("data:image/png;base64,broken", "invalid-raster-data"),
    ("data:image/png;base64,iVBORw0KGgo=", "invalid-raster-data"),
    ("ddna://blobs/" + "0" * 64 + ".png", "missing-blob"),
])
def test_failure_has_stage_component_path_and_preserves_input(src, code):
    source = block(src)
    before = copy.deepcopy(source)
    with pytest.raises(scraper.CanonicalRasterAssetError) as raised:
        scraper.canonicalize_source_blocks([source], stage="ds-build-assets")
    assert source == before
    assert raised.value.detail == {
        "code": code, "message": raised.value.detail["message"], "stage": "ds-build-assets",
        "component": "product-image", "path": "blocks[0].ir.tree[0].children[0].src",
        "retryable": False,
    }
    assert src not in str(raised.value)


def test_storage_failure_is_retryable_and_capture_wrapper_is_atomic(monkeypatch):
    ir = block()["ir"]
    before = copy.deepcopy(ir)
    def denied(_png):
        raise PermissionError("denied")
    monkeypatch.setattr(scraper, "put_png_blob", denied)
    with pytest.raises(scraper.CanonicalRasterAssetError) as raised:
        scraper._persist_ir_raster_data_urls(ir)
    assert raised.value.detail["retryable"] is True
    assert raised.value.detail["code"] == "blob-write-failed"
    assert ir == before


def test_corrupt_object_is_never_replaced():
    raw, _ = raster()
    digest = scraper.put_png_blob(raw)
    target = scraper.blobs_dir() / scraper.blob_object_name(digest)
    target.write_bytes(b"corrupt")  # isolated fixture only
    with pytest.raises(scraper.CanonicalRasterAssetError, match="integrity"):
        scraper.canonicalize_source_blocks([block()])
    assert target.read_bytes() == b"corrupt"
    assert scraper.resolve_ir_blobs(block(scraper.blob_ref(digest))["ir"])[1]


def test_legacy_jpeg_evidence_is_verified_and_converted_without_overwrite():
    import hashlib
    raw, _ = raster("JPEG")
    digest = hashlib.sha256(raw).hexdigest()
    scraper.blobs_dir().mkdir(parents=True)
    old_file = scraper.blobs_dir() / f"{digest}.jpg"
    old_file.write_bytes(raw)
    source = block()
    source["preview"] = source["previews"]["desktop"] = f"ddna://blobs/{digest}.jpg"
    canonical = scraper.canonicalize_source_blocks([source], include_evidence=True)[0]
    assert scraper.parse_blob_ref(canonical["preview"])
    rendered = scraper.source_block_render_copy(canonical)
    assert rendered["preview"].startswith("data:image/png")
    assert old_file.read_bytes() == raw
    with Image.open(io.BytesIO(raw)) as original, Image.open(io.BytesIO(
            scraper.read_png_blob(scraper.parse_blob_ref(canonical["preview"])))) as png:
        assert original.convert("RGBA").tobytes() == png.convert("RGBA").tobytes()
    old_file.write_bytes(b"corrupt")
    with pytest.raises(scraper.CanonicalRasterAssetError, match="integrity"):
        scraper.canonicalize_source_blocks([source], include_evidence=True)


def test_polish_measures_resolved_copy_and_fails_closed(monkeypatch):
    import fidelity_harness
    from design_system import polish
    canonical = scraper.canonicalize_source_blocks([block()])[0]["ir"]
    before = copy.deepcopy(canonical)
    seen = []
    def measure(_page, ir, viewport, *_args, **_kwargs):
        image = next(n for n in scraper_nodes(ir) if n.get("type") == "image")
        assert image["src"].startswith("data:image/png")
        seen.append(viewport)
        return {"defects": []}
    monkeypatch.setattr(fidelity_harness, "measure_layout", measure)
    assert polish.lint_master(canonical, page=object()) == []
    assert seen == ["desktop", "tablet", "mobile"]
    assert canonical == before
    with pytest.raises(scraper.CanonicalRasterAssetError) as raised:
        polish.lint_master(block()["ir"], page=object())
    assert raised.value.detail["stage"] == "ds-polish-render"
    assert seen == ["desktop", "tablet", "mobile"]


def test_pack_and_legacy_raw_blocks_build_canonical_masters_without_polish(monkeypatch):
    from design_system import polish
    source = block()
    before = copy.deepcopy(source)
    pack = builder.build_source_pack({"blocks": [source]})
    canonical_ir = pack["blocks"][0]["ir"]
    assert not scraper.resolve_ir_blobs(canonical_ir)[1]
    pack["_raw_blocks"] = [source]  # old callers must not bypass the boundary
    checked = []
    def unexpected_polish(*_args, **_kwargs):
        raise AssertionError("Catalog construction must not run automatic polish")
    monkeypatch.setattr(polish, "polish_document", unexpected_polish)
    doc = builder.build_draft(pack, create_mock=False)
    for pool in ("components", "reviewComponents", "suggestions"):
        for comp in doc[pool].values():
            if comp.get("origin") == "observed":
                assert not scraper.resolve_ir_blobs(comp["masterIr"])[1]
                assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(comp["masterIr"])
                checked.append(comp)
    assert checked
    assert source == before
    assert pack["_raw_blocks"] == [before]


def test_build_persists_canonical_masters_and_master_renderer_accepts_them(monkeypatch):
    import fidelity_harness
    source = block()
    before = copy.deepcopy(source)
    response = api.build_design_system(api.BuildRequest(blocks=[source], createMock=False))
    assert isinstance(response, dict), getattr(response, "body", None)
    persisted = store.get_revision(response["document"]["id"], 0)
    for evidence in persisted["referenceAssets"].values():
        assert all(scraper.parse_blob_ref(ref) for ref in evidence["referencePreviews"].values())
    components = [c for pool in ("components", "reviewComponents") for c in persisted[pool].values()]
    assert components
    def render(_page, ir, *_args):
        assert any(n["src"].startswith("data:image/png") for n in scraper_nodes(ir) if "src" in n)
        return b"rendered"
    monkeypatch.setattr(fidelity_harness, "_render_block_png", render)
    for comp in components:
        assert master_review.render_master_png(None, comp, "desktop") == b"rendered"
        assert not scraper.resolve_ir_blobs(comp["masterIr"])[1]
    assert source == before


def scraper_nodes(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key != "sourceMeta":
                yield from scraper_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from scraper_nodes(child)


def test_build_api_error_does_not_save(monkeypatch):
    import json
    def forbidden(_doc):
        pytest.fail("must not save a failed canonicalization")
    monkeypatch.setattr(store, "save_draft", forbidden)
    response = api.build_design_system(api.BuildRequest(blocks=[block("data:image/png;base64,broken")]))
    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload["stage"] == "ds-build-assets"
    assert payload["component"] == "product-image"
    assert payload["path"].endswith(".src")
    assert payload["retryable"] is False


def test_rebuild_keeps_identity_and_published_snapshot():
    source = block()
    source["fidelityReport"] = {
        "gate": {"passed": True}, "viewports": {"desktop": {
            "pixel_similarity": 100, "paint_coverage": 100, "bbox_p95": 0,
            "grid_origin_error": 0, "unexplained_losses": 0, "size_match": True,
            "gate": {"passed": True},
        }},
    }
    initial = api.build_design_system(api.BuildRequest(blocks=[source], name="My kit"))["document"]
    published = store.publish(initial)
    assert published["ok"], published
    snapshot = store.get_revision(initial["id"], published["document"]["revision"])
    for url in ("https://slsbmb.com/", "https://rsale.net/"):
        result = api.build_design_system(api.BuildRequest(
            systemId=initial["id"], blocks=[block()], sourceUrl=url))["document"]
        assert result["id"] == initial["id"]
        assert result["name"] == "My kit"
        assert result["status"] == "draft"
        assert len(store.list_systems()) == 1
        assert store.get_revision(initial["id"], snapshot["revision"]) == snapshot
    fresh = api.build_design_system(api.BuildRequest(blocks=[block()], name="Other kit"))["document"]
    assert fresh["id"] != initial["id"]
    assert len(store.list_systems()) == 2


def test_rebuild_unknown_id_fails_before_build(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unknown target must not create a new system")
    monkeypatch.setattr(builder, "build_draft", forbidden)
    response = api.build_design_system(api.BuildRequest(systemId="ds-missing", blocks=[block()]))
    assert response.status_code == 404


def test_desktop_ai_routes_are_included():
    import server
    paths = server.app.openapi()["paths"]
    assert "/api/design-system/desktop-ai/prepare" in paths
    assert "/api/design-system/desktop-ai/apply" in paths


def test_refine_returns_canonical_ir_and_evidence():
    import server
    source = block()
    req = server.BlockParseRefineReq(blocks=[source], operations=[])
    before = copy.deepcopy(req.blocks)
    response = server.block_parse_refine(req)
    assert response["blocks"][0]["preview"].startswith("ddna://blobs/")
    assert response["blocks"][0]["previews"]["desktop"].startswith("ddna://blobs/")
    assert not scraper.resolve_ir_blobs(response["blocks"][0]["ir"])[1]
    assert req.blocks == before
    assert response["sourceArtifact"]


@pytest.mark.parametrize("metadata", [None, {"url": "https://rsale.net/",
    "authenticated": True, "pipelineVersion": "dom-captured-version"}])
def test_refine_preserves_capture_url_redirect_auth_and_version(metadata):
    import server
    original = block()
    original["finalUrl"] = "https://rsale.net/sr"
    req = server.BlockParseRefineReq(blocks=[original], operations=[], source=metadata)
    before = copy.deepcopy(req.blocks)
    source = server.block_parse_refine(req)["sourceArtifact"]["source"]
    assert source["url"] == (metadata["url"] if metadata else original["finalUrl"])
    assert source["finalUrl"] == original["finalUrl"]
    assert source["authenticated"] is bool(metadata)
    if metadata:
        assert source["pipelineVersion"] == metadata["pipelineVersion"]
    assert req.blocks == before


@pytest.mark.parametrize("accepted", [False, True])
def test_repair_uses_render_copies_and_returns_canonical_state(monkeypatch, accepted):
    import server
    import fidelity_repair
    import playwright.sync_api
    source = block()
    before = copy.deepcopy(source)
    page = SimpleNamespace(route=lambda *_a: None)
    browser = SimpleNamespace(new_page=lambda **_kw: page, close=lambda: None)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(scraper, "launch_chromium", lambda _p: browser)
    measured = []
    def make_measure(*_args):
        def measure(ir):
            assert ir["tree"][0]["children"][0]["src"].startswith("data:image/png")
            measured.append(ir)
            return 90.0
        return measure
    def repair(ir, **kwargs):
        assert not scraper.resolve_ir_blobs(ir)[1]
        kwargs["measure"](ir)
        return {"ir": ir, "applied": [{}] if accepted else [], "gain": 0}
    refreshed = []
    def refresh(candidate, _page):
        assert not scraper.resolve_ir_blobs(candidate["ir"])[1]
        assert candidate["previews"]["desktop"].startswith("data:image/png")
        refreshed.append(candidate)
        return False
    monkeypatch.setattr(fidelity_repair, "make_browser_measurer", make_measure)
    monkeypatch.setattr(fidelity_repair, "repair_block", repair)
    monkeypatch.setattr(server, "_refresh_block_fidelity", refresh)
    req = server.FidelityRepairReq(blocks=[source], rawOutputs=[{"blockIndex": 0, "content": "{}"}])
    result = server.block_parse_repair(req)
    assert isinstance(result, dict), getattr(result, "body", None)
    assert measured and bool(refreshed) == accepted
    canonical = result["blocks"][0]
    assert canonical["preview"].startswith("ddna://blobs/")
    assert not scraper.resolve_ir_blobs(canonical["ir"])[1]
    assert req.blocks == [before]


def test_optional_real_capture_transport_refine_build_and_render(tmp_path, monkeypatch):
    """Opt-in replay of an owned capture; copy its assets, never change evidence."""
    import hashlib
    import json
    import os
    import shutil
    from pathlib import Path
    import server
    from design_system import polish

    capture_path = os.environ.get("CANONICAL_RASTER_CAPTURE")
    capture_data = os.environ.get("CANONICAL_RASTER_CAPTURE_DATA")
    if not capture_path or not capture_data:
        pytest.skip("set CANONICAL_RASTER_CAPTURE and CANONICAL_RASTER_CAPTURE_DATA to replay a real capture")
    source_file = Path(capture_path)
    original_bytes = source_file.read_bytes()
    payload = json.loads(original_bytes)
    destination = tmp_path / "data"
    for folder in ("blobs", "fonts"):
        origin = Path(capture_data) / folder
        if origin.is_dir():
            shutil.copytree(origin, destination / folder, dirs_exist_ok=True)
    blocks = payload["blocks"]
    original = copy.deepcopy(blocks)
    # Reproduce desktop expansion before Source refine, then DS build.
    transport = [scraper.source_block_render_copy(b) for b in blocks]
    assert any(scraper.resolve_ir_blobs(b["ir"])[1] for b in transport)
    refined = server.block_parse_refine(server.BlockParseRefineReq(blocks=transport, operations=[]))
    assert isinstance(refined, dict), getattr(refined, "body", None)
    original_polish = polish.polish_document
    full_build = os.environ.get("CANONICAL_RASTER_FULL_BUILD") == "1"
    if not full_build:
        monkeypatch.setattr(polish, "polish_document",
                            lambda doc, **_kw: original_polish(doc, headless=False))
    else:
        original_component_polish = polish.polish_component
        def traced_component(comp, **kwargs):
            try:
                return original_component_polish(comp, **kwargs)
            except Exception:
                print(json.dumps({"failedComponent": comp.get("componentKey"),
                                  "sourceKey": (comp.get("sourceRef") or {}).get("sourceKey"),
                                  "requiredViewports": (comp.get("fidelity") or {}).get("requiredViewports"),
                                  "roots": [{"type": root.get("type"), "visible": root.get("visible"),
                                             "responsive": root.get("responsive")}
                                            for root in comp["masterIr"]["tree"]]}))
                raise
        monkeypatch.setattr(polish, "polish_component", traced_component)
    response = api.build_design_system(api.BuildRequest(
        blocks=refined["blocks"], tokens=payload.get("tokens") or {},
        sourceUrl=payload.get("url") or "", sourceArtifact=refined["sourceArtifact"], createMock=False))
    assert isinstance(response, dict), getattr(response, "body", None)
    doc = response["document"]
    masters = [c for pool in ("components", "reviewComponents") for c in doc[pool].values()]
    assert masters
    for comp in masters:
        assert not scraper.resolve_ir_blobs(comp["masterIr"])[1]
        assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(comp["masterIr"])
        assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(node_json_roundtrip(comp["masterIr"]))
    from playwright.sync_api import sync_playwright
    rendered_count = 0
    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            page = browser.new_page(device_scale_factor=1)
            page.route("https://**/*", lambda route: route.abort("blockedbyclient"))
            for comp in masters[:3]:
                for viewport in ("desktop", "tablet", "mobile"):
                    png = master_review.render_master_png(page, comp, viewport)
                    assert png.startswith(b"\x89PNG\r\n\x1a\n")
                    rendered_count += 1
        finally:
            browser.close()
    assert store.get_revision(doc["id"], 0)["id"] == doc["id"]
    assert blocks == original
    assert source_file.read_bytes() == original_bytes
    print(json.dumps({"captureSha256": hashlib.sha256(original_bytes).hexdigest(),
                      "sourceBlocks": len(blocks), "canonicalMasters": len(masters),
                      "realMasterRenders": rendered_count, "published": False}))


@pytest.mark.parametrize("negative_x", [False, True])
def test_capture_pipeline_calls_viewport_helper_before_compile_and_reference(monkeypatch, negative_x):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import source_capture_viewport

    html = b'''<style>body{margin:0;background:white}header{position:fixed;top:0;
    width:100%;height:110px;background:#ee2222;z-index:100}main{padding-top:300px;height:2400px}
    #block{height:196px;position:relative;background:#6622ee}
    #child{position:absolute;left:40px;top:50px;color:white}</style>
    <header>Header</header><main><section id="block"><span id="child">Editable child</span></section></main>'''
    if negative_x:
        html = html.replace(b"position:relative;background", b"position:relative;left:-7.5px;background")
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *_args):
            pass

    original_prepare = source_capture_viewport.prepare_capture_viewport
    placements = []
    def prepare(page, locator):
        # Force the exact transport-independent header overlap at the hook.
        locator.evaluate("el => window.scrollTo({top:el.getBoundingClientRect().top+scrollY+126,behavior:'instant'})")
        placed = original_prepare(page, locator)
        assert placed["clear"] and placed["fullyVisible"], placed
        placements.append(placed)
        return placed

    monkeypatch.setattr(source_capture_viewport, "prepare_capture_viewport", prepare)
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as local:
        thread = Thread(target=local.serve_forever, daemon=True)
        thread.start()
        try:
            captures = scraper.capture_block_irs(
                f"http://127.0.0.1:{local.server_port}/start",
                [{"name": "card", "selector": "#block", "kind": "section"}],
                viewports=[{"name": "tablet", "width": 768, "height": 844}])
        finally:
            local.shutdown()
            thread.join(timeout=5)
    assert len(placements) == 1
    captured = captures["#block"]
    assert captured["finalUrl"] == f"http://127.0.0.1:{local.server_port}/final"
    assert not captured.get("error"), captured
    from blockparse import _capture_validation_diagnostics
    assert _capture_validation_diagnostics(captured["ir"]) == []
    with Image.open(io.BytesIO(scraper._decode_data_url_bytes(captured["preview"])[0])) as screenshot:
        assert screenshot.getpixel((screenshot.width // 2, 10))[:3] == (102, 34, 238)
        assert screenshot.size == (761 if negative_x else 768, 196)
        assert screenshot.width == captured["ir"]["frame"]["width"]
    import json
    assert "Editable child" in json.dumps(captured["ir"])
    if negative_x:
        geometry = captured["captureGeometryByViewport"]["tablet"]
        assert geometry["originalBounds"]["x"] == -7.5
        assert geometry["originalBounds"]["width"] == 768
        assert geometry["visibleCrop"]["x"] == 7.5
        assert geometry["captureRect"]["x"] == 0
        assert geometry["captureRect"]["width"] == 761
    assert not scraper.resolve_ir_blobs(captured["ir"])[1]


def node_json_roundtrip(value):
    import json
    import subprocess
    result = subprocess.run(
        ["node", "-e", "process.stdout.write(JSON.stringify(JSON.parse(require('fs').readFileSync(0,'utf8'))))"],
        input=json.dumps(value, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_source_compiler_default_matches_pipeline_and_invalidates_preclip_cache(monkeypatch):
    import blockparse
    assert builder.SOURCE_COMPILER_DEFAULT == blockparse.SOURCE_COMPILER_VERSION
    current = blockparse._block_cache_key("https://example.test/", "hero", "#hero")
    monkeypatch.setattr(blockparse, "SOURCE_COMPILER_VERSION", "dom-v43")
    assert current != blockparse._block_cache_key("https://example.test/", "hero", "#hero")


def test_new_master_numeric_pins_survive_node_without_mutating_input():
    from design_system.master_repair import pin_master
    original = {"tree": [{"frame": {"width": 114.0, "x": -0.0, "y": 2.75}}]}
    before = copy.deepcopy(original)
    canonical = builder.normalize_new_master_numbers(original)
    assert original == before and type(original["tree"][0]["frame"]["width"]) is float
    assert type(canonical["tree"][0]["frame"]["width"]) is int
    assert canonical["tree"][0]["frame"]["y"] == 2.75
    comp = {"sourceRef": {"sourceKey": "root"}}
    pin_master(comp, original)
    assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(node_json_roundtrip(comp["masterIr"]))


def test_project_load_preserves_source_and_pinned_snapshots(tmp_path, monkeypatch):
    import project_store
    import server
    from ir.migrate import migrate_project_payload
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "projects.db")
    source = scraper.canonicalize_source_blocks([block()], include_evidence=True)[0]
    master = copy.deepcopy(source["ir"])
    comp = {"masterIr": master, "sourceRef": {"masterHash": dsdoc.content_hash(master)},
            "polish": {"before": copy.deepcopy(master)}, "variants": [{"masterIr": master}]}
    payload = {"nodes": [
        {"type": "sourceimport", "data": {"blocks": [source], "ir": master}},
        {"type": "designsystem", "data": {"document": {"components": {"card": comp}}}}],
        "channels": {"source": master}}
    before = copy.deepcopy(payload)
    project_store.save_project(payload)
    first = server.project_load(server.ProjectLoadReq())
    second = server.project_load(server.ProjectLoadReq())
    assert first["project"] == before == second["project"] == payload
    assert first["revision"] == second["revision"]
    assert migrate_project_payload(migrate_project_payload(payload)) == before
    assert "provenance" not in first["project"]["nodes"][1]["data"]["document"]["components"]["card"]["masterIr"]


def test_metadata_nested_rasters_are_canonical_but_text_is_unchanged():
    _, png = raster()
    value = {"sourceMeta": {"url": png}, "provenance": {"images": [png],
             "url": "https://example.test/source", "note": "source capture"}}
    original = copy.deepcopy(value)
    result = scraper.canonicalize_ir_raster_assets(value)
    assert result["sourceMeta"]["url"].startswith("ddna://blobs/")
    assert result["provenance"]["images"] == [result["sourceMeta"]["url"]]
    assert result["provenance"]["url"] == value["provenance"]["url"]
    assert result["provenance"]["note"] == "source capture" and value == original


def test_hidden_root_measurement_skips_only_explicit_absence(monkeypatch):
    import fidelity_harness
    from design_system import polish
    master = {"tree": [{"type": "frame", "sourceKey": "root", "frame": {"width": 0, "height": 0},
                       "responsive": {"mobile": {"visible": False}},
                       "children": [{"type": "text", "visible": False}]}]}
    measured = []
    monkeypatch.setattr(fidelity_harness, "measure_layout", lambda _page, _ir, vp, *_a, **_k:
                        measured.append(vp) or {"defects": []})
    polish.lint_master(master, page=object())
    assert measured == ["desktop", "tablet"]  # zero-size/hidden child cannot suppress visible roots
    assert not polish._master_hidden({"tree": []}, "mobile")


def test_real_browser_hidden_section_timeout_is_avoided_without_skipping_visible():
    import fidelity_harness
    from design_system import polish
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    master = scraper.canonicalize_source_blocks([block()])[0]["ir"]
    master["tree"][0]["responsive"] = {"mobile": {"visible": False, "frame": {"width": 0, "height": 0}}}
    master["responsive"] = {"viewports": {vp: {"width": width, "height": 844}
                                          for vp, width in (("desktop", 1440), ("tablet", 768), ("mobile", 390))}}
    original = copy.deepcopy(master)
    render_ir, errors = scraper.resolve_ir_blobs(master)
    assert not errors
    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            page = browser.new_page()
            # The old unconditional measurement reproduces the exact reported wait.
            with pytest.raises(fidelity_harness.FidelityRenderError, match="data-ir-sec") as failure:
                fidelity_harness.measure_layout(page, render_ir, "mobile", 390, 844)
            assert isinstance(failure.value.__cause__, BrowserTimeout)
            assert failure.value.detail["viewport"] == "mobile" and failure.value.detail["retryable"]
            defects = polish.lint_master(master, page=page)
            assert all(item["viewport"] != "mobile" for item in defects)
            # Last visible pass was tablet: no fabricated hidden screenshot.
            assert page.locator('[data-ir-sec="0"]').is_visible()
        finally:
            browser.close()
    assert master == original


@pytest.mark.parametrize("proof,visible_reference,expected", [
    (True, True, "ready"), (False, True, "needs-review"), (True, False, "needs-review")])
def test_hidden_polish_acceptance_requires_source_proof(monkeypatch, proof, visible_reference, expected):
    import playwright.sync_api
    from design_system import polish, desktop_ai, styleguide
    raw, png = raster()
    master = {"version": "1.1", "tokens": {}, "tree": [{"type": "frame", "sourceKey": "root",
              "frame": {"width": 20, "height": 12}, "responsive": {"mobile": {"visible": False}}}],
              "responsive": {"viewports": {"mobile": {"width": 20, "height": 12}}}}
    comp = {"origin": "observed", "masterIr": master,
            "sourceRef": {"sourceKey": "root", "sourceRevisionHash": "revision", "evidenceKey": "block",
                          "masterHash": dsdoc.content_hash(master), "boundsByViewport": {"desktop": {}}},
            "fidelity": {"requiredViewports": ["desktop", "mobile"]}}
    doc = {"components": {"card": comp}, "sourceRefs": [{"revisionHash": "revision"}],
           "referenceAssets": {"block": {"referencePreviews": {"desktop": png, "mobile": png},
                                          "blockSizes": {"desktop": {"width": 20, "height": 12},
                                                         "mobile": {"width": 20, "height": 12}}}}}
    if not proof:
        doc["sourceRefs"] = []
    if not visible_reference:
        del doc["referenceAssets"]["block"]["referencePreviews"]["desktop"]
    assert bool(desktop_ai._hidden_evidence(doc, comp, "mobile")) == proof
    fake = SimpleNamespace(stop=lambda: None)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: SimpleNamespace(start=lambda: fake))
    monkeypatch.setattr(scraper, "launch_chromium", lambda _p: SimpleNamespace(
        new_page=lambda **_k: object(), close=lambda: None))
    monkeypatch.setattr(polish, "lint_master", lambda *_a, **_k: [])
    monkeypatch.setattr(styleguide, "proof_crop", lambda *_a, **_k: (png, (20, 12), ""))
    rendered = []
    monkeypatch.setattr(master_review, "render_master_png", lambda _p, _c, vp: rendered.append(vp) or raw)
    result, _ = polish.polish_document(doc, headless=True)
    trace = result["components"]["card"]["fidelity"]["polish"]
    assert trace["status"] == expected
    assert "mobile" not in rendered
    assert rendered == (["desktop"] if visible_reference else [])
