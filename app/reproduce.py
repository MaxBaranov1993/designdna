"""Pixel-perfect UI reproduction pipeline.

Скриншот → VLM-анализ структуры (любой провайдер) → Python-измерения
(цвета, bounding boxes, border-radius из пикселей) → извлечение иконок/контента
как PNG base64 → сборка HTML с absolute positioning → native screenshot
(Playwright) → pixel diff по регионам.

Все измерения — из пикселей, VLM даёт только структуру (какие элементы, layout).
"""
import base64
import contextlib
import io
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from urlguard import install_playwright_offline_guard


# ---------- извлечение цветов ----------

def extract_colors(arr: np.ndarray) -> dict:
    """Извлечь доминирующие цвета из пиксельного массива (H×W×3 uint8)."""
    h, w = arr.shape[:2]
    result = {"image_size": [w, h], "colors": {}}

    # тёмный текст (самый частый тёмный)
    dark_mask = (arr[:, :, 0] < 80) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80)
    dark_px = [tuple(arr[y, x]) for y, x in np.argwhere(dark_mask)]
    if dark_px:
        c, n = Counter(dark_px).most_common(1)[0]
        result["colors"]["text_dark"] = {"hex": _rgb_hex(c), "pixels": int(n)}

    # серый текст
    gray_mask = (
        (np.abs(arr[:, :, 0].astype(int) - arr[:, :, 1].astype(int)) < 12)
        & (np.abs(arr[:, :, 1].astype(int) - arr[:, :, 2].astype(int)) < 12)
        & (arr[:, :, 0] > 90) & (arr[:, :, 0] < 200)
    )
    gray_px = [tuple(arr[y, x]) for y, x in np.argwhere(gray_mask)]
    if gray_px:
        for c, n in Counter(gray_px).most_common(3):
            key = f"gray_{n}"
            result["colors"][key] = {"hex": _rgb_hex(c), "pixels": int(n)}

    # фон (самый частый цвет overall)
    flat = arr.reshape(-1, 3)
    bg_c, bg_n = Counter(map(tuple, flat)).most_common(1)[0]
    result["colors"]["background"] = {"hex": _rgb_hex(bg_c), "pixels": int(bg_n)}

    # цветные акценты (насыщенные пиксели, не серые)
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    sat_mask = ((max_c - min_c) > 40) & (max_c > 60)
    sat_px = [tuple(arr[y, x]) for y, x in np.argwhere(sat_mask)]
    if sat_px:
        for i, (c, n) in enumerate(Counter(sat_px).most_common(5)):
            result["colors"][f"accent_{i}"] = {"hex": _rgb_hex(c), "pixels": int(n)}

    # бордеры (светло-серые пиксели у краёв)
    border_mask = (
        (np.abs(r - g) < 8) & (np.abs(g - b) < 8)
        & (arr[:, :, 0] > 200) & (arr[:, :, 0] < 250)
    )
    border_px = [tuple(arr[y, x]) for y, x in np.argwhere(border_mask)]
    if border_px:
        c, n = Counter(border_px).most_common(1)[0]
        result["colors"]["border"] = {"hex": _rgb_hex(c), "pixels": int(n)}

    return result


def _rgb_hex(c) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


# ---------- измерение bounding boxes ----------

def measure_elements(arr: np.ndarray, color_masks: dict | None = None) -> dict:
    """Измерить bounding boxes цветных регионов.

    color_masks: {"name": mask(H×W bool)} — если None, строит маски сам.
    """
    h, w = arr.shape[:2]
    result = {"image_size": [w, h], "elements": {}}

    if color_masks is None:
        color_masks = _auto_masks(arr)

    for name, mask in color_masks.items():
        if not mask.any():
            continue
        cols = np.where(mask.any(axis=0))[0]
        rows = np.where(mask.any(axis=1))[0]
        x1, x2 = int(cols.min()), int(cols.max())
        y1, y2 = int(rows.min()), int(rows.max())

        # найти отдельные кластеры (кнопки) по колонкам
        clusters = _find_clusters(mask, min_width=20)
        result["elements"][name] = {
            "bbox": [x1, y1, x2, y2],
            "width": x2 - x1 + 1,
            "height": y2 - y1 + 1,
            "clusters": clusters,
        }

    # общий контент (не-белые строки)
    non_white = [y for y in range(h) if not np.all(arr[y] > 250)]
    if non_white:
        result["content_rows"] = [int(non_white[0]), int(non_white[-1])]
        result["content_height"] = int(non_white[-1] - non_white[0] + 1)

    return result


