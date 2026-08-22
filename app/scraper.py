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
import contextlib
import copy
import hashlib
import io
import math
import os
import re
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag
from PIL import Image

from urlguard import fetch_public_bytes, install_playwright_url_guard, validate_public_url

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
_MAX_HTML_BYTES = 5_000_000


def fetch_html(url: str, timeout: float = 20.0) -> str:
    """Быстрый fetch HTML через httpx (без JS-рендера)."""
    response = fetch_public_bytes(
        url, timeout=timeout, headers=_HEADERS, max_bytes=_MAX_HTML_BYTES,
    )
    content_type = response.headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    encoding = match.group(1).strip("\"'") if match else "utf-8"
    try:
        return response.content.decode(encoding, errors="replace")
    except LookupError:
        return response.content.decode("utf-8", errors="replace")


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


# ---------- детекция границ блоков (Source Import, docs/ARCHITECTURE.md) ----------

# Контентные семантические теги — кандидаты в блоки; шапка/подвал — отдельно
_BLOCK_TAGS = ("main", "section", "aside")
# clone каждого блока = LLM-вызов; ограничиваем расход
_MAX_BLOCKS = 16
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

_SEMANTIC_PATTERNS = (
    ("navigation", re.compile(r"(?:^|[-_ ])(?:rail|sidebar|side[-_ ]?nav|navigation|dock)(?:$|[-_ ])", re.I)),
    ("status", re.compile(r"(?:^|[-_ ])(?:shell[-_ ]?act|action[-_ ]?bar|status[-_ ]?bar|bottom[-_ ]?bar)(?:$|[-_ ])", re.I)),
    ("profile", re.compile(r"(?:^|[-_ ])(?:profile|account[-_ ]?summary|user[-_ ]?panel)(?:$|[-_ ])", re.I)),
    ("panel", re.compile(r"(?:^|[-_ ])(?:panel|widget|module)(?:$|[-_ ])", re.I)),
    ("carousel", re.compile(r"carousel|slider|slideshow|swiper|\bhero\b|promo[-_ ]?slider", re.I)),
    ("categories", re.compile(r"categor|catalog|rubric|taxonomy|departments", re.I)),
    ("product-grid", re.compile(r"listing|product[-_ ]?grid|product[-_ ]?list|shelf|market[-_ ]?grid", re.I)),
    ("journal", re.compile(r"journal|blog|editorial|articles|stories|news[-_ ]?grid", re.I)),
    ("how-it-works", re.compile(r"how[-_ ]?(?:it[-_ ]?)?works|steps|process", re.I)),
    ("faq", re.compile(r"faq|questions|accordion|help[-_ ]?center", re.I)),
    ("cta", re.compile(r"\bcta\b|seller|sell[-_ ]?banner|conversion|call[-_ ]?to[-_ ]?action", re.I)),
    ("trust", re.compile(r"trust|safety|security|benefits|advantages|guarantee", re.I)),
    ("pricing", re.compile(r"pricing|plans|tariffs", re.I)),
    ("testimonials", re.compile(r"testimonials|reviews|social[-_ ]?proof", re.I)),
    ("gallery", re.compile(r"gallery|portfolio|showcase", re.I)),
)

_HEADING_PATTERNS = (
    ("services-grid", re.compile(r"услуг|services?|мастер", re.I)),
    ("product-grid", re.compile(r"новое|товар|объявлен|products?|listings?", re.I)),
    ("journal", re.compile(r"журнал|блог|стать", re.I)),
    ("how-it-works", re.compile(r"как это работает|how it works", re.I)),
    ("faq", re.compile(r"частые вопросы|вопросы и ответы|frequently asked|faq", re.I)),
    ("trust", re.compile(r"безопас|защит|гарант|trust|safety", re.I)),
    ("cta", re.compile(r"продать|разместить|начать|sell|place an ad|get started", re.I)),
)

_ROLE_LABELS = {
    "header": "Header",
    "footer": "Footer",
    "carousel": "Carousel",
    "categories": "Categories",
    "product-grid": "Product cards",
    "services-grid": "Service cards",
    "journal": "Journal",
    "how-it-works": "How it works",
    "faq": "FAQ",
    "cta": "CTA",
    "trust": "Trust / benefits",
    "pricing": "Pricing",
    "testimonials": "Testimonials",
    "gallery": "Gallery",
    "navigation": "Navigation",
    "status": "Status / actions",
    "toolbar": "Toolbar",
    "profile": "Profile",
    "panel": "Panel",
    "section": "Section",
}

_ARIA_ROLE_KINDS = {
    "navigation": "navigation",
    "status": "status",
    "toolbar": "toolbar",
    "complementary": "panel",
    "region": "panel",
}


def _slug(text: str) -> str:
    """Короткий идентификатор блока из текста: слова в нижнем регистре через дефис."""
    return "-".join(re.findall(r"[^\W_]+", text.lower()))[:24].strip("-")


def _css_selector(el: Tag) -> str:
    """Детерминированный CSS-селектор элемента (повторный выбор через soup.select)."""
    # уникальный безопасный id — самый короткий путь; [id="..."] не требует CSS-экранирования
    el_id = el.get("id")
    if el_id and _SAFE_ID.match(el_id):
        root = el.find_parent("[document]")
        if root is not None and len(root.find_all(attrs={"id": el_id})) == 1:
            return f'[id="{el_id}"]'
    parts = []
    cur = el
    while cur is not None and cur.name not in (None, "[document]", "html"):
        seg = cur.name
        if cur.name == "body":
            parts.append(seg)
            break
        parent = cur.parent
        if parent is not None and parent.name not in (None, "[document]", "html"):
            same = parent.find_all(cur.name, recursive=False)
            if len(same) > 1:
                seg += f":nth-of-type({same.index(cur) + 1})"
        parts.append(seg)
        cur = cur.parent
    return " > ".join(reversed(parts))


def _block_heading(el: Tag) -> str:
    h = el.find(["h1", "h2", "h3"])
    return h.get_text(" ", strip=True)[:80] if h else ""


def _identity_role(el: Tag) -> str:
    """Role expressed by tag/id/class only; safe for promoting generic divs."""
    if el.name == "header":
        return "header"
    if el.name == "footer":
        return "footer"

    aria_role = str(el.get("role") or "").strip().lower()
    if aria_role in _ARIA_ROLE_KINDS:
        return _ARIA_ROLE_KINDS[aria_role]

    identity = " ".join((
        str(el.get("id") or ""),
        " ".join(el.get("class") or []),
        str(el.get("role") or ""),
    ))
    for role, pattern in _SEMANTIC_PATTERNS:
        if pattern.search(identity):
            return role

    if el.name == "nav":
        return "navigation"
    return "section"


def _semantic_role(el: Tag) -> str:
    """Best-effort semantic role without treating repeated cards as page sections."""
    identity_role = _identity_role(el)
    if identity_role != "section":
        if identity_role == "product-grid" and _HEADING_PATTERNS[0][1].search(_block_heading(el)):
            return "services-grid"
        return identity_role

    heading = _block_heading(el)
    for role, pattern in _HEADING_PATTERNS:
        if pattern.search(heading):
            return role
    if el.find("h1"):
        return "carousel"
    return "section"


def _block_label(el: Tag, role: str) -> str:
    heading = _block_heading(el)
    return heading or _ROLE_LABELS.get(role, role.replace("-", " ").title())


