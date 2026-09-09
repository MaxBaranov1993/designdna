"""Нода «Изображение»: конвертация, удаление фона и генерация SVG → PNG.

Подписочная модель (Codex / Claude) пишет самодостаточный SVG по промпту,
сервер санитизирует его и рендерит PNG через Playwright. Маршруты
/api/image/convert, /api/image/remove-background, /api/image/generate.
"""
from __future__ import annotations

import base64
import re

from fastapi import APIRouter
from pydantic import BaseModel

import llm_client as llm
from ir_render import render_svg_png
from api.common import err

router = APIRouter()


class ImageGenReq(BaseModel):
    """Нода «Изображение»: SVG от подписочной модели → PNG на сервере."""
    prompt: str = ""
    style: str = "vector"       # vector | texture | icon
    width: int = 1024
    height: int = 1024
    tileable: bool = False
    model: str | None = None
    provider: str = "codex"
    effort: str = "medium"
    prepareOnly: bool = False     # desktop: вернуть промпт вместо LLM-вызова
    rawOutput: str | None = None  # desktop: ответ подключённого аккаунта
    referenceImage: str | None = None  # data:image/… — образец для модели (vision-вход)


class ImageConvertReq(BaseModel):
    image: str
    outputFormat: str = "png"
    requireTransparency: bool = False


class ImageMaskReq(BaseModel):
    image: str
    mask: str


_IMAGE_STYLE_HINTS = {
    "vector": "Flat vector illustration: clean shapes, layered gradients, one consistent light direction, no text unless the prompt asks for it.",
    "texture": "Seamless material texture: build it from <pattern> and <filter> noise (feTurbulence, feDisplacementMap, feDiffuseLighting), subtle lighting, fill the whole canvas edge to edge.",
    "icon": "Single icon on a transparent background: bold silhouette, consistent 2px strokes, centered with 8% padding.",
}


def _extract_svg(raw: str) -> str | None:
    match = re.search(r"<svg[\s\S]*?</svg>", raw or "", re.IGNORECASE)
    return match.group(0) if match else None


def _sanitize_svg(svg: str) -> str:
    """Parse XML, allow static SVG only, and never execute returned markup."""
    import xml.etree.ElementTree as ET
    if len(svg.encode("utf-8")) > 100_000 or re.search(r"<!DOCTYPE|<!ENTITY", svg, re.I):
        raise ValueError("SVG слишком большой или содержит запрещённые объявления")
    root = ET.fromstring(svg)
    local = lambda name: name.rsplit("}", 1)[-1]
    allowed = set("svg g defs title desc path rect circle ellipse line polyline polygon text tspan linearGradient radialGradient stop pattern filter clipPath mask use feTurbulence feDisplacementMap feGaussianBlur feColorMatrix feComposite feDiffuseLighting feSpecularLighting feDistantLight fePointLight feSpotLight feBlend feFlood feMerge feMergeNode feOffset feMorphology feComponentTransfer feFuncR feFuncG feFuncB feFuncA".split())
    if local(root.tag) != "svg":
        raise ValueError("Ожидался SVG")
    for parent in root.iter():
        for child in list(parent):
            if local(child.tag) not in allowed or ("}" in child.tag and not child.tag.startswith("{http://www.w3.org/2000/svg}")):
                parent.remove(child)
        for name, value in list(parent.attrib.items()):
            key = local(name).lower()
            if key.startswith("on") or (key == "href" and not value.startswith("#")) or key == "style":
                del parent.attrib[name]
            elif re.search(r"url\((?!['\"]?#)[^)]*\)", value, re.I):
                del parent.attrib[name]
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="unicode")


@router.post("/api/image/convert")
def image_convert(req: ImageConvertReq):
    from image_output import convert_image
    try:
        return convert_image(req.image, req.outputFormat, req.requireTransparency)
    except ValueError as exc:
        return err(422, str(exc))


@router.post("/api/image/remove-background")
def image_remove_background(req: ImageMaskReq):
    from image_output import apply_background_mask
    try:
        return apply_background_mask(req.image, req.mask)
    except ValueError as exc:
        return err(422, str(exc))


@router.post("/api/image/generate")
def image_generate(req: ImageGenReq):
    """«Изображение»: подписочная модель (Codex / Claude) пишет самодостаточный
    SVG по промпту, сервер санитизирует его и рендерит PNG через Playwright.
    prepareOnly → промпт для аккаунта десктопа; rawOutput → ответ модели."""
    prompt = (req.prompt or "").strip()
    if not prompt:
        return err(422, "Опишите изображение")
    width = max(64, min(2048, int(req.width or 1024)))
    height = max(64, min(2048, int(req.height or 1024)))
    style = req.style if req.style in _IMAGE_STYLE_HINTS else "vector"
    system = (
        "You are a senior graphics engineer who draws with SVG only. Return exactly one self-contained "
        "<svg> document and nothing else: no markdown, no explanations, no code fences.\n"
        f"Canvas: width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\". Fill the whole canvas.\n"
        "Allowed: shapes, paths, linear/radial gradients, <pattern>, <filter> (feTurbulence, feDisplacementMap, "
        "feGaussianBlur, feColorMatrix, feComposite, feDiffuseLighting, feSpecularLighting), <clipPath>, <mask>, transforms. "
        "Forbidden: <script>, <foreignObject>, <image>, external hrefs, web fonts. Keep the document under 40 KB.\n"
        f"Style: {_IMAGE_STYLE_HINTS[style]}"
        + ("\nTileable: the result must tile seamlessly. Build it from a <pattern> that repeats at least twice per axis "
           "or make every edge continue exactly into the opposite edge. No vignette, no centered hero object." if req.tileable else "")
    )
    reference = (req.referenceImage or "").strip()
    if reference and (not reference.startswith("data:image/") or len(reference) > 8_000_000):
        return err(422, "Референс должен быть изображением (data:image/…) до 6 МБ")
    if reference:
        user_content = [
            {"type": "text", "text": prompt + "\n\nA reference image is attached. Reproduce its palette, materials, "
                                        "motif, proportions and level of detail in SVG; do not describe it, draw it."},
            {"type": "image_url", "image_url": {"url": reference, "detail": "high"}},
        ]
    else:
        user_content = prompt
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
    if req.prepareOnly:
        return {"prompts": [{"messages": messages}]}
    provider = req.provider if req.provider in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
    try:
        raw = req.rawOutput if req.rawOutput is not None else llm.chat(
            provider, messages, 0.8, role="graphics", reasoning_effort=effort, model=req.model)
    except Exception as e:
        return err(502, str(e))
    svg = _extract_svg(raw)
    if not svg:
        return err(502, "Модель не вернула SVG — попробуйте переформулировать промпт")
    try:
        svg = _sanitize_svg(svg)
        png = render_svg_png(svg, width, height)
    except Exception as e:
        return err(502, f"Не удалось отрисовать SVG: {e}")
    return {"svg": svg, "png": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            "width": width, "height": height}
