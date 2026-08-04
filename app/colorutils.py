"""Конвертация sRGB <-> OKLab/OKLCH и взвешенный микс цветов.

Формулы публичные (Bjorn Ottosson, https://bottosson.github.io/posts/oklab/).
Только stdlib.
"""
import math


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
