"""Subprocess round-trips for the DesignDNA stdio MCP server.

Запуск: .venv/Scripts/python -m pytest app/designdna_mcp_server_test.py -q
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import project_store  # noqa: E402
import designdna_mcp_server as mcp_server  # noqa: E402
from designdna_mcp_server import (  # noqa: E402
    CACHE_TTL_MS,
    JSONRPC_UNSUPPORTED_PROTOCOL,
    LEGACY_PROTOCOL_VERSIONS,
    MAX_ID_LEN,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    META_PROTOCOL_VERSION,
    META_SERVER_INFO,
    MODERN_PROTOCOL_VERSION,
    PREFERRED_LEGACY_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    _dispatch_tool,
    validate_embedded_irs,
    validate_project_shape,
)
from design_system import document as design_system_document  # noqa: E402
from design_system import store as design_system_store  # noqa: E402

SERVER = ROOT / "app" / "designdna_mcp_server.py"
FRAME = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
TOOL_NAMES = [
    "designdna_generate",
    "designdna_list_design_systems",
    "designdna_review",
    "designdna_rules_get",
    "designdna_rules_set",
    "designdna_project_get",
    "designdna_project_put",
    "designdna_design_ir_validate",
    "designdna_project_summary",
    "designdna_live_command",
]


def _env(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["DESIGNDNA_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(ROOT / "app") + os.pathsep + env.get("PYTHONPATH", "")
    return env


class McpProc:
    def __init__(self, data_dir: Path):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_env(data_dir),
        )
        self._n = 0
        self.stdout_lines: list[str] = []

    def close_stdin(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
            self.proc.stdin = None

    def stop(self) -> int:
        self.close_stdin()
        try:
            return self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=4)
            return -1

    def send_raw(self, raw: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def rpc(self, method: str, params: dict | None = None, ident=None):
        self._n += 1
        if ident is None:
            ident = self._n
        msg = {"jsonrpc": "2.0", "id": ident, "method": method, "params": {} if params is None else params}
        self.send_raw((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        line = self.proc.stdout.readline()
        assert line, "server closed stdout"
        decoded = line.decode("utf-8")
        self.stdout_lines.append(decoded)
        return json.loads(decoded)

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.send_raw((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))

    def tool(self, name: str, arguments: dict, params: dict | None = None):
        body = {"name": name, "arguments": arguments}
        if params:
            body.update(params)
        reply = self.rpc("tools/call", body)
        result = reply.get("result") or {}
        text = (result.get("content") or [{}])[0].get("text") or "{}"
        return reply, json.loads(text)

    def handshake(self, protocol_version: str = PREFERRED_LEGACY_PROTOCOL_VERSION) -> dict:
        init = self.rpc("initialize", {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        })
        self.notify("notifications/initialized", {})
        return init


def _modern_params(**extra) -> dict:
    params = {
        "_meta": {
            META_PROTOCOL_VERSION: MODERN_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    params.update(extra)
    return params


def _project(ir_doc: dict | None, *, name: str = "Home", extra_node=None) -> dict:
    nodes = [
        {"id": 1, "type": "prompt", "data": {"text": "brief"}},
    ]
    if ir_doc is not None:
        nodes.append({"id": 2, "type": "edit", "data": {"ir": ir_doc}})
    if extra_node:
        nodes.append(extra_node)
    return {
        "version": "designai-pages-v1",
        "activePageId": "page-1",
        "pages": [{
            "id": "page-1",
            "name": name,
            "graph": {"nodes": nodes, "edges": [], "view": {"x": 0, "y": 0, "zoom": 1}, "nextId": 9},
        }],
        "channels": {},
    }


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(root))
    monkeypatch.setattr(project_store, "DATA_ROOT", root)
    monkeypatch.setattr(project_store, "DB_PATH", root / "projects.db")
    return root


def test_initialize_list_get_round_trip(data_dir):
    mcp = McpProc(data_dir)
    try:
        init = mcp.handshake()
        assert init["result"]["protocolVersion"] in SUPPORTED_PROTOCOL_VERSIONS
        assert init["result"]["serverInfo"]["name"] == SERVER_NAME
        listed = mcp.rpc("tools/list", {})
        assert "resultType" not in listed["result"]
        names = [tool["name"] for tool in listed["result"]["tools"]]
        assert names == TOOL_NAMES
        by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}
        assert by_name["designdna_project_get"]["annotations"]["readOnlyHint"] is True
        assert by_name["designdna_project_put"]["annotations"]["readOnlyHint"] is False
        assert by_name["designdna_project_put"]["annotations"]["destructiveHint"] is True
        assert "Service/transfer-only" in by_name["designdna_project_put"]["description"]
        assert "full DesignDNA Generator pipeline" in by_name["designdna_generate"]["description"]
        reply, body = mcp.tool("designdna_project_get", {})
        assert reply["result"]["isError"] is False
        assert body["ok"] is True
        assert body["revision"] == project_store.EMPTY_REVISION
        assert body["payload"] == {}
        for raw_line in mcp.stdout_lines:
            parsed = json.loads(raw_line)
            assert parsed.get("jsonrpc") == "2.0"
    finally:
        assert mcp.stop() == 0


class _FakeHttpResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self.raw[:limit]


def _mock_http(monkeypatch, responses):
    calls = []
    queue = list(responses)

    def open_request(request, timeout):
        calls.append({
            "url": request.full_url,
            "method": request.get_method(),
            "body": json.loads(request.data.decode("utf-8")) if request.data else None,
            "timeout": timeout,
        })
        return _FakeHttpResponse(queue.pop(0))

    monkeypatch.setattr(mcp_server.urllib.request, "urlopen", open_request)
    return calls


def test_generate_uses_configured_http_server_and_returns_pipeline_fields(monkeypatch):
    monkeypatch.setenv("DESIGNDNA_SERVER_URL", "http://127.0.0.1:8499/")
    calls = _mock_http(monkeypatch, [{
        "variants": [{"version": "1.1", "tokens": {}, "tree": []}],
        "generationLog": {"variants": [{"index": 0}]},
        "qa": [{"index": 0, "journal": []}],
        "designSystem": {"errors": [], "warnings": []},
    }])
    payload, failed = _dispatch_tool("designdna_generate", {
        "brief": "Account settings",
        "designSystem": {"systemId": "ds-main", "revision": 4, "usageMode": "strict"},
        "count": 1,
        "referenceIrs": [{"version": "1.1", "tokens": {}, "tree": []}],
    })
    assert failed is False
    assert payload["ok"] is True
    assert set(("variants", "generationLog", "qa")) <= set(payload)
    assert calls == [{
        "url": "http://127.0.0.1:8499/api/generate",
        "method": "POST",
        "body": {
            "brief": "Account settings",
            "designSystem": {"systemId": "ds-main", "revision": 4, "usageMode": "strict"},
            "count": 1,
            "referenceIrs": [{"version": "1.1", "tokens": {}, "tree": []}],
        },
        "timeout": mcp_server.HTTP_TIMEOUT_SECONDS,
    }]


def test_generate_rejects_bad_count_reference_irs_and_design_system():
    payload, failed = _dispatch_tool("designdna_generate", {
        "brief": "Settings",
        "designSystem": {"systemId": "", "revision": -1, "usageMode": "free"},
        "count": 0,
        "referenceIrs": [{}, "not-an-ir"],
    })
    assert failed is True
    assert len(payload["errors"]) >= 4


def test_list_design_systems_returns_compact_component_registry(data_dir):
    document = design_system_document.new_document("Acme")
    document["components"] = {
        "button": {
            "name": "Button",
            "category": "action",
            "origin": "user",
            "confirmed": True,
            "masterIr": FRAME,
            "variants": {
                "primary": {"label": "Primary", "semanticKey": "primary"},
                "quiet": {"label": "Quiet", "semanticKey": "secondary"},
            },
        }
    }
    document["styleGuide"] = {"irTokens": {"color": {"primary": "#123456"}}}
    design_system_store.save_draft(document)
    payload, failed = _dispatch_tool("designdna_list_design_systems", {})
    assert failed is False
    assert payload["systems"][0] == {
        "systemId": document["id"],
        "name": "Acme",
        "status": "draft",
        "revision": 0,
        "components": [{
            "key": "button", "name": "Button", "category": "action",
            "variants": [
                {"key": "primary", "label": "Primary", "semanticKey": "primary"},
                {"key": "quiet", "label": "Quiet", "semanticKey": "secondary"},
            ],
        }],
        "irTokens": {"color": {"primary": "#123456"}},
    }


def test_review_calls_quality_gate_then_resolve_context(monkeypatch):
    source_ir = {"version": "1.1", "tokens": {}, "tree": []}
    fixed_ir = {"version": "1.1", "tokens": {"color": {}}, "tree": []}
    calls = _mock_http(monkeypatch, [
        {"passed": False, "violations": [{"rule": "token-color"}], "journal": [{"action": "snap"}], "fixed_ir": fixed_ir},
        {"context": {"systemRef": {"systemId": "ds-main", "revision": 2}}},
    ])
    validated = {}

    def validate(candidate, context):
        validated.update({"ir": candidate, "context": context})
        return {"errors": [], "warnings": [], "identity": {"score": 95}}

    monkeypatch.setattr(mcp_server.design_system_resolver, "validate_generation", validate)
    payload, failed = _dispatch_tool("designdna_review", {
        "ir": source_ir,
        "designSystem": {"systemId": "ds-main", "revision": 2, "usageMode": "strict"},
    })
    assert failed is False
    assert payload["violations"] == [{"rule": "token-color"}]
    assert payload["journal"] == [{"action": "snap"}]
    assert payload["fixed_ir"] == fixed_ir
    assert payload["designSystem"]["identity"]["score"] == 95
    assert validated["ir"] == fixed_ir
    assert [call["url"] for call in calls] == [
        "http://127.0.0.1:8420/api/quality-gate",
        "http://127.0.0.1:8420/api/design-system/resolve-context",
    ]
    assert calls[0]["body"] == {"ir": source_ir, "fix": True, "strictTokens": True}
    assert calls[1]["body"] == {
        "ref": {"systemId": "ds-main", "revision": 2},
        "usageMode": "strict",
        "brief": "",
    }


def test_review_without_design_system_only_calls_quality_gate(monkeypatch):
    ir_doc = {"version": "1.1", "tokens": {}, "tree": []}
    calls = _mock_http(monkeypatch, [{"passed": True, "violations": [], "journal": [], "fixed_ir": ir_doc}])
    payload, failed = _dispatch_tool("designdna_review", {"ir": ir_doc})
    assert failed is False and payload["passed"] is True
    assert len(calls) == 1


def test_rules_tools_proxy_shared_server_rules(monkeypatch):
    calls = _mock_http(monkeypatch, [
        {"builtIn": {"design": "..."}, "project": "old"},
        {"builtIn": {"design": "..."}, "project": "new"},
    ])
    got, get_failed = _dispatch_tool("designdna_rules_get", {})
    saved, set_failed = _dispatch_tool("designdna_rules_set", {"text": "new"})
    assert get_failed is False and set_failed is False
    assert got["project"] == "old" and saved["project"] == "new"
    assert [(call["method"], call["url"], call["body"]) for call in calls] == [
        ("GET", "http://127.0.0.1:8420/api/rules", None),
        ("POST", "http://127.0.0.1:8420/api/rules/project", {"text": "new"}),
    ]


def test_valid_dry_run_then_put_and_store_round_trip(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        project = _project(FRAME, name="Главная")
        reply, dry = mcp.tool("designdna_project_put", {
            "project": project,
            "expectedRevision": got["revision"],
            "dryRun": True,
        })
        assert reply["result"]["isError"] is False
        assert dry["ok"] is True and dry["dryRun"] is True
        assert dry["revision"] == project_store.payload_revision(project)
        loaded = project_store.load_project()
        assert loaded is None
        reply, put = mcp.tool("designdna_project_put", {
            "project": project,
            "expectedRevision": got["revision"],
            "dryRun": False,
        })
        assert reply["result"]["isError"] is False
        assert put["ok"] is True and put["dryRun"] is False
        assert dry["revision"] == put["revision"] == project_store.payload_revision(project)
        loaded = project_store.load_project()
        assert loaded is not None
        assert loaded["payload"]["pages"][0]["name"] == "Главная"
        assert loaded["payload"]["pages"][0]["id"] == "page-1"
        assert loaded["payload"]["pages"][0]["graph"]["nodes"][0]["id"] == 1
        assert project_store.inspect_project()["revision"] == put["revision"]
        _, summary = mcp.tool("designdna_project_summary", {})
        assert summary["pages"] == 1 and summary["nodes"] == 2
        assert summary["embeddedIrs"] >= 1
    finally:
        assert mcp.stop() == 0


def test_stale_revision_conflict(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        first = _project(FRAME, name="one")
        _, put = mcp.tool("designdna_project_put", {
            "project": first, "expectedRevision": got["revision"],
        })
        assert put["ok"] is True
        stale = _project(FRAME, name="two")
        reply, body = mcp.tool("designdna_project_put", {
            "project": stale, "expectedRevision": got["revision"],
        })
        assert reply["result"]["isError"] is True
        assert body["ok"] is False and body["stale"] is True
        assert body["revision"] == put["revision"]
        loaded = project_store.load_project()
        assert loaded["payload"]["pages"][0]["name"] == "one"
    finally:
        assert mcp.stop() == 0


def test_invalid_embedded_ir_fail_closed(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        bad_ir = {"version": "1.0", "tree": "nope"}
        project = _project(bad_ir)
        reply, body = mcp.tool("designdna_project_put", {
            "project": project, "expectedRevision": got["revision"],
        })
        assert reply["result"]["isError"] is True
        assert body["ok"] is False
        assert any("tree" in err or "IR" in err or "object" in err.lower() or "array" in err.lower()
                   for err in body.get("errors") or [])
        assert project_store.load_project() is None
        _, validated = mcp.tool("designdna_design_ir_validate", {"ir": bad_ir})
        assert validated["ok"] is False
        assert validated["errors"]
    finally:
        assert mcp.stop() == 0


def test_unicode_round_trip(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        ir_doc = json.loads(json.dumps(FRAME))
        ir_doc["tree"][0]["props"]["heading"] = "Свежие объявления"
        project = _project(ir_doc, name="Карточка")
        _, put = mcp.tool("designdna_project_put", {
            "project": project, "expectedRevision": got["revision"],
        })
        assert put["ok"] is True
        _, again = mcp.tool("designdna_project_get", {})
        assert again["payload"]["pages"][0]["name"] == "Карточка"
        heading = again["payload"]["pages"][0]["graph"]["nodes"][1]["data"]["ir"]["tree"][0]["props"]["heading"]
        assert heading == "Свежие объявления"
        loaded = project_store.load_project()
        assert loaded["payload"]["pages"][0]["name"] == "Карточка"
    finally:
        assert mcp.stop() == 0


def test_oversized_request_rejected(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        huge = b'{"jsonrpc":"2.0","id":99,"method":"tools/list","params":{"pad":"' + (b"A" * (MAX_REQUEST_BYTES + 64)) + b'"}}\n'
        mcp.send_raw(huge)
        line = mcp.proc.stdout.readline()
        decoded = line.decode("utf-8")
        mcp.stdout_lines.append(decoded)
        reply = json.loads(decoded)
        assert reply.get("error", {}).get("code") == -32600
        listed = mcp.rpc("tools/list", {})
        assert "tools" in listed["result"]
    finally:
        assert mcp.stop() == 0


def test_clean_eof_exits_zero(data_dir):
    mcp = McpProc(data_dir)
    mcp.handshake()
    code = mcp.stop()
    assert code == 0


def test_shape_helpers_local():
    assert validate_project_shape({"pages": [{"id": "p", "graph": {"nodes": [{"id": 1}]}}]}) == []
    assert validate_project_shape({"pages": [{"id": "p"}, {"id": "p"}]})
    errors = validate_embedded_irs(_project({"version": "1.0", "tree": "x"}))
    assert errors
    nested = {"pages": [{"id": "p", "graph": {"nodes": [{"id": 1, "type": "x", "data": {
        "wrapper": {"nested": {"version": "1.0", "tree": "bad", "tokens": {}}}
    }}]}}]}
    nested_errors = validate_embedded_irs(nested)
    assert nested_errors
    assert any("wrapper.nested" in item["path"] or "nested" in item["path"] for item in nested_errors)
    unhashable = validate_project_shape({"pages": [{"id": "p", "graph": {
        "nodes": [{"id": {"nested": True}}],
        "edges": [{"id": ["x"]}],
    }}]})
    assert unhashable
    assert all(isinstance(item, str) for item in unhashable)
    unknown_ir = validate_embedded_irs({"pages": [{"id": "p", "graph": {"nodes": [{
        "id": 1, "type": "x", "data": {"ir": {"version": "9.9", "tree": []}},
    }]}}]})
    assert unknown_ir
    assert any("9.9" in item["message"] or "version" in item["message"].lower() or "unsupported" in item["message"].lower()
               for item in unknown_ir)


def test_legacy_raw_row_revision_stable_and_put_succeeds(data_dir):
    project_store.save_project({"version": "designai-pages-v1", "pages": []})
    legacy = '{"z":1, "version":"designai-pages-v1", "pages":[{"id":"page-1","name":"Лего","graph":{"nodes":[],"edges":[]}}]}'
    with sqlite3.connect(str(project_store.DB_PATH)) as con:
        con.execute(
            "UPDATE projects SET payload=? WHERE user_id=? AND project_id=?",
            (legacy, project_store.DEFAULT_USER_ID, project_store.DEFAULT_PROJECT_ID),
        )
        con.commit()
    expected = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, first = mcp.tool("designdna_project_get", {})
        _, second = mcp.tool("designdna_project_get", {})
        assert first["revision"] == second["revision"] == expected
        assert first["payload"]["pages"][0]["name"] == "Лего"
        # Put the migrated get payload, not a re-serialized raw row.
        updated = first["payload"]
        updated["pages"][0]["name"] = "Новое"
        _, put = mcp.tool("designdna_project_put", {
            "project": updated, "expectedRevision": first["revision"],
        })
        assert put["ok"] is True
        loaded = project_store.load_project()
        assert loaded["payload"]["pages"][0]["name"] == "Новое"
        assert project_store.inspect_project()["revision"] == put["revision"]
    finally:
        assert mcp.stop() == 0


def test_two_process_put_race_one_stale_no_lost_write(data_dir):
    a = McpProc(data_dir)
    b = McpProc(data_dir)
    try:
        a.handshake()
        b.handshake()
        _, ga = a.tool("designdna_project_get", {})
        _, gb = b.tool("designdna_project_get", {})
        assert ga["revision"] == gb["revision"]
        rev = ga["revision"]

        def put_as(proc: McpProc, name: str):
            return proc.tool("designdna_project_put", {
                "project": _project(FRAME, name=name),
                "expectedRevision": rev,
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(put_as, a, "alpha")
            fb = pool.submit(put_as, b, "beta")
            ra, rb = fa.result(timeout=30), fb.result(timeout=30)
        bodies = [ra[1], rb[1]]
        oks = [body for body in bodies if body.get("ok") is True]
        stales = [body for body in bodies if body.get("stale") is True]
        assert len(oks) == 1, bodies
        assert len(stales) == 1, bodies
        loaded = project_store.load_project()
        winner = loaded["payload"]["pages"][0]["name"]
        assert winner in ("alpha", "beta")
        assert project_store.inspect_project()["revision"] == oks[0]["revision"]
    finally:
        a.stop()
        b.stop()


def test_corrupt_stored_payload_fail_closed(data_dir):
    project_store.save_project(_project(FRAME, name="ok"))
    with sqlite3.connect(str(project_store.DB_PATH)) as con:
        con.execute(
            "UPDATE projects SET payload=? WHERE user_id=? AND project_id=?",
            ("not-json{", project_store.DEFAULT_USER_ID, project_store.DEFAULT_PROJECT_ID),
        )
        con.commit()
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        reply, body = mcp.tool("designdna_project_get", {})
        assert reply["result"]["isError"] is True
        assert body.get("corrupt") is True
        assert project_store.load_project() is None
        reply2, body2 = mcp.tool("designdna_project_put", {
            "project": _project(FRAME, name="rescue"),
            "expectedRevision": project_store.EMPTY_REVISION,
        })
        assert reply2["result"]["isError"] is True
        assert body2.get("corrupt") is True
        assert project_store.load_project() is None
    finally:
        assert mcp.stop() == 0


def test_rejects_invalid_tool_arguments(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        extra = mcp.rpc("tools/call", {"name": "designdna_project_get", "arguments": {"nope": 1}})
        assert extra.get("error", {}).get("code") == -32602
        typed = mcp.rpc("tools/call", {"name": "designdna_project_get", "arguments": {"userId": 1}})
        assert typed.get("error", {}).get("code") == -32602
        arrayed = mcp.rpc("tools/call", {"name": "designdna_project_put", "arguments": []})
        assert arrayed.get("error", {}).get("code") == -32602
        rev_type = mcp.rpc("tools/call", {"name": "designdna_project_put", "arguments": {
            "project": {}, "expectedRevision": 0,
        }})
        assert rev_type.get("error", {}).get("code") == -32602
        mcp.send_raw(b"\xff\xfe\n")
        raw_line = mcp.proc.stdout.readline().decode("utf-8")
        mcp.stdout_lines.append(raw_line)
        utf = json.loads(raw_line)
        assert utf.get("error", {}).get("code") == -32700
        for raw_line in mcp.stdout_lines:
            parsed = json.loads(raw_line)
            assert parsed.get("jsonrpc") == "2.0"
    finally:
        assert mcp.stop() == 0


def test_stdout_is_protocol_only(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        mcp.tool("designdna_project_get", {})
        mcp.rpc("tools/list", {})
        for raw_line in mcp.stdout_lines:
            parsed = json.loads(raw_line)
            assert parsed.get("jsonrpc") == "2.0"
            assert "result" in parsed or "error" in parsed
    finally:
        code = mcp.stop()
        err = mcp.proc.stderr.read().decode("utf-8", errors="replace")
        assert code == 0
        assert "jsonrpc" not in err
        assert not any(line.lstrip().startswith("{") for line in err.splitlines())


def test_server_discover_without_initialize(data_dir):
    mcp = McpProc(data_dir)
    try:
        reply = mcp.rpc("server/discover", _modern_params(), ident="discover-1")
        assert "error" not in reply
        result = reply["result"]
        assert result["resultType"] == "complete"
        assert result["supportedVersions"] == list(SUPPORTED_PROTOCOL_VERSIONS)
        assert result["capabilities"] == {"tools": {}}
        assert result["ttlMs"] == CACHE_TTL_MS
        assert result["cacheScope"] == "public"
        assert result["_meta"][META_SERVER_INFO] == {
            "name": SERVER_NAME, "version": SERVER_VERSION,
        }
        assert "expectedRevision" in result["instructions"]
        assert "resultType" not in mcp.rpc("initialize", {
            "protocolVersion": PREFERRED_LEGACY_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        }).get("result", {})
    finally:
        assert mcp.stop() == 0


def test_server_discover_without_meta_still_succeeds(data_dir):
    mcp = McpProc(data_dir)
    try:
        reply = mcp.rpc("server/discover", {}, ident="discover-bare")
        assert reply["result"]["resultType"] == "complete"
        assert reply["result"]["supportedVersions"] == [
            MODERN_PROTOCOL_VERSION, "2025-11-25", "2024-11-05",
        ]
    finally:
        assert mcp.stop() == 0


def test_modern_tools_list_and_get_without_initialize(data_dir):
    mcp = McpProc(data_dir)
    try:
        listed = mcp.rpc("tools/list", _modern_params())
        result = listed["result"]
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == CACHE_TTL_MS
        assert result["cacheScope"] == "public"
        assert result["_meta"][META_SERVER_INFO]["name"] == SERVER_NAME
        assert [tool["name"] for tool in result["tools"]] == TOOL_NAMES
        reply, body = mcp.tool("designdna_project_get", {}, params=_modern_params())
        assert reply["result"]["resultType"] == "complete"
        assert reply["result"]["_meta"][META_SERVER_INFO]["version"] == SERVER_VERSION
        assert reply["result"]["isError"] is False
        assert body["ok"] is True
        assert body["revision"] == project_store.EMPTY_REVISION
    finally:
        assert mcp.stop() == 0


def test_unsupported_protocol_version_error(data_dir):
    mcp = McpProc(data_dir)
    try:
        listed = mcp.rpc("tools/list", {
            "_meta": {META_PROTOCOL_VERSION: "1900-01-01",
                      "io.modelcontextprotocol/clientCapabilities": {}},
        })
        error = listed["error"]
        assert error["code"] == JSONRPC_UNSUPPORTED_PROTOCOL
        assert error["message"] == "Unsupported protocol version"
        assert error["data"]["requested"] == "1900-01-01"
        assert error["data"]["supported"] == list(SUPPORTED_PROTOCOL_VERSIONS)
        discover = mcp.rpc("server/discover", {
            "_meta": {META_PROTOCOL_VERSION: "1900-01-01",
                      "io.modelcontextprotocol/clientCapabilities": {}},
        })
        assert discover["error"]["code"] == JSONRPC_UNSUPPORTED_PROTOCOL
        assert discover["error"]["data"]["supported"] == list(SUPPORTED_PROTOCOL_VERSIONS)
    finally:
        assert mcp.stop() == 0


def test_legacy_initialize_2024_and_ping(data_dir):
    mcp = McpProc(data_dir)
    try:
        init = mcp.handshake("2024-11-05")
        assert init["result"]["protocolVersion"] == "2024-11-05"
        assert init["result"]["protocolVersion"] in LEGACY_PROTOCOL_VERSIONS
        ping = mcp.rpc("ping", {})
        assert ping["result"] == {}
        modern_ping = mcp.rpc("ping", _modern_params())
        assert modern_ping.get("error", {}).get("code") == -32601
    finally:
        assert mcp.stop() == 0


def test_legacy_and_modern_on_same_process(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, legacy = mcp.tool("designdna_project_get", {})
        listed = mcp.rpc("tools/list", _modern_params())
        assert listed["result"]["resultType"] == "complete"
        _, modern = mcp.tool("designdna_project_get", {}, params=_modern_params())
        assert legacy["revision"] == modern["revision"] == project_store.EMPTY_REVISION
    finally:
        assert mcp.stop() == 0


def test_legacy_tools_list_without_initialize_rejected(data_dir):
    mcp = McpProc(data_dir)
    try:
        listed = mcp.rpc("tools/list", {})
        assert listed.get("error", {}).get("code") == -32600
        assert "initialize" in listed["error"]["message"]
    finally:
        assert mcp.stop() == 0


def test_initialize_with_modern_version_stays_legacy(data_dir):
    mcp = McpProc(data_dir)
    try:
        init = mcp.handshake(MODERN_PROTOCOL_VERSION)
        assert init["result"]["protocolVersion"] == PREFERRED_LEGACY_PROTOCOL_VERSION
        listed = mcp.rpc("tools/list", {})
        assert "resultType" not in listed["result"]
    finally:
        assert mcp.stop() == 0


def _raw_revision(data_dir: Path) -> tuple[str, str]:
    with sqlite3.connect(str(data_dir / "projects.db")) as con:
        row = con.execute(
            "SELECT payload FROM projects WHERE user_id=? AND project_id=?",
            (project_store.DEFAULT_USER_ID, project_store.DEFAULT_PROJECT_ID),
        ).fetchone()
    assert row and isinstance(row[0], str)
    return row[0], project_store.revision_of_raw(row[0])


def test_save_project_after_other_process_overwrite(data_dir):
    x = {"version": "designai-pages-v1", "pages": [{"id": "page-1", "name": "X", "graph": {"nodes": [], "edges": []}}]}
    y = {"version": "designai-pages-v1", "pages": [{"id": "page-1", "name": "Y", "graph": {"nodes": [], "edges": []}}]}
    first = project_store.save_project(x)
    assert first["ok"] is True
    script = (
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['PYTHONPATH'].split(os.pathsep)[0])\n"
        "import project_store\n"
        "r = project_store.save_project(json.loads(sys.argv[1]))\n"
        "print(json.dumps({'ok': r['ok'], 'revision': r['revision']}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, json.dumps(y, ensure_ascii=False)],
        env=_env(data_dir), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    peer = json.loads(proc.stdout.strip().splitlines()[-1])
    assert peer["ok"] is True
    again = project_store.save_project(x)
    assert again["ok"] is True
    assert again.get("unchanged") is not True
    loaded = project_store.load_project()
    assert loaded["payload"]["pages"][0]["name"] == "X"
    inspect = project_store.inspect_project()
    raw, raw_rev = _raw_revision(data_dir)
    assert inspect["revision"] == again["revision"] == raw_rev
    assert json.loads(raw)["pages"][0]["name"] == "X"


def test_cas_rewrite_x_after_other_process_y(data_dir):
    a = McpProc(data_dir)
    b = McpProc(data_dir)
    try:
        a.handshake()
        b.handshake()
        _, got = a.tool("designdna_project_get", {})
        _, px = a.tool("designdna_project_put", {
            "project": _project(FRAME, name="X"), "expectedRevision": got["revision"],
        })
        assert px["ok"] is True
        _, py = b.tool("designdna_project_put", {
            "project": _project(FRAME, name="Y"), "expectedRevision": px["revision"],
        })
        assert py["ok"] is True
        _, px2 = a.tool("designdna_project_put", {
            "project": _project(FRAME, name="X"), "expectedRevision": py["revision"],
        })
        assert px2["ok"] is True
        loaded = project_store.load_project()
        assert loaded["payload"]["pages"][0]["name"] == "X"
        inspect = project_store.inspect_project()
        _, raw_rev = _raw_revision(data_dir)
        assert inspect["revision"] == px2["revision"] == raw_rev
    finally:
        a.stop()
        b.stop()


def test_rejects_overlong_and_nonconforming_ids(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        long_id = "a" * (MAX_ID_LEN + 1)
        over = mcp.rpc("tools/call", {"name": "designdna_project_get", "arguments": {"userId": long_id}})
        assert over.get("error", {}).get("code") == -32602
        slash = mcp.rpc("tools/call", {"name": "designdna_project_get", "arguments": {"projectId": "a/b"}})
        assert slash.get("error", {}).get("code") == -32602
        space = mcp.rpc("tools/call", {"name": "designdna_project_get", "arguments": {"userId": "bad id"}})
        assert space.get("error", {}).get("code") == -32602
    finally:
        assert mcp.stop() == 0


def test_unhashable_ids_fail_closed_not_internal(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        project = {
            "version": "designai-pages-v1",
            "pages": [{"id": "page-1", "graph": {
                "nodes": [{"id": {"oops": 1}, "type": "prompt", "data": {}}],
                "edges": [{"id": ["e1"]}],
            }}],
        }
        reply, body = mcp.tool("designdna_project_put", {
            "project": project, "expectedRevision": got["revision"],
        })
        assert reply["result"]["isError"] is True
        assert body["ok"] is False
        assert body.get("errors")
        assert project_store.load_project() is None
    finally:
        assert mcp.stop() == 0


def test_unknown_ir_version_fail_closed(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        project = _project({"version": "9.9", "tree": []})
        reply, body = mcp.tool("designdna_project_put", {
            "project": project, "expectedRevision": got["revision"],
        })
        assert reply["result"]["isError"] is True
        assert body["ok"] is False
        assert project_store.load_project() is None
    finally:
        assert mcp.stop() == 0


def test_over_1mib_project_put_then_get(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        _, got = mcp.tool("designdna_project_get", {})
        project = _project(None, name="pad")
        project["blob"] = "A" * 1_200_000
        assert len(json.dumps(project).encode("utf-8")) > 1_048_576
        assert len(json.dumps(project).encode("utf-8")) < MAX_RESPONSE_BYTES
        reply, put = mcp.tool("designdna_project_put", {
            "project": project, "expectedRevision": got["revision"],
        })
        assert reply.get("error") is None
        assert put["ok"] is True
        greply, again = mcp.tool("designdna_project_get", {})
        assert greply["result"]["isError"] is False
        assert again["ok"] is True
        assert again["payload"]["blob"] == project["blob"]
        assert again["revision"] == put["revision"]
        assert len(greply["result"]["content"][0]["text"].encode("utf-8")) > 1_048_576
    finally:
        assert mcp.stop() == 0


def test_rejects_non_object_params_and_bad_id(data_dir):
    mcp = McpProc(data_dir)
    try:
        mcp.handshake()
        listed = mcp.rpc("tools/list", [])
        assert listed.get("error", {}).get("code") == -32602
        assert "params" in listed["error"]["message"]
        bad_id = mcp.rpc("tools/list", {}, ident=True)
        assert bad_id.get("error", {}).get("code") == -32600
        mcp.send_raw(b'{"jsonrpc":"2.0","id":1,"method":1,"params":{}}\n')
        raw_line = mcp.proc.stdout.readline().decode("utf-8")
        mcp.stdout_lines.append(raw_line)
        typed_method = json.loads(raw_line)
        assert typed_method.get("error", {}).get("code") == -32600
        still = mcp.rpc("tools/list", {})
        assert "tools" in still["result"]
    finally:
        assert mcp.stop() == 0
