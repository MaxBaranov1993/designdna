"""Deterministic resource evidence. Pixel aesthetics and editor interaction stay unknown."""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import re

from config.settings import blobs_dir
from image_output import convert_image


def image_consumers(ir: dict):
    def walk(node, path, parent_type=""):
        if not isinstance(node, dict):
            return
        if node.get("type") == "image" or parent_type in {"gallery", "feature-alternating"}:
            yield path, node
        media = (node.get("props") or {}).get("media")
        if node.get("type") == "hero" and isinstance(media, dict):
            yield path + ".props.media", media
        for index, child in enumerate(node.get("children") or []):
            yield from walk(child, f"{path}.children.{index}", node.get("type"))
    for index, node in enumerate(ir.get("tree") or []):
        yield from walk(node, f"tree.{index}")


def image_identity(src: str) -> str:
    match = re.fullmatch(r"ddna://blobs/([a-f0-9]{64})\.(png|jpeg|jpg|webp)", src)
    if match:
        return match[1]
    if src.startswith("data:image/"):
        try:
            return hashlib.sha256(base64.b64decode(src.split(",", 1)[1], validate=True)).hexdigest()
        except (ValueError, IndexError):
            pass
    return src


def preserves_resources(before: dict, after: dict) -> bool:
    def images(ir):
        return Counter(image_identity(node["src"]) for _, node in image_consumers(ir) if isinstance(node.get("src"), str) and node["src"])
    return not (images(before) - images(after))


def audit(ir: dict) -> dict:
    images, errors, warnings = [], [], []
    for path, node in image_consumers(ir):
        src = node.get("src")
        item = {"path": path, "status": "unknown"}
        if not src:
            item["status"] = "fail"
            errors.append({"path": path, "problem": "Изображение не заполнено"})
        elif isinstance(src, str):
            try:
                data = src
                if src.startswith("ddna://blobs/"):
                    match = re.fullmatch(r"ddna://blobs/([a-f0-9]{64})\.(png|jpeg|jpg|webp|svg|gif)", src)
                    if not match:
                        raise ValueError("Некорректная ссылка на ресурс")
                    raw = (blobs_dir() / src.rsplit("/", 1)[1]).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != match[1]:
                        raise ValueError("Файл ресурса повреждён")
                    mime = {"jpg": "jpeg", "svg": "svg+xml"}.get(match[2], match[2])
                    data = "data:image/" + mime + ";base64," + base64.b64encode(raw).decode()
                if data.startswith(("data:image/png;", "data:image/jpeg;", "data:image/webp;")):
                    alpha = bool(re.search(r"transparent background|прозрачн\w* фон", str(node.get("imagePrompt") or ""), re.I))
                    validated = convert_image(data, require_transparency=alpha)
                    validated.pop("png")
                    item.update(validated, status="pass")
                    frame = node.get("frame") or {}
                    if any(isinstance(frame.get(key), (float, int)) and frame[key] > validated[key] * 1.5 for key in ("width", "height")):
                        warnings.append({"path": path, "problem": "Разрешение изображения меньше его размера в макете"})
            except (ValueError, OSError) as exc:
                item["status"] = "fail"
                errors.append({"path": path, "problem": str(exc)})
        images.append(item)
    def text_count(node):
        if not isinstance(node, dict):
            return 0
        props = node.get("props") or {}
        own = int(isinstance(node.get("text"), str) and bool(node["text"].strip()))
        own += sum(isinstance(props.get(key), str) and bool(props[key].strip()) for key in ("heading", "title", "text", "subheading", "label"))
        return own + sum(text_count(child) for child in node.get("children") or [])
    return {"status": "fail" if errors else "unknown" if any(item["status"] == "unknown" for item in images) else "pass",
            "images": images, "errors": errors, "warnings": warnings,
            "nativeTextCount": sum(text_count(node) for node in ir.get("tree") or []),
            "checks": {"pixelContent": "unknown", "editUndo": "unknown", "exportReopen": "unknown"}}
