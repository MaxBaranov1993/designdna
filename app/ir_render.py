"""Offline Design IR screenshot rendering for the vision quality judge."""
from __future__ import annotations

from pathlib import Path
import re

from playwright.sync_api import sync_playwright

from timeline_assets import (
    install_render_asset_guard,
    materialize_render_assets,
    rewrite_local_asset_urls,
)
from timeline_render import (
    _READINESS_JS,
    _builtin_inter_faces,
    _design_needs_inter,
)


APP_ROOT = Path(__file__).resolve().parent
RENDERER_JS = APP_ROOT / "static" / "flow" / "engine.js"
RENDER_DOCUMENT_URL = "https://render.ir.invalid/document"
RENDER_DOCUMENT_HTML = (
    "<style>html,body{margin:0;padding:0;background:transparent}"
    "body{overflow-x:hidden}#host{position:relative;transform-origin:top left}</style>"
    '<div id="host"></div>'
)


def _requested_font_families(ir: dict) -> set[str]:
    """Return primary custom families that the rendered DOM can request."""
    families: set[str] = set()

    def add(value) -> None:
        if not isinstance(value, str):
            return
        primary = re.split(r",", value, maxsplit=1)[0].strip().strip("'\"")
        if primary:
            families.add(primary)

    tokens = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else {}
    font = tokens.get("font") if isinstance(tokens.get("font"), dict) else {}
    for role in ("display", "body"):
        entry = font.get(role)
        if isinstance(entry, dict):
            add(entry.get("family"))
    token_type = tokens.get("type") if isinstance(tokens.get("type"), dict) else {}
    type_families = token_type.get("families") if isinstance(token_type.get("families"), dict) else {}
    add(type_families.get("display"))
    add(type_families.get("body"))

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        style = node.get("style")
        if isinstance(style, dict):
            add(style.get("fontFamily"))
        for child in node.get("children") or []:
            walk(child)

    for section in ir.get("tree") or []:
        walk(section)
    return families


def _install_deterministic_font_fallbacks(render_ir: dict, assets: dict) -> None:
    """Back missing catalog families with bundled Inter, without network drift."""
    fallback_faces, fallback_assets = _builtin_inter_faces()
    if not fallback_faces:
        return
    meta = render_ir.setdefault("meta", {})
    faces = list(meta.get("fontFaces") or [])
    declared = {
        str(face.get("family") or "").strip().lower()
        for face in faces if isinstance(face, dict)
    }
    requested = _requested_font_families(render_ir)
    if _design_needs_inter(render_ir):
        requested.add("Inter")
    for family in sorted(requested):
        if family.lower() in declared:
            continue
        for face in fallback_faces:
            alias = dict(face)
            alias["family"] = family
            faces.append(alias)
        declared.add(family.lower())
    meta["fontFaces"] = faces
    assets.update(fallback_assets)


_ASSET_HREF_PREFIXES = ("ddna://", "/fonts/", "data:")


def _neutralize_links(ir: dict) -> dict:
    """Копия IR без href, не указывающих на локальные ассеты (гард считает
    ассетом любой непустой href, включая «#»)."""
    import copy

    out = copy.deepcopy(ir)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            href = node.get("href")
            if isinstance(href, str) and not href.startswith(_ASSET_HREF_PREFIXES):
                del node["href"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)
    return out


WEBFONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")


