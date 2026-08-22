"""SSRF защита для пользовательских URL.

Бросает ValueError с человекочитаемой причиной. HTTP redirect-ы обрабатываются
вручную, чтобы каждый Location проходил ту же проверку.

HTTPX-соединения повторно резолвятся и закрепляются за проверенным numeric IP
непосредственно на connect boundary. Chromium-запросы всё ещё должны быть
дополнительно ограничены egress-политикой production-среды.
"""
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
import httpcore

ALLOWED_SCHEMES = {"http", "https"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5

# DNS-кэш для одного процесса: Source Import скачивает 5-8 шрифтов с одного
# домена, каждый вызов resolve_public_ips делал полный getaddrinfo. Профиль:
# rsale.net — 9.2с на 8 запросов → ~0.5с с кэшем.
_DNS_CACHE: dict[str, tuple[tuple[str, ...], str | None]] = {}
_DNS_CACHE_MAX = 256


@dataclass(frozen=True)
class PublicHttpResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes


def resolve_public_ips(host: str, port: int) -> tuple[str, ...]:
    """Resolve a host and return only after every answer is proven globally routable."""
    cache_key = host.lower()
    cached = _DNS_CACHE.get(cache_key)
    if cached is not None:
        ips_str, cached_error = cached
        if cached_error:
            raise ValueError(cached_error)
        return ips_str
    try:
        ips = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError) as e:
            if len(_DNS_CACHE) < _DNS_CACHE_MAX:
                _DNS_CACHE[cache_key] = ((), f"Хост {host!r} не резолвится: {e}")
            raise ValueError(f"Хост {host!r} не резолвится: {e}") from None
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not ips:
        if len(_DNS_CACHE) < _DNS_CACHE_MAX:
            _DNS_CACHE[cache_key] = ((), f"Хост {host!r} не резолвится")
        raise ValueError(f"Хост {host!r} не резолвится")
    for ip in ips:
        if _bad_ip(ip):
            error = f"Хост {host!r} ведёт во внутреннюю сеть ({ip}) — запрос заблокирован"
            if len(_DNS_CACHE) < _DNS_CACHE_MAX:
                _DNS_CACHE[cache_key] = ((), error)
            raise ValueError(error)
    # Preserve resolver preference while avoiding duplicate connection attempts.
    result = tuple(dict.fromkeys(str(ip) for ip in ips))
    if len(_DNS_CACHE) < _DNS_CACHE_MAX:
        _DNS_CACHE[cache_key] = (result, None)
    return result


class PublicSyncBackend(httpcore.SyncBackend):
    """Resolve and vet the destination at the exact httpcore TCP-connect boundary."""

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options=None):
        addresses = resolve_public_ips(host, port)
        last_error = None
        for address in addresses:
            try:
                # A numeric address prevents a second hostname DNS lookup. TLS is
                # started later by httpcore with the original Origin host as SNI.
                return super().connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError(f"Хост {host!r} не имеет допустимых IP-адресов")


class PublicHTTPTransport(httpx.HTTPTransport):
    """HTTPX transport with a connect-time public-network backend."""

    def __init__(self, *, network_backend=None):
        super().__init__(trust_env=False)
        # HTTPX 0.28 does not expose httpcore's network_backend parameter. The
        # dependency is pinned; replacement happens before the pool is used.
        self._pool._network_backend = network_backend or PublicSyncBackend()


def _bad_ip(ip: "ipaddress._BaseAddress") -> bool:
    return not ip.is_global  # private/loopback/link-local/multicast/reserved/unspecified


def validate_public_url(url: str) -> str:
    """Возвращает нормализованный URL или бросает ValueError (SSRF-гард)."""
    p = urlparse((url or "").strip())
    if p.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Схема {p.scheme or '<пусто>'!r} не разрешена — только http/https")
    host = p.hostname
    if not host:
        raise ValueError("В URL нет хоста")
    if p.username is not None or p.password is not None:
        raise ValueError("Логин и пароль в URL не разрешены")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError as e:
        raise ValueError(f"Недопустимый порт: {e}") from None
    resolve_public_ips(host, port)
    return p.geturl()


def fetch_public_bytes(url: str, *, timeout: float, headers: dict[str, str] | None = None,
                       max_bytes: int, max_redirects: int = MAX_REDIRECTS) -> PublicHttpResponse:
    """GET public HTTP(S) URL with per-hop validation and a hard body limit."""
    if max_bytes < 1:
        raise ValueError("Лимит ответа должен быть положительным")
    current = validate_public_url(url)
    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
        trust_env=False,
        transport=PublicHTTPTransport(),
    ) as client:
        for redirect_count in range(max_redirects + 1):
            with client.stream("GET", current) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                        raise ValueError("Redirect не содержит Location")
                    if redirect_count >= max_redirects:
                        raise ValueError(f"Слишком много redirect-ов (>{max_redirects})")
                    current = validate_public_url(urljoin(current, location))
                    continue

                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError:
                        declared_size = None
                    if declared_size is not None and declared_size > max_bytes:
                        raise ValueError(f"Ответ превышает лимит {max_bytes} байт")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError(f"Ответ превышает лимит {max_bytes} байт")
                return PublicHttpResponse(
                    url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=bytes(body),
                )
    raise ValueError("Не удалось загрузить URL")


def validate_browser_request_url(url: str, validate_url=validate_public_url) -> str:
    """Validate a browser network request; inert local browser schemes are allowed."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme in {"about", "blob", "data"}:
        return parsed.geturl()
    return validate_url(url)


def install_playwright_url_guard(context, validate_url=validate_public_url,
                                 allow_document_url=None) -> None:
    """Block private destinations for navigations, subresources and WebSockets."""
    def guard_route(route, request):
        try:
            candidate = validate_browser_request_url(request.url, validate_url)
            if (allow_document_url is not None
                    and getattr(request, "resource_type", None) == "document"
                    and not allow_document_url(candidate)):
                raise ValueError("Document navigation is outside the approved origin")
        except ValueError:
            route.abort("blockedbyclient")
            return
        route.continue_()

    def guard_websocket(route):
        try:
            parsed = urlparse(route.url)
            if parsed.scheme not in {"ws", "wss"}:
                raise ValueError("Недопустимая WebSocket-схема")
            equivalent = parsed._replace(
                scheme="https" if parsed.scheme == "wss" else "http",
            ).geturl()
            validate_url(equivalent)
        except ValueError:
            route.close(code=1008, reason="Blocked private destination")
            return
        route.connect_to_server()

    context.route("**/*", guard_route)
    if hasattr(context, "route_web_socket"):
        context.route_web_socket("**/*", guard_websocket)


def install_playwright_offline_guard(context) -> None:
    """Allow inert/local document resources and block every network request."""
    allowed = {"about", "blob", "data", "file"}

    def guard_route(route, request):
        if urlparse((request.url or "").strip()).scheme in allowed:
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def guard_websocket(route):
        route.close(code=1008, reason="Network disabled for local rendering")

    context.route("**/*", guard_route)
    if hasattr(context, "route_web_socket"):
        context.route_web_socket("**/*", guard_websocket)
