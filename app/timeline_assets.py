"""Ассеты рендера Timeline IR: офлайн-детерминизм без внешних сетей.

Рендер агентского таймлайна прогоняет Design IR через headless Chromium и
обязан быть детерминированным: ноль произвольных сетевых запросов, никаких
приватных адресов (SSRF), никакого дрейфа на fallback-шрифты.

Политика ассетов:
* ``ddna://blobs/<полный-sha256>.<ext>`` — контент-адресные блобы из
  ``DESIGNDNA_DATA_DIR/blobs``; перед использованием проверяются ПОЛНЫЙ
  SHA-256 и размер файла, битый/чужой хэш — отказ;
* ``/fonts/<stored-name>`` и ``ddna://fonts/<stored-name>`` — локальные
  шрифты из ``DESIGNDNA_DATA_DIR/fonts``; имена — скреперный формат
  ``<первые 16 hex sha1(байтов)>.<ext>``, поэтому материализация хеширует
  ВСЕ байты и требует ``sha1(data).hexdigest()[:16] == имя`` — валидный,
  но подменённый шрифт отказывает ещё до Chromium (полный SHA-256 для
  легаси-имён не заявляется);
* мелкие ``data:`` URL (инкапсулированы, сети не требуют);
* всё остальное — включая удалённые http(s) с «хэшеподобными» путями —
  отклоняется: байты удалённого URL невозможно верифицировать детерминизмом
  контракта, поэтому такие ассеты сначала сохраняются в локальное
  контент-адресное хранилище.

Разрешение идёт через материализацию (``materialize_render_assets``):
байты читаются с диска, проверяются и передаются рендеру, который
исполняет их через Playwright route.fulfill; любые другие запросы
браузера абортируются (``install_render_asset_guard``).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from config import settings

# Крупные инлайн-ассеты недопустимы: ~150 КБ после base64 достаточно для
# иконки/текстуры, остальное — в контент-адресные блобы.
MAX_DATA_URL_CHARS = 200_000
MAX_URL_CHARS = 2048
MAX_BLOB_BYTES = 10 * 1024 * 1024
MAX_FONT_BYTES = 5 * 1024 * 1024

# Канонический контент-адресный блоб: полный sha256 (64 hex) + расширение.
BLOB_EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
    "woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "otf": "font/otf",
}
BLOB_URL_RE = re.compile(r"^ddna://blobs/([0-9a-f]{64})\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|otf)$")
# Зеркало серверного /fonts/{name} (app/server.py): 16 hex + расширение.
FONT_NAME_RE = re.compile(r"^[0-9a-f]{16}\.(woff2|woff|ttf|otf)$")
FONT_URL_RE = re.compile(r"^(?:ddna://fonts/|/fonts/)([0-9a-f]{16}\.(woff2|woff|ttf|otf))$")
FONT_EXT_MIME = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "otf": "font/otf"}

# Канонические ddna://-ссылки внутри произвольного текста (в т.ч. CSS url(...)):
# только точные форматы блобов/шрифтов, ничего вокруг не трокается.
DDNA_ASSET_URL_RE = re.compile(
    r"ddna://(?:blobs/[0-9a-f]{64}\.(?:png|jpg|jpeg|gif|webp|svg|woff2?|ttf|otf)"
    r"|fonts/[0-9a-f]{16}\.(?:woff2|woff|ttf|otf))")

URL_IN_STYLE_RE = re.compile(r"url\(\s*['\"]?([^'\")\s]+)", re.IGNORECASE)
DATA_URL_MIME_RE = re.compile(r"^data:([a-z0-9.+-]+/[a-z0-9.+-]+)?", re.IGNORECASE)
ALLOWED_DATA_MIME_PREFIXES = ("image/", "font/", "application/")


def _data_root() -> Path:
    return settings.data_dir()


@dataclass(frozen=True)
class MaterializedAsset:
    url: str
    data: bytes
    mime: str
    source: str  # путь на диске — для диагностики


def iter_asset_urls(design_ir: dict):
    """Все ассет-ссылки, которые Design IR попросит при рендере.

    Источники: ``src``/``href`` узлов, ``url(...)`` в инлайн-стилях и
    ``meta.fontFaces[].url`` (локальные шрифты источника). Пары
    ``(путь-в-дереве, url)`` позволяют давать человекочитаемые ошибки.
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

    if not isinstance(design_ir, dict):
        return
    tree = design_ir.get("tree")
    if isinstance(tree, list):
        for index, section in enumerate(tree):
            if isinstance(section, dict):
                yield from walk(section, f"/tree/{index}")
    faces = (design_ir.get("meta") or {}).get("fontFaces") if isinstance(design_ir.get("meta"), dict) else None
    if isinstance(faces, list):
        for index, face in enumerate(faces):
            if isinstance(face, dict) and isinstance(face.get("url"), str) and face.get("url", "").strip():
                yield f"/meta/fontFaces/{index}/url", str(face["url"]).strip()


