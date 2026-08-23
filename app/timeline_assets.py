"""Гард ассетов для рендера Timeline IR: только детерминированные ассеты.

Рендер агентского таймлайна прогоняет Design IR через headless Chromium.
Любой сетевой запрос из этой страницы — это недетерминизм ролика (контент
может измениться между рендерами) и SSRF-поверхность (ИИ-план или
пользовательский IR может сослаться на внутренний адрес). Политика:

* ``data:`` URL — только мелкие (изображения/шрифты, инкапсулированы);
* ``http(s)`` — только контент-адресные ассеты: хэш ≥32 hex-символов в пути,
  без query/fragment (signed-параметры = изменяемый контент), хост резолвится
  только в публичные IP;
* локальные пути (``/fonts/...``) — инертны на странице ``about:blank``;
* всё остальное (приватные адреса, изменяемые URL, file:/javascript:) —
  отказ с человекочитаемой ошибкой, где именно и что чинить.

Статическая проверка (``validate_render_assets``) выполняется до запуска
браузера; маршрутный гард (``install_render_asset_guard``) — защита вглубь на
случай запросов, которые генерирует сам движок рендера.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from urlguard import resolve_public_ips

# data: URL ограничен, чтобы агентский IR не протаскивал гигабайты инлайн:
# ~150 КБ после base64-декодирования достаточно для иконки/текстуры.
MAX_DATA_URL_CHARS = 200_000
MAX_URL_CHARS = 2048

# Контент-адресность: ≥32 строчных hex-символов подряд в пути (короткие хэши
# дают коллизии и не гарантируют неизменность контента).
CONTENT_HASH_RE = re.compile(r"[0-9a-f]{32,}")
URL_IN_STYLE_RE = re.compile(r"url\(\s*['\"]?([^'\")\s]+)", re.IGNORECASE)
DATA_URL_MIME_RE = re.compile(r"^data:([a-z0-9.+-]+/[a-z0-9.+-]+)?", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"^(\.{0,2}/)?[a-z0-9@._/-]+$", re.IGNORECASE)
ALLOWED_DATA_MIME_PREFIXES = ("image/", "font/", "application/")


def iter_asset_urls(design_ir: dict):
    """Все URL, которые Design IR попросит загрузить при рендере.

    Источники: ``src``/``href`` узлов (картинки) и ``url(...)`` в инлайн-стилях.
    Возвращает пары ``(путь-в-дереве, url)`` для человекочитаемых ошибок.
    """
    def walk(node: dict, path: str):
        if not isinstance(node, dict):
            return
        for key in ("src", "href"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                yield f"{path}/{key}", value.strip()
        style = node.get("style")
        if isinstance(style, dict):
            for prop, value in style.items():
                if isinstance(value, str):
                    for match in URL_IN_STYLE_RE.finditer(value):
                        yield f"{path}/style/{prop}", match.group(1)
        elif isinstance(style, str):
            for match in URL_IN_STYLE_RE.finditer(style):
                yield f"{path}/style", match.group(1)
        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    yield from walk(child, f"{path}/children/{index}")

    tree = design_ir.get("tree") if isinstance(design_ir, dict) else None
    if not isinstance(tree, list):
        return
    for index, section in enumerate(tree):
        if isinstance(section, dict):
            yield from walk(section, f"/tree/{index}")


def _is_content_addressed_http(parsed) -> bool:
    return bool(parsed.hostname) and not parsed.query and not parsed.fragment \
        and bool(CONTENT_HASH_RE.search(parsed.path))


def validate_asset_url(url: str, *, resolve_dns: bool = True) -> str:
    """Проверить один ассет-URL. Бросает ValueError с человекочитаемой причиной."""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL ассета пустой — замените его контент-адресной ссылкой")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "data":
        match = DATA_URL_MIME_RE.match(url)
        mime = (match.group(1) or "").lower() if match else ""
        if mime and not mime.startswith(ALLOWED_DATA_MIME_PREFIXES):
            raise ValueError(
                f"data: URL с типом {mime!r} не разрешён — только image/, font/ или application/")
        if len(url) > MAX_DATA_URL_CHARS:
            raise ValueError(
                f"data: URL занимает {len(url)} символов (лимит {MAX_DATA_URL_CHARS}) — "
                "вынесите ассет во внешнее контент-адресное хранилище")
        return url

    if len(url) > MAX_URL_CHARS:
        raise ValueError(
            f"URL ассета длиннее {MAX_URL_CHARS} символов — "
            "замените его более короткой контент-адресной ссылкой")

    if scheme in ("http", "https"):
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("логин и пароль в URL ассета не разрешены")
        if parsed.query or parsed.fragment:
            raise ValueError(
                f"недетерминированный ассет {url!r}: query/fragment-параметры могут менять контент — "
                "используйте контент-адресную ссылку без параметров")
        if not _is_content_addressed_http(parsed):
            raise ValueError(
                f"недетерминированный ассет {url!r}: разрешены только контент-адресные ассеты "
                "(хэш ≥32 hex-символов в пути) или data: URL до "
                f"{MAX_DATA_URL_CHARS} символов")
        host = parsed.hostname or ""
        # IP-литерал проверяется без DNS: приватный адрес виден сразу.
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            ip = None
        if ip is not None:
            if not ip.is_global:
                raise ValueError(
                    f"ассет {url!r} указывает во внутреннюю сеть ({ip}) — "
                    "замените его публичным контент-адресным ассетом")
        elif resolve_dns:
            try:
                port = parsed.port or (443 if scheme == "https" else 80)
                resolve_public_ips(host, port)
            except ValueError as exc:
                raise ValueError(
                    f"ассет {url!r} недоступен для рендера: {exc} — "
                    "замените его публичным контент-адресным ассетом") from None
        return url

    if not scheme and LOCAL_PATH_RE.match(url):
        # Локальный путь рендер-страницы (например /fonts/...): на about:blank
        # он не резолвится в сетевой запрос — инертен.
        return url

    raise ValueError(
        f"схема {scheme or '<пусто>'!r} не разрешена для ассетов рендера — "
        "используйте контент-адресный http(s) ассет или data: URL")


def validate_render_assets(design_ir: dict) -> list[str]:
    """Все ошибки ассетов Design IR (пустой список — рендеру ничего не мешает)."""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for where, url in iter_asset_urls(design_ir):
        key = (where, url)
        if key in seen:
            continue
        seen.add(key)
        try:
            validate_asset_url(url)
        except ValueError as exc:
            errors.append(f"{where}: {exc}")
    return errors


def _runtime_allowed(url: str) -> bool:
    """Быстрая структурная проверка для маршрутного гарда (без DNS)."""
    try:
        validate_asset_url(url, resolve_dns=False)
        return True
    except ValueError:
        return False


def install_render_asset_guard(context) -> None:
    """Блокировать в рендер-браузере любой запрос вне политики ассетов."""

    def guard_route(route, request):
        url = request.url or ""
        if _runtime_allowed(url):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def guard_websocket(route):
        route.close(code=1008, reason="WebSockets are not allowed in timeline render")

    context.route("**/*", guard_route)
    if hasattr(context, "route_web_socket"):
        context.route_web_socket("**/*", guard_websocket)
