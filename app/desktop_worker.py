#!/usr/bin/env python3
"""In-process desktop bridge for DesignDNA's ASGI application.

The protocol is newline-delimited JSON over stdin/stdout. stdout is reserved for
protocol frames; application logs are redirected to stderr.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

APP_DIRECTORY = Path(__file__).resolve().parent
if str(APP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(APP_DIRECTORY))


def _load_application():
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        from server import app as application
    if captured.getvalue():
        print(captured.getvalue(), file=sys.stderr, end="")
    return application


ASGI_APP = _load_application()


async def asgi_request(params: dict[str, Any]) -> dict[str, Any]:
    method = str(params.get("method", "GET")).upper()
    raw_path = str(params.get("path", "/"))
    path, _, inline_query = raw_path.partition("?")
    query = params.get("query")
    if isinstance(query, dict):
        query_string = urlencode(query, doseq=True)
    else:
        query_string = str(query or inline_query)

    # Тело приходит либо сырыми байтами бинарного фрейма (bodyBytes, v2),
    # либо legacy-строкой (base64/utf8) для совместимости со старым main
    body_bytes = params.get("bodyBytes")
    if not isinstance(body_bytes, (bytes, bytearray)):
        body = params.get("body", "")
        if params.get("encoding") == "base64":
            body_bytes = base64.b64decode(str(body))
        elif isinstance(body, (dict, list)):
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        else:
            body_bytes = str(body or "").encode("utf-8")
        body_bytes = bytes(body_bytes)

    request_headers = {
        str(key).lower(): str(value)
        for key, value in (params.get("headers") or {}).items()
    }
    # Browser fetch intentionally omits the forbidden ``Host`` header when the
    # renderer request is serialized over IPC.  The ASGI app still runs behind
    # TrustedHostMiddleware, so identify this internal transport as loopback.
    # An explicitly supplied Host is preserved and remains subject to the
    # middleware's rejection policy.
    request_headers.setdefault("host", "127.0.0.1")
    headers = [
        (key.encode("latin-1"), value.encode("latin-1"))
        for key, value in request_headers.items()
    ]
    sent_request = False
    response_status = 500
    response_headers: list[tuple[bytes, bytes]] = []
    response_parts: list[bytes] = []

    async def receive() -> dict[str, Any]:
        nonlocal sent_request
        if sent_request:
            return {"type": "http.disconnect"}
        sent_request = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal response_status, response_headers
        if message["type"] == "http.response.start":
            response_status = int(message["status"])
            response_headers = list(message.get("headers", []))
        elif message["type"] == "http.response.body":
            response_parts.append(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string.encode("utf-8"),
        "root_path": "",
        "headers": headers,
        "client": ("desktop", 0),
        "server": ("127.0.0.1", 8420),
    }
    with contextlib.redirect_stdout(sys.stderr):
        await ASGI_APP(scope, receive, send)
    content = b"".join(response_parts)
    normalized_headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in response_headers}
    content_type = normalized_headers.get("content-type", "")
    textual = content_type.startswith("text/") or "json" in content_type or "javascript" in content_type or "xml" in content_type
    if textual:
        return {
            "status": response_status,
            "headers": normalized_headers,
            "body": content.decode("utf-8", errors="replace"),
            "encoding": "utf8",
        }
    # Бинарный ответ уходит сырыми байтами бинарного фрейма (encoding=raw,
    # bodyLen) — без base64-инфляции на мегабайтных скриншотах/рендерах
    return {
        "status": response_status,
        "headers": normalized_headers,
        "encoding": "raw",
        "bodyBytes": bytes(content),
    }


async def dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "health":
        return {"ok": True, "transport": "stdio", "backend": "asgi"}
    if method == "runtime.configure":
        openai_key = str(params.get("openaiApiKey") or "").strip()
        if openai_key:
            os.environ["OPENAI_API_KEY"] = openai_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        for retired in ("KIMI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "XAI_API_KEY"):
            os.environ.pop(retired, None)
        return {"ok": True, "openaiConfigured": bool(openai_key)}
    if method == "http.request":
        return await asgi_request(params)
    if method == "debug.sleep":
        # Только для регрессионного теста конкурентности (worker_protocol private
        # surface): рендерер не имеет доступа к stdio-методам воркера.
        await asyncio.sleep(max(0.0, min(30.0, float(params.get("seconds", 1.0)))))
        return {"ok": True}
    if method == "shutdown":
        return {"ok": True, "shutdown": True}
    raise ValueError(f"Unknown method: {method}")


def _read_exact(stream, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("worker stdin closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(frame: dict[str, Any]) -> None:
    """Протокол v2: header-строка JSON; если в result есть bytes (bodyBytes),
    они уходят сырыми байтами сразу после header (bodyLen). Чистые JSON-фреймы
    остаются однострочными — repo-canvas и health их используют как раньше."""
    payload = frame.get("result")
    raw: bytes | None = None
    if isinstance(payload, dict) and isinstance(payload.get("bodyBytes"), (bytes, bytearray)):
        raw = bytes(payload.pop("bodyBytes"))
        payload["bodyLen"] = len(raw)
    header = json.dumps(frame, ensure_ascii=True, separators=(",", ":")) + "\n"
    out = sys.stdout.buffer
    out.write(header.encode("ascii"))
    if raw is not None:
        out.write(raw)
    out.flush()


def main() -> int:
    stdin = sys.stdin.buffer
    # http.request обрабатывается ограниченным пулом потоков: Source Import
    # занимает минуты (Chromium × viewports, LLM), а серийная обработка
    # замораживала ВЕСЬ UI — даже /api/design-system/list ждал окончания
    # импорта. FastAPI-эндпоинты синхронные (anyio threadpool), хранилища
    # ходят в SQLite per-call соединениями под локами — конкурентные вызовы
    # безопасны. Служебные методы (runtime.configure/shutdown) остаются
    # инлайн: env-мутации не должны гоняться с запросами.
    from concurrent.futures import ThreadPoolExecutor
    import threading

    write_lock = threading.Lock()

    # Персистентный event loop на поток пула: asyncio.run на каждый запрос
    # создавал/закрывал loop (плюс shutdown_asyncgens), что добавляло
    # латентность каждому вызову и мешало переиспользованию ресурсов ASGI.
    thread_loops = threading.local()

    def run_async(coro: Any) -> Any:
        loop = getattr(thread_loops, "loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            thread_loops.loop = loop
        return loop.run_until_complete(coro)

    def process(message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        try:
            result = run_async(dispatch(method, params))
            with write_lock:
                write_frame({"id": message.get("id"), "result": result})
            if result.get("shutdown"):
                os._exit(0)
        except Exception as error:  # protocol boundary: structured failure
            with write_lock:
                write_frame({
                    "id": message.get("id"),
                    "error": {"code": type(error).__name__, "message": str(error)},
                })

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="asgi") as pool:
        pending = 0
        drained = threading.Condition()

        def process_counted(message: dict[str, Any]) -> None:
            nonlocal pending
            try:
                process(message)
            finally:
                with drained:
                    pending -= 1
                    drained.notify_all()

        while True:
            line = stdin.readline()
            if not line:
                pool.shutdown(wait=True)
                return 0
            try:
                message = json.loads(line)
            except Exception as error:
                with write_lock:
                    write_frame({"id": None, "error": {"code": type(error).__name__, "message": str(error)}})
                continue
            params = message.get("params") or {}
            body_len = params.pop("bodyLen", 0)
            if isinstance(body_len, int) and body_len > 0:
                try:
                    params["bodyBytes"] = _read_exact(stdin, body_len)
                except EOFError as error:
                    with write_lock:
                        write_frame({"id": message.get("id"),
                                     "error": {"code": type(error).__name__, "message": str(error)}})
                    pool.shutdown(wait=True)
                    return 0
            if str(message.get("method", "")) in ("runtime.configure", "shutdown"):
                # env-мутации не гоняются с запросами: ждём, пока активные
                # и уже поставленные в очередь задачи пула завершатся
                # (http.request читает credentials из os.environ по ходу
                # выполнения). Ответы пула продолжают уходить; stdin не
                # читается только пока идёт редкий configure.
                with drained:
                    while pending:
                        drained.wait()
                process(message)
            else:
                # Резервируем pending ДО submit: новый worker thread может
                # стартовать позже следующего stdin frame, и configure не
                # должен проскочить в этом окне или перед queued job.
                with drained:
                    pending += 1
                try:
                    pool.submit(process_counted, message)
                except Exception as error:
                    with drained:
                        pending -= 1
                        drained.notify_all()
                    with write_lock:
                        write_frame({
                            "id": message.get("id"),
                            "error": {"code": type(error).__name__, "message": str(error)},
                        })


if __name__ == "__main__":
    raise SystemExit(main())
