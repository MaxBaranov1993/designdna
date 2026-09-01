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
import errno
import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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
# Верхняя граница выдачи. Раньше лишние блоки отсекались молча — теперь
# усечение попадает в diagnostics импорта (см. parse_blocks).
_MAX_BLOCKS = 28
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


def _structural_role(el: Tag) -> str:
    """Роль по структуре содержимого — без имён классов и языковых литералов.

    Регэкспы по id/class и по тексту заголовков работают только на сайтах, чью
    вёрстку и язык мы заранее знаем. Здесь роль выводится из того, из чего блок
    состоит: повторяющиеся однотипные потомки — сетка, форма — CTA, длинный
    список ссылок — навигация. Возвращает "section", если структура ничего
    определённого не говорит.
    """
    if el.find(["input", "select", "textarea"]) and el.find(["button", "form"]):
        return "cta"

    # Повтор: ≥3 потомка одного тега с сопоставимым составом содержимого.
    for container in [el, *el.find_all(["ul", "ol", "div"], recursive=True, limit=12)]:
        children = [child for child in container.find_all(recursive=False) if isinstance(child, Tag)]
        if len(children) < 3:
            continue
        tags = [child.name for child in children]
        dominant = max(set(tags), key=tags.count)
        repeated = [child for child in children if child.name == dominant]
        if len(repeated) < 3:
            continue
        with_media = sum(1 for child in repeated if child.find(["img", "svg", "picture", "video"]))
        with_heading = sum(1 for child in repeated if child.find(["h1", "h2", "h3", "h4", "h5", "h6"]))
        if with_media >= len(repeated) // 2 and with_heading:
            return "product-grid"
        if with_media >= len(repeated) // 2:
            return "gallery"
        if with_heading:
            return "journal"

    links = el.find_all("a", href=True)
    text_length = len(el.get_text(" ", strip=True))
    if len(links) >= 6 and text_length and text_length < 40 * len(links):
        return "navigation"
    return "section"


def _semantic_role(el: Tag) -> str:
    """Best-effort semantic role without treating repeated cards as page sections."""
    identity_role = _identity_role(el)
    if identity_role != "section":
        if identity_role == "product-grid" and _HEADING_PATTERNS[0][1].search(_block_heading(el)):
            return "services-grid"
        return identity_role

    # Языковые подсказки по заголовку остаются, но только как подсказки:
    # на сайте на неизвестном языке решает структура, а не словарь.
    heading = _block_heading(el)
    for role, pattern in _HEADING_PATTERNS:
        if pattern.search(heading):
            return role

    structural_role = _structural_role(el)
    if structural_role != "section":
        return structural_role

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

    # Все верхнеуровневые header/footer, а не только первые: страницы с
    # несколькими шапками (языковая полоса + основная навигация) теряли их.
    for el in body.find_all("header"):
        if not any(parent.name in ("header", "footer") for parent in el.parents):
            add(el)

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

    for el in body.find_all("footer"):
        if not any(parent.name in ("header", "footer") for parent in el.parents):
            add(el)

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

    # Last-resort fallback (html.to.design default): import the whole page as
    # one block. Old-school/table-based/legacy sites (no semantics, no h1/h2)
    # previously produced ZERO blocks and the import came back empty.
    if not meaningful:
        meaningful = [body]

    blocks = []
    names: set[str] = set()
    truncated = max(0, len(meaningful) - _MAX_BLOCKS)
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
    # Усечение больше не молчаливое: помечаем последний блок, чтобы pipeline
    # мог доложить о потере в diagnostics вместо вида «всё импортировано».
    if truncated and blocks:
        blocks[-1]["truncatedAfter"] = truncated
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


# ---------- lossless capture/replay intermediates ----------
# Capture and IR replay must consume the same content-addressed source bytes
# decoded once to a PNG at the measured CSS box. Chromium's WebP/JPEG decode
# + CSS resample is not bit-stable across the source page vs <img> replay
# (live residual: Z.AI/arena section-2 mobile 84.86 vs the 85.0 gate).

SOURCE_CAPTURE_VERSION = "asset-blob-v2"
BLOCK_LAZY_SETTLE_MS = 1200
MATERIALIZED_IMAGE_SETTLE_MS = 1500
_MAX_ASSET_BYTES = 8_000_000
_MAX_ASSET_EDGE = 4096
BLOB_REF_PREFIX = "ddna://blobs/"
_BLOB_REF_RE = re.compile(r"^ddna://blobs/([0-9a-f]{64})\.png$")
_RASTER_DATA_URL_RE = re.compile(r"^data:image/(png|jpe?g|webp|gif|avif|bmp)\b", re.I)


def _object_position_fractions(value: str | None) -> tuple[float, float]:
    """CSS object-position / background-position → (x, y) in 0..1."""
    raw = str(value or "50% 50%").strip().lower().replace(",", " ")
    keywords = {"left": 0.0, "center": 0.5, "right": 1.0, "top": 0.0, "bottom": 1.0}

    def axis_token(tok: str, axis: str) -> float | None:
        tok = tok.strip()
        if tok in keywords:
            if axis == "x" and tok in ("top", "bottom"):
                return None
            if axis == "y" and tok in ("left", "right"):
                return None
            return keywords[tok]
        if tok.endswith("%"):
            try:
                return max(0.0, min(1.0, float(tok[:-1]) / 100.0))
            except ValueError:
                return None
        try:
            number = float(tok)
        except ValueError:
            return None
        if number > 1.0:
            return max(0.0, min(1.0, number / 100.0))
        return max(0.0, min(1.0, number))

    parts = [part for part in raw.split() if part]
    if not parts:
        return 0.5, 0.5
    if len(parts) == 1:
        token = parts[0]
        if token in ("top", "bottom"):
            return 0.5, keywords[token]
        if token in ("left", "right"):
            return keywords[token], 0.5
        x = axis_token(token, "x")
        return (x if x is not None else 0.5), 0.5
    x = axis_token(parts[0], "x")
    y = axis_token(parts[1], "y")
    return (x if x is not None else 0.5), (y if y is not None else 0.5)


