from __future__ import annotations

import pytest

import colorutils


@pytest.mark.parametrize(
    "seed",
    [
        {"background": {"lightness": 0.97, "chroma": 0.01, "hue": 85},
         "accent": {"lightness": 0.62, "chroma": 0.18, "hues": [35, 210]}},
        {"background": {"lightness": 0.08, "chroma": 0.025, "hue": 260},
         "accent": {"lightness": 0.72, "chroma": 0.2, "hues": [145]}},
    ],
)
def test_tonal_palette_passes_every_declared_wcag_pair(seed: dict) -> None:
    palette = colorutils.generate_tonal_palette(seed)
    assert set(palette) == {
        "bg", "bg2", "surface", "surface2", "ink", "ink2", "inkMuted",
        "line", "accent", "accentInk", "accent2",
    }
    assert colorutils.validate_palette_contrast(palette) == []
    for foreground, background in colorutils.TEXT_BACKGROUND_PAIRS:
        assert colorutils.contrast_ratio(palette[foreground], palette[background]) >= 4.5


def test_single_accent_hue_deterministically_derives_second_accent() -> None:
    seed = {"background": {"lightness": 0.96, "chroma": 0.01, "hue": 60},
            "accent": {"lightness": 0.6, "chroma": 0.15, "hues": [20]}}
    assert colorutils.generate_tonal_palette(seed) == colorutils.generate_tonal_palette(seed)
    assert colorutils.generate_tonal_palette(seed)["accent"] != colorutils.generate_tonal_palette(seed)["accent2"]


def test_invalid_accent_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        colorutils.generate_tonal_palette({
            "background": {"lightness": 0.96, "chroma": 0.01, "hue": 60},
            "accent": {"lightness": 0.6, "chroma": 0.15, "hues": []},
        })
