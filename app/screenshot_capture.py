"""Скриншот + принятые рамки сегментатора → Source-блок с мастерами.

Каждая рамка становится узлом с sourceMeta.componentBoundary — ровно той
меткой, по которой билдер дизайн-системы создаёт мастеров. Содержимое узла —
честный растровый слой: кроп скриншота как locked image (editable:false,
reason:"raster-fallback"). Никакой выдуманной геометрии и стилей: пиксели
источника и рамки, прошедшие детерминированную проверку сегментатора.

Растровый мастер — базовая линия, а не финал: редактируемый разбор кропа
(отдельный AI-шаг) принимается только если его рендер достаточно похож на
этот же кроп — судья тот же, что у AI-починки. Хуже растра стать нельзя.

DOM-улик здесь нет, поэтому такие мастера не могут пройти полный
fidelity-гейт (bbox и потери меряются против DOM) — билдер честно положит
их в пул «на ревью», и кит покажет их с этой пометкой.
"""
from __future__ import annotations

import base64
import io

# Роль сегментатора → (тип узла IR, componentRole для таксономии билдера).
# componentRole — переносимая семантика, которую понимает
# design_system.builder._semantic_component_key; тип — из закрытого списка
# element-типов схемы design-ir.
ROLE_MAP: dict[str, tuple[str, str]] = {
    "button": ("button", "button"),
    "toggle": ("button", "button"),
    "chip": ("button", "button"),
    "badge": ("badge", "button"),
    "tab": ("button", "tab"),
    "link": ("button", "a"),
    "tile": ("card", "a"),
    "input": ("input", "textbox"),
    "search": ("input", "searchbox"),
    "select": ("input", "combobox"),
    "nav": ("card", "nav"),
    "menu": ("card", "menu"),
    "pagination": ("card", "nav"),
    "footer": ("card", "navigation"),
    "heading": ("heading", "heading"),
    "text": ("text", "region"),
    "card": ("card", "article"),
    "list-item": ("card", "listitem"),
    "stat": ("stat", "widget"),
    "price": ("stat", "widget"),
    "rating": ("rating", "widget"),
    "icon": ("icon", "widget"),
    "logo": ("image", "widget"),
    "avatar": ("avatar", "widget"),
    "image": ("image", "widget"),
    "banner": ("card", "region"),
    "hero": ("card", "region"),
    "carousel": ("card", "region"),
}

PIPELINE_VERSION = "screenshot-v1"


def measured_tokens(arr_rgb) -> dict:
    """Полные IR-токены, измеренные из пикселей скриншота.

    Схема design-ir требует mode/color/font/radius/spacing/shadow целиком.
    Все цвета — из extract_colors (реальные пиксели, не гипотеза); шрифт
    честно ставится системным: из статичного изображения имя шрифта не
    измерить, а угадывать — значит врать. AI-стиль-ревью уточнит позже.
    """
    from reproduce import extract_colors

    colors = extract_colors(arr_rgb).get("colors") or {}

    def hex_of(key: str, fallback: str) -> str:
        value = colors.get(key) or {}
        return str(value.get("hex") or fallback)

    background = hex_of("background", "#ffffff")
    luma = sum(int(background[i:i + 2], 16) for i in (1, 3, 5)) / 3
    dark_mode = luma < 128
    accent = hex_of("accent_0", "#3b6cff")
    text = hex_of("text_dark", "#f5f5f5" if dark_mode else "#111111")
    muted = next((str(v["hex"]) for k, v in colors.items() if k.startswith("gray_")),
                 "#9aa2b4" if dark_mode else "#6b7280")
    return {
        "mode": "dark" if dark_mode else "light",
        "color": {
            "primary": accent, "secondary": accent, "accent": accent,
            "background": background, "surface": background,
            "text": text, "textMuted": muted,
            "border": hex_of("border", muted),
        },
        "font": {
            "display": {"family": "system-ui", "weight": 700},
            "body": {"family": "system-ui", "weight": 400},
            "scale": "default",
        },
        "radius": {"card": "md", "button": "md", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "none",
    }


def _decode_image(image_data_url: str):
    from PIL import Image

    encoded = image_data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def _crop_data_url(img, region: dict) -> str:
    crop = img.crop((region["x"], region["y"],
                     region["x"] + region["width"], region["y"] + region["height"]))
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def component_node(region: dict, crop_url: str) -> dict:
    """Узел-мастер одной рамки: boundary-контейнер + locked raster внутри."""
    node_type, component_role = ROLE_MAP.get(region["role"], ("card", "region"))
    key = str(region.get("key") or f"seg-{region['x']}-{region['y']}")
    label = str(region.get("label") or "").strip() or region["role"]
    meta = {
        "kind": "vision",
        "componentBoundary": True,
        "componentRole": component_role,
        "componentLabel": label,
        "captureVersion": PIPELINE_VERSION,
    }
    if region.get("repeatGroup"):
        meta["repeatGroup"] = str(region["repeatGroup"])
    return {
        "type": node_type,
        "sourceKey": key,
        "frame": {"x": region["x"], "y": region["y"],
                  "width": region["width"], "height": region["height"],
                  "layout": "free"},
        "sourceMeta": meta,
        "children": [{
            "type": "image",
            "sourceKey": f"{key}::raster",
            "src": crop_url,
            "editable": False,
            "frame": {"x": 0, "y": 0,
                      "width": region["width"], "height": region["height"]},
            "sourceMeta": {"kind": "vision", "reason": "raster-fallback"},
        }],
    }


def build_screenshot_block(image_data_url: str, regions: list[dict],
                           tokens: dict | None = None, name: str = "capture") -> dict:
    """Блок в формате результата /api/block-parse: ir + эталон для судьи.

    previews.desktop — весь скриншот: это тот же эталон, которым judge
    AI-починки и скриншот-harness меряют пиксельное сходство рендера.
    """
    import numpy as np

    img = _decode_image(image_data_url)
    width, height = img.size
    children = [component_node(region, _crop_data_url(img, region))
                for region in regions or []]
    ir = {
        "version": "1.1",
        "tokens": tokens or measured_tokens(np.array(img)),
        "tree": [{
            "id": "screenshot-root",
            "type": "source-block",
            "variant": "screenshot-import",
            "sourceKey": "screenshot-root",
            "frame": {"x": 0, "y": 0, "width": width, "height": height,
                      "layout": "free"},
            "props": {},
            "children": children,
        }],
    }
    return {
        "name": name,
        "selector": "screenshot",
        "kind": "source-block",
        "ir": ir,
        "source": "vision",
        "size": {"width": width, "height": height},
        "sizes": {"desktop": {"width": width, "height": height}},
        "preview": image_data_url,
        "previews": {"desktop": image_data_url},
        "layers": len(children),
        "warnings": [] if children else ["Сегментатор не дал ни одной рамки"],
    }
