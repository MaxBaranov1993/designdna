"""Negative DNS cache must expire so transient getaddrinfo failures recover."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import urlguard


def test_negative_dns_cache_expires(monkeypatch):
    urlguard._DNS_CACHE.clear()
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise OSError(11001, "getaddrinfo failed")

    monkeypatch.setattr(urlguard.socket, "getaddrinfo", boom)
    try:
        urlguard.resolve_public_ips("flaky.example", 443)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "cannot resolve" in str(exc)
    assert calls["n"] == 1

    # Immediate retry must reuse the negative cache.
    try:
        urlguard.resolve_public_ips("flaky.example", 443)
        assert False, "expected cached ValueError"
    except ValueError:
        pass
    assert calls["n"] == 1

    # Force the negative entry to expire, then allow a successful resolve.
    ips, err, _exp = urlguard._DNS_CACHE["flaky.example"]
    urlguard._DNS_CACHE["flaky.example"] = (ips, err, 0.0)

    def ok(*_args, **_kwargs):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(urlguard.socket, "getaddrinfo", ok)
    resolved = urlguard.resolve_public_ips("flaky.example", 443)
    assert resolved == ("93.184.216.34",)
    assert calls["n"] == 2
