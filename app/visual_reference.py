"""Explicit image-reference roles; visual evidence never becomes output IR."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field
from config.settings import app_dir
from image_output import convert_image


class VisualReference(BaseModel):
    image: str = Field(max_length=28_000_000)
    role: Literal["style", "composition", "reproduce"] = "style"
    origin: str = Field(default="", max_length=300)
    conceptOnly: bool = False
    notes: str = Field(default="", max_length=2000)


def prepare(reference: VisualReference | None) -> dict | None:
    if reference is None:
        return None
    if reference.conceptOnly and reference.role != "composition":
        raise ValueError("Эскиз может задавать только композицию")
    converted = convert_image(reference.image)
    raw = base64.b64decode(converted["png"].split(",", 1)[1])
    info = {"role": reference.role, "origin": reference.origin, "notes": reference.notes, "conceptOnly": reference.conceptOnly,
            "sha256": hashlib.sha256(raw).hexdigest(), "width": converted["width"], "height": converted["height"]}
    instructions = (app_dir() / "prompts" / f"visual-reference-{reference.role}.md").read_text(encoding="utf-8")
    return {"info": info, "instruction": instructions + "\nReference metadata: " + json.dumps(info, ensure_ascii=False),
            "part": {"type": "image_url", "image_url": {"url": converted["png"]}}}


def policy_fingerprint() -> str:
    contents = [(app_dir() / "prompts" / f"visual-reference-{role}.md").read_text(encoding="utf-8")
                for role in ("style", "composition", "reproduce")]
    return hashlib.sha256("\n".join(contents).encode()).hexdigest()


def concept_used_in_output(ir: dict, visual: dict | None) -> bool:
    if not visual or not (visual["info"]["conceptOnly"] or visual["info"]["role"] == "composition"):
        return False
    from asset_quality import image_identity
    expected = visual["info"]["sha256"]
    def walk(value):
        if isinstance(value, str):
            return image_identity(value) == expected
        if isinstance(value, dict):
            return any(walk(child) for child in value.values())
        return isinstance(value, list) and any(walk(child) for child in value)
    return walk(ir.get("tree") or [])


def concept_prompt(brief: str, tokens: dict | None, design_system: dict | None, notes: str = "", reference_role: str = "style") -> str:
    foundations = tokens or {}
    if design_system:
        from design_system import store
        document, error = store.resolve_ref(design_system)
        if error:
            raise ValueError(str(error))
        foundations = (document.get("styleGuide") or {}).get("tokens") or document.get("foundations") or foundations
    template = (app_dir() / "prompts" / "visual-concept.md").read_text(encoding="utf-8")
    return template.format(brief=brief[:12000], foundations=json.dumps(foundations, ensure_ascii=False)[:12000], notes=notes, reference_role=reference_role)
