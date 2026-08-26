from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import designdna_mcp_server as mcp


def live_request() -> dict:
    return {
        "commandId": "cmd-1",
        "idempotencyKey": "idem-1",
        "projectId": "default",
        "pageId": "page-1",
        "baseRevision": "a" * 64,
        "intent": "Move node",
        "scope": {"nodeIds": ["1"], "sourceKeys": [], "viewports": ["desktop"]},
        "action": "graph.node.move",
        "arguments": {"nodeId": "1", "x": 10, "y": 20},
        "mode": "preview",
        "correlationId": "trace-1",
        "timeoutMs": 10_000,
    }


class LiveMcpTests(unittest.TestCase):
    def test_live_tool_is_explicit_and_mutating(self) -> None:
        tools = {tool["name"]: tool for tool in mcp._tool_defs()}
        tool = tools["designdna_live_command"]
        self.assertFalse(tool["annotations"]["readOnlyHint"])
        self.assertIn("baseRevision", tool["inputSchema"]["properties"])

    def test_live_arguments_are_strict(self) -> None:
        self.assertEqual(mcp._check_arguments("designdna_live_command", live_request()), [])
        broken = live_request()
        broken["unexpected"] = True
        self.assertTrue(mcp._check_arguments("designdna_live_command", broken))

    def test_missing_desktop_returns_a_structured_tool_error(self) -> None:
        original = mcp.project_store.DATA_ROOT
        try:
            with tempfile.TemporaryDirectory() as directory:
                mcp.project_store.DATA_ROOT = Path(directory)
                payload, is_error = mcp._dispatch_tool("designdna_live_command", live_request())
                self.assertTrue(is_error)
                self.assertEqual(payload["error"]["code"], "LIVE_EDITOR_UNAVAILABLE")
        finally:
            mcp.project_store.DATA_ROOT = original


if __name__ == "__main__":
    unittest.main()
