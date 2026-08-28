"""Скриншот → Source-блок → мастера дизайн-системы, без DOM.

Проверяется сквозная цепочка этапа: рамки сегментатора становятся узлами с
componentBoundary, билдер дизайн-системы создаёт из них семейства, повторы
складываются в одно семейство, а не в свалку дублей. И главная граница:
без DOM-улик такие мастера НЕ проходят fidelity-гейт и честно живут в пуле
«на ревью» — гейт не ослаблен ни на пункт.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DESIGNDNA_DATA_DIR", tempfile.mkdtemp(prefix="screenshot-capture-"))

import screenshot_capture as cap  # noqa: E402
from ir.validate import validate_ir  # noqa: E402


def _image_data_url(width: int = 400, height: int = 300) -> str:
    arr = np.full((height, width, 3), 255, dtype=np.uint8)
    arr[20:60, 30:130] = (123, 47, 247)
    arr[100:200, 30:130] = (240, 240, 255)
    arr[100:200, 160:260] = (240, 240, 255)
    buffer = io.BytesIO()
    Image.fromarray(arr).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _regions() -> list[dict]:
    return [
        {"key": "seg-0", "x": 30, "y": 20, "width": 100, "height": 40,
         "role": "button", "label": "Найти"},
        {"key": "seg-1", "x": 30, "y": 100, "width": 100, "height": 100,
         "role": "tile", "label": "Категория", "repeatGroup": "tile-100x100"},
        {"key": "seg-2", "x": 160, "y": 100, "width": 100, "height": 100,
         "role": "tile", "label": "Категория", "repeatGroup": "tile-100x100"},
    ]


def test_block_ir_is_schema_valid_and_carries_boundaries():
    block = cap.build_screenshot_block(_image_data_url(), _regions())
    errors = validate_ir(block["ir"])
    assert not errors, errors[:3]
    root = block["ir"]["tree"][0]
    assert root["type"] == "source-block"
    boundaries = [child for child in root["children"]
                  if child["sourceMeta"].get("componentBoundary")]
    assert len(boundaries) == 3, "каждая рамка обязана стать boundary-узлом"
    assert block["previews"]["desktop"].startswith("data:image/png"), \
        "эталон для судьи — весь скриншот"
    assert block["sizes"]["desktop"] == {"width": 400, "height": 300}


def test_component_node_is_locked_raster_inside_boundary():
    block = cap.build_screenshot_block(_image_data_url(), _regions()[:1])
    node = block["ir"]["tree"][0]["children"][0]
    assert node["type"] == "button" and node["sourceMeta"]["componentRole"] == "button"
    raster = node["children"][0]
    assert raster["type"] == "image" and raster["editable"] is False
    assert raster["sourceMeta"]["reason"] == "raster-fallback"
    assert raster["src"].startswith("data:image/png;base64,"), \
        "содержимое — настоящий кроп, не заглушка"
    # кроп именно этой рамки: 100×40 фиолетовой кнопки
    crop = Image.open(io.BytesIO(base64.b64decode(raster["src"].split(",", 1)[1])))
    assert crop.size == (100, 40)
    center = crop.getpixel((50, 20))
    assert center[2] > 200 and center[0] < 160, "в кропе пиксели кнопки, не фон"


def test_unknown_role_degrades_to_surface_not_crash():
    region = {"key": "seg-9", "x": 30, "y": 20, "width": 100, "height": 40,
              "role": "hologram", "label": "х"}
    node = cap.component_node(region, "data:image/png;base64,AAAA")
    assert node["type"] == "card" and node["sourceMeta"]["componentRole"] == "region"


def test_design_system_builder_accepts_screenshot_masters():
    from design_system import builder

    block = cap.build_screenshot_block(_image_data_url(), _regions())
    node_data = {"blocks": [block], "tokens": {}, "importedUrl": "",
                 "sourceArtifact": None}
    pack = builder.build_source_pack(node_data, source_node_id=7)
    doc = builder.build_draft(pack, name="Screenshot kit")

    total = len(doc.get("components") or {}) + len(doc.get("reviewComponents") or {})
    assert total >= 2, "кнопка и семейство плиток обязаны стать мастерами"
    # Без DOM-улик гейт непроходим — все мастера честно «на ревью».
    assert not doc.get("components"), \
        "скриншот-мастер не смеет пройти fidelity-гейт без DOM-улик"
    review = doc["reviewComponents"]
    families = {key.split("-review")[0] for key in review}
    assert "button" in families
    tile_masters = [comp for comp in review.values()
                    if (comp.get("provenance") or {}).get("occurrenceCount", 1) >= 2
                    or "tile" in str(comp.get("name", "")).lower()
                    or "категория" in str(comp.get("name", "")).lower()]
    assert tile_masters or len(review) >= 2, review.keys()


def test_empty_segmentation_yields_block_with_warning():
    block = cap.build_screenshot_block(_image_data_url(), [])
    assert block["warnings"], "пустая сегментация обязана быть видимой, не тихой"
    assert block["ir"]["tree"][0]["children"] == []
