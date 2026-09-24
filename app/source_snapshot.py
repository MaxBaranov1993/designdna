"""Snapshot capture engine for Source Import (html.to.design-style).

One navigation, one lazy-content pass, geometry-based page segmentation and a
single in-page compile of every section in absolute mode. Reference pixels come
from CDP viewport tiles (no element "stability" waits, no viewport inflation).

The engine plugs into ``scraper.capture_block_irs(engine="snapshot")`` and
produces the same capture items as the legacy per-block path, plus the
section's document rectangle (``pageRect``) so the Page node can put sections
back exactly where they were on the site.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from typing import Callable

# Lazy-content pass: scroll the whole document in viewport steps so
# IntersectionObserver/lazy images/reveal-on-scroll content materialize once,
# then return to the top. Bounded in steps and wall time.
PRELOAD_JS = """async ({step, maxSteps, pauseMs, budgetMs}) => {
  const started = performance.now();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let steps = 0, y = 0;
  while (steps < maxSteps && performance.now() - started < budgetMs) {
    const height = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
    if (y >= height - innerHeight) break;
    y = Math.min(height - innerHeight, y + step);
    window.scrollTo(0, y);
    steps += 1;
    await sleep(pauseMs);
  }
  const pending = [...document.images].filter((img) => !img.complete && img.loading !== 'lazy');
  await Promise.race([
    Promise.all(pending.slice(0, 200).map((img) => new Promise((resolve) => {
      img.addEventListener('load', resolve, {once: true});
      img.addEventListener('error', resolve, {once: true});
    }))),
    sleep(Math.max(0, Math.min(2500, budgetMs - (performance.now() - started)))),
  ]);
  window.scrollTo(0, 0);
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {steps, height: document.documentElement.scrollHeight, ms: Math.round(performance.now() - started)};
}"""

# Geometry-based segmentation. Page sections are the visible children of the
# content root (single full-page wrappers are descended), tall vertical stacks
# (main/wrappers) are split into their stacked children, and top chrome
# (fixed/sticky header) is its own section. Floating widgets are ignored.
SEGMENT_JS = """({maxBlocks}) => {
  const vw = innerWidth, vh = innerHeight;
  const docH = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','LINK','META','BR']);
  const cs = (el) => getComputedStyle(el);
  const pr = (el) => { const r = el.getBoundingClientRect(); return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; };
  const vis = (el) => {
    if (SKIP.has(el.tagName)) return false;
    const s = cs(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  };
  const painted = (el) => {
    const s = cs(el);
    return s.backgroundImage !== 'none' || !/^(rgba\\(0, 0, 0, 0\\)|transparent)$/.test(s.backgroundColor)
      || parseFloat(s.borderTopWidth) > 0 || parseFloat(s.borderBottomWidth) > 0 || s.boxShadow !== 'none';
  };
  const hasContent = (el) => (el.innerText || '').trim().length > 0
    || !!el.querySelector('img,svg,video,canvas,picture,iframe,input,button,textarea,select') || painted(el);
  // display:contents wrappers have no box: their children belong to the parent.
  const kids = (el) => [...el.children].flatMap((child) => cs(child).display === 'contents' ? kids(child) : [child]).filter(vis);
  const position = (el) => cs(el).position;
  const topChrome = (el) => {
    const p = position(el);
    if (p !== 'fixed' && p !== 'sticky') return false;
    const r = el.getBoundingClientRect();
    return r.top <= 4 && r.width >= vw * 0.6 && r.height <= Math.max(180, vh * 0.3);
  };
  const floating = (el) => position(el) === 'fixed' && !topChrome(el);
  const stacked = (list) => {
    const sorted = [...list].sort((a, b) => pr(a).y - pr(b).y);
    for (let i = 1; i < sorted.length; i++) {
      const a = pr(sorted[i - 1]), b = pr(sorted[i]);
      if (b.y < a.y + a.h * 0.5) return false;   // side by side → a row, not sections
    }
    return true;
  };
  let root = document.body;
  for (let depth = 0; depth < 15; depth++) {
    const list = kids(root).filter((el) => !floating(el));
    const big = list.filter((el) => pr(el).h >= docH * 0.5);
    if (list.length === 1 && big.length === 1) { root = list[0]; continue; }
    if (big.length === 1 && list.length <= 4 && kids(big[0]).length >= 2
        && list.every((el) => el === big[0] || (pr(el).h < 80 && !topChrome(el)))) { root = big[0]; continue; }
    break;
  }
  const out = [];
  const contentW = Math.max(1, pr(root).w);
  const isBand = (rect, parent) => rect.w >= Math.min(contentW, parent.w) * 0.85;
  const offscreen = (rect) => rect.x + rect.w <= 1 || rect.x >= vw - 1;
  const consider = (el, depth, split) => {
    const r = pr(el);
    if (r.h < 8 || offscreen(r) || !hasContent(el) || floating(el)) return;
    const list = kids(el).filter((child) => !floating(child));
    const semanticLeaf = /^(HEADER|FOOTER|NAV)$/.test(el.tagName) || topChrome(el);
    if (split && depth < 6 && !semanticLeaf && (el.tagName === 'MAIN' || r.h > vh * 1.2)) {
      const significant = list.filter((child) => { const c = pr(child); return c.h >= 24 && !offscreen(c); });
      const bands = significant.filter((child) => isBand(pr(child), r));
      const covered = bands.reduce((sum, child) => sum + pr(child).h, 0);
      // Split only a vertical stack of full-width bands; a row of columns stays one section.
      if (bands.length >= 1 && bands.length === significant.length && stacked(bands) && covered >= r.h * 0.6
          && (bands.length >= 2 || (bands.length === 1 && pr(bands[0]).h >= r.h * 0.85))) {
        list.forEach((child) => consider(child, depth + 1, split));
        return;
      }
    }
    out.push(el);
  };
  const collect = (split) => { out.length = 0; kids(root).forEach((el) => consider(el, 0, split)); };
  collect(true);
  if (out.length > maxBlocks) collect(false);
  const path = (el) => {
    const parts = [];
    let node = el;
    while (node && node !== document.body && node.parentElement) {
      const index = [...node.parentElement.children].indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}:nth-child(${index})`);
      node = node.parentElement;
    }
    return 'body > ' + parts.join(' > ');
  };
  const heading = (el) => {
    const h = el.querySelector('h1,h2,h3,[role=heading]');
    return (h ? h.innerText : (el.innerText || '')).trim().replace(/\\s+/g, ' ').slice(0, 80);
  };
  const blocks = out.slice(0, maxBlocks).map((el, index) => {
    const r = pr(el);
    const selector = path(el);
    return {
      selector: document.querySelector(selector) === el ? selector : null,
      tag: el.tagName.toLowerCase(),
      html: el.outerHTML.length <= 400000 ? el.outerHTML : el.outerHTML.slice(0, 400000),
      id: el.id || '',
      cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').slice(0, 120),
      heading: heading(el),
      hasH1: !!el.querySelector('h1'),
      hasNav: !!(el.tagName === 'NAV' || el.querySelector('nav') || el.querySelectorAll('a').length >= 4 && r.h < 200),
      topChrome: topChrome(el),
      rect: {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.w), height: Math.round(r.h)},
      index,
    };
  }).filter((b) => b.selector);
  // Page background behind every section: the first painted of body/html.
  const pageBackground = (() => {
    for (const el of [document.body, document.documentElement]) {
      if (!el) continue;
      const s = cs(el);
      const color = /^(rgba\\(0, 0, 0, 0\\)|transparent)$/.test(s.backgroundColor) ? '' : s.backgroundColor;
      if (s.backgroundImage !== 'none' && !/url\\(/.test(s.backgroundImage)) return [s.backgroundImage, color].filter(Boolean).join(', ');
      if (color) return color;
    }
    return '#ffffff';
  })();
  return {blocks, total: out.length, docHeight: docH, root: root.tagName.toLowerCase(), pageBackground};
}"""

# Document rectangles for sections and their raster requests (one round trip).
RECTS_JS = """(specs) => specs.map(({selector, children}) => {
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const base = {x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height};
  const kids = {};
  for (const sub of children || []) {
    const node = sub ? el.querySelector(sub) : null;
    if (!node) continue;
    const c = node.getBoundingClientRect();
    kids[sub] = {x: c.left - r.left, y: c.top - r.top, width: c.width, height: c.height};
  }
  return {rect: base, children: kids};
})"""

FOREIGN_CHROME_JS = """({selector, hide}) => {
  // fixed/sticky elements are collected once per viewport (full-DOM style scan is expensive)
  if (!window.__ddnaChrome) {
    window.__ddnaChrome = [...document.querySelectorAll('body *')].filter((el) => {
      const p = getComputedStyle(el).position; return p === 'fixed' || p === 'sticky';
    });
  }
  const own = selector ? document.querySelector(selector) : null;
  if (!hide) {
    for (const el of window.__ddnaChrome) {
      if (!('ddnaHiddenChrome' in el.dataset)) continue;
      el.style.removeProperty('visibility');
      if (el.dataset.ddnaHiddenChrome) el.style.visibility = el.dataset.ddnaHiddenChrome;
      delete el.dataset.ddnaHiddenChrome;
    }
    return 0;
  }
  let hidden = 0;
  for (const el of window.__ddnaChrome) {
    if (!el.isConnected) continue;
    if (own && (own === el || own.contains(el) || el.contains(own))) continue;
    el.dataset.ddnaHiddenChrome = el.style.visibility || '';
    el.style.setProperty('visibility', 'hidden', 'important');
    hidden += 1;
  }
  return hidden;
}"""

CHILDREN_VISIBILITY_JS = """({selector, hide}) => {
  const el = document.querySelector(selector);
  if (!el) return false;
  for (const child of el.children) {
    if (hide) { child.dataset.ddnaPrevVisibility = child.style.visibility || ''; child.style.setProperty('visibility', 'hidden', 'important'); }
    else { child.style.removeProperty('visibility'); if (child.dataset.ddnaPrevVisibility) child.style.visibility = child.dataset.ddnaPrevVisibility; delete child.dataset.ddnaPrevVisibility; }
  }
  return true;
}"""

IMAGES_SETTLE_JS = """(budgetMs) => Promise.race([
  Promise.all([...document.images].map((img) => img.complete && img.naturalWidth > 0
    ? (img.decode ? img.decode().catch(() => {}) : Promise.resolve())
    : new Promise((resolve) => { img.addEventListener('load', resolve, {once: true}); img.addEventListener('error', resolve, {once: true}); })))
    .then(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))),
  new Promise((resolve) => setTimeout(resolve, budgetMs)),
])"""

# Web fonts that are downloaded but not applied (font-display: optional/fallback
# timed out on first paint). The page then renders with fallback metrics while
# the IR would carry the real font: geometry and glyphs disagree. A loaded face
# is "unused" when text set in it measures exactly like the generic fallback.
UNUSED_WEB_FONTS_JS = """() => {
  const sample = 'mmmWWWlli0123 ГЖЯфщ';
  const width = (family) => { const s = document.createElement('span'); s.textContent = sample;
    s.style.cssText = 'position:absolute;left:-99999px;top:0;white-space:nowrap;font-size:40px;font-family:' + family;
    document.body.appendChild(s); const w = s.getBoundingClientRect().width; s.remove(); return w; };
  const out = new Set();
  for (const face of document.fonts) {
    const family = String(face.family || '').replace(/["']/g, '').trim();
    if (!family || /fallback/i.test(family) || face.status !== 'loaded') continue;
    const quoted = '"' + family.replace(/"/g, '') + '"';
    if (Math.abs(width(quoted + ', monospace') - width('monospace')) < 0.5
        && Math.abs(width(quoted + ', serif') - width('serif')) < 0.5) out.add(family);
  }
  return [...out];
}"""


# Re-register the page's own @font-face rules for unapplied families with
# font-display: block and wait for them, so layout uses the designed typography.
ACTIVATE_WEB_FONTS_JS = r"""async (families) => {
  const wanted = new Set(families.map((f) => f.toLowerCase()));
  const rules = [];
  const walk = (list) => { for (const r of Array.from(list || [])) {
    if (r.cssRules && r.cssRules.length) { try { walk(r.cssRules); } catch (e) {} continue; }
    if (r instanceof CSSFontFaceRule) rules.push(r);
  } };
  for (const s of document.styleSheets) { try { walk(s.cssRules); } catch (e) {} }
  const added = [];
  for (const r of rules) {
    const family = r.style.getPropertyValue('font-family').replace(/["']/g, '').trim();
    if (!wanted.has(family.toLowerCase())) continue;
    const base = r.parentStyleSheet && r.parentStyleSheet.href || document.baseURI;
    const src = r.style.getPropertyValue('src').replace(/url\((['"]?)([^'")]+)\1\)/g, (m, q, u) => { try { return `url("${new URL(u, base).href}")`; } catch (e) { return m; } });
    const descriptors = {display: 'block'};
    for (const [prop, key] of [['font-weight', 'weight'], ['font-style', 'style'], ['font-stretch', 'stretch'], ['unicode-range', 'unicodeRange']]) {
      const v = r.style.getPropertyValue(prop); if (v) descriptors[key] = v;
    }
    try { const face = new FontFace(family, src, descriptors); await Promise.race([face.load(), new Promise((_, j) => setTimeout(() => j(new Error('timeout')), 8000))]); document.fonts.add(face); added.push(family); } catch (e) {}
  }
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return added;
}"""


def activate_web_fonts(page, families: list[str]) -> list[str]:
    try:
        return [str(name) for name in (page.evaluate(ACTIVATE_WEB_FONTS_JS, families) or [])]
    except Exception:
        return []

def unused_web_fonts(page) -> list[str]:
    try:
        return [str(name) for name in (page.evaluate(UNUSED_WEB_FONTS_JS) or [])]
    except Exception:
        return []


_BLOCK_ALL = ["http://*", "https://*", "ws://*", "wss://*", "ftp://*"]


def freeze_network(context, cdp) -> bool:
    """Block every network request inside Chromium, then drop the Python route guard.

    The per-request SSRF guard is a Python callback; while the capture thread
    is busy with screenshots/PIL, page requests (analytics, lazy media) queue
    behind it, pages stall and ``browser.close()`` waits for the whole queue
    (97 s on glebkudr.com in the desktop worker). A browser-level block list
    keeps the guarantee — nothing leaves the browser — without callbacks.
    """
    try:
        cdp.send("Network.enable")
        cdp.send("Network.setBlockedURLs", {"urls": _BLOCK_ALL})
    except Exception:
        return False
    try:
        context.unroute_all(behavior="ignoreErrors")
    except Exception:
        try:
            context.unroute("**/*")
        except Exception:
            pass
    return True


def thaw_network(context, cdp, install_guard: Callable) -> None:
    """Re-install the SSRF route guard before lifting the browser block list."""
    install_guard(context)
    try:
        cdp.send("Network.setBlockedURLs", {"urls": []})
    except Exception:
        pass


MAX_TILES = 40


def preload_lazy_content(page, viewport_h: int, budget_ms: int = 20_000) -> dict:
    try:
        return page.evaluate(PRELOAD_JS, {"step": max(200, int(viewport_h * 0.85)), "maxSteps": 80,
                                          "pauseMs": 90, "budgetMs": budget_ms}) or {}
    except Exception:
        try:
            page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass
        return {}


def block_name(block: dict, index: int, count: int, used: set[str]) -> tuple[str, str, str]:
    """(name, kind, label): kind is a schema role from the semantic classifier."""
    tag = block.get("tag") or ""
    rect = block.get("rect") or {}
    kind, label = "section", ""
    try:
        from bs4 import BeautifulSoup
        import scraper
        soup = BeautifulSoup(block.get("html") or "", "lxml")
        element = soup.find(tag) or (soup.body.find() if soup.body else None)
        if element is not None:
            kind = scraper._semantic_role(element) or "section"
            label = scraper._block_label(element, kind) or ""
    except Exception:
        kind = "section"
    if index == 0 and (tag in ("header", "nav") or block.get("topChrome") or
                       (block.get("hasNav") and float(rect.get("height") or 0) <= 200)):
        kind = "header"
    elif tag == "footer" or (index == count - 1 and kind == "footer"):
        kind = "footer"
    elif kind in ("header", "footer"):
        kind = "section"
    if kind == "section" and block.get("hasH1") and index <= 2:
        base = "hero"
    elif kind != "section":
        base = kind
    else:
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", block.get("heading") or "")
        slug = re.sub(r"[^a-z0-9-]", "", _translit("-".join(words[:3]).lower()))[:32].strip("-")
        base = slug or "section"
    name, n = base, 2
    while name in used:
        name = f"{base}-{n}"
        n += 1
    used.add(name)
    return name, kind, label or (block.get("heading") or name)[:80]


_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                     ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                      "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _translit(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def segment_page(cdp, evaluate_bounded: Callable, max_blocks: int) -> list[dict]:
    result = evaluate_bounded(cdp, SEGMENT_JS, {"maxBlocks": max_blocks}, 20_000) or {}
    raw = [b for b in result.get("blocks") or [] if isinstance(b, dict) and b.get("selector")]
    raw.sort(key=lambda b: ((b.get("rect") or {}).get("y", 0), (b.get("rect") or {}).get("x", 0)))
    used: set[str] = set()
    blocks = []
    for index, item in enumerate(raw):
        name, kind, label = block_name(item, index, len(raw), used)
        blocks.append({
            "name": name, "kind": kind, "label": label[:80],
            "selector": item["selector"], "tag": item.get("tag"), "heading": item.get("heading") or "",
            "pageRect": item.get("rect"), "segmentation": "geometry", "topChrome": bool(item.get("topChrome")),
            "pageBackground": str(result.get("pageBackground") or "#ffffff")[:4096],
        })
    if int(result.get("total") or 0) > len(blocks) and blocks:
        blocks[-1]["truncatedAfter"] = int(result["total"]) - len(blocks)
    print(json.dumps({"event": "source_snapshot.segment", "blocks": len(blocks), "root": result.get("root"),
                      "docHeight": result.get("docHeight")}, ensure_ascii=False), flush=True)
    return blocks


def _scroll_to(page, y: float) -> float:
    return float(page.evaluate("(y) => { window.scrollTo(0, y); return window.scrollY; }", y))


def _capture_clip(cdp, x: float, y: float, width: float, height: float):
    from PIL import Image

    shot = cdp.send("Page.captureScreenshot", {"format": "png", "optimizeForSpeed": True, "clip": {
        "x": x, "y": y, "width": width, "height": height, "scale": 1}})
    return Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")


def _region_image(page, cdp, top: float, height: float, viewport: dict):
    """Full-width stitched image of the document band [top, top+height) (CSS px)."""
    from PIL import Image

    vw, vh = int(viewport["width"]), int(viewport["height"])
    top = max(0.0, float(top))
    height = max(1, int(round(float(height))))
    canvas = Image.new("RGB", (vw, height), "white")
    offset = 0
    tiles = 0
    while offset < height and tiles < MAX_TILES:
        want_top = top + offset
        scroll_y = _scroll_to(page, want_top)
        chunk_top = max(want_top, scroll_y)
        chunk_h = min(height - offset, scroll_y + vh - chunk_top)
        if chunk_h <= 0:
            break
        canvas.paste(_capture_clip(cdp, 0, chunk_top, vw, chunk_h), (0, int(round(chunk_top - top))))
        offset = int(round(chunk_top - top + chunk_h))
        tiles += 1
    return canvas


def _png_from(image, box: dict, origin_y: float = 0.0) -> bytes | None:
    x, y = max(0, int(round(float(box["x"])))), max(0, int(round(float(box["y"]) - origin_y)))
    w, h = int(round(float(box["width"]))), int(round(float(box["height"])))
    if w < 1 or h < 1 or x >= image.width or y >= image.height:
        return None
    out = io.BytesIO()
    image.crop((x, y, min(image.width, x + w), min(image.height, y + h))).save(out, format="PNG", compress_level=1)
    return out.getvalue()


def _tile_png(page, cdp, rect: dict, viewport: dict) -> bytes:
    """Stitch viewport tiles of a document rectangle into one PNG (CSS px)."""
    band = _region_image(page, cdp, float(rect["y"]), float(rect["height"]), viewport)
    return _png_from(band, {**rect, "y": 0}) or b""


def _crop_png(png: bytes, box: dict) -> bytes | None:
    from PIL import Image

    image = Image.open(io.BytesIO(png))
    x, y = max(0, int(round(box["x"]))), max(0, int(round(box["y"])))
    w, h = int(round(box["width"])), int(round(box["height"]))
    if w < 1 or h < 1 or x >= image.width or y >= image.height:
        return None
    out = io.BytesIO()
    image.crop((x, y, min(image.width, x + w), min(image.height, y + h))).save(out, format="PNG")
    return out.getvalue()


def capture_viewport(page, cdp, blocks: list[dict], viewport: dict, compiler_js: str, *,
                     evaluate_bounded: Callable, materialize: Callable, store_png: Callable,
                     namespace: Callable, find_node: Callable, report: Callable[[int, int], None],
                     timings: dict | None = None) -> dict[str, dict]:
    """Compile and capture every section of one viewport; returns {selector: item}."""
    started = time.perf_counter()
    timings = timings if timings is not None else {}
    prefix = "snap" + str(viewport.get("name") or "")[:1].upper() + str(viewport.get("name") or "")[1:]
    clock = [started]

    def lap(name: str) -> None:
        now = time.perf_counter()
        timings[prefix + name] = timings.get(prefix + name, 0) + round((now - clock[0]) * 1000)
        clock[0] = now
    compile_specs = [{"name": b["name"], "selector": b["selector"], "absolute": True} for b in blocks]
    page.evaluate("() => window.scrollTo(0, 0)")
    raw = evaluate_bounded(cdp, compiler_js, compile_specs, 180_000) or []
    compiled_ms = round((time.perf_counter() - started) * 1000)
    lap("Compile")
    items = {entry.get("selector"): entry for entry in raw if isinstance(entry, dict)}
    by_selector: dict[str, dict] = {}
    # Materialize raster bytes in the live DOM first so reference tiles and IR replay share them.
    for block in blocks:
        item = items.get(block["selector"])
        if item and not item.get("error"):
            try:
                item["assets"] = materialize(page, item, block["selector"])
            except Exception:
                item["assets"] = []
    lap("Materialize")
    try:
        page.evaluate(IMAGES_SETTLE_JS, 2000)
    except Exception:
        pass
    lap("ImageSettle")
    page.evaluate("() => { window.__ddnaChrome = null; }")
    specs = [{"selector": b["selector"], "children": [str(req.get("selector") or "")
                                                     for req in (items.get(b["selector"]) or {}).get("rasterRequests") or []
                                                     if req.get("mode") != "backdrop" and req.get("selector")]}
             for b in blocks]
    rects = page.evaluate(RECTS_JS, specs)
    shots: list[tuple[dict, dict, dict | None]] = []   # (block, item, shot_rect)
    for index, block in enumerate(blocks, start=1):
        item = items.get(block["selector"])
        measured = rects[index - 1] if index - 1 < len(rects) else None
        rect = (measured or {}).get("rect") or block.get("pageRect")
        if not item or item.get("error") or not rect:
            if item is not None and not item.get("error"):
                item.setdefault("warnings", []).append("snapshot: section element not found for reference")
            shots.append((block, item, None))
            continue
        root = item.get("root") or {}
        capture_rect = root.get("captureRect") if isinstance(root.get("captureRect"), dict) else None
        shot_rect = dict(capture_rect) if capture_rect else {
            "x": rect["x"], "y": rect["y"], "width": root.get("width") or rect["width"],
            "height": root.get("height") or rect["height"]}
        item["pageRect"] = {k: round(float(rect[k]), 2) for k in ("x", "y", "width", "height")}
        if block.get("pageBackground"):
            item["pageBackground"] = block["pageBackground"]
        item["_children"] = (measured or {}).get("children") or {}
        shots.append((block, item, shot_rect))
    live = [(block, item, rect) for block, item, rect in shots if rect]
    top = min((float(rect["y"]) for _, _, rect in live), default=0.0)
    bottom = max((float(rect["y"]) + float(rect["height"]) for _, _, rect in live), default=0.0)
    vh = float(viewport["height"])
    page_image = backdrop_image = first_screen = None
    try:
        if live:
            # first screen with its own fixed/sticky chrome (header sections)
            _scroll_to(page, 0)
            first_screen = _capture_clip(cdp, 0, 0, float(viewport["width"]), vh)
            page.evaluate(FOREIGN_CHROME_JS, {"selector": "", "hide": True})
            try:
                page_image = _region_image(page, cdp, top, bottom - top, viewport)
                backdrop_blocks = [block["selector"] for block, item, _ in live
                                   if any(req.get("mode") == "backdrop" for req in item.get("rasterRequests") or [])]
                if backdrop_blocks:
                    for selector in backdrop_blocks:
                        page.evaluate(CHILDREN_VISIBILITY_JS, {"selector": selector, "hide": True})
                    try:
                        backdrop_image = _region_image(page, cdp, top, bottom - top, viewport)
                    finally:
                        for selector in backdrop_blocks:
                            page.evaluate(CHILDREN_VISIBILITY_JS, {"selector": selector, "hide": False})
            finally:
                page.evaluate(FOREIGN_CHROME_JS, {"selector": "", "hide": False})
    except Exception as exc:  # noqa: BLE001 — references are evidence; IR is already compiled
        for _, item, _ in live:
            item.setdefault("warnings", []).append(f"snapshot reference unavailable: {str(exc)[:160]}")
    for index, (block, item, shot_rect) in enumerate(shots, start=1):
        if item is None or item.get("error") or shot_rect is None:
            if item is not None:
                by_selector[block["selector"]] = item
            report(index, len(blocks))
            continue
        children = item.pop("_children", {})
        try:
            in_first_screen = float(shot_rect["y"]) + float(shot_rect["height"]) <= vh + 0.5
            source = first_screen if (block.get("topChrome") or block.get("kind") == "header") and in_first_screen and first_screen is not None else page_image
            origin = 0.0 if source is first_screen else top
            reference = _png_from(source, shot_rect, origin) if source is not None else None
            if reference:
                item["preview"] = "data:image/png;base64," + base64.b64encode(reference).decode()
            if backdrop_image is not None:
                backdrop_png = _png_from(backdrop_image, shot_rect, top)
                for req in item.get("rasterRequests") or []:
                    if req.get("mode") != "backdrop" or not backdrop_png:
                        continue
                    node = find_node(item.get("nodes"), req.get("sourceKey"))
                    if node is not None:
                        node["src"] = store_png(backdrop_png)
            for req in item.get("rasterRequests") or []:
                if req.get("mode") == "backdrop":
                    continue
                node = find_node(item.get("nodes"), req.get("sourceKey"))
                box = children.get(str(req.get("selector") or ""))
                if node is None or not box or str(node.get("src") or "").startswith("data:image"):
                    continue
                crop = _crop_png(reference, box) if reference else None
                if crop:
                    node["src"] = store_png(crop)
                else:
                    item.setdefault("extras", []).append({"sourceKey": str(req.get("sourceKey") or ""),
                                                          "reason": "raster-unavailable", "visual": True,
                                                          "rect": {"x": 0, "y": 0, "width": 0, "height": 0}})
        except Exception as exc:  # noqa: BLE001 — one section must not sink the page
            item.setdefault("warnings", []).append(f"snapshot reference unavailable: {str(exc)[:160]}")
        namespace(item, re.sub(r"[^A-Za-z0-9_-]+", "-", str(block.get("name") or "block")))
        by_selector[block["selector"]] = item
        report(index, len(blocks))
    page.evaluate("() => window.scrollTo(0, 0)")
    lap("References")
    print(json.dumps({"event": "source_snapshot.viewport", "viewport": viewport.get("name"), "blocks": len(blocks),
                      "compileMs": compiled_ms, "totalMs": round((time.perf_counter() - started) * 1000)},
                     ensure_ascii=False), flush=True)
    return by_selector
