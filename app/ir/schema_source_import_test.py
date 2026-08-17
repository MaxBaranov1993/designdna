import json
import copy
from pathlib import Path

from app.ir.validate import validate_ir


def test_source_import_metadata_is_part_of_design_ir_contract() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "frame-example.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["meta"].update({
        "qaWarnings": ["qa: flow drift at root -> layout free, pinned 2 children"],
        "fontFaces": [
            {
                "family": "Fixture Serif",
                "weight": "400",
                "style": "normal",
                "url": "/fonts/fixture-serif.woff2",
            }
        ],
    })

    assert validate_ir(document) == []


def test_source_import_font_faces_reject_css_and_remote_urls() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "frame-example.json"
    base = json.loads(fixture.read_text(encoding="utf-8"))
    valid_face = {
        "family": "Fixture Serif",
        "weight": "400",
        "style": "normal",
        "url": "/fonts/fixture-serif.woff2",
    }
    malicious_values = [
        ("family", "Fixture';src:url(https://example.invalid/x)"),
        ("weight", "400;src:url(https://example.invalid/x)"),
        ("style", "normal;display:block"),
        ("url", "https://example.invalid/font.woff2"),
        ("url", "/fonts/../secret.woff2"),
        ("url", "/fonts/font.woff2?cache=1"),
    ]

    for key, value in malicious_values:
        document = copy.deepcopy(base)
        face = {**valid_face, key: value}
        document["meta"]["fontFaces"] = [face]
        assert validate_ir(document), f"unsafe font face unexpectedly accepted: {key}={value!r}"