def validate_asset_url(url: str) -> str:
    """Политика одного ассет-URL. Бросает ValueError с человекочитаемой причиной."""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL ассета пустой — замените его локальным контент-адресным ассетом")
    if url.startswith("data:"):
        match = DATA_URL_MIME_RE.match(url)
        mime = (match.group(1) or "").lower() if match else ""
        if mime and not mime.startswith(ALLOWED_DATA_MIME_PREFIXES):
            raise ValueError(
                f"data: URL с типом {mime!r} не разрешён — только image/, font/ или application/")
        if len(url) > MAX_DATA_URL_CHARS:
            raise ValueError(
                f"data: URL занимает {len(url)} символов (лимит {MAX_DATA_URL_CHARS}) — "
                "сохраните ассет как контент-адресный блоб ddna://blobs/<sha256>.<ext>")
        return url
    if len(url) > MAX_URL_CHARS:
        raise ValueError(
            f"URL ассета длиннее {MAX_URL_CHARS} символов — используйте короткую локальную ссылку")
    if BLOB_URL_RE.match(url) or FONT_URL_RE.match(url):
        return url
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        raise ValueError(
            f"удалённый ассет {url!r} не разрешён: офлайн-рендер не ходит в сеть и не может "
            "верифицировать байты удалённого ответа — скачайте ассет и сохраните его как "
            "контент-адресный блоб ddna://blobs/<sha256>.<ext> в DESIGNDNA_DATA_DIR/blobs "
            "или локальный шрифт /fonts/<имя>")
    raise ValueError(
        f"схема {scheme or '<пусто>'!r} не разрешена для ассетов рендера — используйте "
        "ddna://blobs/<sha256>.<ext>, /fonts/<имя> или data: URL")


def validate_render_assets(design_ir: dict) -> list[str]:
    """Ошибки политики ассетов (без обращения к диску)."""
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


def _safe_child(base: Path, name: str) -> Path:
    """Ребёнок каталога без traversal: строгий формат имени + проверка резолва."""
    resolved = (base / name).resolve()
    if resolved.parent != base.resolve():
        raise ValueError(f"путь {name!r} выходит за пределы хранилища")
    return resolved


def materialize_render_assets(design_ir: dict, data_dir: Path | None = None
                              ) -> tuple[dict[str, MaterializedAsset], list[str]]:
    """Проверить политику И материализовать локальные ассеты.

    Возвращает ``(карта url -> байты, ошибки)``. Любой отсутствующий или
    повреждённый объект — ошибка (fail closed): рендер не стартует на
    полусломанных ассетах и не дрейфит на запасные.
    """
    root = Path(data_dir) if data_dir is not None else _data_root()
    blobs_dir = root / "blobs"
    fonts_dir = root / "fonts"
    assets: dict[str, MaterializedAsset] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for where, url in iter_asset_urls(design_ir):
        if url in seen:
            continue
        seen.add(url)
        try:
            validate_asset_url(url)
        except ValueError as exc:
            errors.append(f"{where}: {exc}")
            continue
        if url.startswith("data:"):
            continue  # инкапсулирован — материализация не нужна
        blob = BLOB_URL_RE.match(url)
        if blob:
            sha, ext = blob.group(1), blob.group(2)
            try:
                path = _safe_child(blobs_dir, f"{sha}.{ext}")
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                continue
            if not path.is_file():
                errors.append(
                    f"{where}: блоб {url!r} не найден — сохраните файл как {path} "
                    "(имя = полный sha256 содержимого)")
                continue
            data = path.read_bytes()
            if len(data) > MAX_BLOB_BYTES:
                errors.append(
                    f"{where}: блоб {url!r} больше {MAX_BLOB_BYTES} байт — рендер не принимает крупные ассеты")
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest != sha:
                errors.append(
                    f"{where}: блоб {url!r} повреждён — sha256 содержимого {digest} не совпадает "
                    "с именем; пересохраните файл под его настоящим хэшем")
                continue
            assets[url] = MaterializedAsset(url=url, data=data, mime=BLOB_EXT_MIME[ext], source=str(path))
            continue
        font = FONT_URL_RE.match(url)
        if font:
            name = font.group(1)
            try:
                path = _safe_child(fonts_dir, name)
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                continue
            if not path.is_file():
                errors.append(
                    f"{where}: шрифт {url!r} не найден — ожидается файл {path} "
                    "(локальная база шрифтов DESIGNDNA_DATA_DIR/fonts)")
                continue
            data = path.read_bytes()
            if len(data) > MAX_FONT_BYTES:
                errors.append(f"{where}: шрифт {url!r} больше {MAX_FONT_BYTES} байт")
                continue
            # Скреперный формат имени: <первые 16 hex sha1(байтов)>.<ext>.
            # Валидный, но подменённый файл не совпадёт по хэшу и откажет
            # ДО Chromium — дрейф на фолбэк-шрифт исключён.
            stem = name.rsplit(".", 1)[0]
            digest = hashlib.sha1(data).hexdigest()[:16]
            if digest != stem:
                errors.append(
                    f"{where}: шрифт {url!r} повреждён или подменён — sha1-префикс содержимого "
                    f"{digest} не совпадает с именем файла {stem}")
                continue
            ext = name.rsplit(".", 1)[-1]
            assets[url] = MaterializedAsset(url=url, data=data, mime=FONT_EXT_MIME[ext], source=str(path))
            continue
        errors.append(f"{where}: ассет {url!r} не удалось материализовать для офлайн-рендера")
    return assets, errors


