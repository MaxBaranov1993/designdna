"""Style DNA endpoints repair legacy responsive viewport metadata before validation."""
from __future__ import annotations

from fastapi.testclient import TestClient

from server import app


def document() -> dict:
    return {
        "version": "1.1",
        "frame": {"width": 1440, "height": 900},
        "responsive": {"viewports": {
            "desktop": {"width": 1440},
            "tablet": {"width": 768},
            "mobile": {"width": 390},
        }},
        "tokens": {
            "mode": "light",
            "color": {"primary": "#5b5bd6", "background": "#ffffff", "surface": "#f5f5f7", "text": "#111111", "textMuted": "#666666", "border": "#dddddd"},
            "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"},
            "radius": {"card": "md", "button": "md", "input": "md"},
            "spacing": {"section": "md", "container": "default"},
            "shadow": "sm",
        },
        "tree": [{
            "id": "source-hero", "type": "source-block", "variant": "dom-capture", "props": {},
            "frame": {"width": "fill", "height": 320, "layout": "free", "padding": 0},
            "children": [],
        }],
    }


def main() -> None:
    source = document()
    with TestClient(app) as client:
        extracted = client.post("/api/style-dna/extract", json={"ir": source})
        assert extracted.status_code == 200, extracted.text
        applied = client.post("/api/style-dna/apply", json={
            "ir": source, "tokens": extracted.json()["tokens"],
        })
        assert applied.status_code == 200, applied.text
        viewports = applied.json()["ir"]["responsive"]["viewports"]
        assert [viewports[name]["height"] for name in ("desktop", "tablet", "mobile")] == [900, 1024, 844]
    print("ALL STYLE DNA ENDPOINT CHECKS PASSED")


if __name__ == "__main__":
    main()
