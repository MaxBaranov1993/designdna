"""Focused regressions for URL fetching, browser egress and lifecycle cleanup."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx
import httpcore
import pytest

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import reproduce
import scraper
import urlguard


def _public_dns(_host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]


def _mock_client(monkeypatch, handler):
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(urlguard.httpx, "Client", factory)


def test_fetch_blocks_private_redirect_before_second_request(monkeypatch):
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", _public_dns)
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="внутреннюю сеть"):
        urlguard.fetch_public_bytes(
            "https://public.test/start", timeout=1, max_bytes=100,
        )
    assert requests == ["https://public.test/start"]


def test_fetch_allows_public_redirect_and_bounds_stream(monkeypatch):
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", _public_dns)

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, content=b"0123456789")

    _mock_client(monkeypatch, handler)
    response = urlguard.fetch_public_bytes(
        "https://public.test/start", timeout=1, max_bytes=10,
    )
    assert response.content == b"0123456789"
    assert response.url == "https://public.test/final"

    with pytest.raises(ValueError, match="превышает лимит"):
        urlguard.fetch_public_bytes(
            "https://public.test/start", timeout=1, max_bytes=9,
        )


def test_connect_backend_selects_vetted_numeric_ip(monkeypatch):
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", _public_dns)
    connected = []
    sentinel = object()

    def connect(_self, host, port, **_kwargs):
        connected.append((host, port))
        return sentinel

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    result = urlguard.PublicSyncBackend().connect_tcp("public.test", 443)
    assert result is sentinel
    assert connected == [("8.8.8.8", 443)]


def test_connect_backend_rejects_rebinding_before_socket_connect(monkeypatch):
    def private_dns(_host, port, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]

    connected = []
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", private_dns)
    monkeypatch.setattr(
        httpcore.SyncBackend,
        "connect_tcp",
        lambda *_args, **_kwargs: connected.append(True),
    )
    with pytest.raises(ValueError, match="внутреннюю сеть"):
        urlguard.PublicSyncBackend().connect_tcp("rebind.test", 80)
    assert connected == []


def test_fetch_revalidates_dns_at_connect_and_rejects_private_rebind(monkeypatch):
    answers = iter([
        [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 80))],
        [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80))],
    ])
    connected = []
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        httpcore.SyncBackend,
        "connect_tcp",
        lambda *_args, **_kwargs: connected.append(True),
    )
    with pytest.raises(ValueError, match="внутреннюю сеть"):
        urlguard.fetch_public_bytes(
            "http://rebind.test/", timeout=1, max_bytes=100,
        )
    assert connected == []


class _HttpStream(httpcore.NetworkStream):
    def __init__(self):
        self.server_hostname = None
        self.writes = []
        self.response_pending = True

    def read(self, _max_bytes, timeout=None):
        if self.response_pending:
            self.response_pending = False
            return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        return b""

    def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    def close(self):
        return None

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.server_hostname = server_hostname
        return self

    def get_extra_info(self, _info):
        return None


def test_https_keeps_original_host_and_sni_above_numeric_transport(monkeypatch):
    monkeypatch.setattr(urlguard.socket, "getaddrinfo", _public_dns)
    stream = _HttpStream()
    connected = []

    def connect(_self, host, port, **_kwargs):
        connected.append((host, port))
        return stream

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    with httpx.Client(transport=urlguard.PublicHTTPTransport()) as client:
        response = client.get("https://original.example/path")
    assert response.status_code == 200
    assert connected == [("8.8.8.8", 443)]
    assert stream.server_hostname == "original.example"
    request_bytes = b"".join(stream.writes).lower()
    assert b"host: original.example\r\n" in request_bytes


@pytest.mark.parametrize("value", [
    "http://user@example.com/",
    "http://user:secret@example.com/",
    "http://example.com:99999/",
])
def test_strict_outbound_host_syntax(value):
    with pytest.raises(ValueError):
        urlguard.validate_public_url(value)


class _FakeRoute:
    def __init__(self):
        self.action = None

    def abort(self, _reason):
        self.action = "abort"

    def continue_(self):
        self.action = "continue"


class _FakeWsRoute:
    def __init__(self, url):
        self.url = url
        self.action = None

    def close(self, **_kwargs):
        self.action = "close"

    def connect_to_server(self):
        self.action = "connect"


class _GuardContext:
    def route(self, _pattern, handler):
        self.http_handler = handler

    def route_web_socket(self, _pattern, handler):
        self.ws_handler = handler


def test_playwright_guard_filters_subresources_and_websockets():
    context = _GuardContext()
    urlguard.install_playwright_url_guard(context)

    private_route = _FakeRoute()
    context.http_handler(private_route, type("Request", (), {"url": "http://169.254.169.254/latest"})())
    assert private_route.action == "abort"

    public_route = _FakeRoute()
    context.http_handler(public_route, type("Request", (), {"url": "https://8.8.8.8/image.png"})())
    assert public_route.action == "continue"

    private_ws = _FakeWsRoute("ws://127.0.0.1/socket")
    context.ws_handler(private_ws)
    assert private_ws.action == "close"


def test_playwright_guard_applies_document_origin_policy_and_offline_mode():
    context = _GuardContext()
    urlguard.install_playwright_url_guard(
        context,
        validate_url=lambda candidate: candidate,
        allow_document_url=lambda candidate: candidate.startswith("https://approved.example/"),
    )
    rejected = _FakeRoute()
    context.http_handler(
        rejected,
        type("Request", (), {"url": "https://other.example/", "resource_type": "document"})(),
    )
    assert rejected.action == "abort"

    offline = _GuardContext()
    urlguard.install_playwright_offline_guard(offline)
    local = _FakeRoute()
    offline.http_handler(local, type("Request", (), {"url": "file:///tmp/render.html"})())
    assert local.action == "continue"
    remote = _FakeRoute()
    offline.http_handler(remote, type("Request", (), {"url": "http://127.0.0.1/private"})())
    assert remote.action == "abort"


class _FailingPage:
    url = "https://8.8.8.8/"

    def goto(self, *_args, **_kwargs):
        raise RuntimeError("navigation failed")


class _PrivateFinalPage:
    url = "http://127.0.0.1/private"

    def goto(self, *_args, **_kwargs):
        return None


class _FakeContext(_GuardContext):
    def __init__(self, page):
        self.page = page
        self.closed = 0

    def new_page(self):
        return self.page

    def close(self):
        self.closed += 1


class _FakeBrowser:
    def __init__(self, page):
        self.context = _FakeContext(page)
        self.closed = 0

    def new_context(self, **_kwargs):
        return self.context

    def close(self):
        self.closed += 1


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = type("Chromium", (), {"launch": lambda _self, **_kwargs: browser})()


class _PlaywrightManager:
    def __init__(self, browser):
        self.playwright = _FakePlaywright(browser)

    def __enter__(self):
        return self.playwright

    def __exit__(self, *_args):
        return False


@pytest.mark.parametrize("page", [_FailingPage(), _PrivateFinalPage()])
def test_scraper_closes_context_and_browser_on_navigation_failure(monkeypatch, page):
    import playwright.sync_api

    browser = _FakeBrowser(page)
    monkeypatch.setattr(
        playwright.sync_api, "sync_playwright", lambda: _PlaywrightManager(browser),
    )
    with pytest.raises((RuntimeError, ValueError)):
        scraper.render_page_sync("https://8.8.8.8/", screenshot=False)
    assert browser.context.closed == 1
    assert browser.closed == 1


def test_reproduce_closes_context_and_browser_on_navigation_failure(monkeypatch):
    import playwright.sync_api

    browser = _FakeBrowser(_FailingPage())
    monkeypatch.setattr(
        playwright.sync_api, "sync_playwright", lambda: _PlaywrightManager(browser),
    )
    with pytest.raises(RuntimeError, match="navigation failed"):
        reproduce.screenshot_html("<div class='repro'>test</div>")
    assert browser.context.closed == 1
    assert browser.closed == 1


def test_inbound_host_guard_allows_testclient_and_rejects_untrusted_host():
    from fastapi.testclient import TestClient
    import server

    with TestClient(server.app) as client:
        allowed = client.get("/", follow_redirects=False)
        localhost = client.get(
            "/", headers={"host": "localhost:8420"}, follow_redirects=False,
        )
        rejected = client.get("/", headers={"host": "evil.example"}, follow_redirects=False)
    assert allowed.status_code == 307
    assert localhost.status_code == 307
    assert rejected.status_code == 400
