"""Агент-сегментатор: модель размечает, судит детерминированный код.

Гарантия та же, что у AI-починки: ни одна цифра модели не принимается на
веру. Рамки клампятся в тайл, гигантские и вырожденные отклоняются, рамка
без пиксельного содержимого (галлюцинация) отклоняется, роль — только из
закрытого списка, метка проходит charset-фильтр. Повторы схлопываются в
repeatGroup детерминированной кластеризацией — без модели.

Тесты гоняют логику без сети и без VLM: синтетическое изображение с
цветными прямоугольниками играет роль скриншота.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DESIGNDNA_DATA_DIR", tempfile.mkdtemp(prefix="segmenter-"))

import screenshot_segmenter as seg  # noqa: E402


def _synthetic_image(width: int = 400, height: int = 300) -> np.ndarray:
    """Белый фон + три «компонента»: кнопка и две одинаковые плитки."""
    arr = np.full((height, width, 3), 255, dtype=np.uint8)
    arr[20:60, 30:130] = (123, 47, 247)     # «кнопка» 100×40
    arr[100:200, 30:130] = (240, 240, 255)  # «плитка» 100×100 со «значком»
    arr[130:170, 60:100] = (255, 120, 40)
    arr[100:200, 160:260] = (240, 240, 255)  # вторая такая же плитка
    arr[130:170, 190:230] = (255, 120, 40)
    return arr


def _tile() -> dict:
    return {"index": 0, "x": 0, "y": 0, "width": 400, "height": 300}


# ---------- тайлинг ----------

def test_tile_grid_covers_image_with_overlap():
    tiles = seg.tile_grid(2000, 900)
    assert tiles, "непустое изображение обязано дать тайлы"
    covered_x = max(t["x"] + t["width"] for t in tiles)
    covered_y = max(t["y"] + t["height"] for t in tiles)
    assert covered_x == 2000 and covered_y == 900, "тайлы обязаны покрыть всё изображение"
    assert all(t["width"] <= seg.TILE_SIZE and t["height"] <= seg.TILE_SIZE for t in tiles)
    # маленький скриншот — один тайл, без лишних заданий модели
    assert len(seg.tile_grid(800, 600)) == 1


# ---------- промпт ----------

def test_prompt_carries_tile_image_and_closed_role_list():
    tile = _tile()
    messages = seg.build_segment_prompt(tile, "data:image/png;base64,AAAA",
                                        {"width": 400, "height": 300})
    assert messages[0]["role"] == "system"
    assert "do not invent components" in messages[0]["content"].lower()
    parts = messages[1]["content"]
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == 1, "тайл обязан уехать картинкой, не описанием"
    payload = json.loads(next(p["text"] for p in parts if p.get("type") == "text"))
    assert payload["tile"]["offset"] == {"x": 0, "y": 0}
    assert "button" in payload["output"]["regions"][0]["role"]


# ---------- валидация ----------

def test_validation_rejects_out_of_bounds_giant_and_unknown_roles():
    arr = _synthetic_image()
    parsed = {"regions": [
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button", "label": "Найти"},
        # клампится в тайл и выживает: правая граница за краем
        {"x": 160, "y": 100, "width": 900, "height": 100, "role": "card", "label": "Плитка"},
        # отклоняется: вся картинка — не компонент
        {"x": 0, "y": 0, "width": 400, "height": 300, "role": "card", "label": "Страница"},
        # отклоняется: вырожденная
        {"x": 10, "y": 10, "width": 4, "height": 4, "role": "icon", "label": "точка"},
        # отклоняется: неизвестная роль
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "spaceship", "label": "х"},
        # отклоняется: не числа
        {"x": "left", "y": 20, "width": 100, "height": 40, "role": "button", "label": "х"},
    ]}
    regions = seg.validate_regions(parsed, _tile(), arr)
    roles = [r["role"] for r in regions]
    assert roles == ["button", "card"]
    clamped = regions[1]
    assert clamped["x"] + clamped["width"] <= 400, "рамка обязана клампиться в тайл"


def test_validation_rejects_hallucinated_region_on_plain_background():
    arr = _synthetic_image()
    parsed = {"regions": [
        # однотонный белый угол: пиксельного содержимого нет — галлюцинация
        {"x": 280, "y": 220, "width": 100, "height": 60, "role": "card", "label": "Призрак"},
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button", "label": "Найти"},
    ]}
    regions = seg.validate_regions(parsed, _tile(), arr)
    assert [r["label"] for r in regions] == ["Найти"]


def test_validation_strips_control_chars_and_caps_label():
    arr = _synthetic_image()
    parsed = {"regions": [
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button",
         "label": "Най\x00ти\x1b[31m" + "!" * 200},
    ]}
    regions = seg.validate_regions(parsed, _tile(), arr)
    label = regions[0]["label"]
    assert "\x00" not in label and "\x1b" not in label
    assert len(label) <= seg.MAX_LABEL_LENGTH


def test_validation_offsets_regions_into_global_coordinates():
    arr = np.full((300, 800, 3), 255, dtype=np.uint8)
    arr[20:60, 430:530] = (123, 47, 247)
    tile = {"index": 1, "x": 400, "y": 0, "width": 400, "height": 300}
    parsed = {"regions": [
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button", "label": "Найти"},
    ]}
    regions = seg.validate_regions(parsed, tile, arr)
    assert regions[0]["x"] == 430 and regions[0]["y"] == 20


def test_validation_requires_json_object():
    try:
        seg.validate_regions(["not", "an", "object"], _tile())
    except ValueError:
        pass
    else:
        raise AssertionError("список вместо объекта обязан отклоняться")


# ---------- дедуп и повторы ----------

def test_merge_dedupes_seam_duplicates_keeping_the_larger_box():
    full = {"x": 100, "y": 50, "width": 120, "height": 80, "role": "card", "label": "A"}
    seam_cut = {"x": 104, "y": 52, "width": 100, "height": 76, "role": "card", "label": "A"}
    far = {"x": 500, "y": 50, "width": 120, "height": 80, "role": "card", "label": "B"}
    merged = seg.merge_regions([seam_cut, full, far])
    assert len(merged) == 2
    assert any(r["width"] == 120 and r["x"] == 100 for r in merged), \
        "из двойников обязана выживать большая рамка"


def test_merge_groups_repeated_tiles_and_orders_reading_flow():
    tiles = [
        {"x": 30 + i * 130, "y": 100, "width": 100, "height": 100, "role": "tile",
         "label": f"Категория {i}"}
        for i in range(4)
    ]
    button = {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button", "label": "Найти"}
    merged = seg.merge_regions([*tiles, button])
    groups = {r.get("repeatGroup") for r in merged if r["role"] == "tile"}
    assert len(groups) == 1 and None not in groups, "4 одинаковые плитки → один repeatGroup"
    assert "repeatGroup" not in merged[0] or merged[0]["role"] == "tile"
    assert merged[0]["label"] == "Найти", "порядок чтения: сверху вниз"
    assert all(r["key"] == f"seg-{i}" for i, r in enumerate(merged))


def test_merge_does_not_group_different_sizes_or_roles():
    a = {"x": 0, "y": 0, "width": 100, "height": 100, "role": "tile", "label": "A"}
    b = {"x": 200, "y": 0, "width": 150, "height": 100, "role": "tile", "label": "B"}
    c = {"x": 400, "y": 0, "width": 100, "height": 100, "role": "card", "label": "C"}
    merged = seg.merge_regions([a, b, c])
    assert all("repeatGroup" not in r for r in merged)


# ---------- эндпоинт ----------

def _endpoint_client():
    from fastapi.testclient import TestClient

    import server

    # Без `with`: контекст TestClient гоняет lifespan приложения, а его
    # shutdown гасит общий EXECUTOR сервера (образец fidelity_repair_evidence).
    return TestClient(server.app)


def _image_data_url(arr: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(arr).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_endpoint_prepare_then_apply_round_trip():
    client = _endpoint_client()
    image = _image_data_url(_synthetic_image())

    prepared = client.post("/api/reproduce/segment",
                           json={"image": image, "prepareOnly": True})
    assert prepared.status_code == 200, prepared.text
    tasks = prepared.json()["tasks"]
    assert len(tasks) == 1
    assert any(part.get("type") == "image_url"
               for part in tasks[0]["messages"][1]["content"])

    answer = json.dumps({"regions": [
        {"x": 30, "y": 20, "width": 100, "height": 40, "role": "button", "label": "Найти"},
        {"x": 30, "y": 100, "width": 100, "height": 100, "role": "tile", "label": "Плитка"},
        {"x": 160, "y": 100, "width": 100, "height": 100, "role": "tile", "label": "Плитка"},
        {"x": 280, "y": 220, "width": 100, "height": 60, "role": "card", "label": "Призрак"},
    ]})
    applied = client.post("/api/reproduce/segment",
                          json={"image": image,
                                "rawOutputs": [{"tileIndex": 0, "content": answer}]})
    assert applied.status_code == 200, applied.text
    body = applied.json()
    labels = [r["label"] for r in body["regions"]]
    assert "Призрак" not in labels, "галлюцинация обязана отсеяться пиксельной проверкой"
    assert labels[0] == "Найти"
    assert body["repeatGroups"] == ["tile-100x100"]
    # Эндпоинт сразу отдаёт готовый Source-блок с boundary-узлами.
    block = body["block"]
    boundaries = [child for child in block["ir"]["tree"][0]["children"]
                  if (child.get("sourceMeta") or {}).get("componentBoundary")]
    assert len(boundaries) == len(body["regions"])
    assert block["previews"]["desktop"].startswith("data:image/png")


def test_endpoint_survives_broken_model_output():
    client = _endpoint_client()
    image = _image_data_url(_synthetic_image())
    applied = client.post("/api/reproduce/segment",
                          json={"image": image, "rawOutputs": [
                              {"tileIndex": 0, "content": "sorry, I cannot"},
                              {"tileIndex": 99, "content": "{}"},
                              "not-a-dict",
                          ]})
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["regions"] == []
    assert body["rejectedOutputs"] >= 1


def test_endpoint_rejects_non_image_payloads():
    client = _endpoint_client()
    assert client.post("/api/reproduce/segment",
                       json={"image": "", "prepareOnly": True}).status_code == 422
    assert client.post("/api/reproduce/segment",
                       json={"image": "data:image/png;base64,%%%",
                             "prepareOnly": True}).status_code == 422
