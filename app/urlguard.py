"""SSRF-гард: пользовательские URL разрешаются только в публичные сети.
Только stdlib. Бросает ValueError с человекочитаемой причиной.

Ограничение: проверка и запрос разнесены во времени (TOCTOU/DNS-rebinding
не закрыты полностью) — для локального dev-инструмента это осознанно.
"""
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


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
    try:
        ips = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            raise ValueError(f"Хост {host!r} не резолвится: {e}") from None
        ips = [ipaddress.ip_address(i[4][0]) for i in infos]
    for ip in ips:
        if _bad_ip(ip):
            raise ValueError(f"Хост {host!r} ведёт во внутреннюю сеть ({ip}) — запрос заблокирован")
    return p.geturl()
