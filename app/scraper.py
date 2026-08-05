"""DesignAI Web — scraper: считывание контента и стилей с реальных сайтов.

Библиотеки:
  httpx        — HTTP-клиент (быстрый fetch, редиректы, cookies)
  beautifulsoup4 — парсинг HTML, извлечение структуры без галлюцинаций
  trafilatura  — извлечение основного контента страницы (статьи, текст)
  tinycss2     — парсинг CSS → точные цвета/шрифты/отступы
  playwright   — headless Chromium: рендер JS, скриншоты, computed styles
  Pillow       — подготовка изображений для vision API (resize, формат)
"""
from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag
from PIL import Image

from urlguard import validate_public_url

# ---------- data ----------

@dataclass
class PageData:
    url: str
    html: str = ""
    title: str = ""
    text_content: str = ""
    css_text: str = ""
    tokens: dict = field(default_factory=dict)
    structure: list = field(default_factory=list)
    screenshot_b64: str = ""
    viewport: dict = field(default_factory=lambda: {"width": 1440, "height": 900})


# ---------- fetch (httpx) ----------

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.9",
}


def fetch_html(url: str, timeout: float = 20.0) -> str:
    """Быстрый fetch HTML через httpx (без JS-рендера)."""
    validate_public_url(url)  # SSRF-гард
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


# ---------- parse (beautifulsoup4 + trafilatura) ----------

