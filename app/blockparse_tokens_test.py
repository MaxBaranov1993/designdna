from __future__ import annotations

import blockparse


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