def render_png(ir: dict, width: int = 1440, *, webfonts: bool = False) -> bytes:
    """Render a complete Design IR page to PNG with the offline timeline path.

    The renderer materializes local assets, blocks every other browser request,
    waits for fonts and images, and uses the same ``engine.js`` as the editor.

    ``webfonts=True`` (режим vision-судьи) разрешает каталог Google Fonts:
    детерминизм менее важен, чем настоящая типографика на скриншоте.
    """
    if not isinstance(ir, dict):
        raise TypeError("ir must be an object")
    try:
        output_width = int(width)
    except (TypeError, ValueError) as exc:
        raise ValueError("width must be an integer") from exc
    if not 320 <= output_width <= 4096:
        raise ValueError("width must be between 320 and 4096 pixels")
    if not RENDERER_JS.is_file():
        raise RuntimeError(
            f"Design IR renderer is missing: {RENDERER_JS}; run the frontend build first")

    # Ссылки (href кнопок/навигации: якоря, mailto, внешние URL) при рендере
    # не загружаются — это не ассеты. Сгенерированный IR полон таких href;
    # без нейтрализации гард ассетов ронял судью на каждой второй странице.
    ir = _neutralize_links(ir)
    assets, asset_errors = materialize_render_assets(ir)
    if asset_errors:
        raise ValueError("render assets failed validation: " + "; ".join(asset_errors[:3]))
    render_ir = rewrite_local_asset_urls(ir)
    if not webfonts:
        _install_deterministic_font_fallbacks(render_ir, assets)

    blocked: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": output_width, "height": 900}, device_scale_factor=1)
            install_render_asset_guard(
                context, assets, blocked, RENDER_DOCUMENT_URL, RENDER_DOCUMENT_HTML,
                allow_hosts=WEBFONT_HOSTS if webfonts else ())
            page = context.new_page()
            page.goto(RENDER_DOCUMENT_URL)
            page.add_script_tag(path=str(RENDERER_JS))
            dimensions = page.evaluate(
                """({designIr, outputWidth, webfonts}) => {
                  const host = document.querySelector('#host');
                  window.IRRenderer.renderIR(host, designIr, {
                    fit: false, viewport: 'desktop', offline: !webfonts,
                  });
                  const catalogLink = document.getElementById('ir-fonts');
                  if (catalogLink && !webfonts) catalogLink.removeAttribute('href');
                  const inner = host.querySelector('[data-design-width]');
                  const artWidth = Number(inner?.dataset.designWidth) || 1440;
                  const scale = outputWidth / artWidth;
                  const artHeight = Math.max(
                    inner?.scrollHeight || 0, inner?.getBoundingClientRect().height || 0, 1);
                  host.style.width = artWidth + 'px';
                  host.style.height = artHeight + 'px';
                  host.style.transform = `scale(${scale})`;
                  document.body.style.width = outputWidth + 'px';
                  document.body.style.height = Math.ceil(artHeight * scale) + 'px';
                  return {artHeight, scale};
                }""",
                {"designIr": render_ir, "outputWidth": output_width, "webfonts": bool(webfonts)},
            )
            if webfonts:
                # Каталог Google Fonts грузится асинхронно: дождаться стилей и
                # явно запросить каждое семейство, иначе readiness увидит
                # «не объявлено» до прихода @font-face.
                families = sorted(_requested_font_families(render_ir))
                try:
                    page.wait_for_function(
                        "() => [...document.styleSheets].some((s) => { try { return !!(s.href && s.href.includes('fonts.googleapis')) && s.cssRules.length >= 0; } catch (e) { return false; } })",
                        timeout=15_000)
                except Exception:  # noqa: BLE001 — без каталога readiness ниже скажет, чего не хватает
                    pass
                page.evaluate(
                    """async (families) => {
                      const loads = [];
                      for (const family of families) for (const w of [400, 500, 600, 700, 800])
                        loads.push(document.fonts.load(w + ' 16px "' + family + '"').catch(() => []));
                      await Promise.race([Promise.all(loads), new Promise((r) => setTimeout(r, 12000))]);
                    }""",
                    families)
            readiness = page.evaluate(_READINESS_JS)
            problems = [str(item) for item in (readiness.get("errors") or [])]
            if blocked:
                problems.append("render attempted network access: " + "; ".join(blocked[:3]))
            if problems:
                raise ValueError("render assets are not ready: " + "; ".join(problems[:5]))
            height = max(1, int(float(dimensions["artHeight"]) * float(dimensions["scale"])))
            # full_page: без него clip режется по вьюпорту 900px и судья видел
            # только первый экран («CTA ниже сгиба», «изображения нет»).
            return page.screenshot(
                type="png",
                full_page=True,
                clip={"x": 0, "y": 0, "width": output_width, "height": min(height, 8000)},
                animations="disabled",
                caret="hide",
            )
        finally:
            browser.close()