def rewrite_local_asset_urls(design_ir: dict) -> dict:
    """Заменить ``ddna://…`` ссылки на относительные пути рендер-страницы.

    На странице рендера (локальный документ, см. timeline_render) ``/fonts/…``
    и ``/blobs/…`` резолвятся в обычные http-запросы, которые гард исполняет
    из материализованных байт; кастомная схема ddna:// для этого не нужна.

    Перезаписываются все канонические ddna-ссылки: поля ``src``/``href``,
    ``meta.fontFaces[].url`` и CSS ``url(...)`` внутри стилей — как в
    dict-форме (каждое строковое значение), так и в строковой форме; прочий
    CSS (градиенты, цвета, раскладка) не изменяется.
    """
    import copy
    rewritten = copy.deepcopy(design_ir)

    def rewrite_text(value: str) -> str:
        return DDNA_ASSET_URL_RE.sub(lambda match: _relative_local_url(match.group(0)), value)

    def walk(node):
        if not isinstance(node, dict):
            return
        for key in ("src", "href"):
            value = node.get(key)
            if isinstance(value, str):
                node[key] = rewrite_text(value)
        style = node.get("style")
        if isinstance(style, dict):
            for prop, value in style.items():
                if isinstance(value, str):
                    style[prop] = rewrite_text(value)
        elif isinstance(style, str):
            node["style"] = rewrite_text(style)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    tree = rewritten.get("tree")
    if isinstance(tree, list):
        for section in tree:
            walk(section)
    meta = rewritten.get("meta")
    faces = meta.get("fontFaces") if isinstance(meta, dict) else None
    if isinstance(faces, list):
        for face in faces:
            if isinstance(face, dict) and isinstance(face.get("url"), str):
                face["url"] = rewrite_text(face["url"])
    return rewritten


def _relative_local_url(url: str) -> str:
    if url.startswith("ddna://blobs/"):
        return "/blobs/" + url[len("ddna://blobs/"):]
    if url.startswith("ddna://fonts/"):
        return "/fonts/" + url[len("ddna://fonts/"):]
    return url


def install_render_asset_guard(context, assets: dict[str, MaterializedAsset],
                               blocked: list, document_url: str, document_html: str,
                               allow_hosts: tuple[str, ...] = ()) -> None:
    """Полный офлайн: документ и ассеты — только из материализованных байтов.

    Любой запрос вне карты ассетов абортируется и запоминается в ``blocked`` —
    рендер видит попытку внешнего запроса и падает с объяснением вместо
    тихого дрейфа.
    """
    parsed_doc = urlparse(document_url)
    origin = parsed_doc._replace(path="", query="", fragment="").geturl()
    asset_by_path: dict[str, MaterializedAsset] = {}
    for url, asset in assets.items():
        relative = _relative_local_url(url)
        asset_by_path[origin + relative] = asset

    def guard_route(route, request):
        url = request.url or ""
        if getattr(request, "resource_type", None) == "document" and url == document_url:
            route.fulfill(body=document_html, content_type="text/html")
            return
        asset = asset_by_path.get(url)
        if asset is not None:
            route.fulfill(body=asset.data, content_type=asset.mime)
            return
        if url.startswith("data:") or url.startswith("about:"):
            route.continue_()
            return
        # Режим судьи: веб-шрифты с разрешённых хостов (Google Fonts) — иначе
        # подмена на Inter искажает типографику, которую оценивает vision-модель.
        if allow_hosts:
            host = urlparse(url).hostname or ""
            if any(host == allowed or host.endswith("." + allowed) for allowed in allow_hosts):
                route.continue_()
                return
        blocked.append(url)
        route.abort("blockedbyclient")

    def guard_websocket(route):
        blocked.append(route.url)
        route.close(code=1008, reason="Network disabled for offline timeline render")

    context.route("**/*", guard_route)
    if hasattr(context, "route_web_socket"):
        context.route_web_socket("**/*", guard_websocket)