def extract_text_content(html: str) -> str:
    """Извлечение основного текстового контента (trafilatura + fallback bs4)."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_tables=True, include_links=False, favor_recall=True)
        if text and len(text.strip()) > 50:
            return text.strip()
    except Exception:
        pass
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8000]


def extract_structure(html: str) -> list:
    """Извлечение структуры страницы: список секций с типами и текстами."""
    soup = BeautifulSoup(html, "lxml")
    sections = []

    # navbar
    nav = soup.find("nav") or soup.find("header")
    if nav:
        links = [a.get_text(strip=True) for a in nav.find_all("a") if a.get_text(strip=True)]
        logo_el = nav.find(["a", "img", "span"], class_=re.compile(r"logo|brand", re.I))
        logo = logo_el.get_text(strip=True) if logo_el else ""
        sections.append({"type": "navbar", "logo": logo, "links": links[:10]})

    # hero / main heading
    h1 = soup.find("h1")
    if h1:
        sections.append({"type": "hero", "heading": h1.get_text(strip=True)})

    # sections by headings
    for h in soup.find_all(["h2", "h3"]):
        text = h.get_text(strip=True)
        if text and len(text) < 100:
            parent = h.parent
            body_text = ""
            if parent:
                p = parent.find("p")
                body_text = p.get_text(strip=True)[:200] if p else ""
            sections.append({"type": "section", "heading": text, "body": body_text})

    # buttons / CTAs
    buttons = []
    for btn in soup.find_all(["a", "button"], class_=re.compile(r"btn|cta|button", re.I)):
        t = btn.get_text(strip=True)
        if t and len(t) < 40:
            buttons.append(t)
    if buttons:
        sections.append({"type": "cta", "buttons": buttons[:5]})

    # footer
    footer = soup.find("footer")
    if footer:
        sections.append({"type": "footer", "text": footer.get_text(strip=True)[:300]})

    return sections


# ---------- CSS parsing (tinycss2) ----------

def extract_css(html: str) -> str:
    """Извлечение inline + linked CSS из HTML."""
    soup = BeautifulSoup(html, "lxml")
    parts = []
    for style in soup.find_all("style"):
        parts.append(style.get_text())
    return "\n".join(parts)[:12000]


def parse_design_tokens(css_text: str) -> dict:
    """Извлечение design-токенов из CSS (цвета, шрифты, радиусы)."""
    import tinycss2

    tokens = {"color": {}, "font": {}, "radius": {}}
    color_re = re.compile(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)")
    font_re = re.compile(r"font-family:\s*([^;]+)", re.I)
    radius_re = re.compile(r"border-radius:\s*([^;]+)", re.I)

    # CSS custom properties (--var)
    var_re = re.compile(r"--([\w-]+):\s*([^;]+)")
    for m in var_re.finditer(css_text):
        name, val = m.group(1).strip(), m.group(2).strip()
        if color_re.search(val):
            tokens["color"][name] = val
        elif "px" in val or "rem" in val or "em" in val:
            tokens["radius"][name] = val

    # direct color declarations
    colors_found = set()
    for m in color_re.finditer(css_text):
        c = m.group(0)
        if c not in colors_found and not c.startswith("#000") and not c.startswith("#fff"):
            colors_found.add(c)
    if colors_found:
        tokens["color"]["_extracted"] = list(colors_found)[:12]

    # font families
    fonts = set()
    for m in font_re.finditer(css_text):
        fam = m.group(1).strip().strip("'\"").split(",")[0].strip("'\"")
        if fam and fam.lower() not in ("sans-serif", "serif", "monospace", "inherit"):
            fonts.add(fam)
    if fonts:
        tokens["font"]["_extracted"] = list(fonts)[:6]

    return tokens


# ---------- image prep (Pillow) ----------

MAX_VISION_DIM = 1568  # qwen-vl-max max dimension


def prepare_image_b64(data_url: str) -> str:
    """Resize image for vision API, return base64 data URL."""
    if not data_url or not data_url.startswith("data:"):
        return data_url
    header, b64data = data_url.split(",", 1)
    raw = base64.b64decode(b64data)
    img = Image.open(io.BytesIO(raw))

    # convert RGBA → RGB (vision models don't need alpha)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # resize if too large
    w, h = img.size
    if max(w, h) > MAX_VISION_DIM:
        ratio = MAX_VISION_DIM / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def image_dimensions(data_url: str) -> tuple[int, int]:
    """Return (width, height) of image from data URL."""
    if not data_url or not data_url.startswith("data:"):
        return (0, 0)
    _, b64data = data_url.split(",", 1)
    raw = base64.b64decode(b64data)
    img = Image.open(io.BytesIO(raw))
    return img.size


# ---------- Playwright: JS-render + screenshot + computed styles ----------

def render_page_sync(url: str, viewport_w: int = 1440, viewport_h: int = 900,
                     screenshot: bool = True, timeout_ms: int = 15000) -> PageData:
    """Рендер страницы в headless Chromium: HTML после JS + скриншот + computed styles."""
    from playwright.sync_api import sync_playwright

    validate_public_url(url)  # SSRF-гард: headless Chromium тоже не ходит во внутреннюю сеть
    result = PageData(url=url, viewport={"width": viewport_w, "height": viewport_h})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport_w, "height": viewport_h})
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        page.wait_for_timeout(1000)  # доп. время для анимаций/ленивой загрузки
        result.html = page.content()
        result.title = page.title()

        if screenshot:
            png_bytes = page.screenshot(full_page=True, type="png")
            result.screenshot_b64 = base64.b64encode(png_bytes).decode()

        # извлекаем computed styles ключевых элементов
        result.tokens = page.evaluate("""() => {
            const tokens = {colors: [], fonts: [], sizes: []};
            const els = document.querySelectorAll('body, h1, h2, h3, a, button, .btn, nav, header, footer, .card, [class*="hero"]');
            const seen = new Set();
            els.forEach(el => {
                const cs = getComputedStyle(el);
                const bg = cs.backgroundColor;
                const color = cs.color;
                const ff = cs.fontFamily;
                const fs = cs.fontSize;
                const br = cs.borderRadius;
                if (bg && !seen.has('bg:'+bg)) { seen.add('bg:'+bg); tokens.colors.push({prop:'bg', val:bg, tag:el.tagName}); }
                if (color && !seen.has('c:'+color)) { seen.add('c:'+color); tokens.colors.push({prop:'color', val:color, tag:el.tagName}); }
                if (ff && !seen.has('ff:'+ff)) { seen.add('ff:'+ff); tokens.fonts.push(ff); }
                if (fs && !seen.has('fs:'+fs)) { seen.add('fs:'+fs); tokens.sizes.push(fs); }
                if (br && br !== '0px' && !seen.has('br:'+br)) { seen.add('br:'+br); tokens.sizes.push('radius:'+br); }
            });
            return tokens;
        }""")

        browser.close()

    result.text_content = extract_text_content(result.html)
    result.css_text = extract_css(result.html)
    result.structure = extract_structure(result.html)
    return result


# ---------- high-level: full page analysis ----------

def analyze_url(url: str, use_playwright: bool = True) -> PageData:
    """Полный анализ URL: fetch → parse → tokens → структура."""
    if use_playwright:
        return render_page_sync(url)

    html = fetch_html(url)
    result = PageData(url=url, html=html)
    result.title = BeautifulSoup(html, "lxml").title.get_text(strip=True) if BeautifulSoup(html, "lxml").title else ""
    result.text_content = extract_text_content(html)
    result.css_text = extract_css(html)
    result.tokens = parse_design_tokens(result.css_text)
    result.structure = extract_structure(html)
    return result
