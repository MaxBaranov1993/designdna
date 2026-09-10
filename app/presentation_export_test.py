import base64
import copy
import io
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from PIL import Image

from api.export import PresentationRequest, presentation_export
from presentation_export import NS, build_pptx
from presentation_scene import capture_scene, needs_font_catalog
from quality_test_fixtures import QUALITY_IR


def fixture():
    ir = copy.deepcopy(QUALITY_IR)
    ir["frame"] = {"width": 960, "height": "hug"}
    ir["tokens"]["shadow"] = "none"
    ir["tokens"]["font"]["display"]["family"] = "Arial"
    ir["tokens"]["font"]["body"]["family"] = "Arial"
    image = io.BytesIO()
    Image.new("RGBA", (48, 48), (30, 120, 170, 128)).save(image, format="PNG")
    ir["tree"] = [{"id": "diagram", "type": "composition", "variant": "default", "props": {},
        "frame": {"layout": "free", "width": 960, "height": 540}, "children": [
            {"type": "rect", "fill": "#E6EDF7", "radius": 10, "frame": {"x": 40, "y": 90, "width": 260, "height": 120}},
            {"type": "heading", "text": "Проверяемый процесс", "frame": {"x": 40, "y": 25, "width": 800, "height": 50}, "style": {"fontSize": 30}},
            {"type": "text", "text": "Точный текст: 1490 ₽", "href": "https://example.com/quote?price=1490&currency=RUB", "frame": {"x": 60, "y": 125, "width": 220, "height": 30}, "style": {"fontSize": 18}},
            {"type": "text", "text": "→", "frame": {"x": 318, "y": 125, "width": 35, "height": 35}},
            {"type": "image", "src": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode(), "frame": {"x": 380, "y": 90, "width": 120, "height": 120}},
            {"type": "rect", "fill": "#ffffff", "frame": {"x": 40, "y": 240, "width": 460, "height": 90},
             "style": {"backgroundImage": "linear-gradient(90deg, #3359ad, #9ab6e7)"}},
        ]}]
    return ir


def test_real_renderer_exports_live_text_geometry_alpha_and_exact_source(tmp_path, monkeypatch):
    ir = fixture()
    import hashlib
    import timeline_assets
    monkeypatch.setattr(timeline_assets, "_data_root", lambda: tmp_path)
    image_node = ir["tree"][0]["children"][4]
    png = base64.b64decode(image_node["src"].split(",", 1)[1])
    name = hashlib.sha256(png).hexdigest() + ".png"
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / name).write_bytes(png)
    image_node["src"] = "ddna://blobs/" + name
    before = copy.deepcopy(ir)
    scene, source = capture_scene(ir, width=960)
    assert ir == before == source
    assert scene["width"] == 960
    texts = [x["text"] for x in scene["items"] if x["kind"] == "text"]
    assert "Проверяемый процесс" in texts and "Точный текст: 1490 ₽" in texts
    images = [x for x in scene["items"] if x["kind"] == "image"]
    assert any(x["reason"] == "image" for x in images)
    assert any("background" in x["reason"] for x in images)
    alpha = Image.open(io.BytesIO(base64.b64decode(next(x for x in images if x["reason"] == "image")["png"])))
    assert alpha.mode == "RGBA" and alpha.getextrema()[3][1] <= 130
    content, report = build_pptx(scene, source)
    assert report["text"] >= 3 and report["shapes"] >= 1 and report["images"] >= 2
    assert report["links"] == 1
    with ZipFile(io.BytesIO(content)) as archive:
        assert b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"' in archive.read("[Content_Types].xml")
        assert b'<Default ' in archive.read("[Content_Types].xml")
        assert b'<Relationship ' in archive.read("ppt/slides/_rels/slide1.xml.rels")
        slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
        assert slide.findall(".//a:t", NS)
        assert "Точный текст: 1490 ₽" in [x.text for x in slide.findall(".//a:t", NS)]
        assert slide.findall(".//p:pic", NS)
        reopened = json.loads(ET.fromstring(archive.read("customXml/designDNA.xml")).text)
        assert reopened["ir"] == before and reopened["report"] == report
        assert reopened["assets"]
        # Every internal relationship resolves within the package.
        import posixpath
        for name in archive.namelist():
            if not name.endswith(".rels"):
                continue
            base = posixpath.dirname(name.replace("/_rels/", "/")) if name != "_rels/.rels" else ""
            for rel in ET.fromstring(archive.read(name)):
                if rel.get("TargetMode") == "External":
                    continue
                target = posixpath.normpath(posixpath.join(base, rel.get("Target"))).lstrip("/")
                assert target in archive.namelist(), (name, target)
    (tmp_path / "roundtrip.pptx").write_bytes(content)


def test_missing_asset_or_font_blocks_export_without_changing_ir():
    ir = fixture()
    ir["tree"][0]["children"][4]["src"] = "ddna://blobs/" + "a" * 64 + ".png"
    before = copy.deepcopy(ir)
    with pytest.raises(ValueError, match="Ресурсы экспорта"):
        capture_scene(ir)
    assert ir == before


def test_export_route_validates_and_passes_canonical_refs(monkeypatch):
    import api.export as routes
    ir = fixture()
    ir["tree"][0]["children"][4]["src"] = "ddna://blobs/" + "b" * 64 + ".png"
    calls = []
    monkeypatch.setattr(routes, "export_presentation", lambda ir, **kwargs: calls.append((ir, kwargs)) or {"filename": "test.pptx"})
    assert presentation_export(PresentationRequest(ir=ir, width=768, viewport="tablet"))["filename"] == "test.pptx"
    assert calls == [(ir, {"width": 768, "viewport": "tablet"})]
    with pytest.raises(ValueError):
        PresentationRequest(ir=ir, width=1)


def test_font_catalog_only_for_undeclared_custom_families():
    ir = fixture()
    assert not needs_font_catalog(ir)
    ir["tokens"]["font"]["display"]["family"] = "Sora"
    assert needs_font_catalog(ir)
    ir.setdefault("meta", {})["fontFaces"] = [{"family": "Sora", "url": "/fonts/1234567890abcdef.woff2"}]
    assert not needs_font_catalog(ir)


def test_background_raster_keeps_opacity_from_its_parent():
    ir = fixture()
    gradient = ir["tree"][0]["children"][-1]
    gradient["frame"] = {"x": 0, "y": 0, "width": 200, "height": 100}
    gradient["style"]["opacity"] = 0.5
    ir["tree"][0]["children"] = [{"type": "frame", "frame": {"x": 40, "y": 40, "width": 200, "height": 100, "layout": "free"},
                                    "style": {"opacity": 0.5}, "children": [gradient]}]
    scene, _ = capture_scene(ir, width=960)
    item = next(item for item in scene["items"] if item["kind"] == "image" and item["backgroundOnly"])
    with Image.open(io.BytesIO(base64.b64decode(item["png"]))) as png:
        assert 62 <= png.getextrema()[3][1] <= 65