def _auto_masks(arr: np.ndarray) -> dict:
    """Автоматически построить цветовые маски для типичных UI-элементов."""
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    masks = {}

    # тёмный текст/иконки
    masks["dark"] = (arr[:, :, 0] < 100) & (arr[:, :, 1] < 100) & (arr[:, :, 2] < 100)

    # насыщенные цветные (кнопки, акценты)
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    masks["saturated"] = ((max_c - min_c) > 50) & (max_c > 80)

    # средне-серый (вторичный текст)
    masks["gray"] = (
        (np.abs(r - g) < 12) & (np.abs(g - b) < 12)
        & (arr[:, :, 0] > 90) & (arr[:, :, 0] < 200)
    )

    return masks


def _find_clusters(mask: np.ndarray, min_width: int = 20) -> list:
    """Найти горизонтальные кластеры в маске (отдельные кнопки/элементы)."""
    h, w = mask.shape
    in_cluster = False
    clusters = []
    for x in range(w):
        has = mask[:, x].any()
        if has and not in_cluster:
            start = x
            in_cluster = True
        elif not has and in_cluster:
            if x - start >= min_width:
                sub = mask[:, start:x]
                rows = np.where(sub.any(axis=1))[0]
                if len(rows):
                    clusters.append({
                        "x1": int(start), "x2": int(x - 1),
                        "y1": int(rows.min()), "y2": int(rows.max()),
                        "width": int(x - start),
                        "height": int(rows.max() - rows.min() + 1),
                    })
            in_cluster = False
    if in_cluster and w - start >= min_width:
        sub = mask[:, start:w]
        rows = np.where(sub.any(axis=1))[0]
        if len(rows):
            clusters.append({
                "x1": int(start), "x2": int(w - 1),
                "y1": int(rows.min()), "y2": int(rows.max()),
                "width": int(w - start),
                "height": int(rows.max() - rows.min() + 1),
            })
    return clusters


# ---------- анализ border-radius через ASCII-матрицу ----------

def analyze_corner(arr: np.ndarray, x: int, y: int, size: int = 12,
                  color_mask: np.ndarray | None = None) -> dict:
    """Определить border-radius по кривой скругления угла.

    Возвращает матрицу и оценку радиуса.
    """
    h, w = arr.shape[:2]
    x2 = min(x + size, w)
    y2 = min(y + size, h)
    region = arr[y:y2, x:x2]

    if color_mask is not None:
        mask_region = color_mask[y:y2, x:x2]
    else:
        # по умолчанию: не-белые пиксели
        mask_region = ~np.all(region > 250, axis=2)

    matrix = []
    for row_y in range(mask_region.shape[0]):
        row = ""
        for col_x in range(mask_region.shape[1]):
            row += "#" if mask_region[row_y, col_x] else "."
        matrix.append(row)

    # оценка радиуса: сколько строк сверху частично заполнены
    radius = 0
    for row_y in range(mask_region.shape[0]):
        filled = mask_region[row_y].sum()
        total = mask_region.shape[1]
        if filled > 0 and filled < total * 0.8:
            radius = row_y + 1
        else:
            break

    return {"matrix": matrix, "estimated_radius": int(radius), "corner": [int(x), int(y)]}


# ---------- извлечение иконок ----------

