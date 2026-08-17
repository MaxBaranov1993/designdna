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

    body = params.get("body", "")
    if params.get("encoding") == "base64":
        body_bytes = base64.b64decode(str(body))
    elif isinstance(body, (dict, list)):
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    else:
        body_bytes = str(body or "").encode("utf-8")

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
    return {
        "status": response_status,
        "headers": normalized_headers,
        "body": content.decode("utf-8", errors="replace") if textual else base64.b64encode(content).decode("ascii"),
        "encoding": "utf8" if textual else "base64",
    }


async def dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "health":
        return {"ok": True, "transport": "stdio", "backend": "asgi"}
    if method == "http.request":
        return await asgi_request(params)
    if method == "shutdown":
        return {"ok": True, "shutdown": True}
    raise ValueError(f"Unknown method: {method}")


def write_frame(frame: dict[str, Any]) -> None:
    # Keep the JSONL transport ASCII-only. Windows may give a hidden Python
    # worker a legacy stdout code page; escaped JSON still restores Unicode.
    sys.stdout.write(json.dumps(frame, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        message: dict[str, Any] | None = None
        try:
            message = json.loads(line)
            result = asyncio.run(dispatch(str(message.get("method", "")), message.get("params") or {}))
            write_frame({"id": message.get("id"), "result": result})
            if result.get("shutdown"):
                return 0
        except Exception as error:  # protocol boundary: always return a structured failure
            write_frame({
                "id": message.get("id") if message else None,
                "error": {"code": type(error).__name__, "message": str(error)},
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
