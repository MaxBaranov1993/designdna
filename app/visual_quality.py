"""Rendered desktop/mobile acceptance capture for generated Design IR."""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path


QUALITY_RENDER_URL = os.environ.get(
    "QUALITY_RENDER_URL", "http://127.0.0.1:8420/static/flow/quality-render.html"
)
ENGINE_BUNDLE = Path(__file__).resolve().parent / "static" / "flow" / "engine.js"


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _montage(desktop: bytes, mobile: bytes) -> bytes:
    from PIL import Image, ImageDraw

    desk = Image.open(io.BytesIO(desktop)).convert("RGB")
    mob = Image.open(io.BytesIO(mobile)).convert("RGB")
    max_height = 1100
    if desk.height > max_height:
        desk.thumbnail((desk.width, max_height))
    if mob.height > max_height:
        mob.thumbnail((mob.width, max_height))
    gap = 32
    header = 56
    canvas = Image.new("RGB", (desk.width + mob.width + gap, max(desk.height, mob.height) + header), "#eceef2")
    canvas.paste(desk, (0, header))
    canvas.paste(mob, (desk.width + gap, header))
    draw = ImageDraw.Draw(canvas)
    draw.text((16, 18), "DESKTOP 1440", fill="#111827")
    draw.text((desk.width + gap + 16, 18), "MOBILE 390", fill="#111827")
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _measure(page) -> dict:
    data = page.evaluate("""() => {
      const root = document.querySelector('#quality-root');
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      const textNodes = [...root.querySelectorAll('h1,h2,h3,h4,p,span,button,a,label')].filter(visible);
      const controls = [...root.querySelectorAll('button,a,input,select,textarea')].filter(visible);
      const sections = [...root.querySelectorAll('[data-ir-sec]')].filter(visible);
      return {
        overflowX: Math.max(0, root.scrollWidth - root.clientWidth, document.documentElement.scrollWidth - innerWidth),
        emptySections: sections.filter((el) => !(el.textContent || '').trim() && !el.querySelector('img,svg,button,input')).length,
        missingAlt: [...root.querySelectorAll('img')].filter((el) => !el.hasAttribute('alt')).length,
        missingDimensions: [...root.querySelectorAll('img')].filter((el) => !el.hasAttribute('width') || !el.hasAttribute('height')).length,
        tinyText: textNodes.filter((el) => parseFloat(getComputedStyle(el).fontSize) < 12).length,
        smallTargets: controls.filter((el) => { const r = el.getBoundingClientRect(); return r.width < 24 || r.height < 24; }).length,
        unlabeledForms: [...root.querySelectorAll('input,select,textarea')].filter((el) => !el.labels?.length && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')).length,
        placeholderAssets: root.querySelectorAll('.img-ph,.asset-loading').length,
        sections: sections.length,
        images: root.querySelectorAll('img').length,
        controls: controls.length,
      };
    }""")
    focus_failures = 0
    seen = set()
    for _ in range(min(int(data.get("controls", 0)) + 2, 40)):
        page.keyboard.press("Tab")
        state = page.evaluate("""() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const s = getComputedStyle(el);
          return {key: el.tagName + '|' + (el.getAttribute('data-ir-path') || '') + '|' + (el.textContent || '').slice(0,40),
                  visible: s.outlineStyle !== 'none' && s.outlineWidth !== '0px' || s.boxShadow !== 'none'};
        }""")
        if not state or state["key"] in seen:
            continue
        seen.add(state["key"])
        if not state["visible"]:
            focus_failures += 1
    data["missingFocus"] = focus_failures
    return data


def capture_quality_bundle(ir: dict, render_url: str = QUALITY_RENDER_URL) -> dict:
    """Render the same IR at 1440 and 390, returning screenshots and DOM metrics."""
    from playwright.sync_api import sync_playwright

    shots: dict[str, bytes] = {}
    metrics: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for viewport, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.route("http*", lambda route: route.abort())
                page.set_content("<!doctype html><html><body style='margin:0'><main id='quality-root' style='width:100%;min-height:100vh;overflow:hidden'></main></body></html>")
                page.add_script_tag(path=str(ENGINE_BUNDLE))
                page.evaluate("""async ([ir, viewport]) => {
                  const root = document.querySelector('#quality-root');
                  window.IRRenderer.renderIR(root, ir, { viewport });
                  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
                  await Promise.race([document.fonts.ready, wait(800)]);
                  const images = Promise.all([...root.querySelectorAll('img')].map(img => img.complete
                    ? Promise.resolve()
                    : new Promise(resolve => { img.addEventListener('load', resolve, {once:true}); img.addEventListener('error', resolve, {once:true}); })));
                  await Promise.race([images, wait(800)]);
                }""", [ir, viewport])
                page.wait_for_timeout(80)
                metrics[viewport] = _measure(page)
                root = page.locator("#quality-root")
                shots[viewport] = root.screenshot(type="png", animations="disabled", caret="hide")
                page.close()
        finally:
            browser.close()
    montage = _montage(shots["desktop"], shots["mobile"])
    return {
        "screenshots": {name: _data_url(raw) for name, raw in shots.items()},
        "montage": _data_url(montage),
        "metrics": metrics,
    }
