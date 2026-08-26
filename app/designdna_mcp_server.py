"""DesignDNA stdio MCP server — project database access for agent harnesses.

Stdout is newline-delimited JSON-RPC only. Diagnostics go to stderr and never
include payloads or secrets. Talks to the same SQLite file as the desktop app
via DESIGNDNA_DATA_DIR (projects.db). When Electron is running, the capability-
gated local bridge also exposes preview/apply commands against the open editor;
Apply returns only after the normal CAS save acknowledges the real revision.

Dual-era protocol: 2026-07-28 is stateless (per-request
io.modelcontextprotocol/protocolVersion in _meta, server/discover, no
initialize). 2025-11-25 and 2024-11-05 still use the initialize handshake.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import uuid
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import ir  # noqa: E402
import project_store  # noqa: E402

MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2024-11-05")
SUPPORTED_PROTOCOL_VERSIONS = (MODERN_PROTOCOL_VERSION,) + LEGACY_PROTOCOL_VERSIONS
PREFERRED_PROTOCOL_VERSION = MODERN_PROTOCOL_VERSION
PREFERRED_LEGACY_PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "designdna-project"
SERVER_VERSION = "1.2.0"
MAX_MESSAGE_BYTES = 2_097_152
MAX_REQUEST_BYTES = MAX_MESSAGE_BYTES
MAX_RESPONSE_BYTES = MAX_MESSAGE_BYTES
MAX_ID_LEN = 128
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
CACHE_TTL_MS = 3_600_000
JSONRPC_PARSE = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL = -32603
JSONRPC_UNSUPPORTED_PROTOCOL = -32022
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
_OVERSIZED = object()
_TOOLS_CALL_PARAM_KEYS = {"name", "arguments", "_meta", "inputResponses", "requestState"}


def _err(msg: str) -> None:
    sys.stderr.write(f"[designdna-mcp] {msg}\n")
    sys.stderr.flush()


def _negotiate_legacy_version(requested: Any) -> str:
    text = str(requested or "")
    if text in LEGACY_PROTOCOL_VERSIONS:
        return text
    return PREFERRED_LEGACY_PROTOCOL_VERSION


def _request_meta(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    meta = params.get("_meta")
    return meta if isinstance(meta, dict) else {}


def _meta_protocol_version(params: Any) -> str | None:
    version = _request_meta(params).get(META_PROTOCOL_VERSION)
    if version is None or version == "":
        return None
    return str(version)


def _server_info() -> dict[str, str]:
    return {"name": SERVER_NAME, "version": SERVER_VERSION}


def _with_modern_result(result: dict[str, Any], *, cacheable: bool = False) -> dict[str, Any]:
    out = dict(result)
    out["resultType"] = "complete"
    meta = out.get("_meta")
    merged = dict(meta) if isinstance(meta, dict) else {}
    merged.setdefault(META_SERVER_INFO, _server_info())
    out["_meta"] = merged
    if cacheable:
        out.setdefault("ttlMs", CACHE_TTL_MS)
        out.setdefault("cacheScope", "public")
    return out


def _discover_result() -> dict[str, Any]:
    return _with_modern_result(
        {
            "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            "capabilities": {"tools": {}},
            "instructions": (
                "DesignDNA saved-project database. Use designdna_project_get, then "
                "designdna_project_put with expectedRevision from get. Validate Design IR "
                "with designdna_design_ir_validate. While Electron is running, use "
                "designdna_live_command for approved Preview/Apply against the open editor."
            ),
        },
        cacheable=True,
    )


def _encode_rpc(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _jsonrpc_id_ok(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, str) or isinstance(value, int)


def _write(message: dict[str, Any]) -> None:
    encoded = _encode_rpc(message)
    if len(encoded) > MAX_RESPONSE_BYTES:
        ident = message.get("id")
        encoded = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": JSONRPC_INTERNAL, "message": "response exceeds bounded output"},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def _result(ident: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": ident, "result": result})


def _error(ident: Any, code: int, message: str, data: Any = None) -> None:
    body: dict[str, Any] = {"code": int(code), "message": str(message)[:500]}
    if data is not None:
        body["data"] = data
    _write({"jsonrpc": "2.0", "id": ident, "error": body})


def _tool_rpc(ident: Any, payload: dict[str, Any], *, is_error: bool = False, modern: bool = False) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    body: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
    if modern:
        body = _with_modern_result(body)
    return {"jsonrpc": "2.0", "id": ident, "result": body}


def _tool_text(ident: Any, payload: dict[str, Any], *, is_error: bool = False, modern: bool = False) -> None:
    message = _tool_rpc(ident, payload, is_error=is_error, modern=modern)
    if len(_encode_rpc(message)) > MAX_RESPONSE_BYTES:
        message = _tool_rpc(
            ident,
            {"ok": False, "errors": [f"result exceeds bounded output ({MAX_RESPONSE_BYTES} UTF-8 bytes)"]},
            is_error=True,
            modern=modern,
        )
    _write(message)


def _unsupported_protocol(ident: Any, requested: Any) -> None:
    _error(
        ident,
        JSONRPC_UNSUPPORTED_PROTOCOL,
        "Unsupported protocol version",
        {"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": str(requested or "")},
    )


def _read_line(stream) -> bytes | None | object:
    buf = bytearray()
    while True:
        chunk = stream.read(1)
        if not chunk:
            return bytes(buf) if buf else None
        if chunk == b"\n":
            return bytes(buf)
        buf.extend(chunk)
        if len(buf) > MAX_REQUEST_BYTES:
            while True:
                rest = stream.read(1)
                if not rest or rest == b"\n":
                    break
            return _OVERSIZED


def _stable_graph_id(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    return False


def _record_id(seen: set[Any], value: Any, path: str, errors: list[str], *, required: bool) -> None:
    if value is None or value == "":
        if required:
            errors.append(f"{path}: required non-empty string or integer")
        return
    if not _stable_graph_id(value):
        errors.append(f"{path}: must be a non-empty string or integer")
        return
    try:
        if value in seen:
            errors.append(f"{path}: duplicate {value!r}")
        else:
            seen.add(value)
    except TypeError:
        errors.append(f"{path}: must be a non-empty string or integer")


def validate_project_shape(payload: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        return ["(root): project must be an object"]
    errors: list[str] = []
    pages = payload.get("pages")
    if pages is None:
        pages = []
    if not isinstance(pages, list):
        return ["pages: must be an array"]
    page_ids: set[Any] = set()
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            errors.append(f"pages[{i}]: must be an object")
            continue
        pid = page.get("id")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"pages[{i}].id: required non-empty string")
        elif pid in page_ids:
            errors.append(f"pages[{i}].id: duplicate {pid!r}")
        else:
            page_ids.add(pid)
        graph = page.get("graph")
        if graph is None:
            continue
        if not isinstance(graph, dict):
            errors.append(f"pages[{i}].graph: must be an object")
            continue
        nodes = graph.get("nodes")
        if nodes is not None and not isinstance(nodes, list):
            errors.append(f"pages[{i}].graph.nodes: must be an array")
            nodes = []
        edges = graph.get("edges")
        if edges is not None and not isinstance(edges, list):
            errors.append(f"pages[{i}].graph.edges: must be an array")
            edges = []
        seen: set[Any] = set()
        for j, node in enumerate(nodes or []):
            if not isinstance(node, dict):
                errors.append(f"pages[{i}].graph.nodes[{j}]: must be an object")
                continue
            _record_id(seen, node.get("id"), f"pages[{i}].graph.nodes[{j}].id", errors, required=True)
        edge_ids: set[Any] = set()
        for k, edge in enumerate(edges or []):
            if not isinstance(edge, dict):
                errors.append(f"pages[{i}].graph.edges[{k}]: must be an object")
                continue
            if "id" in edge:
                _record_id(edge_ids, edge.get("id"), f"pages[{i}].graph.edges[{k}].id", errors, required=False)
    return errors


def _looks_like_design_ir(value: Any) -> bool:
    if not isinstance(value, dict) or "tree" not in value:
        return False
    return "version" in value or "tokens" in value


def iter_embedded_irs(payload: Any, path: str = "$"):
    """Yield every Design IR document anywhere in the JSON tree."""
    if isinstance(payload, dict):
        if _looks_like_design_ir(payload):
            yield path, payload
        for key, child in payload.items():
            child_path = f"{path}.{key}" if path != "$" else key
            yield from iter_embedded_irs(child, child_path)
    elif isinstance(payload, list):
        for index, child in enumerate(payload):
            yield from iter_embedded_irs(child, f"{path}[{index}]")


def validate_embedded_irs(payload: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path, document in iter_embedded_irs(payload):
        for err in ir.validate_ir(document):
            if err.severity == "error":
                found.append({"path": f"{path}/{err.path}", "message": err.message})
    return found


def project_summary(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload.get("pages") if isinstance(payload, dict) else None
    page_count = len(pages) if isinstance(pages, list) else 0
    node_count = 0
    edge_count = 0
    types: dict[str, int] = {}
    ir_count = 0
    for _path, _doc in iter_embedded_irs(payload if isinstance(payload, dict) else {}):
        ir_count += 1
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            graph = page.get("graph") if isinstance(page.get("graph"), dict) else {}
            nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
            edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
            node_count += len(nodes)
            edge_count += len(edges)
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                kind = str(node.get("type") or "unknown")[:80]
                types[kind] = types.get(kind, 0) + 1
    bounded_types = dict(sorted(types.items(), key=lambda item: (-item[1], item[0]))[:64])
    return {
        "pages": page_count,
        "nodes": node_count,
        "edges": edge_count,
        "embeddedIrs": ir_count,
        "nodeTypes": bounded_types,
    }


def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": "designdna_project_get",
            "description": "Read the saved DesignDNA project. payload is migrated; revision is SHA-256 of the exact raw stored JSON so put-after-get is stable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "userId": {"type": "string"},
                    "projectId": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
        },
        {
            "name": "designdna_project_put",
            "description": "Replace the saved project if expectedRevision matches the raw stored SHA-256. dryRun returns the revision that json.dumps(project, ensure_ascii=False) would store, without writing.",
            "inputSchema": {
                "type": "object",
                "required": ["project", "expectedRevision"],
                "properties": {
                    "project": {"type": "object"},
                    "expectedRevision": {"type": "string"},
                    "dryRun": {"type": "boolean"},
                    "userId": {"type": "string"},
                    "projectId": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
        },
        {
            "name": "designdna_design_ir_validate",
            "description": "Validate a Design IR document; returns every schema/semantic error.",
            "inputSchema": {
                "type": "object",
                "required": ["ir"],
                "properties": {"ir": {"type": "object"}},
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
        },
        {
            "name": "designdna_project_summary",
            "description": "Bounded counts of pages, nodes, edges and types without large payloads.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "userId": {"type": "string"},
                    "projectId": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
        },
        {
            "name": "designdna_live_command",
            "description": "Preview or apply a revision-safe command to the currently open DesignDNA editor. Requires the desktop app to be running; mutations use native approval and return only after CAS persistence.",
            "inputSchema": {
                "type": "object",
                "required": ["commandId", "idempotencyKey", "projectId", "intent", "scope", "action", "arguments", "mode", "correlationId", "timeoutMs"],
                "properties": {
                    "commandId": {"type": "string"}, "idempotencyKey": {"type": "string"},
                    "projectId": {"type": "string"}, "pageId": {"type": ["string", "null"]},
                    "baseRevision": {"type": "string"}, "intent": {"type": "string"},
                    "scope": {"type": "object"}, "action": {"type": "string"},
                    "arguments": {"type": "object"}, "mode": {"type": "string", "enum": ["preview", "apply"]},
                    "correlationId": {"type": "string"}, "timeoutMs": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
        },
    ]


_TOOL_ARGS = {
    "designdna_project_get": {
        "allowed": {"userId", "projectId"},
        "required": set(),
        "types": {"userId": str, "projectId": str},
    },
    "designdna_project_put": {
        "allowed": {"project", "expectedRevision", "dryRun", "userId", "projectId"},
        "required": {"project", "expectedRevision"},
        "types": {"project": dict, "expectedRevision": str, "dryRun": bool,
                  "userId": str, "projectId": str},
    },
    "designdna_design_ir_validate": {
        "allowed": {"ir"},
        "required": {"ir"},
        "types": {"ir": dict},
    },
    "designdna_project_summary": {
        "allowed": {"userId", "projectId"},
        "required": set(),
        "types": {"userId": str, "projectId": str},
    },
    "designdna_live_command": {
        "allowed": {"commandId", "idempotencyKey", "projectId", "pageId", "baseRevision", "intent", "scope", "action", "arguments", "mode", "correlationId", "timeoutMs"},
        "required": {"commandId", "idempotencyKey", "projectId", "intent", "scope", "action", "arguments", "mode", "correlationId", "timeoutMs"},
        "types": {"commandId": str, "idempotencyKey": str, "projectId": str, "pageId": (str, type(None)),
                  "baseRevision": str, "intent": str, "scope": dict, "action": str, "arguments": dict,
                  "mode": str, "correlationId": str, "timeoutMs": int},
    },
}


def _check_arguments(name: str, arguments: Any) -> list[str]:
    spec = _TOOL_ARGS.get(name)
    if spec is None:
        return [f"unknown tool: {name}"]
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ["arguments: must be an object"]
    extra = sorted(set(arguments) - spec["allowed"])
    if extra:
        return [f"arguments: unexpected {extra}"]
    errors: list[str] = []
    for key in spec["required"]:
        if key not in arguments:
            errors.append(f"arguments.{key}: required")
    for key, value in arguments.items():
        expected = spec["types"].get(key)
        if expected is dict and not isinstance(value, dict):
            errors.append(f"arguments.{key}: must be an object")
        elif expected is str:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"arguments.{key}: must be a non-empty string")
            elif key in ("userId", "projectId") and not _ID_RE.fullmatch(value):
                errors.append(
                    f"arguments.{key}: must match [A-Za-z0-9._:-]{{1,{MAX_ID_LEN}}}"
                )
        elif expected is bool and not isinstance(value, bool):
            errors.append(f"arguments.{key}: must be a boolean")
    return errors


def _ids(arguments: dict[str, Any]) -> tuple[str, str]:
    user = arguments.get("userId")
    project = arguments.get("projectId")
    user_id = user if isinstance(user, str) and user.strip() else project_store.DEFAULT_USER_ID
    project_id = project if isinstance(project, str) and project.strip() else project_store.DEFAULT_PROJECT_ID
    return user_id, project_id


def _call_get(arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    user_id, project_id = _ids(arguments)
    record = project_store.inspect_project(user_id, project_id)
    if record.get("status") == "corrupt":
        return {"ok": False, "corrupt": True, "errors": record.get("errors") or ["stored project is corrupt"]}, True
    return {
        "ok": True,
        "payload": record.get("payload") or {},
        "updatedAt": record.get("updated_at") or "",
        "revision": record.get("revision") or project_store.EMPTY_REVISION,
        "userId": user_id,
        "projectId": project_id,
    }, False


def _call_put(arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    project = arguments.get("project")
    expected = arguments.get("expectedRevision")
    dry_run = arguments.get("dryRun", False)
    if not isinstance(project, dict):
        return {"ok": False, "errors": ["project: must be an object"]}, True
    if not isinstance(expected, str) or not expected.strip():
        return {"ok": False, "errors": ["expectedRevision: required string"]}, True
    if "dryRun" in arguments and not isinstance(dry_run, bool):
        return {"ok": False, "errors": ["dryRun: must be a boolean"]}, True
    shape = validate_project_shape(project)
    ir_errors = validate_embedded_irs(project)
    if shape or ir_errors:
        return {
            "ok": False,
            "errors": shape + [f"{item['path']}: {item['message']}" for item in ir_errors],
        }, True
    user_id, project_id = _ids(arguments)
    migrated = ir.migrate_project_payload(project)
    preview = {
        "ok": True,
        "payload": migrated,
        "updatedAt": "0000-00-00T00:00:00+00:00",
        "revision": project_store.payload_revision(project),
        "userId": user_id,
        "projectId": project_id,
    }
    if len(_encode_rpc(_tool_rpc(0, preview, modern=True))) > MAX_RESPONSE_BYTES:
        return {
            "ok": False,
            "errors": [f"project exceeds bounded output ({MAX_RESPONSE_BYTES} UTF-8 bytes)"],
        }, True
    result = project_store.commit_project(
        project, expected, dry_run=bool(dry_run), user_id=user_id, project_id=project_id)
    if result.get("corrupt"):
        return {"ok": False, "corrupt": True, "errors": result.get("errors") or ["stored project is corrupt"]}, True
    if result.get("stale"):
        return {
            "ok": False,
            "stale": True,
            "revision": result.get("revision"),
            "updatedAt": result.get("updated_at") or "",
        }, True
    if not result.get("ok"):
        return {"ok": False, "errors": result.get("errors") or ["commit failed"]}, True
    return {
        "ok": True,
        "stale": False,
        "dryRun": bool(result.get("dryRun")),
        "revision": result.get("revision"),
        "updatedAt": result.get("updated_at") or "",
        "userId": user_id,
        "projectId": project_id,
    }, False


def _call_validate(arguments: dict[str, Any]) -> dict[str, Any]:
    document = arguments.get("ir")
    errors = ir.validate_ir(document if isinstance(document, dict) else None)
    return {
        "ok": not errors,
        "errors": [{"path": e.path, "message": e.message, "severity": e.severity} for e in errors],
    }


def _call_summary(arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    user_id, project_id = _ids(arguments)
    record = project_store.inspect_project(user_id, project_id)
    if record.get("status") == "corrupt":
        return {"ok": False, "corrupt": True, "errors": record.get("errors") or ["stored project is corrupt"]}, True
    payload = record.get("payload") or {}
    summary = project_summary(payload)
    summary.update({"ok": True, "userId": user_id, "projectId": project_id})
    return summary, False


def _read_live_capability() -> dict[str, Any]:
    capability_path = project_store.DATA_ROOT / "live-command.json"
    try:
        raw = capability_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("LIVE_EDITOR_UNAVAILABLE: start the DesignDNA desktop app") from exc
    if len(raw) > 16_384:
        raise RuntimeError("LIVE_CAPABILITY_INVALID: capability file is oversized")
    try:
        capability = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("LIVE_CAPABILITY_INVALID: capability file is invalid") from exc
    if not isinstance(capability, dict) or capability.get("version") != 1:
        raise RuntimeError("LIVE_CAPABILITY_INVALID: unsupported capability version")
    endpoint = capability.get("endpoint")
    token = capability.get("token")
    if not isinstance(endpoint, str) or not endpoint or not isinstance(token, str) or len(token) < 32:
        raise RuntimeError("LIVE_CAPABILITY_INVALID: endpoint or token is missing")
    return {"endpoint": endpoint, "token": token}


def _read_bounded_stream(stream: Any) -> bytes:
    data = bytearray()
    while len(data) <= MAX_MESSAGE_BYTES:
        chunk = stream.read(1)
        if not chunk or chunk == b"\n":
            return bytes(data)
        data.extend(chunk)
    raise RuntimeError("LIVE_RESPONSE_TOO_LARGE: desktop response exceeds the MCP bound")


def _call_live(arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    try:
        capability = _read_live_capability()
    except RuntimeError as exc:
        code, _, message = str(exc).partition(": ")
        return {"ok": False, "error": {"code": code, "message": message or code}}, True
    request = json.dumps({
        "token": capability["token"],
        "requestId": f"mcp-{uuid.uuid4()}",
        "command": arguments,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(request) > MAX_MESSAGE_BYTES:
        return {"ok": False, "error": {"code": "MESSAGE_TOO_LARGE", "message": "live command exceeds the MCP bound"}}, True
    try:
        if os.name == "nt":
            with open(capability["endpoint"], "r+b", buffering=0) as pipe:
                pipe.write(request)
                raw = _read_bounded_stream(pipe)
        else:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(130.0)
                client.connect(capability["endpoint"])
                client.sendall(request)
                raw = _read_bounded_stream(client.makefile("rb", buffering=0))
    except OSError as exc:
        return {"ok": False, "error": {"code": "LIVE_EDITOR_UNAVAILABLE", "message": "DesignDNA desktop live bridge is unavailable"}}, True
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"ok": False, "error": {"code": "LIVE_RESPONSE_INVALID", "message": "DesignDNA desktop returned invalid JSON"}}, True
    if not isinstance(response, dict) or response.get("ok") is not True:
        error = response.get("error") if isinstance(response, dict) and isinstance(response.get("error"), dict) else {}
        return {"ok": False, "error": {"code": str(error.get("code") or "LIVE_COMMAND_FAILED"), "message": str(error.get("message") or "Live command failed")}}, True
    return {"ok": True, "result": response.get("result")}, False


def _dispatch_tool(name: str, arguments: Any) -> tuple[dict[str, Any], bool] | str:
    if name not in _TOOL_ARGS:
        return {"ok": False, "errors": [f"unknown tool: {name}"]}, True
    arg_errors = _check_arguments(name, arguments)
    if arg_errors:
        return "invalid-args:" + "; ".join(arg_errors)
    args = arguments if isinstance(arguments, dict) else {}
    if name == "designdna_project_get":
        return _call_get(args)
    if name == "designdna_project_put":
        return _call_put(args)
    if name == "designdna_design_ir_validate":
        payload = _call_validate(args)
        return payload, not payload.get("ok")
    if name == "designdna_project_summary":
        return _call_summary(args)
    if name == "designdna_live_command":
        return _call_live(args)
    return {"ok": False, "errors": [f"unknown tool: {name}"]}, True


def handle(message: dict[str, Any], state: dict[str, bool]) -> None:
    method = message.get("method")
    ident = message.get("id")
    is_notification = "id" not in message
    if not isinstance(method, str) or not method:
        if not is_notification:
            _error(ident if _jsonrpc_id_ok(ident) else None, JSONRPC_INVALID_REQUEST, "invalid request")
        return
    if not is_notification and not _jsonrpc_id_ok(ident):
        _error(None, JSONRPC_INVALID_REQUEST, "invalid request id")
        return
    if "params" in message:
        if not isinstance(message.get("params"), dict):
            if not is_notification:
                _error(ident, JSONRPC_INVALID_PARAMS, "params must be an object")
            return
        params = message["params"]
    else:
        params = {}
    if method == "initialize":
        version = _negotiate_legacy_version(params.get("protocolVersion"))
        state["initialized"] = True
        if is_notification:
            return
        _result(ident, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": _server_info(),
        })
        return
    if method in ("notifications/initialized", "initialized"):
        state["notified"] = True
        return
    if is_notification:
        return
    meta_version = _meta_protocol_version(params)
    if method == "server/discover":
        if meta_version is not None and meta_version not in (MODERN_PROTOCOL_VERSION,):
            _unsupported_protocol(ident, meta_version)
            return
        _result(ident, _discover_result())
        return
    modern = False
    if meta_version is not None:
        if meta_version != MODERN_PROTOCOL_VERSION:
            _unsupported_protocol(ident, meta_version)
            return
        modern = True
    elif not state.get("initialized"):
        _error(ident, JSONRPC_INVALID_REQUEST, "initialize required")
        return
    if method == "tools/list":
        listed = {"tools": _tool_defs()}
        _result(ident, _with_modern_result(listed, cacheable=True) if modern else listed)
        return
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            _error(ident, JSONRPC_INVALID_PARAMS, "tools/call requires name")
            return
        extra = sorted(set(params) - _TOOLS_CALL_PARAM_KEYS)
        if extra:
            _error(ident, JSONRPC_INVALID_PARAMS, f"tools/call unexpected {extra}")
            return
        try:
            dispatched = _dispatch_tool(name, params.get("arguments"))
        except Exception:
            _err("tool raised")
            _error(ident, JSONRPC_INTERNAL, "internal error")
            return
        if isinstance(dispatched, str) and dispatched.startswith("invalid-args:"):
            _error(ident, JSONRPC_INVALID_PARAMS, dispatched.split(":", 1)[1])
            return
        payload, is_error = dispatched
        _tool_text(ident, payload, is_error=is_error, modern=modern)
        return
    if method == "ping":
        if modern:
            _error(ident, JSONRPC_METHOD_NOT_FOUND, "Method not found: ping")
            return
        _result(ident, {})
        return
    _error(ident, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    state = {"initialized": False, "notified": False}
    stdin = sys.stdin.buffer
    while True:
        raw = _read_line(stdin)
        if raw is None:
            return 0
        if raw is _OVERSIZED:
            _error(None, JSONRPC_INVALID_REQUEST, "request exceeds bounded input")
            continue
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            _error(None, JSONRPC_PARSE, "invalid UTF-8")
            continue
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _error(None, JSONRPC_PARSE, "parse error")
            continue
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            ident = message.get("id") if isinstance(message, dict) else None
            _error(ident if _jsonrpc_id_ok(ident) else None,
                   JSONRPC_INVALID_REQUEST, "invalid request")
            continue
        if not isinstance(message.get("method"), str) or not message.get("method"):
            if "id" in message:
                ident = message.get("id")
                _error(ident if _jsonrpc_id_ok(ident) else None, JSONRPC_INVALID_REQUEST, "invalid request")
            continue
        try:
            handle(message, state)
        except Exception:
            _err("handler failed")
            if "id" in message:
                _error(message.get("id"), JSONRPC_INTERNAL, "internal error")


if __name__ == "__main__":
    raise SystemExit(main())