def detect_blocks(html: str) -> list:
    """Детерминированная детекция границ блоков страницы.

    Возвращает список {name, selector, tag, heading} с уникальными name.
    Правила: шапка (header, либо nav при отсутствии header) и footer — по одному
    блоку; контентные теги (main/section/article/aside) — блоки, содержащие
    меньше двух вложенных семантических блоков (main с секциями отбрасывается),
    вложенные друг в друга не дублируются.
    Страницы без семантики: контейнер каждого h1/h2 вне уже найденных блоков.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    candidates: list[Tag] = []

    def add(el: Tag | None) -> None:
        if el is not None and el not in candidates:
            candidates.append(el)

    # Global chrome is one block each. Nested section headers never become outputs.
    add(body.find("header"))

    # A semantic container is the unit of output. Repeated <article> cards/slides are
    # intentionally not candidates: their parent carousel/grid becomes one block.
    for el in body.find_all(_BLOCK_TAGS):
        add(el)
    for el in body.find_all("nav"):
        add(el)

    # ARIA landmarks and stable shell panels are independent visible regions,
    # even when a framework renders them as generic divs outside <main>.
    for el in body.find_all(attrs={"role": True}):
        if str(el.get("role") or "").strip().lower() in _ARIA_ROLE_KINDS:
            add(el)

    # Modern component frameworks often render page sections as divs. Promote only
    # containers with a meaningful id/class; a generic wrapper stays internal.
    for el in body.find_all(["div", "ol", "ul"]):
        if _identity_role(el) != "section":
            add(el)

    add(body.find("footer"))

    # Drop page-wide main and nested aliases of the same semantic block.
    meaningful = []
    for el in candidates:
        nested = [other for other in candidates if other is not el and other in el.descendants]
        if el.name == "main" and len(nested) >= 2:
            continue
        if any(parent is not el and parent.name != "main" and el in parent.descendants and
               (parent.name in ("header", "footer", "section", "aside") or
                _semantic_role(parent) == _semantic_role(el))
               for parent in candidates):
            continue
        meaningful.append(el)

    # Preserve document order, so footer is last rather than the second output.
    document_order = {id(el): i for i, el in enumerate(body.find_all(True))}
    meaningful.sort(key=lambda el: document_order.get(id(el), 10**9))

    # Fallback for sites without semantic markup: nearest page-level h1/h2 wrapper.
    if len(meaningful) <= 2:
        for h in body.find_all(["h1", "h2"])[:20]:
            node = h
            while node.parent is not None and node.parent is not body:
                if node.parent.name in ("main", "section", "article", "aside"):
                    break
                node = node.parent
            if node is not h and node is not body and len(node.get_text(" ", strip=True)) >= 40:
                add(node)
        meaningful = [el for el in candidates if el.name != "main"]
        meaningful.sort(key=lambda el: document_order.get(id(el), 10**9))

    blocks = []
    names: set[str] = set()
    for el in meaningful[:_MAX_BLOCKS]:
        role = _semantic_role(el)
        name, n = role, 1
        while name in names:
            n += 1
            name = f"{role}-{n}"
        names.add(name)
        blocks.append({
            "name": name,
            "label": _block_label(el, role),
            "kind": role,
            "selector": _css_selector(el),
            "tag": el.name,
            "heading": _block_heading(el),
        })
    return blocks


def extract_structure(html: str) -> list:
    """Извлечение структуры страницы: список секций с типами и текстами.

    Секции, для которых найден DOM-элемент, несут name/selector (блоки для
    BlockParse); дополнительно добавляются сами блоки из detect_blocks.
    """
    soup = BeautifulSoup(html, "lxml")
    sections = []

    # navbar
    nav = soup.find("nav") or soup.find("header")
    if nav:
        links = [a.get_text(strip=True) for a in nav.find_all("a") if a.get_text(strip=True)]
        logo_el = nav.find(["a", "img", "span"], class_=re.compile(r"logo|brand", re.I))
        logo = logo_el.get_text(strip=True) if logo_el else ""
        sections.append({"type": "navbar", "name": "header", "selector": _css_selector(nav),
                         "logo": logo, "links": links[:10]})

    # hero / main heading
    h1 = soup.find("h1")
    if h1:
        entry = {"type": "hero", "name": "hero", "heading": h1.get_text(strip=True)}
        if h1.parent is not None and h1.parent.name not in (None, "[document]"):
            entry["selector"] = _css_selector(h1.parent)
        sections.append(entry)

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
        sections.append({"type": "footer", "name": "footer", "selector": _css_selector(footer),
                         "text": footer.get_text(strip=True)[:300]})

    # блоки BlockParse (name+selector): имя уже учтённой секции не дублируем
    have = {s.get("name") for s in sections}
    for b in detect_blocks(html):
        if b["name"] not in have:
            sections.append({"type": "block", **b})

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

MAX_VISION_DIM = 1568  # безопасный предел для vision-API (OpenAI/Kimi)


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

def _guarded_browser_page(browser, viewport: dict):
    context = browser.new_context(viewport=viewport, service_workers="block")
    install_playwright_url_guard(context, validate_public_url)
    return context, context.new_page()


def _normalize_source_cookies(cookies: list[dict] | None, target_url: str) -> list[dict]:
    """Validate short-lived desktop cookies before handing them to Playwright."""
    validate_public_url(target_url)
    parsed = urlparse(target_url)
    host = (parsed.hostname or "").lower()
    scheme = parsed.scheme.lower()
    normalized: list[dict] = []
    for raw in (cookies or [])[:128]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        value = str(raw.get("value") or "")
        domain = str(raw.get("domain") or host).lstrip(".").lower()
        path = str(raw.get("path") or "/")
        if not name or len(name) > 256 or re.search(r"[\x00-\x20;=]", name):
            continue
        if len(value) > 4096 or re.search(r"[\x00-\x08\x0a-\x1f\x7f]", value):
            continue
        if domain != host and not host.endswith("." + domain):
            continue
        if not path.startswith("/") or len(path) > 1024:
            path = "/"
        if raw.get("secure") is True and scheme != "https":
            continue
        same_site = str(raw.get("sameSite") or "").capitalize()
        item = {
            "name": name,
            "value": value,
            "domain": str(raw.get("domain") or host),
            "path": path,
            "secure": raw.get("secure") is True,
            "httpOnly": raw.get("httpOnly") is True,
        }
        if same_site in {"Strict", "Lax", "None"}:
            item["sameSite"] = same_site
        normalized.append(item)
    return normalized


def _wait_capture_settle(page, budget_ms: int = 5000) -> None:
    """Deterministic pre-measure settle: fonts, images, then two rAF.

    Один ритуал для всех viewport-проходов вместо фиксированного sleep:
    document.fonts.ready + decode() видимых <img> + два requestAnimationFrame,
    с жёстким bail-таймером (оживлённые страницы не подвешивают capture).

    Ждём ТОЛЬКО картинки в текущем viewport: lazy-loading изображения
    ниже фолда никогда не грузятся и заставляли settle бить в bail-timer
    на каждом проходе (замер: rsale.net — 52 из 56 lazy → 5 сек × 3
    viewport = 15 секунд чистого ожидания ничего).
    """
    try:
        page.evaluate("""(budgetMs) => new Promise((resolve) => {
          const finish = () => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
          const bail = setTimeout(finish, budgetMs);
          const fonts = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
          const vw = window.innerWidth, vh = window.innerHeight;
          const visible = (img) => {
            if (img.complete) return false;
            const r = img.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
          };
          const imgs = Promise.all(Array.from(document.images || []).filter(visible).slice(0, 100).map((img) => {
            return (img.decode ? img.decode() : Promise.resolve()).catch(() => {});
          }));
          Promise.all([fonts.catch(() => {}), imgs]).then(() => { clearTimeout(bail); finish(); });
        })""", budget_ms)
    except Exception:
        page.wait_for_timeout(400)


def _find_source_node(nodes, source_key):
    for node, _parent in _walk_source_nodes(nodes):
        if str(node.get("sourceKey") or "") == str(source_key or ""):
            return node
    return None


def _namespace_block_keys(item: dict, namespace: str) -> None:
    """Block-scoped sourceKeys: sibling-блоки одной страницы имеют одинаковые
    root-relative DOM-пути ('root/div:1'); namespace делает ключи уникальными
    между блоками (sibling isolation) и стабильными между viewport-ами."""
    prefix = f"{namespace}:"
    def nk(key):
        key = str(key or "")
        return key if not key or key.startswith(prefix) else prefix + key
    for node, _parent in _walk_source_nodes(item.get("nodes")):
        if node.get("sourceKey"):
            node["sourceKey"] = nk(node["sourceKey"])
    for coll in ("dropped", "extras", "leafBoxes"):
        for rec in item.get(coll) or []:
            if isinstance(rec, dict) and rec.get("sourceKey"):
                rec["sourceKey"] = nk(rec["sourceKey"])

def render_page_sync(url: str, viewport_w: int = 1440, viewport_h: int = 900,
                     screenshot: bool = True, timeout_ms: int = 15000) -> PageData:
    """Рендер страницы в headless Chromium: HTML после JS + скриншот + computed styles."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

    validate_public_url(url)  # SSRF-гард: headless Chromium тоже не ходит во внутреннюю сеть
    result = PageData(url=url, viewport={"width": viewport_w, "height": viewport_h})

    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.launch(headless=True)
            context, page = _guarded_browser_page(
                browser, {"width": viewport_w, "height": viewport_h},
            )
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            validate_public_url(page.url)

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
        finally:
            if context is not None:
                with contextlib.suppress(Exception):
                    context.close()
            if browser is not None:
                with contextlib.suppress(Exception):
                    browser.close()

    result.text_content = extract_text_content(result.html)
    result.css_text = extract_css(result.html)
    result.structure = extract_structure(result.html)
    return result