def extract_icon(img: Image.Image, x1: int, y1: int, x2: int, y2: int,
                 mode: str = "dark") -> dict:
    """Извлечь иконку из региона, сделать фон прозрачным, вернуть PNG base64.

    mode: 'dark' — тёмная иконка на светлом фоне
          'white' — белая иконка на цветном фоне
    """
    crop = img.crop((x1, y1, x2, y2)).convert("RGBA")
    arr = np.array(crop)

    if mode == "dark":
        mask = (arr[:, :, 0] < 150) | (arr[:, :, 1] < 150) | (arr[:, :, 2] < 150)
        arr[~mask, 3] = 0
        arr[mask, 0] = 43
        arr[mask, 1] = 43
        arr[mask, 2] = 43
        arr[mask, 3] = 255
    elif mode == "white":
        mask = (arr[:, :, 0] > 220) & (arr[:, :, 1] > 220) & (arr[:, :, 2] > 220)
        arr[~mask, 3] = 0
        arr[mask, :3] = 255
        arr[mask, 3] = 255

    icon = Image.fromarray(arr)
    # tight crop
    bg = Image.new("RGBA", icon.size, (255, 255, 255, 0))
    diff = ImageChops.difference(icon, bg)
    bbox = diff.getbbox()
    if bbox:
        icon = icon.crop(bbox)
        abs_x = x1 + bbox[0]
        abs_y = y1 + bbox[1]
    else:
        abs_x, abs_y = x1, y1

    buf = io.BytesIO()
    icon.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "b64": b64,
        "size": list(icon.size),
        "position": [int(abs_x), int(abs_y)],
        "original_region": [int(x1), int(y1), int(x2), int(y2)],
    }


def extract_content(img: Image.Image, x1: int, y1: int, x2: int, y2: int,
                    bg_mode: str = "white") -> dict:
    """Извлечь контент (иконка + текст) как единый PNG с прозрачным фоном."""
    crop = img.crop((x1, y1, x2, y2)).convert("RGBA")
    arr = np.array(crop)

    if bg_mode == "white":
        mask = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
        arr[mask, 3] = 0
    elif bg_mode == "colored":
        # цветной фон → прозрачный, светлый контент → opaque
        r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
        max_c = np.maximum(np.maximum(r, g), b)
        min_c = np.minimum(np.minimum(r, g), b)
        bg_mask = ((max_c - min_c) > 30) & (max_c > 60)
        arr[bg_mask, 3] = 0
        light = (arr[:, :, 0] > 230) & (arr[:, :, 1] > 230) & (arr[:, :, 2] > 230)
        arr[light, :3] = 255
        arr[light, 3] = 255

    icon = Image.fromarray(arr)
    bg = Image.new("RGBA", icon.size, (255, 255, 255, 0))
    diff = ImageChops.difference(icon, bg)
    bbox = diff.getbbox()
    if bbox:
        icon = icon.crop(bbox)
        abs_x = x1 + bbox[0]
        abs_y = y1 + bbox[1]
    else:
        abs_x, abs_y = x1, y1

    buf = io.BytesIO()
    icon.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "b64": b64,
        "size": list(icon.size),
        "position": [int(abs_x), int(abs_y)],
        "original_region": [int(x1), int(y1), int(x2), int(y2)],
    }


# ---------- сборка HTML ----------

