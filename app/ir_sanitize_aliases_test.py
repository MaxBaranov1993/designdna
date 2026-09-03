"""sanitize_generated_ir: алиасы size/tone, которые модель берёт из ролей токенов v2."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ir import sanitize_generated_ir


def _ir(children):
    return {"version": "1.1", "tree": [{"type": "composition", "props": {}, "children": [
        {"type": "frame", "frame": {"layout": "column"}, "children": children},
    ]}]}


def test_type_role_names_map_to_schema_sizes():
    out = sanitize_generated_ir(_ir([
        {"type": "text", "text": "a", "size": "lead"},
        {"type": "text", "text": "b", "size": "eyebrow"},
        {"type": "heading", "text": "c", "size": "hero"},
        {"type": "text", "text": "d", "size": "md"},
    ]))
    kids = out["tree"][0]["children"][0]["children"]
    assert [k["size"] for k in kids] == ["lg", "xs", "display", "md"]


def test_color_role_names_map_to_schema_tones():
    out = sanitize_generated_ir(_ir([
        {"type": "button", "text": "a", "tone": "secondary"},
        {"type": "badge", "text": "b", "tone": "brand"},
        {"type": "badge", "text": "c", "tone": "accent"},
    ]))
    kids = out["tree"][0]["children"][0]["children"]
    assert [k["tone"] for k in kids] == ["muted", "primary", "accent"]
