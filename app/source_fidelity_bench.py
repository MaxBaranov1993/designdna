"""Whole-page fidelity bench for Source Import (html.to.design parity check).

Reference: the live page as a person sees it while scrolling (1440 px wide,
animations frozen, lazy content loaded, fixed chrome kept only on the first
screen). Candidate: the Source Import result composed into one page (the same
concatenation the Page node performs) and rendered by the offline engine.

    .venv/Scripts/python app/source_fidelity_bench.py https://rsale.net/ --out artifacts/bench

Writes ref.png, render.png, side.png and metrics.json per site. Similarity is a
coarse structural score per 150 px band (1.0 = identical), good enough to rank
engines and catch misplaced or missing blocks; it is not a WCAG/pixel gate.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

BAND_PX = 150
WIDTH = 1440


def _slug(url: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in url.split("//", 1)[-1]).strip("-")[:60] or "site"


def reference_png(url: str, width: int = WIDTH, height: int = 900, max_height: int = 16000) -> bytes:
    """Scroll-and-stitch screenshot of the live page (no viewport inflation)."""
    from PIL import Image
    from playwright.sync_api import sync_playwright

    import scraper

    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            context, page = scraper._guarded_browser_page(browser, {"width": width, "height": height})
            scraper._goto_resilient(page, url, 45000)
            scraper._wait_capture_settle(page)
            page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}"
                                       "html{scroll-behavior:auto!important}")
            scraper._dismiss_cookie_overlays(page)
            import source_snapshot
            source_snapshot.preload_lazy_content(page, height)
            unused = source_snapshot.unused_web_fonts(page)
            if unused:
                source_snapshot.activate_web_fonts(page, unused)
            total = min(max_height, int(page.evaluate("() => document.documentElement.scrollHeight")))
            canvas = Image.new("RGB", (width, total), "white")
            y = 0
            first = True
            while y < total:
                page.evaluate("(y) => window.scrollTo(0, y)", y)
                page.wait_for_timeout(120)
                actual = int(page.evaluate("() => Math.round(window.scrollY)"))
                shot = Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")
                canvas.paste(shot, (0, actual))
                if first:
                    # fixed/sticky chrome belongs to the first screen only
                    page.evaluate("""() => document.querySelectorAll('body *').forEach(el => {
                      const p = getComputedStyle(el).position;
                      if (p === 'fixed' || p === 'sticky') el.style.setProperty('visibility', 'hidden', 'important');
                    })""")
                    first = False
                if actual + height >= total:
                    break
                y = actual + height
            out = io.BytesIO()
            canvas.save(out, format="PNG")
            return out.getvalue()
        finally:
            browser.close()


def compose_page(blocks: list[dict], tokens: dict | None = None) -> dict:
    """Python mirror of frontend composePage: sections stacked in document order."""
    tree: list[dict] = []
    faces: dict[str, dict] = {}
    for block in blocks:
        ir = block.get("ir") if isinstance(block.get("ir"), dict) else None
        if not ir:
            continue
        for face in ((ir.get("meta") or {}).get("fontFaces") or []):
            if isinstance(face, dict):
                faces[json.dumps(face, sort_keys=True)] = face
        for section in ir.get("tree") or []:
            if not isinstance(section, dict):
                continue
            s = copy.deepcopy(section)
            frame = dict(s.get("frame") or {})
            for key in ("x", "y", "absolute"):
                frame.pop(key, None)
            frame["width"] = "fill"
            s["frame"] = frame
            tree.append(s)
    return {
        "version": "1.1",
        "meta": {"name": "Bench page", **({"fontFaces": list(faces.values())} if faces else {})},
        "frame": {"width": WIDTH, "height": "hug", "layout": "auto", "direction": "column"},
        "tokens": copy.deepcopy(tokens or {}),
        "tree": tree,
    }


def similarity(ref_png: bytes, got_png: bytes) -> dict:
    import numpy as np
    from PIL import Image, ImageFilter

    ref = Image.open(io.BytesIO(ref_png)).convert("L")
    got = Image.open(io.BytesIO(got_png)).convert("L")
    if got.width != ref.width:
        got = got.resize((ref.width, max(1, round(got.height * ref.width / got.width))))
    height = min(ref.height, got.height)
    scale = 0.5
    a = np.asarray(ref.crop((0, 0, ref.width, height)).resize((int(ref.width * scale), int(height * scale)))
                   .filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32)
    b = np.asarray(got.crop((0, 0, got.width, height)).resize((int(ref.width * scale), int(height * scale)))
                   .filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32)
    band = int(BAND_PX * scale)
    bands = []
    for top in range(0, a.shape[0], band):
        diff = np.abs(a[top:top + band] - b[top:top + band]).mean() / 255.0
        bands.append(round(1.0 - float(diff), 3))
    return {
        "overall": round(float(np.mean(bands)) if bands else 0.0, 3),
        "worstBands": sorted(((round(i * BAND_PX), v) for i, v in enumerate(bands)), key=lambda x: x[1])[:5],
        "refHeight": ref.height,
        "renderHeight": got.height,
        "heightRatio": round(got.height / max(1, ref.height), 3),
        "bands": bands,
    }


def side_by_side(ref_png: bytes, got_png: bytes, column: int = 600) -> bytes:
    from PIL import Image, ImageDraw

    ref = Image.open(io.BytesIO(ref_png)).convert("RGB")
    got = Image.open(io.BytesIO(got_png)).convert("RGB")
    ref = ref.resize((column, max(1, round(ref.height * column / ref.width))))
    got = got.resize((column, max(1, round(got.height * column / got.width))))
    canvas = Image.new("RGB", (column * 2 + 24, max(ref.height, got.height) + 28), (24, 24, 28))
    canvas.paste(ref, (0, 28))
    canvas.paste(got, (column + 24, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), "live site", fill=(230, 230, 230))
    draw.text((column + 32, 8), "DesignDNA Source", fill=(230, 230, 230))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def run(url: str, out_dir: Path, engine: str = "snapshot") -> dict:
    import blockparse
    import ir_render

    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = blockparse.parse_blocks(url, viewports=[{"name": "desktop", "width": WIDTH, "height": 900}],
                                     engine=engine)
    capture_s = time.perf_counter() - started
    blocks = [b for b in result.get("blocks") or [] if isinstance(b, dict) and b.get("ir") and not b.get("error")]
    from source_page_layout import compose_source_page
    page_ir = compose_source_page(blocks, result.get("tokens")) if engine == "snapshot" else compose_page(blocks, result.get("tokens"))
    (out_dir / "page-ir.json").write_text(json.dumps(page_ir, ensure_ascii=False), encoding="utf-8")
    render = ir_render.render_png(page_ir, width=WIDTH)
    ref = reference_png(url)
    (out_dir / "ref.png").write_bytes(ref)
    (out_dir / "render.png").write_bytes(render)
    (out_dir / "side.png").write_bytes(side_by_side(ref, render))
    metrics = {
        "url": url,
        "engine": engine,
        "captureSeconds": round(capture_s, 1),
        "blocks": [{"name": b.get("name"), "kind": b.get("kind"), "pageY": ((b.get("ir") or {}).get("meta") or {}).get("pageRect", {}).get("y")}
                   for b in blocks],
        "errors": [b.get("name") for b in result.get("blocks") or [] if isinstance(b, dict) and b.get("error")],
        "similarity": similarity(ref, render),
    }
    metrics["similarity"].pop("bands", None)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--out", default="artifacts/source-bench")
    parser.add_argument("--engine", default="snapshot", choices=["snapshot", "legacy"])
    args = parser.parse_args(argv)
    os.environ.setdefault("DESIGNDNA_DATA_DIR", str(Path(args.out).resolve() / "data"))
    for url in args.urls:
        metrics = run(url, Path(args.out) / args.engine / _slug(url), args.engine)
        sim = metrics["similarity"]
        print(f"{url} [{args.engine}] capture {metrics['captureSeconds']}s · blocks {len(metrics['blocks'])} "
              f"· errors {len(metrics['errors'])} · similarity {sim['overall']} · height x{sim['heightRatio']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