def _fit_raster(im: Image.Image, width: int, height: int, fit: str | None,
                position: str | None) -> Image.Image:
    """Deterministic object-fit resize of a decoded raster into an RGBA box."""
    width = max(1, min(_MAX_ASSET_EDGE, int(width or 1)))
    height = max(1, min(_MAX_ASSET_EDGE, int(height or 1)))
    src = im.convert("RGBA") if im.mode != "RGBA" else im
    src_w, src_h = src.size
    kind = str(fit or "fill").lower()
    px, py = _object_position_fractions(position)
    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if kind == "fill" or src_w <= 0 or src_h <= 0:
        out.paste(src.resize((width, height), Image.Resampling.LANCZOS), (0, 0))
        return out
    if kind == "none":
        left = int((src_w - width) * px)
        top = int((src_h - height) * py)
        box = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        box.paste(src, (-left, -top))
        return box
    contain = min(width / src_w, height / src_h)
    cover = max(width / src_w, height / src_h)
    if kind == "scale-down":
        scale = min(1.0, contain)
    elif kind == "cover":
        scale = cover
    else:
        scale = contain
    nw = max(1, int(round(src_w * scale)))
    nh = max(1, int(round(src_h * scale)))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if kind == "cover":
        left = max(0, min(nw - width, int((nw - width) * px)))
        top = max(0, min(nh - height, int((nh - height) * py)))
        out.paste(resized.crop((left, top, left + width, top + height)), (0, 0))
        return out
    left = max(0, min(width - nw, int((width - nw) * px)))
    top = max(0, min(height - nh, int((height - nh) * py)))
    out.paste(resized, (left, top))
    return out


def lossless_png_from_bytes(raw: bytes, width: int, height: int, fit: str | None = "fill",
                            position: str | None = "50% 50%") -> bytes:
    """Decode source bytes once and emit a PNG at the measured CSS box."""
    if not raw:
        raise ValueError("empty raster bytes")
    with Image.open(io.BytesIO(raw)) as im:
        fitted = _fit_raster(im, width, height, fit, position)
    buf = io.BytesIO()
    fitted.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def blobs_dir() -> Path:
    """Immutable PNG objects live in DESIGNDNA_DATA_DIR/blobs (same dir Electron serves)."""
    root = Path(os.environ.get("DESIGNDNA_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
    return root / "blobs"


def blob_object_name(object_sha256: str) -> str:
    digest = str(object_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid object sha256")
    return f"{digest}.png"


def blob_ref(object_sha256: str) -> str:
    return BLOB_REF_PREFIX + blob_object_name(object_sha256)


def parse_blob_ref(src: str | None) -> str | None:
    match = _BLOB_REF_RE.fullmatch(str(src or "").strip())
    return match.group(1) if match else None


def is_raster_data_url(src: str | None) -> bool:
    return bool(_RASTER_DATA_URL_RE.match(str(src or "")))


def put_png_blob(png: bytes) -> str:
    """Store PNG bytes under sha256(png).png.

    Publication is create-if-absent: a unique fully-written temp is linked onto
    the digest name (O_EXCL-equivalent). If the target already exists we verify
    exact bytes/hash and reuse; we never replace or delete an existing object.
    """
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG object")
    digest = hashlib.sha256(png).hexdigest()
    directory = blobs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / blob_object_name(digest)
    target_s = os.fspath(target)

    def reuse_existing() -> str:
        existing = target.read_bytes()
        existing_digest = hashlib.sha256(existing).hexdigest()
        if existing_digest != digest or existing != png:
            raise ValueError(f"blob {digest} exists with different bytes; refusing overwrite")
        return digest

    if target.exists():
        return reuse_existing()

    fd, tmp_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=os.fspath(directory))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(png)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, target_s)
        except FileExistsError:
            return reuse_existing()
        except OSError as exc:
            # Windows: ERROR_ALREADY_EXISTS=183; some FS raise EEXIST/EACCES.
            if exc.errno in (errno.EEXIST,) or getattr(exc, "winerror", None) == 183:
                return reuse_existing()
            if target.exists():
                return reuse_existing()
            raise
        stored = target.read_bytes()
        if hashlib.sha256(stored).hexdigest() != digest or stored != png:
            raise ValueError("blob write failed integrity check")
        return digest
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)


