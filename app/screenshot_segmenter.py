"""Агент-сегментатор: скриншот → границы компонентов.

Модель здесь НЕ измеряет и не изобретает: она размечает прямоугольники,
называет роль (button/card/nav…) и метку. Каждое её число проходит
детерминированную проверку по пикселям:

- координаты клампятся в границы тайла, вырожденные и гигантские рамки
  отклоняются;
- рамка без пиксельного содержимого внутри (однотонный фон) отклоняется —
  модель не может «увидеть» несуществующий компонент;
- роль — только из закрытого списка, метка — после charset-фильтра.

Повторы (плитки категорий, карточки товаров) схлопываются в repeatGroup
детерминированной кластеризацией по роли и размеру — как это делает
DOM-компилятор для живой страницы. Здесь ни одного сетевого вызова: промпт
готовится для провайдера пользователя (Claude/GPT), ответ валидируется тут.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Роли — подмножество componentRole, которые понимает билдер дизайн-системы.
# Закрытый список: неизвестная роль отклоняется, а не «пропускается как есть».
SEGMENT_ROLES = (
    "button", "link", "input", "search", "select", "badge", "chip", "icon",
    "logo", "avatar", "image", "card", "tile", "list-item", "tab", "nav",
    "menu", "banner", "hero", "heading", "text", "stat", "price", "rating",
    "footer", "pagination", "toggle", "carousel",
)
_ROLE_SET = set(SEGMENT_ROLES)

# Тайлы: VLM заметно врёт в координатах на больших изображениях, поэтому
# скриншот режется на перекрывающиеся квадраты ~1024px. Перекрытие ловит
# компоненты на швах; дедуп по IoU потом убирает двойников.
TILE_SIZE = 1024
TILE_OVERLAP = 128

MIN_REGION_SIZE = 12          # меньше — шум, не компонент
MAX_REGION_AREA_SHARE = 0.92  # рамка «вся картинка» — не компонент
MIN_CONTENT_SHARE = 0.01      # доля пикселей, отличных от фона рамки
DEDUP_IOU = 0.6
REPEAT_SIZE_TOLERANCE = 0.08  # ±8% по каждой стороне → тот же повтор
MAX_REGIONS_PER_TILE = 40
MAX_LABEL_LENGTH = 80

# Метка идёт в имя компонента: только печатаемые символы, без управляющих.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def tile_grid(width: int, height: int, tile: int = TILE_SIZE,
              overlap: int = TILE_OVERLAP) -> list[dict]:
    """Сетка перекрывающихся тайлов, покрывающая изображение целиком."""
    if width <= 0 or height <= 0:
        return []
    step = max(1, tile - overlap)
    xs = list(range(0, max(1, width - overlap), step))
    ys = list(range(0, max(1, height - overlap), step))
    tiles = []
    for y in ys:
        for x in xs:
            tiles.append({
                "index": len(tiles),
                "x": x, "y": y,
                "width": min(tile, width - x),
                "height": min(tile, height - y),
            })
    return tiles


def build_segment_prompt(tile: dict, tile_data_url: str, image_size: dict) -> list[dict]:
    """Сообщения разметки одного тайла. Модель отвечает рамками в координатах ТАЙЛА."""
    system = (
        "You segment a website screenshot into UI components. Return bounding "
        "boxes in the coordinate system of THIS image tile (top-left is 0,0). "
        "Mark every distinct interactive or content component: buttons, inputs, "
        "cards, tiles, navigation items, badges, headings. Do not mark whole "
        "page sections spanning the entire tile, and do not invent components "
        "you cannot see. For visually repeated items (category tiles, product "
        "cards) mark EACH occurrence separately with the same role and label. "
        "Return ONE JSON object, no prose."
    )
    schema = {
        "regions": [
            {"x": 0, "y": 0, "width": 0, "height": 0,
             "role": "one of " + ", ".join(SEGMENT_ROLES),
             "label": "short human name, e.g. 'Search button'"},
        ],
    }
    payload = {
        "tile": {"index": tile["index"], "offset": {"x": tile["x"], "y": tile["y"]},
                 "size": {"width": tile["width"], "height": tile["height"]}},
        "fullImage": image_size,
        "output": schema,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
            {"type": "image_url", "image_url": {"url": tile_data_url, "detail": "high"}},
        ]},
    ]


def _clean_label(value: Any) -> str:
    text = _CONTROL_CHARS.sub("", str(value or "")).strip()
    return text[:MAX_LABEL_LENGTH]


_SURROUND_PAD = 8
_COLOR_DISTANCE = 30


def _has_content(arr_rgb, rect: dict) -> bool:
    """Детерминированная опора: в рамке настоящего компонента что-то есть.

    Либо внутри есть вариация (текст, иконка, граница), либо рамка целиком
    контрастирует с окружением (сплошная кнопка на белом фоне). Однотонная
    рамка на однотонном фоне — галлюцинация модели, отклоняется.
    """
    import numpy as np

    height, width = arr_rgb.shape[:2]
    x, y = int(rect["x"]), int(rect["y"])
    w, h = int(rect["width"]), int(rect["height"])
    crop = arr_rgb[y:y + h, x:x + w]
    if crop.size == 0:
        return False
    inner_median = np.median(crop.reshape(-1, 3), axis=0)
    distance = np.abs(crop.astype(int) - inner_median.astype(int)).sum(axis=2)
    if float((distance > _COLOR_DISTANCE).mean()) >= MIN_CONTENT_SHARE:
        return True
    # Кольцо вокруг рамки: рамка, вырезанная из расширенного кропа.
    ox1, oy1 = max(0, x - _SURROUND_PAD), max(0, y - _SURROUND_PAD)
    ox2, oy2 = min(width, x + w + _SURROUND_PAD), min(height, y + h + _SURROUND_PAD)
    ring_mask = np.ones((oy2 - oy1, ox2 - ox1), dtype=bool)
    ring_mask[y - oy1:y - oy1 + h, x - ox1:x - ox1 + w] = False
    ring = arr_rgb[oy1:oy2, ox1:ox2][ring_mask]
    if ring.size == 0:
        return False  # рамка упирается во все края — сравнивать не с чем
    ring_median = np.median(ring.reshape(-1, 3), axis=0)
    return float(np.abs(inner_median - ring_median).sum()) > _COLOR_DISTANCE


def validate_regions(parsed: Any, tile: dict, arr_rgb=None) -> list[dict]:
    """Строгая валидация ответа модели по одному тайлу.

    Возвращает рамки в ГЛОБАЛЬНЫХ координатах изображения. arr_rgb — полное
    изображение (numpy RGB); без него проверка содержимого пропускается
    (юнит-тесты промпта), с ним — обязательна.
    """
    if not isinstance(parsed, dict):
        raise ValueError("segment response must be a JSON object")
    raw_regions = parsed.get("regions")
    if not isinstance(raw_regions, list):
        raise ValueError("regions must be a list")

    tile_w, tile_h = int(tile["width"]), int(tile["height"])
    clean: list[dict] = []
    for raw in raw_regions[:MAX_REGIONS_PER_TILE]:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "")
        if role not in _ROLE_SET:
            continue
        try:
            x = max(0, int(float(raw.get("x", 0))))
            y = max(0, int(float(raw.get("y", 0))))
            w = int(float(raw.get("width", 0)))
            h = int(float(raw.get("height", 0)))
        except (TypeError, ValueError):
            continue
        w = min(w, tile_w - x)
        h = min(h, tile_h - y)
        if w < MIN_REGION_SIZE or h < MIN_REGION_SIZE:
            continue
        if (w * h) / float(tile_w * tile_h) > MAX_REGION_AREA_SHARE:
            continue
        region = {
            "x": x + int(tile["x"]), "y": y + int(tile["y"]),
            "width": w, "height": h,
            "role": role, "label": _clean_label(raw.get("label")),
        }
        if arr_rgb is not None and not _has_content(arr_rgb, region):
            continue
        clean.append(region)
    return clean


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["width"], a["y"] + a["height"]
    bx2, by2 = b["x"] + b["width"], b["y"] + b["height"]
    ix = max(0, min(ax2, bx2) - max(a["x"], b["x"]))
    iy = max(0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = ix * iy
    if not inter:
        return 0.0
    union = a["width"] * a["height"] + b["width"] * b["height"] - inter
    return inter / float(union)


def merge_regions(regions: list[dict]) -> list[dict]:
    """Дедуп двойников с перекрывающихся тайлов + группировка повторов.

    Двойники (IoU > 0.6): остаётся рамка большей площади — модель на «своём»
    тайле видит компонент целиком, на соседнем — обрезанным швом.
    Повторы: одинаковая роль и размер ±8% → общий repeatGroup, как у
    DOM-компилятора для плиток и карточек.
    """
    ordered = sorted(regions, key=lambda r: -(r["width"] * r["height"]))
    kept: list[dict] = []
    for region in ordered:
        if any(_iou(region, other) > DEDUP_IOU for other in kept):
            continue
        kept.append(dict(region))

    # Жадная кластеризация повторов: первый экземпляр задаёт эталонный размер.
    clusters: list[dict] = []
    for region in kept:
        home = None
        for cluster in clusters:
            if cluster["role"] != region["role"]:
                continue
            dw = abs(region["width"] - cluster["width"]) / max(1.0, cluster["width"])
            dh = abs(region["height"] - cluster["height"]) / max(1.0, cluster["height"])
            if dw <= REPEAT_SIZE_TOLERANCE and dh <= REPEAT_SIZE_TOLERANCE:
                home = cluster
                break
        if home is None:
            clusters.append({"role": region["role"], "width": region["width"],
                             "height": region["height"], "members": [region]})
        else:
            home["members"].append(region)

    for cluster in clusters:
        if len(cluster["members"]) < 2:
            continue
        group = f"{cluster['role']}-{cluster['width']}x{cluster['height']}"
        for member in cluster["members"]:
            member["repeatGroup"] = group

    # Стабильный порядок чтения: сверху вниз, слева направо.
    kept.sort(key=lambda r: (r["y"], r["x"]))
    for index, region in enumerate(kept):
        region["key"] = f"seg-{index}"
    return kept
