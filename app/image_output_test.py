import base64
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

import server
from image_output import convert_image, apply_background_mask


def picture(alpha=False):
    image = Image.new("RGBA", (64, 64), (0, 0, 255, 255))
    if alpha:
        image.putpixel((0, 0), (0, 0, 255, 0))
        image.putpixel((1, 0), (0, 0, 255, 100))
    output = io.BytesIO()
    image.save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def decoded(result):
    return Image.open(io.BytesIO(base64.b64decode(result["png"].split(",")[1])))


def test_png_preserves_real_alpha_and_partial_edge_pixels():
    result = convert_image(picture(True), require_transparency=True)
    assert (result["width"], result["height"], result["transparent"]) == (64, 64, True)
    assert decoded(result).getpixel((1, 0)) == (0, 0, 255, 100)


def test_jpeg_encodes_actual_jpeg_with_white_matte():
    result = convert_image(picture(True), "jpeg")
    image = decoded(result)
    assert image.format == "JPEG" and image.mode == "RGB"
    assert result["png"].startswith("data:image/jpeg;base64,")
    assert not result["transparent"]


def test_background_removal_rejects_opaque_or_empty_results():
    with pytest.raises(ValueError, match="прозрачном"):
        convert_image(picture(), require_transparency=True)
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    output = io.BytesIO(); image.save(output, "PNG")
    with pytest.raises(ValueError, match="прозрачном"):
        convert_image("data:image/png;base64," + base64.b64encode(output.getvalue()).decode(), require_transparency=True)
    with pytest.raises(ValueError, match="PNG"):
        convert_image(picture(True), "jpeg", True)


@pytest.mark.parametrize("value", ["not-an-image", "data:image/png;base64,AAAA", "data:image/svg+xml;base64,PHN2Zy8+"])
def test_corrupt_or_vector_results_are_not_accepted_as_raster(value):
    with pytest.raises(ValueError):
        convert_image(value)


def test_convert_route_exposes_validation_error():
    response = server.image_convert(server.ImageConvertReq(image=picture(), requireTransparency=True))
    assert response.status_code == 422


def test_svg_sanitizer_removes_active_content_and_external_links():
    clean = server._sanitize_svg('''<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">
      <script>alert(1)</script><foreignObject><div>html</div></foreignObject>
      <rect width="64" height="64" fill="blue"/><use href='https://example.test/a'/>
      <use href="#shape"/><animate attributeName="onload" to="alert(1)"/>
    </svg>''')
    root = ET.fromstring(clean)
    assert len(list(root)) == 3
    assert "onload" not in clean and "https://" not in clean and "alert" not in clean
    assert 'href="#shape"' in clean


def test_unquoted_handler_and_doctype_are_rejected_before_render():
    with pytest.raises(ET.ParseError):
        server._sanitize_svg('<svg onload=alert(1)></svg>')
    with pytest.raises(ValueError):
        server._sanitize_svg('<!DOCTYPE svg><svg/>')


def test_empty_desktop_output_never_falls_back_to_a_second_llm(monkeypatch):
    monkeypatch.setattr(server.llm, "chat", lambda *_a, **_k: pytest.fail("No fallback allowed"))
    response = server.image_generate(server.ImageGenReq(prompt="draw", rawOutput=""))
    assert response.status_code == 502


def test_background_mask_preserves_original_rgb_canvas_and_antialiased_edges():
    mask = Image.new("RGB", (64, 64), "white")
    mask.putpixel((0, 0), (0, 0, 0)); mask.putpixel((1, 0), (100, 100, 100))
    buffer = io.BytesIO(); mask.save(buffer, "PNG")
    result = apply_background_mask(picture(), "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
    image = decoded(result)
    assert image.size == (64, 64) and image.mode == "RGBA"
    assert image.getpixel((0, 0)) == (0, 0, 255, 0)
    assert image.getpixel((1, 0)) == (0, 0, 255, 100)
    assert image.getpixel((32, 32)) == (0, 0, 255, 255)


def test_background_mask_rejects_color_photo_instead_of_making_a_false_cutout():
    with pytest.raises(ValueError, match="цветное"):
        apply_background_mask(picture(), picture())
