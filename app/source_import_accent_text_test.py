"""Акцентный текст внутри заголовка: свечение и градиентная заливка глифов.

Регрессия из реального импорта: подсвеченное слово («finds your buyers»)
приезжало обычным белым текстом — спан сливался с заголовком, text-shadow
не захватывался вовсе, а градиент через background-clip:text срезался
как «фон контейнера».
"""
from __future__ import annotations

import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import scraper  # noqa: E402
from scraper import capture_block_irs  # noqa: E402

SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK " if ok else "FAIL ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def capture() -> dict:
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        live, _tokens = capture_block_irs(
            f"http://127.0.0.1:{server.server_port}/source_import_accent_text.html",
            [{"name": "hero", "label": "Hero", "kind": "section", "selector": "#accent-hero"}],
            return_tokens=True, timeout_ms=30000,
        )
    finally:
        scraper.validate_public_url = original
        server.shutdown()
        server.server_close()
    return live["#accent-hero"]


def main() -> None:
    captured = capture()
    check("accent fixture captures", "ir" in captured, str(captured.get("error")))
    if "ir" not in captured:
        sys.exit(1)
    ir = captured["ir"]
    jsonschema.Draft7Validator(SCHEMA).validate(ir)
    nodes = [node for node, _parent in scraper._walk_source_nodes(ir["tree"][0]["children"])]

    def text_of(node: dict) -> str:
        return str(node.get("text") or "")

    glow = next((n for n in nodes if "finds your buyers" in text_of(n)), None)
    check("glowing accent word survives as its own layer", glow is not None,
          json.dumps([text_of(n) for n in nodes if text_of(n)], ensure_ascii=False))
    if glow:
        style = glow.get("style") or {}
        check("accent keeps its own colour, not the heading colour",
              str(style.get("color", "")).lower() == "#a78bfa", json.dumps(style))
        check("text-shadow glow is captured",
              "textShadow" in style and "rgba" in str(style["textShadow"]).lower(),
              json.dumps(style))

    gradient = next((n for n in nodes if "Gradient headline" in text_of(n)), None)
    check("gradient headline survives as its own layer", gradient is not None)
    if gradient:
        style = gradient.get("style") or {}
        check("background-clip:text is preserved", style.get("backgroundClip") == "text",
              json.dumps(style))
        check("the gradient itself is preserved",
              "linear-gradient" in str(style.get("backgroundImage") or ""), json.dumps(style))
        # Градиент глифов не должен превращаться в прямоугольную подложку.
        siblings = [n for n in nodes if n.get("type") == "rect"
                    and "linear-gradient" in str((n.get("style") or {}).get("backgroundImage") or "")]
        check("gradient text does not spawn a background rectangle", not siblings,
              json.dumps([n.get("sourceKey") for n in siblings]))

    plain = next((n for n in nodes if "Plain supporting copy" in text_of(n)), None)
    check("plain copy is untouched by the accent path",
          plain is not None and "textShadow" not in (plain.get("style") or {}))

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL ACCENT TEXT CHECKS PASSED")


if __name__ == "__main__":
    main()