def rendered_html(url: str, timeout_ms: int = 20000,
                  cookies: list[dict] | None = None) -> str:
    """HTML живого DOM после JS (один headless-проход Chromium).

    Детекция блоков по raw httpx HTML расходится с capture, который resolve'ит
    селекторы в post-JS DOM (SSR/hydration); page.content() снимает именно его.
    Тот же settle, что и в capture_block_irs: domcontentloaded + 900ms + kill
    анимаций, чтобы раскладка успела стать финальной.
    """
    from playwright.sync_api import sync_playwright

    validate_public_url(url)  # SSRF-гард
    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.launch(headless=True)
            context, page = _guarded_browser_page(browser, {"width": 1440, "height": 900})
            source_cookies = _normalize_source_cookies(cookies, url)
            if cookies is not None and not source_cookies:
                raise ValueError("Authenticated Source Import session has no valid cookies for this URL")
            if source_cookies:
                context.add_cookies(source_cookies)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            validate_public_url(page.url)
            page.wait_for_timeout(900)
            page.add_style_tag(content="""
              *, *::before, *::after { animation:none !important; transition:none !important; }
              html { scroll-behavior:auto !important; }
            """)
            return page.content()
        finally:
            if context is not None:
                with contextlib.suppress(Exception):
                    context.close()
            if browser is not None:
                with contextlib.suppress(Exception):
                    browser.close()


# ---------- BlockParse: точный редактируемый DOM-слепок ----------

def _css_color_to_hex(value: str, fallback: str) -> str:
    """Безопасно приводит computed CSS color к hex для Design IR."""
    value = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
        return value[:7]
    match = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[^)]+)?\)", value)
    if not match:
        return fallback
    return "#" + "".join(f"{min(255, int(part)):02x}" for part in match.groups())


# JS: сырые сигналы дизайн-токенов со всей страницы (один desktop-проход).
# Считаем частоты по живому DOM: фоны кнопок, цвета ссылок, бордеры, мелкий
# (muted) текст, шрифты заголовков/тела, радиусы, тени, отступы секций и
# max-width контейнеров. Маппинг в закрытый enum-контракт схемы — в Python.
_PAGE_TOKEN_SIGNALS_JS = """() => {
  const num = (v) => Number.parseFloat(v) || 0;
  const hex = (v) => {
    const value=String(v||'');
    const rgb=value.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
    if(rgb){
      if(rgb[4]!==undefined && Number(rgb[4])<=.05) return null;
      return '#'+rgb.slice(1,4).map(x=>(+x).toString(16).padStart(2,'0')).join('');
    }
    return null;
  };
  const visible = (el) => {
    const r=el.getBoundingClientRect(), cs=getComputedStyle(el);
    return r.width>=1 && r.height>=1 && cs.display!=='none' && cs.visibility!=='hidden' && Number(cs.opacity)!==0;
  };
  const tally = (map,key) => { if(key) map[key]=(map[key]||0)+1; };
  const top = (map) => { const e=Object.entries(map).sort((a,b)=>b[1]-a[1]); return e.length?e[0][0]:null; };
  const saturation = (color) => {
    if(!color || !/^#[0-9a-f]{6}$/i.test(color)) return 0;
    const rgb=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255), hi=Math.max(...rgb), lo=Math.min(...rgb);
    return hi ? (hi-lo)/hi : 0;
  };
  const bodyCs=getComputedStyle(document.body);
  const sig={bodyBg:hex(bodyCs.backgroundColor)||hex(getComputedStyle(document.documentElement).backgroundColor)||'#ffffff',
    bodyColor:hex(bodyCs.color),buttonBg:{},linkColor:{},borderColor:{},mutedColor:{},brandColor:{},
    buttonRadius:[],cardRadius:[],inputRadius:[],cardShadowBlur:[],sectionPadding:[],containerWidth:[]};
  const radiusOf=(cs,r)=>{ const rad=num(cs.borderTopLeftRadius); const side=Math.min(r.width,r.height);
    return side>0 && rad*2>=side ? 9999 : rad; };
  for(const el of [...document.body.querySelectorAll('*')].slice(0,800)){
    if(!visible(el)) continue;
    const cs=getComputedStyle(el), r=el.getBoundingClientRect();
    const bg=hex(cs.backgroundColor), fg=hex(cs.color), border=hex(cs.borderTopColor);
    for(const color of [bg,fg,border]) if(saturation(color)>=.28) tally(sig.brandColor,color);
    const isButton=el.matches('button,[role="button"]') || (el.tagName==='A' && (bg || num(cs.borderTopWidth)>0));
    if(isButton && bg){ sig.buttonRadius.push(radiusOf(cs,r)); if(bg!==sig.bodyBg) tally(sig.buttonBg,bg); }
    if(el.tagName==='A') tally(sig.linkColor,hex(cs.color));
    if(num(cs.borderTopWidth)>0) tally(sig.borderColor,hex(cs.borderTopColor));
    if(num(cs.fontSize)>0 && num(cs.fontSize)<13 && String(el.innerText||'').trim()) tally(sig.mutedColor,hex(cs.color));
    if(el.matches('input,select,textarea')) sig.inputRadius.push(num(cs.borderTopLeftRadius));
    if(el.matches('[class*="card"],article,[class*="tile"]')){
      sig.cardRadius.push(radiusOf(cs,r));
      if(cs.boxShadow && cs.boxShadow!=='none'){
        const lens=[...cs.boxShadow.matchAll(/(-?\\d+(?:\\.\\d+)?)px/g)].map(m=>Math.abs(Number(m[1])));
        if(lens.length) sig.cardShadowBlur.push(lens.length>=3?lens[2]:Math.max(...lens));
      }
    }
    if(el.matches('body > main > *, body > section, body > div, [class*="section"]')){
      const pad=num(cs.paddingTop)+num(cs.paddingBottom);
      if(pad>0 && r.height>=80) sig.sectionPadding.push(pad);
      if(num(cs.maxWidth)>0) sig.containerWidth.push(num(cs.maxWidth));
    }
  }
  const fontOf=(el)=>{ const cs=getComputedStyle(el);
    return {family:String(cs.fontFamily||''), weight:Number.parseInt(cs.fontWeight,10)||400}; };
  const heading=[...document.querySelectorAll('h1,h2')].find(visible);
  if(heading) sig.displayFont=fontOf(heading);
  const para=[...document.querySelectorAll('p')].find(visible);
  sig.bodyFont=fontOf(para||document.body);
  sig.buttonBg=top(sig.buttonBg); sig.linkColor=top(sig.linkColor);
  sig.borderColor=top(sig.borderColor); sig.mutedColor=top(sig.mutedColor);
  sig.brandColors=Object.entries(sig.brandColor).sort((a,b)=>b[1]-a[1]).map(([color])=>color).slice(0,4);
  delete sig.brandColor;
  return sig;
}"""

_GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "system-ui", "inherit", "initial",
                     "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "cursive",
                     "fantasy", "emoji", "math", "fangsong"}


