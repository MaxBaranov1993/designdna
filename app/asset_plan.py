"""Versioned image-slot plans. Only declared, empty, editable consumers may change."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import tempfile
from config.settings import app_dir, blobs_dir
from image_output import convert_image

VERSION = "design-assets/1.0"
MAX_SLOTS = 64


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _size(node: dict) -> tuple[int, int]:
    frame = node.get("frame") or {}
    def dim(value, fallback):
        return max(64, min(2048, round(value))) if isinstance(value, (float, int)) and value > 0 else fallback
    width = dim(frame.get("width"), 1024)
    height = dim(frame.get("height"), 1024)
    aspect = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", str(node.get("aspect") or ""))
    if aspect and float(aspect[1]) > 0 and float(aspect[2]) > 0 and not frame.get("height"):
        height = dim(width * float(aspect[2]) / float(aspect[1]), 1024)
    return width, height


def slots(ir: dict, replace: bool = False) -> list[dict]:
    found = []
    def visit(node, path, locked=False, master=False, parent_type=""):
        if not isinstance(node, dict):
            return
        meta = node.get("sourceMeta") or {}
        constraints = node.get("constraints") or {}
        locks = constraints.get("intentLocks") or []
        locked = locked or node.get("editable") is False or node.get("type") == "source-block" or node.get("variant") == "dom-capture" \
            or bool(set(locks) & {"content", "brand", "source-link"})
        master = master or bool(node.get("componentRef") or meta.get("componentRef") or node.get("_dsMaster"))
        is_image = node.get("type") == "image" or parent_type in ("gallery", "feature-alternating")
        if is_image and isinstance(node.get("imagePrompt"), str) and node["imagePrompt"].strip() and (not node.get("src") or replace):
            # A missing src field is not a declared content slot in an exact master.
            if not locked and (not master or (not node.get("src") and isinstance(node.get("src"), str))):
                width, height = _size(node)
                found.append({"path": path, "targetHash": digest(node), "subject": node["imagePrompt"].strip(),
                              "operation": "replace" if node.get("src") else "fill",
                              "width": width, "height": height, "sourceKey": node.get("sourceKey"),
                              "requiresAlpha": bool(re.search(r"transparent background|прозрачн\w* фон", node["imagePrompt"], re.I))})
        media = (node.get("props") or {}).get("media")
        if node.get("type") == "hero" and isinstance(media, dict):
            visit({**media, "type": "image"}, path + ["props", "media"], locked, master)
            if found and found[-1]["path"] == path + ["props", "media"]:
                found[-1]["targetHash"] = digest(media)
        for index, child in enumerate(node.get("children") or []):
            visit(child, path + ["children", index], locked, master, str(node.get("type") or ""))
    root_master = bool((ir.get("meta") or {}).get("_dsMaster"))
    for index, node in enumerate(ir.get("tree") or []):
        visit(node, ["tree", index], master=root_master)
    return found


def prepare(variants: list[dict], context: dict | None = None) -> dict:
    context = context or {}
    plan = {"schemaVersion": VERSION, "inputHash": digest(variants), "context": copy.deepcopy(context), "slots": []}
    template = (app_dir() / "prompts" / "asset-image.md").read_text(encoding="utf-8")
    for variant, ir in enumerate(variants):
        visual = {"tokens": ir.get("tokens"), "direction": (ir.get("meta") or {}).get("direction"),
                  "brief": str(context.get("brief") or "")[:2000]}
        for slot in slots(ir, replace=context.get("replaceImages") is True):
            slot.update(id=f"v{variant}-" + digest(slot["path"])[:16], variant=variant,
                        status="planned", attempts=0)
            if re.fullmatch(r"[a-f0-9]{64}", str(context.get("conceptHash") or "")):
                slot["forbiddenImageHashes"] = [context["conceptHash"]]
            slot["prompt"] = template.format(subject=slot["subject"], width=slot["width"], height=slot["height"],
                                            context=json.dumps(visual, ensure_ascii=False)[:5000],
                                            alpha="yes" if slot["requiresAlpha"] else "no")
            plan["slots"].append(slot)
    if len(plan["slots"]) > MAX_SLOTS:
        raise ValueError(f"В одном плане поддерживается до {MAX_SLOTS} изображений; разделите композицию")
    return plan


def _at(ir: dict, path: list):
    value = ir
    for part in path:
        value = value[part]
    return value


def store_image(image: str, requires_alpha: bool = False) -> dict:
    result = convert_image(image, "png", requires_alpha)
    raw = base64.b64decode(result.pop("png").split(",", 1)[1])
    sha = hashlib.sha256(raw).hexdigest()
    folder = blobs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{sha}.png"
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        fd, temporary = tempfile.mkstemp(prefix="asset-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {**result, "src": f"ddna://blobs/{sha}.png", "sha256": sha}


def apply(ir: dict, slot: dict, image: str) -> dict:
    # Re-derive the permission from current IR; a caller cannot invent a path or unlock a source.
    candidate = next((item for item in slots(ir, replace=slot.get("operation") == "replace") if item["path"] == slot.get("path")), None)
    if not candidate or candidate["targetHash"] != slot.get("targetHash"):
        raise ValueError("Место изображения изменилось или защищено; обновите план ресурсов")
    result = store_image(image, candidate["requiresAlpha"])
    if result["sha256"] in (slot.get("forbiddenImageHashes") or []):
        raise ValueError("Эскиз нельзя использовать как готовое изображение; нужен отдельный ресурс")
    updated = copy.deepcopy(ir)
    _at(updated, candidate["path"])["src"] = result["src"]
    return {"ir": updated, "result": result}


def reconcile(ir: dict, completed: list[dict]) -> dict:
    """Restore canonical blob references after the desktop transport expanded them for QA."""
    updated = copy.deepcopy(ir)
    missing = []
    for slot in completed:
        result = slot.get("result") or {}
        sha = str(result.get("sha256") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            continue
        expected = f"ddna://blobs/{sha}.png"
        try:
            target = _at(updated, slot["path"])
            src = target.get("src")
            if isinstance(src, str) and src.startswith("data:image/png;base64,"):
                raw = base64.b64decode(src.split(",", 1)[1], validate=True)
                if hashlib.sha256(raw).hexdigest() == sha:
                    target["src"] = expected
                    src = expected
            blob = blobs_dir() / f"{sha}.png"
            if src != expected or not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest() != sha:
                missing.append(slot.get("id"))
        except (KeyError, IndexError, TypeError, ValueError):
            missing.append(slot.get("id"))
    return {"ir": updated, "missing": missing}
