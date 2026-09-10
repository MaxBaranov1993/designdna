import base64
import io

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from chroma_key import remove_chroma


def url(image):
    output = io.BytesIO()
    image.save(output, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def read(value):
    return Image.open(io.BytesIO(base64.b64decode(value.split(',', 1)[1]))).convert('RGBA')


def fixture():
    image = Image.new('RGBA', (80, 64), '#00ff00')
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 10, 65, 55), fill=(240, 70, 30, 255))
    draw.rectangle((25, 20, 35, 30), fill='#00ff00')
    image.putpixel((14, 20), (0, 210, 0, 255))
    return image


def test_connected_background_alpha_interior_and_edge():
    original = fixture()
    result = remove_chroma(url(original), tolerance=32, softness=24, despill=False)
    image, mask = read(result['png']), read(result['mask'])
    assert image.size == original.size == mask.size
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((30, 25)) == original.getpixel((30, 25))  # enclosed green detail
    assert image.getpixel((20, 20)) == original.getpixel((20, 20))
    assert 0 < image.getpixel((14, 20))[3] < 255
    assert mask.getpixel((14, 20))[0] == image.getpixel((14, 20))[3]
    assert result['transparent'] and result['method'] == 'chroma'
    assert read(result['edge']).getbbox()


def test_despill_only_changes_keyed_edge_and_preserves_input():
    original = fixture()
    before = original.tobytes()
    result = read(remove_chroma(url(original))['png'])
    assert result.getpixel((14, 20))[1] < original.getpixel((14, 20))[1]
    assert result.getpixel((20, 20)) == original.getpixel((20, 20))
    assert original.tobytes() == before


def test_rejects_absent_key_empty_mask_and_bad_parameters():
    with pytest.raises(ValueError, match='всё изображение'):
        remove_chroma(url(Image.new('RGB', (8, 8), '#00ff00')))
    with pytest.raises(ValueError, match='не найден'):
        remove_chroma(url(fixture()), color='#0000ff')
    with pytest.raises(ValueError, match='формате'):
        remove_chroma(url(fixture()), color='green')


def test_local_api_never_calls_a_provider(monkeypatch):
    import server
    monkeypatch.setattr(server.llm, 'chat', lambda *a, **k: pytest.fail('local mode called AI'))
    client = TestClient(server.app)
    result = client.post('/api/image/chroma-key', json={'image': url(fixture())})
    assert result.status_code == 200
    assert result.json()['transparent']
    assert client.post('/api/image/chroma-key', json={'image': url(fixture()), 'softness': 0}).status_code == 422
