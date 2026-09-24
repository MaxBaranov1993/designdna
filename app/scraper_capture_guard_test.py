"""Захват Source не должен зависать на живых страницах (glebkudr.com, 2026-09-23):

* ``_evaluate_bounded`` прерывает runaway-скрипт и незавершающийся промис;
* drain тел картинок читает только завершённые ответы — стрим без конца не блокирует;
* ``_goto_resilient`` переживает страницу, у которой DOMContentLoaded приходит поздно;
* ``_element_png`` снимает элемент с вечной JS-анимацией без ожидания «стабильности».
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

import scraper

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da6360000000020001e221bc330000000049454e44ae426082")


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):  # noqa: D401 — тишина в тестах
        return

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/fast.png"):
            self.send_response(200); self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_1PX))); self.end_headers(); self.wfile.write(PNG_1PX)
        elif self.path.startswith("/stream.png"):
            # Заголовки есть, тело никогда не заканчивается (chunked без терминатора).
            self.send_response(200); self.send_header("Content-Type", "image/png")
            self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            self.wfile.write(b"4\r\n\x89PNG\r\n"); self.wfile.flush()
            time.sleep(20)
        elif self.path.startswith("/slow.js"):
            time.sleep(6)
            self.send_response(200); self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", "0"); self.end_headers()
        else:
            body = (b"<!doctype html><html><body>"
                    b"<img src='/fast.png'><img src='/stream.png'>"
                    b"<div id='mover' style='position:absolute;width:40px;height:40px;background:#f00'></div>"
                    b"<script>let t=0;(function f(){t++;document.getElementById('mover').style.left=(t%200)+'px';requestAnimationFrame(f)})();</script>"
                    b"</body></html>")
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler) as httpd:
        httpd.daemon_threads = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def test_bounded_evaluate_stops_runaway_scripts(browser) -> None:
    context = browser.new_context(); page = context.new_page(); page.set_content("<div id=a>x</div>")
    cdp = context.new_cdp_session(page)
    assert scraper._evaluate_bounded(cdp, "(x) => x.map(v => v * 2)", [1, 2], 2000) == [2, 4]
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="timeout"):
        scraper._evaluate_bounded(cdp, "() => { while (true) {} }", None, 800)
    with pytest.raises(RuntimeError, match="timeout"):
        scraper._evaluate_bounded(cdp, "() => new Promise(() => {})", None, 800)
    assert time.perf_counter() - started < 5
    assert page.evaluate("() => document.getElementById('a').textContent") == "x", "page survives the abort"
    context.close()


def test_image_drain_skips_unfinished_streams(browser, server) -> None:
    context = browser.new_context(); page = context.new_page()
    bodies: dict[str, bytes] = {}
    drain = scraper.install_image_body_listener(page, bodies)
    page.goto(server + "/", wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(500)
    started = time.perf_counter()
    drain()
    assert time.perf_counter() - started < 3, "drain must not wait for the endless stream"
    assert any(url.endswith("/fast.png") for url in bodies), bodies.keys()
    assert not any(url.endswith("/stream.png") for url in bodies)
    context.close()


def test_goto_resilient_survives_late_domcontentloaded(browser, server) -> None:
    context = browser.new_context(); page = context.new_page()
    page.route("**/late.html", lambda route: route.fulfill(status=200, content_type="text/html",
               body=f"<!doctype html><html><head><script src='{server}/slow.js'></script></head><body><p id=p>late</p></body></html>"))
    started = time.perf_counter()
    scraper._goto_resilient(page, server + "/late.html", 1500)
    assert time.perf_counter() - started < 5, "navigation returns after commit instead of waiting for the slow script"
    assert page.url.endswith("/late.html")
    page.wait_for_selector("#p", timeout=15000)
    assert page.evaluate("() => document.getElementById('p')?.textContent") == "late"
    context.close()


def test_element_png_does_not_wait_for_animated_elements(browser, server) -> None:
    context = browser.new_context(); page = context.new_page()
    page.goto(server + "/", wait_until="domcontentloaded", timeout=15000)
    cdp = context.new_cdp_session(page)
    started = time.perf_counter()
    png = scraper._element_png(page, cdp, "#mover", timeout_ms=4000)
    assert time.perf_counter() - started < 6
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100
    context.close()
