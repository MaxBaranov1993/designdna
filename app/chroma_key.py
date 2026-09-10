"""Local color key for deliberately uniform backgrounds. No model or network calls."""
from __future__ import annotations

import base64
import io
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from image_output import convert_image


def remove_chroma(image: str, color: str = "#00ff00", tolerance: int = 32,
                  softness: int = 24, despill: bool = True) -> dict:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color or ""):
        raise ValueError("Укажите цвет фона в формате #RRGGBB")
    if not 0 <= tolerance <= 160 or not 1 <= softness <= 100:
        raise ValueError("Допуск: 0–160, мягкость: 1–100")
    validated = convert_image(image)
    original = Image.open(io.BytesIO(base64.b64decode(validated["png"].split(",", 1)[1]))).convert("RGBA")
    # Float arrays are bounded more tightly than the normal image converter.
    if original.width * original.height > 4_194_304:
        raise ValueError("Для локального удаления фона используйте изображение до 4 мегапикселей")
    pixels = np.array(original)
    rgb = pixels[:, :, :3].astype(np.float32)
    key = np.array([int(color[index:index + 2], 16) for index in (1, 3, 5)], dtype=np.float32)
    distance = np.max(np.abs(rgb - key), axis=2)
    # Only remove matching regions connected to a canvas edge. Matching colors
    # enclosed inside the subject retain their opacity and original RGB.
    candidate = Image.fromarray((distance <= tolerance + softness).astype(np.uint8) * 255)
    canvas = Image.new("L", (original.width + 2, original.height + 2), 255)
    canvas.paste(candidate, (1, 1))
    ImageDraw.floodfill(canvas, (0, 0), 128, thresh=0)
    connected = np.array(canvas.crop((1, 1, original.width + 1, original.height + 1))) == 128
    amount = np.clip((distance - tolerance) / softness, 0, 1)
    amount[~connected] = 1
    alpha = np.rint(pixels[:, :, 3] * amount).astype(np.uint8)
    if not np.any((pixels[:, :, 3] > 0) & (alpha < pixels[:, :, 3])):
        raise ValueError("Выбранный цвет не найден у края. Уточните цвет или допуск")
    if not np.any(alpha > 0):
        raise ValueError("Маска удаляет всё изображение. Уменьшите допуск или выберите другой цвет")
    if despill:
        # Unmix the chosen key color only on the partially keyed boundary.
        edge = connected & (amount > 0) & (amount < 1)
        correction = (rgb[edge] - key * (1 - amount[edge, None])) / amount[edge, None]
        pixels[:, :, :3][edge] = np.clip(np.rint(correction), 0, 255).astype(np.uint8)
    pixels[:, :, 3] = alpha

    def encode(value: Image.Image) -> str:
        output = io.BytesIO()
        value.save(output, "PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    result = convert_image(encode(Image.fromarray(pixels)), require_transparency=True)
    mask = Image.fromarray(alpha)
    result.update(mask=encode(mask.convert("RGB")), edge=encode(mask.filter(ImageFilter.FIND_EDGES).convert("RGB")),
                  method="chroma", keyColor=color, tolerance=tolerance, softness=softness, despill=despill)
    return result
