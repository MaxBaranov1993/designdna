"""Validate generated raster bytes before persisting or downloading them."""
from __future__ import annotations

import base64
import io
import re
import warnings

from PIL import Image, ImageChops, ImageOps

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_777_216


def convert_image(data_url: str, output_format: str = "png", require_transparency: bool = False) -> dict:
    if output_format not in ("png", "jpeg"):
        raise ValueError("Формат должен быть PNG или JPEG")
    if require_transparency and output_format != "png":
        raise ValueError("Для прозрачного фона нужен PNG")
    if not isinstance(data_url, str) or len(data_url) > MAX_BYTES * 4 // 3 + 128:
        raise ValueError("Изображение превышает 20 МБ")
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", data_url)
    if not match:
        raise ValueError("Нужно растровое изображение PNG, JPEG или WebP")
    try:
        raw = base64.b64decode(match[2], validate=True)
        if len(raw) > MAX_BYTES:
            raise ValueError("Изображение превышает 20 МБ")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP") or source.width * source.height > MAX_PIXELS:
                    raise ValueError("Неподдерживаемый формат или слишком большое изображение")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Не удалось прочитать растровое изображение: " + str(exc)) from exc
    low, high = image.getchannel("A").getextrema()
    if require_transparency and (low == 255 or high == 0):
        raise ValueError("GPT не вернул объект на прозрачном фоне. Повторите удаление фона")
    if output_format == "jpeg":
        matte = Image.new("RGB", image.size, "white")
        matte.paste(image, mask=image.getchannel("A"))
        image = matte
    output = io.BytesIO()
    image.save(output, format="PNG" if output_format == "png" else "JPEG", **({"quality": 95} if output_format == "jpeg" else {}))
    return {"png": f"data:image/{output_format};base64," + base64.b64encode(output.getvalue()).decode("ascii"),
            "width": image.width, "height": image.height, "format": output_format,
            "transparent": output_format == "png" and low < 255}


def apply_background_mask(source: str, mask: str) -> dict:
    """GPT supplies geometry only. Original RGB pixels and canvas remain intact."""
    def load_validated(value):
        normalized = convert_image(value)
        return Image.open(io.BytesIO(base64.b64decode(normalized["png"].split(",", 1)[1]))).convert("RGBA")
    original, matte = load_validated(source), load_validated(mask)
    if abs((matte.width / matte.height) / (original.width / original.height) - 1) > 0.05:
        raise ValueError("Маска GPT изменила пропорции исходника. Повторите удаление фона")
    r, g, b, alpha = matte.split()
    if alpha.getextrema()[0] != 255:
        raise ValueError("GPT должен вернуть непрозрачную чёрно-белую маску")
    chroma = ImageChops.lighter(ImageChops.difference(r, g), ImageChops.difference(g, b))
    histogram = chroma.histogram()
    if sum(histogram[16:]) > matte.width * matte.height * 0.01:
        raise ValueError("GPT вернул цветное изображение вместо маски объекта")
    luminance = matte.convert("L")
    low, high = luminance.getextrema()
    if low > 20 or high < 235:
        raise ValueError("Маска GPT должна содержать белый объект и чёрный фон")
    # Remove tiny generative noise in the nominally solid black/white regions.
    luminance = luminance.point(lambda value: 0 if value <= 8 else 255 if value >= 247 else value)
    luminance = luminance.resize(original.size, Image.Resampling.LANCZOS)
    original.putalpha(ImageChops.multiply(original.getchannel("A"), luminance))
    output = io.BytesIO()
    original.save(output, "PNG")
    return convert_image("data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"), require_transparency=True)