def build_html(measurements: dict, colors: dict, icons: list, contents: list,
               structure: dict | None = None) -> str:
    """Собрать reproduction HTML с absolute positioning из измерений."""
    img_w, img_h = measurements.get("image_size", [1920, 100])
    content_h = measurements.get("content_height", img_h)

    color_vars = []
    for name, info in colors.get("colors", {}).items():
        css_name = name.replace("_", "-")
        color_vars.append(f"    --{css_name}: {info['hex']};")
    color_block = "\n".join(color_vars)

    elements_css = []
    elements_html = []

    # иконки
    for i, icon in enumerate(icons):
        px, py = icon["position"]
        sw, sh = icon["size"]
        cls = f"icon-{i}"
        elements_css.append(
            f"  .{cls} {{ position:absolute; left:{px}px; top:{py}px; "
            f"width:{sw}px; height:{sh}px; image-rendering:-webkit-optimize-contrast; }}"
        )
        elements_html.append(
            f'  <img class="{cls}" src="data:image/png;base64,{icon["b64"]}" alt="icon {i}" />'
        )

    # контент (кнопки, логотипы)
    for i, cont in enumerate(contents):
        px, py = cont["position"]
        sw, sh = cont["size"]
        cls = f"content-{i}"
        elements_css.append(
            f"  .{cls} {{ position:absolute; left:{px}px; top:{py}px; "
            f"width:{sw}px; height:{sh}px; image-rendering:-webkit-optimize-contrast; }}"
        )
        elements_html.append(
            f'  <img class="{cls}" src="data:image/png;base64,{cont["b64"]}" alt="content {i}" />'
        )

    css = "\n".join(elements_css)
    html_body = "\n".join(elements_html)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root {{
{color_block}
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  html, body {{
    -webkit-font-smoothing:antialiased;
    -moz-osx-font-smoothing:grayscale;
    text-rendering:optimizeLegibility;
  }}
  .repro {{
    position:relative;
    width:{img_w}px;
    height:{content_h}px;
    background:var(--background, #fff);
    transform-origin:top left;
    overflow:visible;
  }}
{css}
</style>
</head>
<body>
<div class="repro">
{html_body}
</div>
</body>
</html>"""


# ---------- screenshot + pixel diff ----------

def screenshot_html(html: str, viewport_w: int = 2400, viewport_h: int = 1400) -> bytes:
    """Скриншот HTML через Playwright в native масштабе. Возвращает PNG bytes."""
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        html_path = Path(f.name)

    try:
        with sync_playwright() as p:
            browser = None
            ctx = None
            try:
                browser = p.chromium.launch()
                ctx = browser.new_context(
                    viewport={"width": viewport_w, "height": viewport_h},
                    device_scale_factor=1,
                    service_workers="block",
                )
                install_playwright_offline_guard(ctx)
                page = ctx.new_page()
                page.goto(f"file:///{html_path.as_posix()}")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)

                # отключить любой CSS transform
                page.evaluate("""
                    const r = document.querySelector('.repro');
                    if (r) { r.style.transform = 'none'; }
                """)
                page.wait_for_timeout(500)

                el = page.query_selector(".repro")
                if el:
                    return el.screenshot()
                return page.screenshot()
            finally:
                if ctx is not None:
                    with contextlib.suppress(Exception):
                        ctx.close()
                if browser is not None:
                    with contextlib.suppress(Exception):
                        browser.close()
    finally:
        html_path.unlink(missing_ok=True)


def pixel_diff(orig_bytes: bytes, repro_bytes: bytes,
               regions: list | None = None) -> dict:
    """Попиксельное сравнение. Возвращает overall + per-region diff."""
    orig = np.array(Image.open(io.BytesIO(orig_bytes)).convert("RGB")).astype(int)
    repro = np.array(Image.open(io.BytesIO(repro_bytes)).convert("RGB")).astype(int)

    # привести к одному размеру (crop до минимума)
    h = min(orig.shape[0], repro.shape[0])
    w = min(orig.shape[1], repro.shape[1])
    orig = orig[:h, :w]
    repro = repro[:h, :w]

    diff = np.abs(orig - repro)
    very_diff = (diff > 30).any(axis=2)

    result = {
        "size": [int(w), int(h)],
        "overall_pct": round(100 * float(very_diff.sum()) / very_diff.size, 2),
        "mean_rgb": [
            round(float(diff[:, :, 0].mean()), 2),
            round(float(diff[:, :, 1].mean()), 2),
            round(float(diff[:, :, 2].mean()), 2),
        ],
        "regions": {},
    }

    if regions:
        for name, x1, y1, x2, y2 in regions:
            x2 = min(x2, w)
            y2 = min(y2, h)
            if x1 >= x2 or y1 >= y2:
                continue
            sub = diff[y1:y2, x1:x2]
            sub_vd = (sub > 30).any(axis=2)
            result["regions"][name] = {
                "pct": round(100 * float(sub_vd.sum()) / sub_vd.size, 2),
                "max": int(sub.max()),
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
            }

    return result


# ---------- VLM-анализ структуры ----------

STRUCTURE_SYSTEM = """Ты — UI-аналитик. Тебе дают скриншот веб-страницы.
Опиши СТРУКТУРУ: какие компоненты видны, их тип (кнопка, инпут, логотип, иконка, текст),
расположение (лево/центр/право, верх/низ), вложенность.
НЕ угадывай точные цвета или размеры в пикселях — только структура.
Верни JSON: {"components": [{"name": "...", "type": "button|input|icon|logo|text|image",
"position": "left|center|right", "description": "..."}], "layout": "описание раскладки"}"""


def analyze_structure(image_b64: str, provider: str, llm_module) -> dict:
    """VLM-анализ структуры скриншота через OpenRouter роль reproduce."""
    prompt = (
        "Проанализируй этот UI-скриншот. Опиши структуру: какие компоненты видны, "
        "их тип и расположение. Верни JSON по схеме."
    )
    try:
        raw = llm_module.chat_vision(provider, image_b64, prompt, STRUCTURE_SYSTEM, 0.2,
                                     role="reproduce")
        return json.loads(llm_module.extract_json(raw))
    except Exception as e:
        return {"components": [], "layout": "", "error": str(e)}


# ---------- полный пайплайн ----------

def run_pipeline(image_b64: str, provider: str = "openrouter", llm_module=None,
                 regions: list | None = None) -> dict:
    """Полный пайплайн pixel-perfect reproduction.

    1. VLM-анализ структуры через OpenRouter
    2. Python-измерения: цвета, bounding boxes
    3. Извлечение иконок/контента как PNG base64
    4. Сборка HTML с absolute positioning
    5. Screenshot через Playwright
    6. Pixel diff по регионам

    Возвращает: {structure, colors, measurements, icons, contents, html, diff}
    """
    # декодируем изображение
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    img_bytes = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    arr_rgb = np.array(img.convert("RGB"))

    # 1. VLM-анализ структуры
    structure = {}
    if llm_module:
        data_url = f"data:image/png;base64,{image_b64}"
        structure = analyze_structure(data_url, provider, llm_module)

    # 2. Измерения из пикселей
    colors = extract_colors(arr_rgb)
    measurements = measure_elements(arr_rgb)

    # 3. Извлечение иконок из кластеров
    icons = []
    contents = []
    for name, elem in measurements.get("elements", {}).items():
        for j, cl in enumerate(elem.get("clusters", [])):
            w_cl = cl["width"]
            h_cl = cl["height"]
            # маленькие кластеры → иконки, большие → контент
            if w_cl < 60 and h_cl < 60:
                try:
                    icon = extract_icon(img, cl["x1"], cl["y1"],
                                        cl["x2"] + 1, cl["y2"] + 1, mode="dark")
                    icon["source"] = f"{name}_cluster_{j}"
                    icons.append(icon)
                except Exception:
                    pass
            elif w_cl > 60:
                try:
                    cont = extract_content(img, cl["x1"], cl["y1"],
                                           cl["x2"] + 1, cl["y2"] + 1, bg_mode="white")
                    cont["source"] = f"{name}_cluster_{j}"
                    contents.append(cont)
                except Exception:
                    pass

    # 4. Сборка HTML
    html = build_html(measurements, colors, icons, contents, structure)

    # 5. Screenshot
    repro_png = None
    diff_result = None
    try:
        repro_png = screenshot_html(html, viewport_w=max(2400, img.width + 200))
        # 6. Pixel diff
        diff_result = pixel_diff(img_bytes, repro_png, regions)
    except Exception as e:
        diff_result = {"error": str(e)}

    return {
        "structure": structure,
        "colors": colors,
        "measurements": measurements,
        "icons": icons,
        "contents": contents,
        "html": html,
        "diff": diff_result,
        "repro_png_b64": base64.b64encode(repro_png).decode() if repro_png else None,
        "ir": to_design_ir(colors, measurements, structure, icons, contents, img),
    }


# ---------- конвертация в Design IR ----------

def to_design_ir(colors: dict, measurements: dict, structure: dict,
                 icons: list, contents: list, img: Image.Image) -> dict:
    """Конвертировать результаты пайплайна в валидный Design IR.

    Цвета → tokens, VLM-структура → tree, bounding boxes → frame geometry.
    IR проходит валидацию по schema/design-ir.schema.json.
    """
    c = colors.get("colors", {})
    img_w, img_h = measurements.get("image_size", [img.width, img.height])
    content_h = measurements.get("content_height", img_h)

    # --- tokens ---
    bg_hex = c.get("background", {}).get("hex", "#ffffff")
    text_hex = c.get("text_dark", {}).get("hex", "#1a1a1a")
    border_hex = c.get("border", {}).get("hex", "#e0e0e0")

    # определяем mode по яркости фона
    bg_r = int(bg_hex[1:3], 16)
    mode = "dark" if bg_r < 128 else "light"

    # accent цвета
    accents = [c[k]["hex"] for k in sorted(c.keys()) if k.startswith("accent_")]
    primary = accents[0] if accents else "#5B5BD6"
    secondary = accents[1] if len(accents) > 1 else primary
    accent = accents[0] if accents else primary

    # gray для textMuted
    grays = [c[k]["hex"] for k in sorted(c.keys()) if k.startswith("gray_")]
    text_muted = grays[0] if grays else ("#999999" if mode == "light" else "#888888")

    # surface — чуть отличается от background
    if mode == "light":
        surface = "#f5f5f5" if bg_hex == "#ffffff" else bg_hex
    else:
        surface = "#1a1a1a" if bg_hex == "#000000" else bg_hex

    tokens = {
        "mode": mode,
        "color": {
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "background": bg_hex,
            "surface": surface,
            "text": text_hex,
            "textMuted": text_muted,
            "border": border_hex,
        },
        "font": {
            "display": {"family": "Inter", "weight": 600},
            "body": {"family": "Inter", "weight": 400},
            "scale": "default",
        },
        "radius": {"card": "md", "button": "md", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "sm",
    }

    # --- tree: строим секцию из VLM-структуры или из измерений ---
    components = structure.get("components", [])
    layout_desc = structure.get("layout", "")

    # определяем тип секции
    section_type = _guess_section_type(components, layout_desc, measurements)

    # строим props в зависимости от типа
    if section_type == "navbar":
        props = _build_navbar_props(components, contents, icons, measurements)
    elif section_type == "contact-form":
        props = _build_contact_form_props(components)
    elif section_type == "pricing":
        props = _build_pricing_props(components)
    elif section_type == "stats":
        props = _build_stats_props(components)
    else:
        props = _build_generic_props(components, contents, icons, measurements)

    # frame для секции — free layout с измеренными размерами
    section_frame = {
        "width": img_w,
        "height": content_h,
        "layout": "free",
    }

    section = {
        "id": "repro-1",
        "type": section_type,
        "variant": "classic",
        "props": props,
        "frame": section_frame,
    }

    # добавляем children из извлечённых элементов (иконки + контент как image-элементы)
    children = []
    for i, icon in enumerate(icons):
        px, py = icon["position"]
        sw, sh = icon["size"]
        children.append({
            "type": "image",
            "src": f"data:image/png;base64,{icon['b64']}",
            "alt": icon.get("source", f"icon-{i}"),
            "frame": {"x": px, "y": py, "width": sw, "height": sh},
        })
    for i, cont in enumerate(contents):
        px, py = cont["position"]
        sw, sh = cont["size"]
        children.append({
            "type": "image",
            "src": f"data:image/png;base64,{cont['b64']}",
            "alt": cont.get("source", f"content-{i}"),
            "frame": {"x": px, "y": py, "width": sw, "height": sh},
        })
    if children:
        section["children"] = children

    ir = {
        "version": "1.0",
        "meta": {
            "name": "Pixel-perfect reproduction",
            "styleTags": ["reproduction", "pixel-perfect"],
        },
        "frame": {
            "width": img_w,
            "height": content_h,
            "layout": "free",
        },
        "tokens": tokens,
        "tree": [section],
    }

    return ir


def _guess_section_type(components: list, layout: str, measurements: dict) -> str:
    """Определить тип секции по VLM-анализу и измерениям."""
    types_lower = " ".join(c.get("type", "") + " " + c.get("description", "")
                           for c in components).lower()
    layout_lower = layout.lower()

    if any(w in types_lower for w in ["nav", "header", "menu", "logo"]):
        return "navbar"
    if any(w in types_lower for w in ["hero", "banner", "headline"]):
        return "hero"
    if any(w in types_lower for w in ["footer", "copyright"]):
        return "footer"
    if any(w in types_lower for w in ["price", "plan", "tier"]):
        return "pricing"
    if any(w in types_lower for w in ["faq", "question", "accordion"]):
        return "faq"
    if any(w in types_lower for w in ["stat", "metric", "number"]):
        return "stats"

    # по высоте: тонкая полоска = navbar
    content_h = measurements.get("content_height", 0)
    if content_h and content_h < 150:
        return "navbar"

    # структурные сигналы вместо слепого fallback в hero
    if any(w in types_lower for w in ["input", "textarea", "checkbox", "form field"]):
        return "contact-form"
    if sum(1 for c in components
           if "link" in (c.get("type", "") + " " + c.get("description", "")).lower()) >= 3:
        return "navbar"
    names = " ".join(str(c.get("name", "")) for c in components)
    type_counts = Counter(str(c.get("type", "")).lower() for c in components if c.get("type"))
    repeated = type_counts.most_common(1)[0][1] if type_counts else 0
    if repeated >= 3:  # повторяющиеся карточки
        if re.search(r"[$€£₽]\s*\d|\d+\s*(?:usd|eur|rub|/mo|month)", names, re.I):
            return "pricing"
        if sum(1 for c in components
               if re.search(r"\d[\d\s.,]*[%kK+]|\b\d{2,}\b", str(c.get("name", "")))) >= 2:
            return "stats"

    return "hero"


def _build_navbar_props(components: list, contents: list, icons: list,
                        measurements: dict) -> dict:
    """Собрать navbar props из VLM-структуры и извлечённого контента."""
    logo_text = "Logo"
    links = []
    cta_text = "Sign In"

    for c in components:
        desc = c.get("description", "").lower()
        name = c.get("name", "").lower()
        ctype = c.get("type", "").lower()

        if "logo" in desc or "logo" in name:
            logo_text = c.get("name", "Logo")
        elif ctype == "button" and ("sign" in desc or "login" in desc or "cta" in desc):
            cta_text = c.get("name", "Sign In")
        elif ctype in ("text", "link") or "link" in desc or "nav" in desc:
            links.append({"label": c.get("name", "Link"), "href": "#"})

    if not links:
        links = [{"label": "Home", "href": "#"}]

    return {
        "logoText": logo_text,
        "links": links[:6],
        "cta": {"text": cta_text, "variant": "primary"},
    }


def _build_contact_form_props(components: list) -> dict:
    """contact-form props из VLM-структуры: поля формы и кнопка submit."""
    texts = [str(c.get("name", "")) for c in components
             if c.get("type", "").lower() in ("text", "heading") and c.get("name")]
    fields = []
    for c in components:
        blob = (str(c.get("type", "")) + " " + str(c.get("name", "")) + " "
                + str(c.get("description", ""))).lower()
        if not any(w in blob for w in ("input", "textarea", "checkbox", "field")):
            continue
        name = str(c.get("name") or "").strip()
        input_type = ("textarea" if "textarea" in blob or "message" in blob else
                      "email" if "mail" in blob else
                      "tel" if "phone" in blob or "tel" in blob else "text")
        fields.append({"label": (name or input_type.title())[:60], "inputType": input_type})
    if not fields:
        fields = [{"label": "Email", "inputType": "email"}]
    buttons = [str(c.get("name", "")) for c in components
               if c.get("type", "").lower() == "button" and c.get("name")]
    props = {
        "heading": (texts[0] if texts else "Contact us")[:120],
        "fields": fields[:8],
        "submitText": (buttons[0] if buttons else "Send")[:40],
    }
    if len(texts) > 1:
        props["subheading"] = texts[1][:300]
    return props


def _build_pricing_props(components: list) -> dict:
    """pricing props: повторяющиеся карточки → тарифы с реальными ценами."""
    texts = [str(c.get("name", "")) for c in components
             if c.get("type", "").lower() in ("text", "heading") and c.get("name")]
    cards = [c for c in components
             if c.get("type", "").lower() in ("card", "panel", "tile", "item")] or components[:1]
    tiers = []
    for c in cards[:4]:
        name = str(c.get("name") or "").strip()
        desc = str(c.get("description") or "").strip()
        price = re.search(r"[$€£₽]\s*\d[\d\s.,]*|\d[\d\s.,]*\s*(?:usd|eur|rub|₽)",
                          name + " " + desc, re.I)
        tiers.append({
            "name": (name or f"Plan {len(tiers) + 1}")[:60],
            "price": price.group(0).strip()[:40] if price else "Custom",
            "features": ([desc[:120]] if desc else [(name or "See plan details")[:120]]),
            "cta": "Choose",
        })
    return {"heading": (texts[0] if texts else "Pricing")[:120], "tiers": tiers}


def _build_stats_props(components: list) -> dict:
    """stats props: числовые компоненты → value/label (минимум 2 гарантировано типом)."""
    items = []
    for c in components:
        name = str(c.get("name") or "").strip()
        match = re.search(r"\d[\d\s.,]*[%kK+]|\b\d{2,}\b", name)
        if not match:
            continue
        value = match.group(0).strip()
        label = name.replace(value, "").strip(" -–—:·")[:60]
        items.append({"value": value[:20], "label": label or str(c.get("type") or "metric")[:60]})
        if len(items) >= 6:
            break
    props: dict = {"items": items}
    heading = next((str(c.get("name")) for c in components
                    if c.get("type", "").lower() in ("text", "heading") and c.get("name")
                    and not re.search(r"\d", str(c.get("name")))), "")
    if heading:
        props["heading"] = heading[:120]
    return props


def _build_generic_props(components: list, contents: list, icons: list,
                         measurements: dict) -> dict:
    """Собрать hero props как fallback для произвольной структуры."""
    heading = "Reproduced Component"
    subheading = ""
    texts = [c.get("name", "") for c in components
             if c.get("type", "").lower() in ("text", "heading")]
    if texts:
        heading = texts[0]
        subheading = " ".join(texts[1:3]) if len(texts) > 1 else ""

    buttons = [c.get("name", "Button") for c in components
               if c.get("type", "").lower() == "button"]

    props = {
        "heading": heading[:120],
        "ctaPrimary": {"text": buttons[0] if buttons else "Get Started", "variant": "primary"},
    }
    if subheading:
        props["subheading"] = subheading[:300]
    return props