def _luminance(hex_color: str) -> float:
    """Относительная яркость hex-цвета, 0..1 (непонятное → светлое)."""
    value = str(hex_color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return 1.0
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _color_saturation(hex_color: str) -> float:
    value = str(hex_color or "").lstrip("#")
    if len(value) != 6:
        return 0.0
    try:
        channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return 0.0
    high, low = max(channels), min(channels)
    return (high - low) / high if high else 0.0


def _median(values: list) -> float | None:
    nums = sorted(float(v) for v in values or [] if isinstance(v, (int, float)))
    if not nums:
        return None
    mid = len(nums) // 2
    return nums[mid] if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / 2


def _snap_weight(value, fallback: int = 400) -> int:
    """fontWeight → 300..900 с шагом 100 (enum fontFace схемы)."""
    try:
        weight = int(round(float(value) / 100.0) * 100)
    except (TypeError, ValueError):
        return fallback
    return min(900, max(300, weight))


def _font_family(value: str, fallback: str = "Inter") -> str:
    """Первая family из font-stack, без кавычек; generic-семейства не считаются."""
    family = str(value or "").split(",")[0].strip().strip("'\" ").strip()
    if not family or family.lower() in _GENERIC_FAMILIES:
        return fallback
    return family[:60]


def _radius_enum(px: float | None) -> str:
    if px is None:
        return "md"
    if px >= 999:  # pill: JS шлёт 9999, когда radius >= 50% меньшей стороны
        return "full"
    if px < 1:
        return "none"
    if px <= 4:
        return "sm"
    if px <= 8:
        return "md"
    if px <= 14:
        return "lg"
    return "xl"


def _section_spacing_enum(px: float | None) -> str:
    if px is None:
        return "md"
    if px < 40:
        return "sm"
    if px < 80:
        return "md"
    if px < 128:
        return "lg"
    return "xl"


def _container_enum(px: float | None) -> str:
    if px is None:
        return "default"
    if px < 720:
        return "narrow"
    if px <= 1152:
        return "default"
    if px <= 1440:
        return "wide"
    return "full"


def _shadow_enum(blur: float | None) -> str:
    if not blur:
        return "none"
    if blur <= 6:
        return "sm"
    if blur <= 20:
        return "md"
    return "lg"


def _page_tokens_from_signals(signals: dict | None) -> dict | None:
    """Сырые сигналы живой страницы → токены строго по контракту схемы.

    Любой пробой отдельного сигнала — локальный дефолт (как раньше hardcode в
    _captured_ir); полный сбой — None, и caller остаётся на прежних дефолтах.
    """
    if not isinstance(signals, dict):
        return None
    try:
        bg = _css_color_to_hex(str(signals.get("bodyBg") or ""), "#ffffff")
        text = _css_color_to_hex(str(signals.get("bodyColor") or ""), "#171717")
        mode = "dark" if _luminance(bg) < 0.5 else "light"
        button = _css_color_to_hex(str(signals.get("buttonBg") or ""), text)
        link = _css_color_to_hex(str(signals.get("linkColor") or ""), button)
        brand_colors = [
            _css_color_to_hex(str(value), "")
            for value in signals.get("brandColors", [])
            if isinstance(value, str)
        ]
        brand_colors = [value for value in brand_colors if value]
        primary = button if _color_saturation(button) >= 0.2 else (brand_colors[0] if brand_colors else button)
        accent_candidates = [value for value in [link, *brand_colors] if value != primary and _color_saturation(value) >= 0.2]
        accent = accent_candidates[0] if accent_candidates else primary
        display = signals.get("displayFont") or {}
        body_font = signals.get("bodyFont") or {}
        return {
            "mode": mode,
            "color": {
                "primary": primary,
                "secondary": primary,
                "accent": accent,
                "background": bg,
                "surface": bg,
                "text": text,
                "textMuted": _css_color_to_hex(str(signals.get("mutedColor") or ""),
                                               "#9ca3af" if mode == "dark" else "#666666"),
                "border": _css_color_to_hex(str(signals.get("borderColor") or ""),
                                            "#374151" if mode == "dark" else "#d1d5db"),
            },
            "font": {
                "display": {"family": _font_family(display.get("family")),
                            "weight": _snap_weight(display.get("weight", 700), 700)},
                "body": {"family": _font_family(body_font.get("family")),
                         "weight": _snap_weight(body_font.get("weight", 400), 400)},
                "scale": "default",
            },
            "radius": {
                "card": _radius_enum(_median(signals.get("cardRadius"))),
                "button": _radius_enum(_median(signals.get("buttonRadius"))),
                "input": _radius_enum(_median(signals.get("inputRadius"))),
            },
            "spacing": {
                "section": _section_spacing_enum(_median(signals.get("sectionPadding"))),
                "container": _container_enum(_median(signals.get("containerWidth"))),
            },
            "shadow": _shadow_enum(_median(signals.get("cardShadowBlur"))),
        }
    except Exception:
        return None


# ---------- база шрифтов сайтов (Source Import, по мотивам html.to.design) ----------

_DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
_FONTS_DIR = _DATA_ROOT / "fonts"
_FONT_MAGIC = ((b"wOF2", ".woff2"), (b"wOFF", ".woff"), (b"OTTO", ".otf"), (b"\x00\x01\x00\x00", ".ttf"))


def _download_font(url: str, timeout: float = 15.0) -> Optional[bytes]:
    """Скачивает файл шрифта через общий SSRF/DNS/size guard.

    Каждая сетевая загрузка идёт через fetch_public_bytes (per-hop валидация
    URL, connect-time pinning публичного IP, жёсткий лимит байт) — same-origin
    не является основанием для обхода guard-а. Тесты с локальными фикстурами
    подменяют scraper.fetch_public_bytes monkeypatch-ем, production bypass-а нет.
    """
    try:
        response = fetch_public_bytes(
            url, timeout=timeout, headers=_HEADERS, max_bytes=3_000_000,
        )
        data = response.content
    except Exception:
        return None
    if not data or len(data) > 3_000_000:
        return None
    if any(data[:4] == magic for magic, _ in _FONT_MAGIC):
        return data
    return None


def _store_font(data: bytes) -> str:
    """Дедуп-запись в data/fonts; возвращает имя файла."""
    ext = next((e for m, e in _FONT_MAGIC if data[:4] == m), ".ttf")
    name = hashlib.sha1(data).hexdigest()[:16] + ext
    _FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = _FONTS_DIR / name
    if not target.exists():
        target.write_bytes(data)
    return name


def _first_family(css_family: str) -> str:
    return (css_family or "").split(",")[0].strip().strip("\"'").lower()


def _collect_used_families(node, out: set) -> None:
    if not isinstance(node, dict):
        return
    st = node.get("style") or {}
    if isinstance(st, dict) and st.get("fontFamily"):
        out.add(_first_family(str(st["fontFamily"])))
    for ch in node.get("children") or []:
        _collect_used_families(ch, out)


def _collect_used_font_weights(node, out: dict[str, set[int]]) -> None:
    if not isinstance(node, dict):
        return
    st = node.get("style") or {}
    if isinstance(st, dict) and st.get("fontFamily"):
        family = _first_family(str(st["fontFamily"]))
        if family:
            out.setdefault(family, set()).add(_snap_weight(st.get("fontWeight", 400)))
    for ch in node.get("children") or []:
        _collect_used_font_weights(ch, out)


def _resolve_font_faces(raw_faces: list, used: set,
                        used_weights: dict[str, set[int]] | None = None) -> list:
    """Из всех @font-face страницы оставляет только семьи, реально использованные
    в IR блока, скачивает файлы и отдаёт ссылки на локальную базу /fonts."""
    out: list = []
    seen: set = set()
    for face in raw_faces or []:
        fam = str(face.get("family") or "").strip()
        if not fam or fam.lower() not in used:
            continue
        # Preserve a variable font range as one face; unicode-range keeps
        # Google-font subsets (latin/cyrillic/etc.) independently selectable.
        raw_weight = str(face.get("weight") or "400").strip()
        parts = raw_weight.split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            low, high = sorted((int(parts[0]), int(parts[1])))
            low = max(100, min(900, int(round(low / 100.0) * 100)))
            high = max(100, min(900, int(round(high / 100.0) * 100)))
            weights = [f"{low} {high}"]
        else:
            weights = [parts[0] if parts else "400"]
        style = str(face.get("style") or "normal")
        unicode_range = str(face.get("unicodeRange") or "").strip()
        pending = [weight for weight in weights
                   if (fam.lower(), weight, style, unicode_range) not in seen]
        if not pending:
            continue
        for url in face.get("urls") or []:
            data = _download_font(str(url))
            if not data:
                continue
            stored_url = "/fonts/" + _store_font(data)
            for weight in pending:
                seen.add((fam.lower(), weight, style, unicode_range))
                resolved = {"family": fam, "weight": weight,
                            "style": style, "url": stored_url}
                if unicode_range:
                    resolved["unicodeRange"] = unicode_range
                out.append(resolved)
                if len(out) >= 12:
                    break
            break
        if len(out) >= 12:
            break
    return out


def _qa_pixel_pass(nodes: list, root_frame: dict) -> list:
    """Детерминированный QA-пасс захвата: сверяет flow-арифметику auto-контейнеров
    с измеренным размером. Если сумма детей (+gap+padding) расходится с захваченной
    высотой/шириной сильнее допуска — flow в нашем рендерере поедет (чужие шрифты,
    переносы): контейнер переводится в free, дети пиннятся по захваченным x/y
    (они теперь всегда в кадре) — позиции остаются pixel-perfect по конструкции.
    Возвращает журнал предупреждений."""
    warnings: list = []
    TOL = 3

    def pad_main(frame: dict) -> float:
        pad = frame.get("padding") or 0
        if isinstance(pad, (list, tuple)):
            return float(pad[1] + pad[3]) if frame.get("direction") == "row" else float(pad[0] + pad[2])
        return float(pad) * 2

    def drift(frame: dict, kids: list) -> float:
        gap = float(frame.get("gap") or 0)
        total = pad_main(frame) + gap * max(0, len(kids) - 1)
        for k in kids:
            kf = k.get("frame") or {}
            main = kf.get("width") if frame.get("direction") == "row" else kf.get("height")
            if isinstance(main, (int, float)):
                total += float(main)
        captured = frame.get("width") if frame.get("direction") == "row" else frame.get("height")
        if not isinstance(captured, (int, float)):
            return 0.0
        return total - float(captured)

    def pin(frame: dict, kids: list, path: str) -> None:
        frame["layout"] = "free"
        pinned = 0
        for k in kids:
            kf = k.get("frame") or {}
            if isinstance(kf.get("x"), (int, float)) and isinstance(kf.get("y"), (int, float)):
                kf["absolute"] = True
                pinned += 1
        warnings.append(f"qa: flow drift at {path} -> layout free, pinned {pinned} children")

    def walk(node: dict, path: str) -> None:
        frame = node.get("frame") or {}
        kids = node.get("children") or []
        if frame.get("layout") == "auto" and kids and not frame.get("wrap") \
                and frame.get("justify") not in ("space-between", "space-around"):
            placed = [k for k in kids if not (k.get("frame") or {}).get("absolute")]
            # пинним только ПОЛОЖИТЕЛЬНЫЙ дрейф: контент не влезает в захваченный
            # размер и в нашем рендерере полезет на соседей. Отрицательный дрейф —
            # просто свободное место (row во всю ширину, фикс-высоты) — flow честен.
            if placed and drift(frame, placed) > TOL:
                pin(frame, placed, path)
        for i, k in enumerate(kids):
            if isinstance(k, dict):
                walk(k, f"{path}.{i}")

    walk({"frame": root_frame, "children": nodes}, "root")
    for i, n in enumerate(nodes):
        if isinstance(n, dict):
            walk(n, f"children.{i}")
    return warnings


def _captured_ir(block: dict, capture: dict, page_tokens: dict | None = None) -> dict:
    """DOM-capture → валидный свободный Design IR.

    Это не попытка угадать, что такое «hero» или «footer». Блок остаётся
    фреймом с измеренными слоями — именно такая модель нужна Editor-ноде.
    """
    name = block["name"]
    root = capture["root"]
    root_style = root.get("style", {})
    bg = _css_color_to_hex(root_style.get("background", ""), "#ffffff")
    text = _css_color_to_hex(root_style.get("color", ""), "#171717")
    structured = capture.get("nodes")
    source_preview = capture.get("preview") or ""
    if isinstance(structured, list) and structured:
        children = copy.deepcopy(structured)
    elif source_preview.startswith("data:image"):
        # A visible block with no editable children (canvas-only aside, pseudo-
        # only panel, etc.) becomes a locked raster fallback instead of a hard
        # import error. It stays selectable and keeps the source screenshot as
        # evidence; editable:false + lockedReason mark it as an intrinsically
        # non-editable surface (AI/repair ops stay locked via intentLocks too).
        children = [{
            "type": "image",
            "src": source_preview,
            "alt": f"Raster fallback for {block.get('label') or name}",
            "editable": False,
            "lockedReason": "no editable DOM layers captured: locked raster fallback",
            "sourceMeta": {"kind": "dom", "reason": "raster-fallback"},
            "style": {},
            "frame": {"absolute": True, "x": 0, "y": 0,
                      "width": root["width"], "height": root["height"]},
            "constraints": {"intentLocks": ["appearance", "source-link"]},
        }]
    else:
        children = [{
            "type": "rect",
            "fill": bg,
            "radius": float(root_style.get("radius", 0) or 0),
            "style": {"background": bg},
            "frame": {"absolute": True, "x": 0, "y": 0,
                      "width": root["width"], "height": root["height"]},
        }]
    by_id: dict[str, dict] = {}

    def make_node(layer: dict) -> dict:
        frame = {"absolute": True, "x": layer["x"], "y": layer["y"],
                 "width": layer["width"], "height": layer["height"]}
        style = {k: v for k, v in layer.get("style", {}).items() if v is not None}
        if layer.get("kind") == "container":
            role = str(layer.get("role") or "group")
            if role == "button":
                node = {"type": "button", "text": layer.get("text", ""),
                        "variant": "primary", "style": style, "frame": frame,
                        "children": []}
            elif role == "input":
                node = {"type": "input", "placeholder": layer.get("text", ""),
                        "style": style, "frame": frame, "children": []}
            else:
                node = {"type": "card", "role": role, "style": style,
                        "frame": frame, "children": []}
            return node
        if layer["kind"] == "rect":
            fill = style.get("background", "#ffffff")
            return {"type": "rect", "fill": fill,
                    "radius": float(layer.get("radius", 0) or 0),
                    "style": style, "frame": frame}
        elif layer["kind"] == "image":
            return {"type": "image", "src": layer.get("src", ""),
                    "alt": layer.get("alt", ""), "style": style, "frame": frame}
        # text-узлы не должны нести фон/рамку/тень: это всегда родитель
        for k in ("background", "borderColor", "borderWidth", "borderRadius", "boxShadow"):
            style.pop(k, None)
        return {"type": "text", "text": layer.get("text", ""),
                "style": style, "frame": frame}  # fill у text-нод не хранится

    def shift_to_parent(node: dict, parent: dict) -> None:
        nf = node.get("frame") or {}
        pf = parent.get("frame") or {}
        if "x" in nf and "x" in pf:
            nf["x"] = round(float(nf["x"]) - float(pf["x"]), 3)
        if "y" in nf and "y" in pf:
            nf["y"] = round(float(nf["y"]) - float(pf["y"]), 3)

    for layer in ([] if isinstance(structured, list) else capture.get("layers", [])):
        node = make_node(layer)
        layer_id = layer.get("id")
        parent_id = layer.get("parentId")
        if parent_id and parent_id in by_id:
            parent = by_id[parent_id]
            shift_to_parent(node, parent)
            parent.setdefault("children", []).append(node)
        else:
            children.append(node)
        if layer_id:
            by_id[layer_id] = node

    tokens = page_tokens or {
        "mode": "light", "color": {"primary": text, "background": bg, "surface": bg,
            "text": text, "textMuted": "#666666", "border": "#d1d5db"},
        "font": {"display": {"family": "Inter", "weight": 700},
                 "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "md", "button": "md", "input": "md"},
        "spacing": {"section": "md", "container": "default"}, "shadow": "none",
    }
    semantic = {
        "role": block.get("kind", "section"),
        "label": block.get("label") or name,
        "selector": block.get("selector", ""),
    }
    repeat = capture.get("repeat") or {}
    if int(repeat.get("count", 0) or 0) > 1:
        semantic["repeatCount"] = int(repeat["count"])
        semantic["repeatKind"] = str(repeat.get("kind") or "item")

    source_preview = capture.get("preview") or ""
    root_layout = str(capture.get("layout") or ("auto" if isinstance(structured, list) else "free"))

    root_frame = {"width": root["width"], "height": root["height"],
                  "layout": root_layout,
                  "direction": capture.get("direction", "column"),
                  "gap": float(capture.get("gap", 0) or 0),
                  "padding": capture.get("padding", 0), "clip": True}
    if capture.get("justify"):
        root_frame["justify"] = capture.get("justify")
    if capture.get("align"):
        root_frame["align"] = capture.get("align")

    # дополнительный QA-контур парсера: дрейф flow → free + пиннинг по захваченным x/y
    qa_warnings = _qa_pixel_pass(children, root_frame)

    # шрифты источника: только использованные в блоке семьи, файлы — в базе /fonts
    used_families: set = set()
    used_font_weights: dict[str, set[int]] = {}
    for ch in children:
        _collect_used_families(ch, used_families)
        _collect_used_font_weights(ch, used_font_weights)
    _collect_used_families({"style": root_style}, used_families)
    _collect_used_font_weights({"style": root_style}, used_font_weights)
    font_faces = _resolve_font_faces(capture.get("fontFaces") or [], used_families, used_font_weights)

    return {
        "version": "1.0",
        "meta": {"name": f"Импорт: {semantic['label']}",
                 "description": f"Rendered DOM capture · {semantic['role']}",
                 "qaWarnings": qa_warnings,
                 "fontFaces": font_faces},
        "sourcePreview": source_preview,
        # The browser measures this block as its own artboard. Keeping the same
        # root frame prevents Editor from falling back to the generic 960px
        # design canvas and makes section coordinates true artboard coordinates.
        # The section itself owns the captured padding. Repeating it on the
        # outer artboard shifts/scales the entire source block while relative
        # leaf bbox checks remain deceptively green.
        "frame": {k: copy.deepcopy(v) for k, v in root_frame.items() if k != "padding"},
        "tokens": tokens,
        "tree": [{"id": "imported-block", "type": "source-block", "variant": "dom-capture",
                  "semantic": semantic, "props": {"sourcePreview": source_preview},
                  "preview": source_preview,
                  "sourceKey": capture.get("sourceKey", "root"),
                  "style": {k: v for k, v in root_style.items() if v is not None},
                  "frame": copy.deepcopy(root_frame),
                  "children": children}],
    }


DEFAULT_SOURCE_VIEWPORTS = (
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
)


def _normalize_source_viewports(viewports: list[dict] | None) -> list[dict]:
    allowed = {"desktop", "tablet", "mobile"}
    source = viewports or list(DEFAULT_SOURCE_VIEWPORTS)
    out = []
    seen = set()
    for raw in source:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").lower()
        if name not in allowed or name in seen:
            continue
        width = max(240, min(3840, int(raw.get("width") or 0)))
        height = max(320, min(2400, int(raw.get("height") or 0)))
        out.append({"name": name, "width": width, "height": height})
        seen.add(name)
    if not out:
        return [dict(v) for v in DEFAULT_SOURCE_VIEWPORTS]
    order = {"desktop": 0, "tablet": 1, "mobile": 2}
    return sorted(out, key=lambda v: order[v["name"]])


def _walk_source_nodes(nodes: list, parent: dict | None = None):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node, parent
        yield from _walk_source_nodes(node.get("children") or [], node)


def _responsive_override(node: dict) -> dict:
    override = {"visible": True}
    if isinstance(node.get("frame"), dict):
        override["frame"] = copy.deepcopy(node["frame"])
    if isinstance(node.get("style"), dict) and node["style"]:
        override["style"] = copy.deepcopy(node["style"])
    if node.get("type") == "image" and isinstance(node.get("src"), str) and node["src"]:
        override["src"] = node["src"]
    return override


def _merge_responsive_irs(variants: dict[str, dict], viewport_meta: dict[str, dict]) -> dict:
    """Merge viewport captures into one shared tree keyed by stable DOM paths."""
    base_name = "desktop" if "desktop" in variants else next(iter(variants))
    merged = copy.deepcopy(variants[base_name])
    merged["responsive"] = {"viewports": copy.deepcopy(viewport_meta)}
    base_sec = merged["tree"][0]

    def maps(sec: dict):
        by_key = {str(sec.get("sourceKey") or "root"): sec}
        parents = {}
        for node, parent in _walk_source_nodes(sec.get("children") or [], sec):
            key = str(node.get("sourceKey") or "")
            if key:
                by_key[key] = node
                parents[key] = parent
        return by_key, parents

    base_map, _ = maps(base_sec)
    all_names = list(viewport_meta)

    def index_subtree(node: dict) -> None:
        key = str(node.get("sourceKey") or "")
        if key:
            base_map[key] = node
        for child in node.get("children") or []:
            if isinstance(child, dict):
                index_subtree(child)

    def has_missing_ancestor(key: str, current_parents: dict[str, dict], missing: set[str]) -> bool:
        parent = current_parents.get(key)
        while isinstance(parent, dict):
            parent_key = str(parent.get("sourceKey") or "")
            if parent_key in missing:
                return True
            if parent_key == "root":
                return False
            parent = current_parents.get(parent_key)
        return False

    for name, variant in variants.items():
        current_sec = variant["tree"][0]
        current_map, current_parents = maps(current_sec)

        # Add viewport-only branches to the nearest shared parent. They stay hidden
        # in the base viewport and become visible through their responsive override.
        missing_keys = {key for key, current in current_map.items() if key not in base_map and current is not current_sec}
        for key, current in sorted(list(current_map.items()), key=lambda item: item[0].count("/")):
            if key in base_map or current is current_sec:
                continue
            if has_missing_ancestor(key, current_parents, missing_keys):
                continue
            parent = current_parents.get(key)
            parent_key = str((parent or {}).get("sourceKey") or "root")
            target_parent = base_map.get(parent_key, base_sec)
            clone = copy.deepcopy(current)
            clone["responsive"] = {bp: {"visible": False} for bp in all_names}
            clone["responsive"][name] = _responsive_override(current)
            target_parent.setdefault("children", []).append(clone)
            index_subtree(clone)

        for key, target in list(base_map.items()):
            if target is base_sec:
                continue
            current = current_map.get(key)
            target.setdefault("responsive", {})[name] = (
                _responsive_override(current) if current else {"visible": False}
            )

        base_sec.setdefault("responsive", {})[name] = _responsive_override(current_sec)

    # Desktop-base nodes need no redundant desktop override unless a node was
    # introduced by another viewport and therefore explicitly hidden on desktop.
    if base_name == "desktop":
        for target in base_map.values():
            responsive = target.get("responsive")
            if isinstance(responsive, dict) and responsive.get("desktop", {}).get("visible") is True:
                responsive.pop("desktop", None)
            if responsive == {}:
                target.pop("responsive", None)

    # Viewport-only branches are copied into the shared tree whole, and their
    # nested keys may collide with keys already present. sourceKey is the stable
    # element address for merge-back/editor selection, so after merge we enforce
    # uniqueness deterministically: the first occurrence keeps the key, repeats
    # get a zero-padded suffix (#001, #002, ...). Content is preserved; only the
    # identity key is renamed.
    seen_keys: set[str] = set()
    for node, _parent in _walk_source_nodes([base_sec]):
        key = str(node.get("sourceKey") or "")
        if not key:
            continue
        if key not in seen_keys:
            seen_keys.add(key)
            continue
        n = 1
        unique = f"{key}#{n:03d}"
        while unique in seen_keys:
            n += 1
            unique = f"{key}#{n:03d}"
        node["sourceKey"] = unique
        seen_keys.add(unique)
    return merged


def capture_block_irs(url: str, blocks: list[dict], viewport_w: int = 1440,
                      viewport_h: int = 900, timeout_ms: int = 20000,
                      return_tokens: bool = False, viewports: list[dict] | None = None,
                      cookies: list[dict] | None = None):
    """Compile rendered DOM into compact responsive Design IR.

    Text is collected from direct text nodes, so it always remains inside its
    semantic DOM parent. Flex/grid geometry becomes auto-layout; absolute frames
    are reserved for elements that are actually positioned out of flow.
    """
    from playwright.sync_api import sync_playwright

    validate_public_url(url)
    viewport_defs = _normalize_source_viewports(viewports)
    captures: dict[str, dict[str, dict]] = {}
    token_signals = None
    compiler_js = (Path(__file__).resolve().parent / "source_import_compiler.js").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.launch(headless=True)
            context, page = _guarded_browser_page(
                browser,
                {"width": viewport_defs[0]["width"], "height": viewport_defs[0]["height"]},
            )
            source_cookies = _normalize_source_cookies(cookies, url)
            if cookies is not None and not source_cookies:
                raise ValueError("Authenticated Source Import session has no valid cookies for this URL")
            if source_cookies:
                context.add_cookies(source_cookies)
            # Один Chromium-сеанс, ОДНА навигация: все viewport-ы снимаются с
            # того же DOM через resize + settle (fonts/images/2rAF). Повторный
            # goto недетерминирован (lazy-hydration, A/B) и вдвое дороже.
            # networkidle у живых storefront-ов не наступает (analytics/websocket),
            # поэтому DOMContentLoaded + детерминированный settle.
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            validate_public_url(page.url)
            _wait_capture_settle(page)
            page.add_style_tag(content="""
              *, *::before, *::after { animation:none !important; transition:none !important; }
              html { scroll-behavior:auto !important; }
            """)
            for index, viewport in enumerate(viewport_defs):
                if index:
                    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
                    # после resize могут догрузиться responsive images/шрифты
                    _wait_capture_settle(page)
                if index == 0:
                    # дизайн-токены страницы снимаем один раз, на desktop-проходе
                    try:
                        token_signals = page.evaluate(_PAGE_TOKEN_SIGNALS_JS)
                    except Exception:
                        token_signals = None
                raw = page.evaluate(compiler_js, blocks)
                by_selector = {item["selector"]: item for item in raw}
                for block in blocks:
                    item = by_selector.get(block["selector"])
                    if not item or item.get("error"):
                        continue
                    # Capture inherited backdrop before the reference while the
                    # locator establishes its scroll position. The reference is
                    # then taken immediately at the identical fixed-background
                    # phase/offset (critical for mobile pages).
                    for req in item.get("rasterRequests") or []:
                        if req.get("mode") != "backdrop":
                            continue
                        node = _find_source_node(item.get("nodes"), req.get("sourceKey"))
                        if node is None:
                            continue
                        locator = page.locator(block["selector"]).first
                        try:
                            locator.scroll_into_view_if_needed()
                            previous_visibility = locator.evaluate(
                                "el => Array.from(el.children).map(child => child.style.visibility)")
                            locator.evaluate(
                                "el => Array.from(el.children).forEach(child => child.style.setProperty('visibility','hidden','important'))")
                            try:
                                backdrop_shot = locator.screenshot(type="png")
                            finally:
                                locator.evaluate(
                                    "(el, values) => Array.from(el.children).forEach((child, i) => { "
                                    "child.style.removeProperty('visibility'); "
                                    "if (values[i]) child.style.visibility = values[i]; })",
                                    previous_visibility)
                            node["src"] = "data:image/png;base64," + base64.b64encode(backdrop_shot).decode()
                        except Exception:
                            pass
                    try:
                        shot = page.locator(block["selector"]).first.screenshot(type="png")
                        target_w = int(item["root"]["width"])
                        target_h = int(item["root"]["height"])
                        with Image.open(io.BytesIO(shot)) as captured_image:
                            # Element screenshots snap fractional CSS bounds to
                            # device pixels and may gain one bottom/right pixel.
                            # Crop only (never resize) to the exact measured IR
                            # artboard so reference and render use identical dims.
                            if (captured_image.width, captured_image.height) != (target_w, target_h) \
                                    and captured_image.width >= target_w and captured_image.height >= target_h \
                                    and captured_image.width - target_w <= 2 \
                                    and captured_image.height - target_h <= 2:
                                normalized = captured_image.convert("RGB").crop((0, 0, target_w, target_h))
                                out = io.BytesIO()
                                normalized.save(out, format="PNG")
                                shot = out.getvalue()
                        item["preview"] = "data:image/png;base64," + base64.b64encode(shot).decode()
                    except Exception:
                        pass
                    # raster fallback для неeditable-поверхностей (canvas/webgl/
                    # iframe/closed shadow): компилятор не может их сериализовать,
                    # поэтому просит element-screenshot. Слой остаётся видимым.
                    for req in item.get("rasterRequests") or []:
                        node = _find_source_node(item.get("nodes"), req.get("sourceKey"))
                        if node is None or str(node.get("src") or "").startswith("data:image"):
                            continue
                        selector = f"{block['selector']} {req.get('selector')}".strip()
                        try:
                            locator = page.locator(selector).first
                            previous_visibility = None
                            if req.get("mode") == "backdrop":
                                previous_visibility = locator.evaluate(
                                    "el => Array.from(el.children).map(child => child.style.visibility)")
                                locator.evaluate(
                                    "el => Array.from(el.children).forEach(child => child.style.setProperty('visibility','hidden','important'))")
                            try:
                                shot = locator.screenshot(type="png")
                            finally:
                                if previous_visibility is not None:
                                    locator.evaluate(
                                        "(el, values) => Array.from(el.children).forEach((child, i) => { "
                                        "child.style.removeProperty('visibility'); "
                                        "if (values[i]) child.style.visibility = values[i]; })",
                                        previous_visibility)
                            node["src"] = "data:image/png;base64," + base64.b64encode(shot).decode()
                        except Exception:
                            item.setdefault("extras", []).append({
                                "sourceKey": str(req.get("sourceKey") or ""),
                                "reason": "raster-unavailable", "visual": True,
                                "rect": {"x": 0, "y": 0, "width": 0, "height": 0}})
                    _namespace_block_keys(item, re.sub(r"[^A-Za-z0-9_-]+", "-", str(block.get("name") or "block")))
                captures[viewport["name"]] = by_selector
        finally:
            if context is not None:
                with contextlib.suppress(Exception):
                    context.close()
            if browser is not None:
                with contextlib.suppress(Exception):
                    browser.close()

    page_tokens = _page_tokens_from_signals(token_signals)
    result: dict[str, dict] = {}
    for block in blocks:
        selector = block["selector"]
        variants = {}
        meta = {}
        warnings = set()
        layers_by_viewport = {}
        editable_layers_by_viewport: dict[str, int] = {}
        component_boundaries_by_viewport: dict[str, int] = {}
        visited_by_viewport: dict[str, int] = {}
        dropped_by_viewport: dict[str, list] = {}
        extras_by_viewport: dict[str, list] = {}
        paint_coverage: dict[str, int] = {}
        coverage: dict[str, int] = {}
        leaf_boxes_by_viewport: dict[str, list] = {}
        for viewport in viewport_defs:
            name = viewport["name"]
            item = captures.get(name, {}).get(selector)
            # Empty editable nodes are OK when we have a source screenshot: the
            # block becomes a locked raster fallback instead of a hard error.
            if not item or item.get("error") or (
                not item.get("nodes") and not str(item.get("preview") or "").startswith("data:image")
            ):
                continue
            ir = _captured_ir(block, item, page_tokens)
            variants[name] = ir
            meta[name] = {"width": item["root"]["width"], "height": item["root"]["height"],
                          "preview": item.get("preview", "")}
            warnings.update(item.get("warnings") or [])
            editable_layers_by_viewport[name] = int(item.get("emitted") or 0)
            component_boundaries_by_viewport[name] = int(item.get("componentBoundaries") or 0)
            visited_by_viewport[name] = int(item.get("visited") or 0)
            dropped_by_viewport[name] = item.get("dropped") or []
            extras_by_viewport[name] = item.get("extras") or []
            paint_coverage[name] = int(item.get("paintCoverage") or 0)
            coverage[name] = int(item.get("coverage") or paint_coverage[name])
            leaf_boxes_by_viewport[name] = item.get("leafBoxes") or []
        if not variants:
            result[selector] = {"error": "DOM block has no editable visible layers in selected viewports"}
            continue
        merged = _merge_responsive_irs(variants, meta)
        base_name = "desktop" if "desktop" in meta else next(iter(meta))
        result[selector] = {
            "ir": merged,
            "layer_count": max(editable_layers_by_viewport.values(), default=0),
            "layers_by_viewport": editable_layers_by_viewport,
            "editable_layers_by_viewport": editable_layers_by_viewport,
            "component_boundaries_by_viewport": component_boundaries_by_viewport,
            "visited_by_viewport": visited_by_viewport,
            "dropped_by_viewport": dropped_by_viewport,
            "extras_by_viewport": extras_by_viewport,
            "paint_coverage": paint_coverage,
            "coverage": coverage,
            "leaf_boxes_by_viewport": leaf_boxes_by_viewport,
            "width": meta[base_name]["width"], "height": meta[base_name]["height"],
            "preview": meta[base_name].get("preview", ""),
            "previews": {name: value.get("preview", "") for name, value in meta.items()},
            "sizes": {name: {"width": value["width"], "height": value["height"]} for name, value in meta.items()},
            "warnings": sorted(warnings),
        }
    try:
        _attach_block_fidelity(result)
    except Exception:
        pass  # fidelity — честная диагностика, но не должна ронять импорт
    return (result, page_tokens) if return_tokens else result


# ---------- Fidelity: честное пиксельное сходство IR со скриншотом источника ----------

_APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
_RENDERER_JS = _APP_ROOT / "static" / "flow" / "engine.js"


def _render_ir_png(page, ir: dict, width: int, height: int) -> bytes:
    """Отрисовать IR движком редактора (app/static/flow/engine.js) и вернуть PNG."""
    page.set_viewport_size({"width": max(320, int(width)), "height": max(320, int(height) + 40)})
    page.set_content(f'<div id="preview" style="width:{int(width)}px"></div>')
    page.add_script_tag(path=str(_RENDERER_JS))
    page.evaluate("(ir) => window.IRRenderer.renderIR(document.querySelector('#preview'), ir)", ir)
    page.wait_for_selector('[data-ir-sec="0"]', timeout=5000)
    # fitPreview выставляет высоту контейнера в requestAnimationFrame
    page.wait_for_function("() => document.querySelector('#preview').style.height !== ''", timeout=5000)
    return page.locator("#preview").screenshot(type="png")


def _pixel_similarity(render_png: bytes, reference_data_url: str) -> float | None:
    """Доля пикселей с per-channel |diff| < 24 в ТОЧНОМ размере, 0-100.

    Ресайз LANCZOS к размеру референса запрещён: он прятал layout-дрейф
    (сдвинутая сетка того же палитры давала высокий скор). Расхождение
    размеров — честный ноль, как в fidelity harness."""
    try:
        import numpy as np
        _, b64 = reference_data_url.split(",", 1)
        ref = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        got = Image.open(io.BytesIO(render_png)).convert("RGB")
        if got.size != ref.size:
            return 0.0
        diff = np.abs(np.asarray(got, dtype=np.int16) - np.asarray(ref, dtype=np.int16))
        return round(float((diff < 24).all(axis=2).mean()) * 100)
    except Exception:
        return None


def ir_fidelity(ir: dict, reference_jpeg_data_url: str, width: int, height: int,
                page=None) -> float | None:
    """Пиксельное сходство рендера IR со скриншотом источника, 0-100.

    Рендер — тем же движком (app/static/flow/engine.js), что и редактор, поэтому
    метрика измеряет именно то, что увидит пользователь. None при любой ошибке (нет
    Chromium, битый data URL, renderer не отрисовал) — функция никогда не кидает.
    page — переиспользуемая вкладка для пакетного прогона; без неё поднимаем
    одноразовый headless Chromium.
    """
    try:
        if not str(reference_jpeg_data_url or "").startswith("data:image"):
            return None
        if page is not None:
            shot = _render_ir_png(page, ir, width, height)
        else:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    shot = _render_ir_png(browser.new_page(), ir, width, height)
                finally:
                    browser.close()
        return _pixel_similarity(shot, reference_jpeg_data_url)
    except Exception:
        return None


def _p95_layout_error(page, leaf_boxes: list[dict]) -> float | None:
    """Structural layout error: 95th percentile of |Δx|,|Δy|,|Δw|,|Δh| for
    matched source keys between captured leaf boxes and the rendered IR."""
    try:
        rendered = page.evaluate("""() => {
          const sec = document.querySelector('[data-ir-sec="0"]');
          if (!sec) return {};
          const root = sec.getBoundingClientRect();
          const out = {};
          sec.querySelectorAll('[data-ir-path]').forEach(el => {
            const r = el.getBoundingClientRect();
            out[el.getAttribute('data-ir-path')] = {
              x: Math.round(r.left - root.left),
              y: Math.round(r.top - root.top),
              width: Math.round(r.width),
              height: Math.round(r.height)
            };
          });
          return out;
        }""")
    except Exception:
        return None
    if not leaf_boxes:
        return None
    diffs: list[float] = []
    for box in leaf_boxes:
        ref = rendered.get(str(box.get("sourceKey") or ""))
        if ref:
            diffs.append(max(
                abs(float(box.get("x", 0)) - ref["x"]),
                abs(float(box.get("y", 0)) - ref["y"]),
                abs(float(box.get("width", 0)) - ref["width"]),
                abs(float(box.get("height", 0)) - ref["height"]),
            ))
        else:
            diffs.append(max(float(box.get("width", 100)), float(box.get("height", 100)), 100.0))
    diffs.sort()
    idx = max(0, int(math.ceil(0.95 * len(diffs))) - 1)
    return float(diffs[idx])


def _attach_block_fidelity(result: dict) -> None:
    """Fidelity base-viewport (desktop): merged IR против скриншота источника.

    Один лёгкий Chromium на все блоки, после закрытия capture-браузера. Считаем
    только base viewport — для метрики достаточно, а прогон остаётся быстрым.
    """
    jobs = []
    for selector, item in result.items():
        if not isinstance(item, dict) or item.get("error") or not isinstance(item.get("ir"), dict):
            continue
        preview = str(item.get("preview") or "")
        width, height = item.get("width"), item.get("height")
        if not preview.startswith("data:image") or not width or not height:
            continue
        jobs.append((selector, item, preview, int(width), int(height)))
    if not jobs:
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            for selector, item, preview, width, height in jobs:
                try:
                    shot = _render_ir_png(page, item["ir"], width, height)
                    score = _pixel_similarity(shot, preview)
                except Exception:
                    score = None
                viewports = item.get("coverage") or {}
                base_name = "desktop" if "desktop" in viewports else next(iter(viewports))
                leaf_boxes = (item.get("leaf_boxes_by_viewport") or {}).get(base_name, [])
                p95 = None
                if leaf_boxes:
                    try:
                        p95 = _p95_layout_error(page, leaf_boxes)
                    except Exception:
                        p95 = None
                item["fidelity"] = {vp: None for vp in viewports}
                item["p95_layout_error"] = {vp: None for vp in viewports}
                if score is not None:
                    item["fidelity"][base_name] = score
                if p95 is not None:
                    item["p95_layout_error"][base_name] = round(p95, 2)
                # Mirror into the IR responsive payload for the editor/schema.
                # None не пишем: схема требует number, недоступная метрика
                # просто отсутствует.
                ir_viewports = item["ir"].get("responsive", {}).get("viewports") or {}
                if score is not None and base_name and isinstance(ir_viewports.get(base_name), dict):
                    ir_viewports[base_name]["fidelity"] = score
        finally:
            browser.close()


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
