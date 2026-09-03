"""Конвертация sRGB <-> OKLab/OKLCH и взвешенный микс цветов.

Формулы публичные (Bjorn Ottosson, https://bottosson.github.io/posts/oklab/).
Только stdlib.
"""
import math


WCAG_AA = 4.5


def hex_to_srgb(hex_color: str) -> tuple:
    """'#rrggbb' или '#rgb' -> (r, g, b) в 0..1."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_hex(rgb: tuple) -> str:
    def chan(v: float) -> str:
        return f"{max(0, min(255, round(v * 255))):02x}"
    return "#" + "".join(chan(c) for c in rgb)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_oklab(rgb: tuple) -> tuple:
    r, g, b = (_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return (L, a, b2)


def oklab_to_srgb(lab: tuple) -> tuple:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = (v ** 3 for v in (l_, m_, s_))
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b2 = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return (_gamma(r), _gamma(g), _gamma(b2))


def srgb_to_oklch(rgb: tuple) -> tuple:
    L, a, b = srgb_to_oklab(rgb)
    C = math.hypot(a, b)
    H = math.degrees(math.atan2(b, a)) % 360.0
    return (L, C, H)


def oklch_to_srgb(lch: tuple) -> tuple:
    L, C, H = lch
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    return oklab_to_srgb((L, a, b))


def mix_hex_colors(pairs: list) -> str:
    """pairs: [(hex, weight), ...] -> hex. Интерполяция в OKLCH.

    Веса нормализуются; при всех нулевых весах — равные доли.
    Hue интерполируется по кратчайшей дуге; при C~0 (нейтральный цвет)
    hue берётся от доминантного хроматичного цвета.
    """
    if not pairs:
        raise ValueError("пустой список цветов")
    total = sum(w for _, w in pairs)
    if total <= 0:
        weights = [1.0 / len(pairs)] * len(pairs)
    else:
        weights = [w / total for _, w in pairs]

    lchs = [srgb_to_oklch(hex_to_srgb(h)) for h, _ in pairs]

    # Hue: разворачиваем углы вокруг hue доминантного хроматичного цвета
    ref_idx = max(range(len(pairs)), key=lambda i: lchs[i][1] * weights[i] + 1e-9)
    ref_h = lchs[ref_idx][2]
    L = C = H = 0.0
    for (Li, Ci, Hi), w in zip(lchs, weights):
        d = (Hi - ref_h + 180.0) % 360.0 - 180.0
        L += Li * w
        C += Ci * w
        H += (ref_h + d) * w
    rgb = oklch_to_srgb((L, C, H % 360.0))
    return srgb_to_hex(rgb)


def _in_gamut(rgb: tuple) -> bool:
    return all(0.0 <= channel <= 1.0 for channel in rgb)


def oklch_to_hex(lch: tuple) -> str:
    """Convert OKLCH to displayable sRGB, reducing chroma instead of clipping."""
    lightness, chroma, hue = lch
    if not 0.0 <= lightness <= 1.0 or chroma < 0.0:
        raise ValueError("OKLCH lightness must be in 0..1 and chroma must be non-negative")
    hue %= 360.0
    rgb = oklch_to_srgb((lightness, chroma, hue))
    if _in_gamut(rgb):
        return srgb_to_hex(rgb)
    low, high = 0.0, chroma
    for _ in range(24):
        candidate = (low + high) / 2.0
        if _in_gamut(oklch_to_srgb((lightness, candidate, hue))):
            low = candidate
        else:
            high = candidate
    return srgb_to_hex(oklch_to_srgb((lightness, low, hue)))


def relative_luminance(hex_color: str) -> float:
    r, g, b = (_linear(channel) for channel in hex_to_srgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    light, dark = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


TEXT_BACKGROUND_PAIRS = tuple(
    (text, background)
    for text in ("ink", "ink2", "inkMuted")
    for background in ("bg", "bg2", "surface", "surface2")
) + (("accentInk", "accent"), ("accentInk", "accent2"))


def validate_palette_contrast(palette: dict, minimum: float = WCAG_AA) -> list[dict]:
    """Return every text/background pair below WCAG AA (or missing)."""
    failures = []
    for foreground_key, background_key in TEXT_BACKGROUND_PAIRS:
        foreground = palette.get(foreground_key)
        background = palette.get(background_key)
        if not isinstance(foreground, str) or not isinstance(background, str):
            failures.append({"foreground": foreground_key, "background": background_key,
                             "ratio": 0.0, "reason": "missing color"})
            continue
        ratio = contrast_ratio(foreground, background)
        if ratio + 1e-9 < minimum:
            failures.append({"foreground": foreground_key, "background": background_key,
                             "ratio": ratio, "reason": f"below {minimum:g}"})
    return failures


def _seed_component(component: dict, name: str, *, max_chroma: float) -> tuple[float, float, float]:
    if not isinstance(component, dict):
        raise ValueError(f"palette seed {name} must be an object")
    try:
        lightness = float(component["lightness"])
        chroma = float(component["chroma"])
        hue = float(component["hue"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"palette seed {name} requires numeric lightness/chroma/hue") from exc
    if not 0.0 <= lightness <= 1.0 or not 0.0 <= chroma <= max_chroma or not 0.0 <= hue <= 360.0:
        raise ValueError(f"palette seed {name} is outside its OKLCH range")
    return lightness, chroma, hue


def _accessible_color(backgrounds: list[str], preferred_l: float, chroma: float, hue: float) -> str:
    """Nearest OKLCH tone to ``preferred_l`` that passes against every background."""
    def passes(lightness: float) -> tuple[bool, str]:
        color = oklch_to_hex((lightness, chroma, hue))
        return (min(contrast_ratio(color, background) for background in backgrounds)
                + 1e-9 >= WCAG_AA, color)

    valid, color = passes(preferred_l)
    if valid:
        return color
    endpoint = 1.0 if preferred_l >= 0.5 else 0.0
    valid, best = passes(endpoint)
    if not valid:
        raise ValueError("no shared WCAG AA text color exists for the backgrounds")
    inaccessible, accessible = preferred_l, endpoint
    for _ in range(24):
        midpoint = (inaccessible + accessible) / 2.0
        valid, color = passes(midpoint)
        if valid:
            accessible, best = midpoint, color
        else:
            inaccessible = midpoint
    return best


def generate_tonal_palette(seed: dict) -> dict[str, str]:
    """Derive tokens.v2 colors from a compact OKLCH seed.

    ``accent.hues`` carries one or two hues; its shared lightness and chroma
    make the accents tonally related by construction.  Text colors are chosen
    against the complete background family and verified before returning.
    """
    background = _seed_component(seed.get("background"), "background", max_chroma=0.08)
    accent = seed.get("accent")
    if not isinstance(accent, dict):
        raise ValueError("palette seed accent must be an object")
    try:
        accent_lightness = float(accent["lightness"])
        accent_chroma = float(accent["chroma"])
        hues = [float(value) for value in accent["hues"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("palette seed accent requires lightness/chroma/hues") from exc
    if (not 0.0 <= accent_lightness <= 1.0 or not 0.02 <= accent_chroma <= 0.4
            or len(hues) not in (1, 2) or any(not 0.0 <= hue <= 360.0 for hue in hues)):
        raise ValueError("palette seed accent is outside its OKLCH range")

    bg_l, bg_c, bg_h = background
    # Move supporting surfaces away from the mid-tone contrast danger zone.
    base_background = oklch_to_hex(background)
    direction = (-1.0 if contrast_ratio("#ffffff", base_background)
                 >= contrast_ratio("#000000", base_background) else 1.0)
    levels = (bg_l, bg_l + direction * 0.035, bg_l + direction * 0.065,
              bg_l + direction * 0.10)
    levels = tuple(max(0.015, min(0.985, value)) for value in levels)
    backgrounds = {
        key: oklch_to_hex((level, bg_c * factor, bg_h))
        for key, level, factor in zip(
            ("bg", "bg2", "surface", "surface2"), levels, (1.0, 0.8, 0.65, 0.5)
        )
    }
    background_colors = list(backgrounds.values())
    black_floor = min(contrast_ratio("#000000", color) for color in background_colors)
    white_floor = min(contrast_ratio("#ffffff", color) for color in background_colors)
    light_text = white_floor >= black_floor
    text_lightness = (0.98, 0.92, 0.82) if light_text else (0.05, 0.12, 0.22)
    text = {
        key: _accessible_color(background_colors, lightness, min(bg_c, 0.025), bg_h)
        for key, lightness in zip(("ink", "ink2", "inkMuted"), text_lightness)
    }
    accent_color = oklch_to_hex((accent_lightness, accent_chroma, hues[0]))
    accent2_color = oklch_to_hex((accent_lightness, accent_chroma,
                                  hues[1] if len(hues) == 2 else (hues[0] + 150.0) % 360.0))
    accent_backgrounds = [accent_color, accent2_color]
    accent_ink = _accessible_color(
        accent_backgrounds,
        0.98 if min(contrast_ratio("#ffffff", color) for color in accent_backgrounds)
        >= min(contrast_ratio("#000000", color) for color in accent_backgrounds) else 0.02,
        0.0, 0.0,
    )
    palette = {
        **backgrounds, **text,
        "line": oklch_to_hex((max(0.08, min(0.92, bg_l - direction * 0.20)),
                               min(bg_c, 0.035), bg_h)),
        "accent": accent_color, "accentInk": accent_ink, "accent2": accent2_color,
    }
    failures = validate_palette_contrast(palette)
    if failures:
        pairs = ", ".join(f"{item['foreground']}/{item['background']}" for item in failures)
        raise ValueError(f"generated palette failed WCAG AA: {pairs}")
    return palette
