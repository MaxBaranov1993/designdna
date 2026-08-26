from __future__ import annotations

import base64
import io

from PIL import Image

import blockparse
import scraper


def test_current_capture_tokens_keep_brand_colors() -> None:
    captured = {
        "mode": "light",
        "color": {
            "primary": "#f97316", "secondary": "#f97316", "accent": "#7c3aed",
            "background": "#ffffff", "surface": "#ffffff", "text": "#171717",
            "textMuted": "#666666", "border": "#d1d5db",
        },
        "font": {
            "display": {"family": "Inter", "weight": 700},
            "body": {"family": "Inter", "weight": 400}, "scale": "default",
        },
        "radius": {"card": "lg", "button": "md", "input": "md"},
        "spacing": {"section": "lg", "container": "default"},
        "shadow": "none",
    }

    result = blockparse._normalize_captured_page_tokens(captured, "https://example.com")

    assert result["color"]["primary"] == "#f97316"
    assert result["color"]["accent"] == "#7c3aed"
    assert result is not captured


def test_legacy_dom_signals_are_still_supported() -> None:
    result = blockparse._normalize_captured_page_tokens({
        "bodyBg": "#ffffff",
        "bodyColor": "#171717",
        "buttonBg": "#f97316",
        "linkColor": "#7c3aed",
    }, "https://example.com")

    assert result["color"]["primary"] == "#f97316"
    assert result["color"]["accent"] == "#7c3aed"


def test_public_fidelity_report_keeps_evidence_without_diagnostic_bloat() -> None:
    report = {
        "provenance": {"fingerprint": "abc", "assets": ["one"]},
        "gate": {"passed": True, "reasons": []},
        "viewports": {"desktop": {
            "pixel_similarity": 99.4,
            "bbox_p95": 0.5,
            "grid_origin_error": 0,
            "paint_coverage": 100,
            "unexplained_losses": 0,
            "region_diffs": [{"region": [0, 0], "mismatch_pct": 0.1}],
            "artifacts": {"reference": "C:/private/reference.png"},
        }},
        "components": {"card:1": {
            "sourceKey": "card:1",
            "label": "Service card",
            "role": "card",
            "provenance": {"fingerprint": "abc", "assets": ["repeated"]},
            "gate": {"passed": True, "reasons": []},
            "viewports": {"desktop": {
                "pixel_similarity": 98.2,
                "bbox_p95": 0.75,
                "grid_origin_error": 0,
                "paint_coverage": 100,
                "unexplained_losses": 0,
                "region_diffs": [{"region": [0, 0], "mismatch_pct": 0.2}],
                "artifacts": {"diff": "C:/private/diff.png"},
            }},
        }},
    }

    public = blockparse._public_fidelity_report(report)

    assert public["provenance"] == report["provenance"]
    assert public["components"]["card:1"]["label"] == "Service card"
    assert "provenance" not in public["components"]["card:1"]
    assert "region_diffs" not in public["viewports"]["desktop"]
    assert "artifacts" not in public["components"]["card:1"]["viewports"]["desktop"]


def test_full_resolution_preview_is_a_lossless_content_addressed_blob(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    image = Image.new("RGBA", (1232, 421), (112, 24, 230, 255))
    image.putpixel((1231, 420), (255, 105, 29, 127))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")

    ref = blockparse._full_resolution_preview(uri)

    digest = scraper.parse_blob_ref(ref)
    assert digest is not None
    stored = scraper.read_png_blob(digest)
    with Image.open(io.BytesIO(stored)) as restored:
        assert restored.size == (1232, 421)
        assert restored.convert("RGBA").getpixel((0, 0)) == (112, 24, 230, 255)
        assert restored.convert("RGBA").getpixel((1231, 420)) == (255, 105, 29, 127)
