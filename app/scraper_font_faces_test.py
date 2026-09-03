"""_resolve_font_faces: используемые веса не срезаются лимитом faces."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scraper


def _faces() -> list[dict]:
    faces = []
    for weight in (400, 500, 600, 700):
        for subset in ("latin-ext", "latin"):
            faces.append({"family": "Hanken Grotesk", "weight": str(weight), "style": "normal",
                          "unicodeRange": subset, "urls": [f"https://x/hanken-{subset}.woff2"]})
    for weight in (400, 500, 600):
        for subset in ("latin-ext", "latin"):
            faces.append({"family": "JetBrains Mono", "weight": str(weight), "style": "normal",
                          "unicodeRange": subset, "urls": [f"https://x/mono-{subset}.woff2"]})
    return faces


def test_used_weights_survive_and_all_declared_faces_are_kept(monkeypatch):
    monkeypatch.setattr(scraper, "_download_font", lambda url: b"font-" + url.encode())
    monkeypatch.setattr(scraper, "_store_font", lambda data: "f-" + str(abs(hash(data)))[:8] + ".woff2")
    used = {"hanken grotesk", "jetbrains mono"}
    used_weights = {"hanken grotesk": {400, 700}, "jetbrains mono": {500}}
    out = scraper._resolve_font_faces(_faces(), used, used_weights, download_cache={})
    mono = [(f["weight"], f["unicodeRange"]) for f in out if f["family"] == "JetBrains Mono"]
    assert ("500", "latin") in mono and ("500", "latin-ext") in mono
    # используемые веса идут первыми
    assert out[0]["weight"] in ("400", "700", "500")
    assert len(out) == 14  # ничего не срезано старым лимитом 12