def read_png_blob(object_sha256: str) -> bytes:
    digest = str(object_sha256 or "").strip().lower()
    path = blobs_dir() / blob_object_name(digest)
    if not path.is_file():
        raise FileNotFoundError(f"missing blob {digest}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"corrupt blob {digest}")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"blob {digest} is not PNG")
    return data


def _store_png_src(png: bytes) -> str:
    return blob_ref(put_png_blob(png))


def ir_raster_data_urls(ir: dict | None) -> list[str]:
    found: list[str] = []

    def visit(node) -> None:
        if isinstance(node, str):
            if is_raster_data_url(node):
                found.append(node[:48])
            return
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in ("src", "sourcePreview", "preview") and isinstance(value, str):
                if is_raster_data_url(value):
                    found.append(value[:48])
            else:
                visit(value)

    visit(ir)
    return found


def resolve_ir_blobs(ir: dict) -> tuple[dict, list[str]]:
    """Deep-copy IR and expand ddna://blobs refs to data URLs for a one-shot render.

    Canonical IR is not mutated. Missing/corrupt objects and leftover raster
    data URLs fail closed (returned as errors).
    """
    clone = copy.deepcopy(ir)
    errors: list[str] = []

    def resolve_src(holder: dict, key: str) -> None:
        src = holder.get(key)
        if not isinstance(src, str) or not src:
            return
        if is_raster_data_url(src):
            errors.append(f"{key} still has raster data URL")
            return
        digest = parse_blob_ref(src)
        if not digest:
            return
        try:
            png = read_png_blob(digest)
        except Exception as exc:
            errors.append(f"{key} blob {digest[:12]}: {exc}")
            return
        holder[key] = png_data_url(png)

    def visit(node) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("src", "sourcePreview", "preview"):
            if isinstance(node.get(key), str):
                resolve_src(node, key)
        props = node.get("props")
        if isinstance(props, dict) and isinstance(props.get("sourcePreview"), str):
            resolve_src(props, "sourcePreview")
        responsive = node.get("responsive")
        if isinstance(responsive, dict):
            for override in responsive.values():
                if isinstance(override, dict):
                    visit(override)
        for child in node.get("children") or []:
            visit(child)
        for section in node.get("tree") or []:
            visit(section)

    visit(clone)
    return clone, errors


def _persist_ir_raster_data_urls(ir: dict) -> None:
    """Replace leftover PNG/JPEG data URLs in canonical IR with blob refs."""

    def persist(holder: dict, key: str) -> None:
        src = holder.get(key)
        if not isinstance(src, str) or not is_raster_data_url(src):
            return
        decoded = _decode_data_url_bytes(src)
        if not decoded:
            return
        raw, _mime = decoded
        try:
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                png = raw
            else:
                with Image.open(io.BytesIO(raw)) as im:
                    buf = io.BytesIO()
                    im.convert("RGBA").save(buf, format="PNG")
                    png = buf.getvalue()
            holder[key] = _store_png_src(png)
        except Exception:
            return

    def visit(node) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in list(node.items()):
            if isinstance(value, str) and is_raster_data_url(value):
                persist(node, key)
            else:
                visit(value)

    visit(ir)


def _decode_data_url_bytes(src: str) -> tuple[bytes, str] | None:
    if not src.startswith("data:"):
        return None
    head, _, payload = src.partition(",")
    if not payload:
        return None
    mime = head[5:].split(";", 1)[0].strip().lower() or "application/octet-stream"
    try:
        if ";base64" in head.lower():
            raw = base64.b64decode(payload)
        else:
            from urllib.parse import unquote_to_bytes
            raw = unquote_to_bytes(payload)
    except Exception:
        return None
    return raw, mime


def _sniff_image_mime(raw: bytes, src: str, declared: str = "") -> str:
    declared = (declared or "").split(";", 1)[0].strip().lower()
    if declared.startswith("image/"):
        return declared
    if raw[:12] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"\x00\x00\x00\x1c" or src.lower().endswith(".avif"):
        return "image/avif"
    lowered = src.lower()
    for ext, mime in ((".webp", "image/webp"), (".jpg", "image/jpeg"),
                      (".jpeg", "image/jpeg"), (".png", "image/png"),
                      (".gif", "image/gif"), (".avif", "image/avif")):
        if lowered.endswith(ext) or ext in lowered:
            return mime
    return "application/octet-stream"


def _is_image_response(url: str, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    if ctype.startswith("image/"):
        return True
    path = urlparse(url).path.lower()
    return path.endswith((".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif", ".bmp"))


def _remember_image_body(asset_bodies: dict[str, bytes], url: str, body: bytes) -> None:
    if not url or not body or len(body) > _MAX_ASSET_BYTES:
        return
    asset_bodies.setdefault(url, body)


def install_image_body_listener(page, asset_bodies: dict[str, bytes]):
    """Queue image responses; drain bodies after navigation (body() in the
    response event deadlocks Chromium's network stack)."""
    pending: list = []

    def _on_response(response) -> None:
        try:
            url = str(response.url or "")
            if not url or not _is_image_response(url, response.headers.get("content-type") or ""):
                return
            pending.append(response)
        except Exception:
            return

    def drain() -> None:
        while pending:
            response = pending.pop()
            try:
                _remember_image_body(asset_bodies, str(response.url or ""), response.body())
            except Exception:
                continue

    page.on("response", _on_response)
    return drain


def _lookup_asset_body(asset_bodies: dict[str, bytes], src: str) -> bytes | None:
    if src in asset_bodies:
        return asset_bodies[src]
    parsed = urlparse(src)
    stripped = parsed._replace(query="", fragment="").geturl()
    if stripped in asset_bodies:
        return asset_bodies[stripped]
    return None


def _fetch_asset_bytes(src: str, asset_bodies: dict[str, bytes], page=None) -> tuple[bytes | None, str]:
    decoded = _decode_data_url_bytes(src)
    if decoded:
        raw, mime = decoded
        return raw, _sniff_image_mime(raw, src, mime)
    body = _lookup_asset_body(asset_bodies, src)
    if body:
        return body, _sniff_image_mime(body, src)
    if not (src.startswith("http://") or src.startswith("https://")):
        return None, ""
    if page is not None:
        try:
            b64 = page.evaluate("""async (url) => {
              try {
                const r = await fetch(url, {credentials:'same-origin'});
                if (!r.ok) return null;
                const buf = new Uint8Array(await r.arrayBuffer());
                if (buf.length > 8000000) return null;
                let binary = '';
                const step = 0x8000;
                for (let i = 0; i < buf.length; i += step) {
                  binary += String.fromCharCode.apply(null, buf.subarray(i, i + step));
                }
                return btoa(binary);
              } catch (e) { return null; }
            }""", src)
            if b64:
                raw = base64.b64decode(b64)
                _remember_image_body(asset_bodies, src, raw)
                return raw, _sniff_image_mime(raw, src)
        except Exception:
            pass
    host = (urlparse(src).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None, ""
    try:
        validate_public_url(src)
        response = fetch_public_bytes(
            src, timeout=10.0, headers=_HEADERS, max_bytes=_MAX_ASSET_BYTES)
        raw = response.content
        if raw:
            _remember_image_body(asset_bodies, src, raw)
            return raw, _sniff_image_mime(
                raw, src, response.headers.get("content-type") or "")
    except Exception:
        pass
    return None, ""


def provenance_fingerprint(provenance: dict) -> str:
    """Stable hash of the acceptance/cache boundary (no nested fingerprint)."""
    payload = {
        "captureVersion": provenance.get("captureVersion"),
        "compilerSha256": provenance.get("compilerSha256"),
        "browser": provenance.get("browser"),
        "deviceScaleFactor": provenance.get("deviceScaleFactor"),
        "viewports": provenance.get("viewports") or [],
        "fonts": provenance.get("fonts") or [],
        "assets": provenance.get("assets") or [],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_capture_provenance(*, compiler_sha256: str, browser: dict, viewport: dict | None,
                             viewports: list[dict] | None = None,
                             fonts: list[dict] | None = None,
                             assets: list[dict] | None = None,
                             device_scale_factor: float = 1.0) -> dict:
    """Browser/viewport/font/asset/compiler identity for gate + cache admission."""
    vp_list = list(viewports or [])
    if viewport and not vp_list:
        vp_list = [{
            "name": str(viewport.get("name") or ""),
            "width": int(viewport.get("width") or 0),
            "height": int(viewport.get("height") or 0),
            "deviceScaleFactor": float(device_scale_factor),
        }]
    provenance = {
        "captureVersion": SOURCE_CAPTURE_VERSION,
        "compilerSha256": str(compiler_sha256 or ""),
        "browser": {
            "name": str((browser or {}).get("name") or "chromium"),
            "version": str((browser or {}).get("version") or ""),
        },
        "deviceScaleFactor": float(device_scale_factor),
        "viewports": vp_list,
        "fonts": list(fonts or []),
        "assets": list(assets or []),
    }
    provenance["fingerprint"] = provenance_fingerprint(provenance)
    return provenance


def _materialize_capture_assets(page, item: dict, block_selector: str,
                                asset_bodies: dict[str, bytes],
                                memo: dict[tuple, tuple[bytes, str, str, str]] | None = None) -> list[dict]:
    """Rewrite raster IR srcs AND the live DOM to one lossless PNG per asset.

    Editable image/background layers stay image layers; only the bytes they
    paint are replaced. Capture screenshot and IR replay then share the same
    content-addressed source hash and the same decoded PNG box.
    """
    requests = [req for req in (item.get("assetRequests") or []) if isinstance(req, dict)]
    if not requests:
        return []
    by_key = {}
    for node, _parent in _walk_source_nodes(item.get("nodes")):
        key = str(node.get("sourceKey") or "")
        if key:
            by_key[key] = node
    memo = memo if memo is not None else {}
    records: list[dict] = []
    ops: list[dict] = []
    for req in requests:
        src = str(req.get("url") or "")
        key = str(req.get("sourceKey") or "")
        if not src or src.startswith("data:image/svg") or parse_blob_ref(src):
            continue
        width = int(req.get("width") or 1)
        height = int(req.get("height") or 1)
        fit = str(req.get("objectFit") or "fill")
        position = str(req.get("objectPosition") or "50% 50%")
        raw, mime = _fetch_asset_bytes(src, asset_bodies, page)
        if not raw:
            continue
        source_digest = hashlib.sha256(raw).hexdigest()
        memo_key = (source_digest, width, height, fit, position)
        cached = memo.get(memo_key)
        if cached is None:
            try:
                png = lossless_png_from_bytes(raw, width, height, fit, position)
                object_digest = put_png_blob(png)
            except Exception:
                continue
            cached = (png, png_data_url(png), source_digest, object_digest)
            memo[memo_key] = cached
        png, data_url, source_digest, object_digest = cached
        ref = blob_ref(object_digest)
        node = by_key.get(key)
        if isinstance(node, dict):
            node["src"] = ref
            style = node.get("style") if isinstance(node.get("style"), dict) else {}
            style["objectFit"] = "fill"
            style["objectPosition"] = "0 0"
            node["style"] = style
            meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
            # IR schema требует sourceMeta.kind: узел мог прийти без sourceMeta
            meta.setdefault("kind", "dom")
            meta["url"] = meta.get("url") or src
            meta["sourceSha256"] = source_digest
            meta["objectSha256"] = object_digest
            meta["width"] = width
            meta["height"] = height
            meta["objectFit"] = fit
            meta["objectPosition"] = position
            meta["captureVersion"] = SOURCE_CAPTURE_VERSION
            node["sourceMeta"] = meta
        records.append({
            "sourceKey": key,
            "url": src,
            "sourceSha256": source_digest,
            "objectSha256": object_digest,
            "ref": ref,
            "mime": mime or _sniff_image_mime(raw, src),
            "width": width,
            "height": height,
            "objectFit": fit,
            "objectPosition": position,
            "captureVersion": SOURCE_CAPTURE_VERSION,
        })
        ops.append({
            "apply": str(req.get("apply") or "img"),
            "selector": str(req.get("selector") or ""),
            "fromUrl": src,
            "png": data_url,
        })
    if not ops:
        return records
    try:
        page.locator(block_selector).first.evaluate(
            """(root, ops) => {
              const escape = (s) => s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
              for (const op of ops) {
                let target = root;
                if (op.selector) {
                  const found = root.querySelector(op.selector);
                  if (found) target = found;
                }
                if (!target) continue;
                if (op.apply === 'img') {
                  const img = target.tagName === 'IMG' ? target : target.querySelector('img');
                  if (!img) continue;
                  img.src = op.png;
                  img.removeAttribute('srcset');
                  img.removeAttribute('sizes');
                  img.loading = 'eager';
                  img.decoding = 'sync';
                  img.style.setProperty('object-fit', 'fill', 'important');
                  img.style.setProperty('object-position', '0 0', 'important');
                } else {
                  let bg = target.style.backgroundImage;
                  if (!bg || bg === 'none') bg = getComputedStyle(target).backgroundImage;
                  if (op.fromUrl && bg && bg !== 'none') {
                    bg = bg.replace(new RegExp(escape(op.fromUrl), 'g'), op.png);
                    bg = bg.replace(new RegExp(escape(op.fromUrl.split('?')[0]), 'g'), op.png);
                  } else {
                    bg = 'url(\"' + op.png + '\")';
                  }
                  const layers = Math.max(1, (bg.match(/url\\(/g) || []).length);
                  target.style.setProperty('background-image', bg, 'important');
                  target.style.setProperty('background-size',
                    Array.from({length: layers}, () => '100% 100%').join(', '), 'important');
                  target.style.setProperty('background-position',
                    Array.from({length: layers}, () => '0 0').join(', '), 'important');
                  target.style.setProperty('background-repeat',
                    Array.from({length: layers}, () => 'no-repeat').join(', '), 'important');
                }
              }
            }""",
            ops,
        )
    except Exception:
        pass
    return records


# ---------- Playwright: JS-render + screenshot + computed styles ----------

# С включённым network interception (SSRF route guard) Chromium синхронно
# резолвит системный прокси на каждый запрос. Если в WinINET осталась запись
# ProxyServer (например, socks=127.0.0.1 от VPN-клиента) при выключенном
# прокси, каждый loopback-запрос страдает секундами — goto локальных
# фикстур валит 5s-таймауты. Явный loopback-bypass сохраняет системный
# прокси для внешних сайтов и делает локальные запросы детерминированными.
CHROMIUM_LAUNCH_ARGS = ["--proxy-bypass-list=<-loopback>", "--force-color-profile=srgb"]


def launch_chromium(p, **kwargs):
    kwargs.setdefault("args", []).extend(CHROMIUM_LAUNCH_ARGS)
    return p.chromium.launch(headless=True, **kwargs)


def _guarded_browser_page(browser, viewport: dict):
    context = browser.new_context(
        viewport=viewport, service_workers="block", device_scale_factor=1)
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
    for coll in ("dropped", "extras", "leafBoxes", "assetRequests", "assets"):
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
            browser = launch_chromium(p)
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
            browser = launch_chromium(p)
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
_NORMALIZE_CAROUSEL_JS = """() => {
  const vw = window.innerWidth;
  let pinned = 0;
  for (const el of document.querySelectorAll('*')) {
    if (el.scrollLeft || el.scrollTop) {
      // scroll-behavior:smooth у самого скроллера анимирует возврат к 0 —
      // compile ловил середину анимации. Инлайн-стиль перекрывает CSS.
      el.style.scrollBehavior = 'auto';
      if (el.scrollLeft) {
        pinned += 1;
        const pinnedEl = el;
        pinnedEl.scrollLeft = 0;
        // JS-карусели крутят трек через scrollTo/scrollBy уже ПОСЛЕ
        // нормализации — нейтрализуем программную прокрутку на каноническом
        // слайде 0. Скролл-ивенты не перехватываем: реакция на smooth-анимацию
        // сайта превращалась в перетягивание каната.
        pinnedEl.scrollTo = function () {};
        pinnedEl.scrollBy = function () {};
      }
      if (el.scrollTop > 0 && el !== document.documentElement
          && el !== document.body) { el.scrollTop = 0; pinned += 1; }
    }
    const cs = getComputedStyle(el);
    const tm = String(cs.transform || '');
    if (tm.indexOf('matrix(') !== 0) continue;
    const v = tm.slice(7, -1).split(',').map(Number);
    if (v.length !== 6 || v.some(x => !Number.isFinite(x))) continue;
    // чистый горизонтальный translate (tx != 0, без rotate/scale)
    if (Math.abs(v[0] - 1) > 1e-6 || Math.abs(v[3] - 1) > 1e-6
        || Math.abs(v[1]) > 1e-6 || Math.abs(v[2]) > 1e-6
        || Math.abs(v[4]) < 0.5 || Math.abs(v[5]) > 0.5) continue;
    // трек карусели: горизонтальный overflow-контейнер с более широким
    // контентом; off-canvas меню (вынесенные за экран) не трогаем
    if (!/(hidden|clip|scroll|auto)/.test(cs.overflowX)) continue;
    if (el.scrollWidth <= el.clientWidth + 8) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.right <= 0 || r.left >= vw) continue;
    el.style.setProperty('transform', 'none', 'important');
    pinned += 1;
  }
  return pinned;
}"""

_PAGE_TOKEN_SIGNALS_JS = """() => {
  const num = (v) => Number.parseFloat(v) || 0;
  const hex = (v, base) => {
    const value=String(v||'');
    const rgb=value.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
    if(!rgb) return null;
    const a=rgb[4]===undefined?1:Number(rgb[4]);
    if(a<=.05) return null;
    let ch=rgb.slice(1,4).map(Number);
    // Полупрозрачный цвет: сбрасывать альфу нельзя — border rgba(255,255,255,.07)
    // на тёмной теме превращался в токен #ffffff, и генерация рисовала яркие
    // белые рамки. Смешиваем с фоном страницы: токен = ВИДИМЫЙ цвет.
    if(a<1 && base && /^#[0-9a-f]{6}$/i.test(base)){
      const bs=[1,3,5].map(i=>parseInt(base.slice(i,i+2),16));
      ch=ch.map((x,i)=>Math.round(x*a+bs[i]*(1-a)));
    }
    return '#'+ch.map(x=>x.toString(16).padStart(2,'0')).join('');
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
    if(num(cs.borderTopWidth)>0) tally(sig.borderColor,hex(cs.borderTopColor,sig.bodyBg));
    if(num(cs.fontSize)>0 && num(cs.fontSize)<13 && String(el.innerText||'').trim()) tally(sig.mutedColor,hex(cs.color,sig.bodyBg));
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
                        used_weights: dict[str, set[int]] | None = None,
                        download_cache: dict[str, bytes | None] | None = None) -> list:
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
            font_url = str(url)
            if download_cache is not None and font_url in download_cache:
                data = download_cache[font_url]
            else:
                data = _download_font(font_url)
                if download_cache is not None:
                    download_cache[font_url] = data
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


def _captured_ir(block: dict, capture: dict, page_tokens: dict | None = None,
                 font_download_cache: dict[str, bytes | None] | None = None) -> dict:
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
    font_faces = _resolve_font_faces(
        capture.get("fontFaces") or [], used_families, used_font_weights,
        download_cache=font_download_cache)

    return {
        "version": "1.0",
        "meta": {"name": f"Импорт: {semantic['label']}",
                 "description": f"Rendered DOM capture · {semantic['role']}",
                 "qaWarnings": qa_warnings,
                 "fontFaces": font_faces},
        # The browser measures this block as its own artboard. Keeping the same
        # root frame prevents Editor from falling back to the generic 960px
        # design canvas and makes section coordinates true artboard coordinates.
        # The section itself owns the captured padding. Repeating it on the
        # outer artboard shifts/scales the entire source block while relative
        # leaf bbox checks remain deceptively green.
        "frame": {k: copy.deepcopy(v) for k, v in root_frame.items() if k != "padding"},
        "tokens": tokens,
        "tree": [{"id": "imported-block", "type": "source-block", "variant": "dom-capture",
                  "semantic": semantic, "props": {},
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


# Cookie/consent-оверлеи — не дизайн-контент, но position:fixed элементы
# попадают в element-screenshot секций и расходятся с IR-рендером, где
# фиксированные оверлеи не представлены. Прячем их ДО компиляции и скриншотов,
# чтобы reference и IR оставались согласованными на всех viewport-проходах.
_DISMISS_OVERLAYS_JS = """
() => {
  const SIG = /cookie|consent|gdpr|cmp-|iubenda|onetrust|cybot|usercentrics|quantcast|privacy-?(banner|bar|modal)/i;
  const TEXT = /(используем|использует|using|use of|value) [^.]{0,40}cookie|accept (all )?cookies|принять (все )?cookie|разрешить|allow all/i;
  const hidden = [];
  const matches = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) return false;
    if (cs.position !== "fixed" && cs.position !== "absolute") return false;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 40) return false;
    if (el.textContent && el.textContent.length > 4000) return false;
    const sig = ((el.id || "") + " " + (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || "") + " " + (el.getAttribute("aria-label") || "") + " " + (el.getAttribute("role") || ""));
    if (SIG.test(sig)) return true;
    return el.childElementCount <= 6 && TEXT.test((el.innerText || "").slice(0, 400));
  };
  const candidates = Array.from(document.querySelectorAll("body *")).filter(matches);
  candidates.sort((a, b) => {
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return ra.width * ra.height - rb.width * rb.height;
  });
  for (const el of candidates) {
    let ancestorGone = false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p.style && p.style.display === "none") { ancestorGone = true; break; }
    }
    if (ancestorGone) continue;
    el.style.setProperty("display", "none", "important");
    hidden.push(1);
  }
  return hidden.length;
}
"""


def _dismiss_cookie_overlays(page) -> int:
    try:
        return int(page.evaluate(_DISMISS_OVERLAYS_JS) or 0)
    except Exception:
        return 0


def capture_block_irs(url: str, blocks: list[dict] | None, viewport_w: int = 1440,
                      viewport_h: int = 900, timeout_ms: int = 20000,
                      return_tokens: bool = False, viewports: list[dict] | None = None,
                      cookies: list[dict] | None = None,
                      return_blocks: bool = False,
                      on_progress: Callable[[str, int, int, int], None] | None = None):
    """Compile rendered DOM into compact responsive Design IR.

    Text is collected from direct text nodes, so it always remains inside its
    semantic DOM parent. Flex/grid geometry becomes auto-layout; absolute frames
    are reserved for elements that are actually positioned out of flow.
    """
    from playwright.sync_api import sync_playwright

    validate_public_url(url)
    viewport_defs = _normalize_source_viewports(viewports)
    resolved_blocks = blocks
    captures: dict[str, dict[str, dict]] = {}
    token_signals = None
    compiler_js = (Path(__file__).resolve().parent / "source_import_compiler.js").read_text(encoding="utf-8")
    compiler_sha256 = hashlib.sha256(compiler_js.encode("utf-8")).hexdigest()
    browser_info = {"name": "chromium", "version": ""}
    asset_bodies: dict[str, bytes] = {}
    asset_memo: dict[tuple, tuple[bytes, str, str, str]] = {}
    capture_started = time.perf_counter()
    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = launch_chromium(p)
            browser_info = {"name": "chromium", "version": str(browser.version)}
            context, page = _guarded_browser_page(
                browser,
                {"width": viewport_defs[0]["width"], "height": viewport_defs[0]["height"]},
            )
            drain_image_bodies = install_image_body_listener(page, asset_bodies)
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
            drain_image_bodies()
            page.add_style_tag(content="""
              *, *::before, *::after { animation:none !important; transition:none !important; }
              html { scroll-behavior:auto !important; }
            """)
            _dismiss_cookie_overlays(page)
            if resolved_blocks is None:
                # Fast path: detect selectors from the exact hydrated DOM that
                # will be compiled below. This removes a second navigation and
                # guarantees selector/capture consistency on dynamic pages.
                resolved_blocks = detect_blocks(page.content())
                if not resolved_blocks:
                    raise RuntimeError("no visible source blocks detected")
            for index, viewport in enumerate(viewport_defs):
                viewport_started = time.perf_counter()
                if index:
                    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
                    # после resize могут догрузиться responsive images/шрифты
                    _wait_capture_settle(page)
                    drain_image_bodies()
                # Карусели/shelf-ы: каноническое состояние — слайд 0
                # (scrollLeft/inline-transform треков + нейтрализация auto-advance).
                try:
                    page.evaluate(_NORMALIZE_CAROUSEL_JS)
                except Exception:
                    pass
                if index == 0:
                    # дизайн-токены страницы снимаем один раз, на desktop-проходе
                    try:
                        token_signals = page.evaluate(_PAGE_TOKEN_SIGNALS_JS)
                    except Exception:
                        token_signals = None
                by_selector: dict[str, dict] = {}
                for block in resolved_blocks:
                    # Показ блока и ожидание его картинок — ДО компиляции.
                    # Раньше 4-секундное ожидание стояло МЕЖДУ замером IR и
                    # эталонным скриншотом: поздняя гидрация/ленивый контент
                    # успевали сдвинуть блок (карусель rsale уезжала на ~85px,
                    # чипы резались краем эталона, fidelity падал до 25%).
                    ref_locator = page.locator(block["selector"]).first
                    try:
                        ref_locator.scroll_into_view_if_needed(timeout=5000)
                        ref_locator.evaluate("""(el, budgetMs) => Promise.race([
                          Promise.all(Array.from(el.querySelectorAll('img'))
                            .filter(img => !img.complete)
                            .map(img => img.decode ? img.decode().catch(() => {}) : new Promise(resolve => {
                              img.addEventListener('load', resolve, {once:true});
                              img.addEventListener('error', resolve, {once:true});
                            }))),
                          new Promise(resolve => setTimeout(resolve, budgetMs))
                        ])""", BLOCK_LAZY_SETTLE_MS)
                    except Exception:
                        pass
                    # scroll_into_view ставит блок под fixed/sticky-шапку сайта:
                    # element-screenshot рисует её поверх блока (~85px полосы
                    # навбара в эталоне при чистой геометрии IR — сходство
                    # карусели/panel падало до ~58%). Сдвигаем скролл вниз на
                    # высоту верхней fixed-полосы, снимок идёт без перекрытия.
                    try:
                        page.evaluate("""() => {
                          let fixedTop = 0;
                          for (const el of document.querySelectorAll('*')) {
                            const cs = getComputedStyle(el);
                            if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
                            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                            if (parseFloat(cs.opacity || '1') < 0.05) continue;
                            const r = el.getBoundingClientRect();
                            if (r.height < 8 || r.height > 240) continue;
                            if (r.top > 4) continue;
                            if (r.width < window.innerWidth * 0.5) continue;
                            fixedTop = Math.max(fixedTop, r.bottom);
                          }
                          if (fixedTop > 0) window.scrollBy(0, fixedTop + 16);
                        }""")
                    except Exception:
                        pass
                    # scroll_into_view ради ленивых картинок сам прокручивает
                    # внутренние скроллеры (в т.ч. карусели) — возвращаем
                    # канонический слайд 0 непосредственно перед замером.
                    # Сайты отвечают на прокрутку дебаунс-обработчиком
                    # (snap/advance через ~200-400мс): выдерживаем окно дебаунса и
                    # нормализуем ПОВТОАНО — иначе обработчик срабатывал между
                    # компиляцией и эталонным скриншотом (сходство падало до 59%).
                    try:
                        moved = page.evaluate(_NORMALIZE_CAROUSEL_JS) or 0
                        if moved:
                            # сайт ответит на прокрутку дебаунс-обработчиком
                            # (snap/advance ~200-400мс) — выдерживаем и
                            # нормализуем повторно перед замером
                            page.wait_for_timeout(450)
                            page.evaluate(_NORMALIZE_CAROUSEL_JS)
                    except Exception:
                        pass
                    # Компиляция блока непосредственно перед его эталонным
                    # скриншотом: между замером и скриншотом остаются только
                    # backdrop/materialize (~сотни мс) — гонки гидрации и
                    # auto-advance каруселей в это окно не попадают.
                    try:
                        raw_one = page.evaluate(compiler_js, [block])
                    except Exception:
                        raw_one = []
                    item = next((entry for entry in raw_one
                                 if isinstance(entry, dict)
                                 and entry.get("selector") == block["selector"]), None)
                    if not item or item.get("error"):
                        if item is not None:
                            by_selector[block["selector"]] = item
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
                            node["src"] = _store_png_src(backdrop_shot)
                        except Exception:
                            pass
                    try:
                        # Decode every raster asset once to a lossless PNG at the
                        # measured CSS box, then paint that PNG in the live DOM
                        # AND in the IR so the reference screenshot and replay
                        # share bytes. Do this before the element screenshot.
                        item["assets"] = _materialize_capture_assets(
                            page, item, block["selector"], asset_bodies, asset_memo)
                        try:
                            # Replacing an already-complete WebP/JPEG <img> with
                            # the deterministic PNG starts a new asynchronous
                            # decode. Two rAFs alone can still screenshot the old
                            # decoder surface. Wait for the materialized images,
                            # then cross the same two-paint barrier as replay.
                            ref_locator.evaluate("""(el, budgetMs) => Promise.race([
                              Promise.all(Array.from(el.querySelectorAll('img')).map(img =>
                                img.complete && img.naturalWidth > 0
                                  ? (img.decode ? img.decode().catch(() => {}) : Promise.resolve())
                                  : new Promise(resolve => {
                                      img.addEventListener('load', resolve, {once:true});
                                      img.addEventListener('error', resolve, {once:true});
                                    })
                              )).then(() => new Promise(resolve =>
                                requestAnimationFrame(() => requestAnimationFrame(resolve)))),
                              new Promise(resolve => setTimeout(resolve, budgetMs))
                            ])""", MATERIALIZED_IMAGE_SETTLE_MS)
                        except Exception:
                            pass
                        shot = ref_locator.screenshot(type="png")
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
                        existing_src = str((node or {}).get("src") or "")
                        if node is None or existing_src.startswith("data:image") or parse_blob_ref(existing_src):
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
                            node["src"] = _store_png_src(shot)
                        except Exception:
                            item.setdefault("extras", []).append({
                                "sourceKey": str(req.get("sourceKey") or ""),
                                "reason": "raster-unavailable", "visual": True,
                                "rect": {"x": 0, "y": 0, "width": 0, "height": 0}})
                    _namespace_block_keys(item, re.sub(r"[^A-Za-z0-9_-]+", "-", str(block.get("name") or "block")))
                    by_selector[block["selector"]] = item
                captures[viewport["name"]] = by_selector
                viewport_ms = max(0, round((time.perf_counter() - viewport_started) * 1000))
                elapsed_ms = max(0, round((time.perf_counter() - capture_started) * 1000))
                print(json.dumps({
                    "event": "source_capture.viewport",
                    "viewport": viewport["name"],
                    "viewportIndex": index + 1,
                    "viewportCount": len(viewport_defs),
                    "blockCount": len(resolved_blocks or []),
                    "capturedCount": len(by_selector),
                    "durationMs": viewport_ms,
                    "elapsedMs": elapsed_ms,
                }, ensure_ascii=False, separators=(",", ":")), flush=True)
                if on_progress is not None:
                    on_progress(viewport["name"], index + 1, len(viewport_defs), elapsed_ms)
        finally:
            if context is not None:
                with contextlib.suppress(Exception):
                    context.close()
            if browser is not None:
                with contextlib.suppress(Exception):
                    browser.close()

    postprocess_started = time.perf_counter()
    page_tokens = _page_tokens_from_signals(token_signals)
    font_download_cache: dict[str, bytes | None] = {}
    result: dict[str, dict] = {}
    for block in resolved_blocks or []:
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
        assets_by_viewport: dict[str, list] = {}
        previews_by_viewport: dict[str, str] = {}
        for viewport in viewport_defs:
            name = viewport["name"]
            item = captures.get(name, {}).get(selector)
            # Empty editable nodes are OK when we have a source screenshot: the
            # block becomes a locked raster fallback instead of a hard error.
            if not item or item.get("error") or (
                not item.get("nodes") and not str(item.get("preview") or "").startswith("data:image")
            ):
                continue
            ir = _captured_ir(block, item, page_tokens, font_download_cache)
            variants[name] = ir
            # Evidence screenshots belong to the Source response, not canonical
            # Design IR. Keeping three base64 PNGs inside responsive.viewports
            # caused a second decode/hash/fsync pass during IR blob persistence.
            meta[name] = {"width": item["root"]["width"], "height": item["root"]["height"]}
            previews_by_viewport[name] = item.get("preview", "")
            warnings.update(item.get("warnings") or [])
            editable_layers_by_viewport[name] = int(item.get("emitted") or 0)
            component_boundaries_by_viewport[name] = int(item.get("componentBoundaries") or 0)
            visited_by_viewport[name] = int(item.get("visited") or 0)
            dropped_by_viewport[name] = item.get("dropped") or []
            extras_by_viewport[name] = item.get("extras") or []
            paint_coverage[name] = int(item.get("paintCoverage") or 0)
            coverage[name] = int(item.get("coverage") or paint_coverage[name])
            leaf_boxes_by_viewport[name] = item.get("leafBoxes") or []
            assets_by_viewport[name] = item.get("assets") or []
        if not variants:
            result[selector] = {"error": "DOM block has no editable visible layers in selected viewports"}
            continue
        merged = _merge_responsive_irs(variants, meta)
        _persist_ir_raster_data_urls(merged)
        base_name = "desktop" if "desktop" in meta else next(iter(meta))
        asset_records = []
        seen_assets: set[tuple] = set()
        for name in assets_by_viewport:
            for rec in assets_by_viewport[name]:
                if not isinstance(rec, dict):
                    continue
                identity = (rec.get("objectSha256") or rec.get("sha256"),
                            rec.get("width"), rec.get("height"),
                            rec.get("objectFit"), rec.get("objectPosition"))
                if identity in seen_assets:
                    continue
                seen_assets.add(identity)
                asset_records.append(rec)
        font_records = []
        for face in (merged.get("meta") or {}).get("fontFaces") or []:
            if not isinstance(face, dict):
                continue
            url = str(face.get("url") or "")
            filename = url.rsplit("/", 1)[-1] if url.startswith("/fonts/") else ""
            path = _FONTS_DIR / filename if filename else None
            digest = ""
            if path is not None and path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            font_records.append({
                "family": str(face.get("family") or ""),
                "url": url,
                "sha256": digest,
                "weight": str(face.get("weight") or ""),
            })
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
            "preview": previews_by_viewport.get(base_name, ""),
            "previews": previews_by_viewport,
            "sizes": {name: {"width": value["width"], "height": value["height"]} for name, value in meta.items()},
            "warnings": sorted(warnings),
            "provenance": build_capture_provenance(
                compiler_sha256=compiler_sha256,
                browser=browser_info,
                viewport=None,
                viewports=[{
                    "name": vp["name"],
                    "width": vp["width"],
                    "height": vp["height"],
                    "deviceScaleFactor": 1.0,
                } for vp in viewport_defs],
                fonts=font_records,
                assets=asset_records,
                device_scale_factor=1.0,
            ),
        }
    print(json.dumps({
        "event": "source_capture.postprocess",
        "blockCount": len(resolved_blocks or []),
        "durationMs": max(0, round((time.perf_counter() - postprocess_started) * 1000)),
        "elapsedMs": max(0, round((time.perf_counter() - capture_started) * 1000)),
    }, ensure_ascii=False, separators=(",", ":")), flush=True)
    if return_blocks and return_tokens:
        return result, page_tokens, list(resolved_blocks or [])
    if return_blocks:
        return result, list(resolved_blocks or [])
    return (result, page_tokens) if return_tokens else result


# ---------- Fidelity: честное пиксельное сходство IR со скриншотом источника ----------

_APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
_RENDERER_JS = _APP_ROOT / "static" / "flow" / "engine.js"


def _render_ir_png(page, ir: dict, width: int, height: int) -> bytes:
    """Отрисовать IR движком редактора (app/static/flow/engine.js) и вернуть PNG."""
    resolved, errors = resolve_ir_blobs(ir)
    if errors:
        raise RuntimeError("blob resolve failed: " + "; ".join(errors[:6]))
    page.set_viewport_size({"width": max(320, int(width)), "height": max(320, int(height) + 40)})
    page.set_content(f'<div id="preview" style="width:{int(width)}px"></div>')
    page.add_script_tag(path=str(_RENDERER_JS))
    page.evaluate("(ir) => window.IRRenderer.renderIR(document.querySelector('#preview'), ir)", resolved)
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
                browser = launch_chromium(p)
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
        browser = launch_chromium(p)
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
