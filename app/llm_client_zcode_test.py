"""Провайдер «zcode» (локальный ZCode CLI, без API-ключей): мок subprocess.
Запуск: python app/llm_client_zcode_test.py (никаких сетевых вызовов и CLI)
"""
import json
import os
import subprocess
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import pathlib
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import llm_client


class _FakeHome:
    """Временный HOME с ~/.zcode: v2-конфиг с coding-plan и credentials."""

    def __init__(self, with_login=True, with_v2=True):
        self.dir = tempfile.mkdtemp(prefix="zcode-test-home-")
        zcode = pathlib.Path(self.dir) / ".zcode"
        (zcode / "v2").mkdir(parents=True)
        if with_login:
            (zcode / "v2" / "credentials.json").write_text("{}", encoding="utf-8")
        if with_v2:
            (zcode / "v2" / "config.json").write_text(json.dumps({
                "provider": {
                    "builtin:zai-coding-plan": {
                        "name": "Z.AI", "kind": "anthropic", "enabled": True,
                        "options": {"apiKey": "k" * 49, "baseURL": "https://api.z.ai/api/anthropic"},
                        "models": {"GLM-5.3": {}, "GLM-5.2": {}},
                    },
                    "56ce6-plain": {
                        "name": "Kimi", "kind": "anthropic",
                        "options": {"apiKey": "x" * 10, "baseURL": "https://api.moonshot.cn/anthropic"},
                        "models": {"kimi-k3": {}},
                    },
                }
            }), encoding="utf-8")

    def cli_config(self) -> pathlib.Path:
        return pathlib.Path(self.dir) / ".zcode" / "cli" / "config.json"


class ZcodeBootstrapTest(unittest.TestCase):
    def test_bootstrap_prefers_enabled_coding_plan_and_best_model(self):
        home = _FakeHome()
        with mock.patch.object(llm_client.Path, "home", return_value=pathlib.Path(home.dir)), \
             mock.patch.object(llm_client, "_zcode_cli_path", return_value="C:/fake/zcode.cjs"):
            self.assertTrue(llm_client.zcode_available())
        cfg = json.loads(home.cli_config().read_text(encoding="utf-8"))
        self.assertEqual(cfg["model"]["main"], "builtin:zai-coding-plan/GLM-5.3")
        self.assertIn("builtin:zai-coding-plan", cfg["provider"])

    def test_no_login_means_unavailable(self):
        home = _FakeHome(with_login=False)
        with mock.patch.object(llm_client.Path, "home", return_value=pathlib.Path(home.dir)), \
             mock.patch.object(llm_client, "_zcode_cli_path", return_value="C:/fake/zcode.cjs"):
            self.assertFalse(llm_client.zcode_available())
            self.assertFalse(home.cli_config().exists())

    def test_no_cli_means_unavailable(self):
        home = _FakeHome()
        with mock.patch.object(llm_client.Path, "home", return_value=pathlib.Path(home.dir)), \
             mock.patch.object(llm_client, "_zcode_cli_path", return_value=None):
            self.assertFalse(llm_client.zcode_available())


class ZcodeChatTest(unittest.TestCase):
    def _run_with_fakes(self, home, calls):
        def fake_run(cmd, **kwargs):
            calls.append({"cmd": cmd, **kwargs})
            task_dir = kwargs.get("cwd")
            task = (pathlib.Path(task_dir) / "TASK.md").read_text(encoding="utf-8")
            calls[-1]["task"] = task
            return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}'.encode(), stderr=b"")

        return fake_run

    def test_chat_zcode_renders_task_and_parses_stdout(self):
        home = _FakeHome()
        calls = []
        messages = [
            {"role": "system", "content": "SYSTEM RULES: json only"},
            {"role": "user", "content": "Сделай лендинг"},
        ]
        with mock.patch.object(llm_client.Path, "home", return_value=pathlib.Path(home.dir)), \
             mock.patch.object(llm_client, "_zcode_cli_path", return_value="C:/fake/zcode.cjs"), \
             mock.patch.object(llm_client, "_zcode_node_path", return_value="node"), \
             mock.patch.object(llm_client.subprocess, "run", side_effect=self._run_with_fakes(home, calls)):
            for env_key in ("OPENAI_API_KEY", "KIMI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "XAI_API_KEY"):
                os.environ.pop(env_key, None)
            out = llm_client.chat("auto", messages, 0.7, timeout=30)
        self.assertEqual(json.loads(out), {"ok": True})
        self.assertEqual(len(calls), 1)
        cmd = calls[0]["cmd"]
        self.assertIn("--prompt", cmd)
        self.assertIn("--disallowed-tools", cmd)
        self.assertTrue(cmd[0].endswith("node"))
        self.assertIn("zcode.cjs", cmd[1])
        task = calls[0]["task"]
        self.assertIn("### SYSTEM", task)
        self.assertIn("SYSTEM RULES: json only", task)
        self.assertIn("Сделай лендинг", task)

    def test_vision_chain_has_no_zcode(self):
        # модели coding-плана не принимают inline-изображения: vision только прямые API
        for role in ("vision", "vision_fast", "reproduce"):
            chain = llm_client.routing_models(role)
            self.assertNotIn("zcode/GLM-5.3", chain, role)

    def test_zcode_failure_falls_through_chain_with_message(self):
        home = _FakeHome()
        def failing_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom".encode())
        with mock.patch.object(llm_client.Path, "home", return_value=pathlib.Path(home.dir)), \
             mock.patch.object(llm_client, "_zcode_cli_path", return_value="C:/fake/zcode.cjs"), \
             mock.patch.object(llm_client, "_zcode_node_path", return_value="node"), \
             mock.patch.object(llm_client.subprocess, "run", side_effect=failing_run):
            for env_key in ("OPENAI_API_KEY", "KIMI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "XAI_API_KEY"):
                os.environ.pop(env_key, None)
            with self.assertRaises(RuntimeError) as ctx:
                llm_client.chat(None, [{"role": "user", "content": "x"}], 0.5, timeout=5)
        self.assertIn("zcode/GLM-5.3", str(ctx.exception))

    def test_no_auto_discovery_of_installed_app(self):
        # Без явного ZCODE_CLI транспорт отключён, даже если приватный
        # resources/glm/zcode.cjs существует в LOCALAPPDATA.
        fake_root = tempfile.mkdtemp(prefix="zcode-no-discovery-")
        installed = pathlib.Path(fake_root) / "Programs" / "ZCode" / "resources" / "glm"
        installed.mkdir(parents=True)
        (installed / "zcode.cjs").write_text("// private entry", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": fake_root}, clear=False):
            os.environ.pop("ZCODE_CLI", None)
            try:
                self.assertIsNone(llm_client._zcode_cli_path())
            finally:
                import shutil as _shutil
                _shutil.rmtree(fake_root, ignore_errors=True)

    def test_unconfigured_zcode_skip_message_is_loud(self):
        for env_key in ("OPENAI_API_KEY", "KIMI_API_KEY", "GLM_API_KEY", "ZAI_API_KEY", "XAI_API_KEY", "ZCODE_CLI"):
            os.environ.pop(env_key, None)
        with self.assertRaises(RuntimeError) as ctx:
            llm_client.chat(None, [{"role": "user", "content": "x"}], 0.5, timeout=5)
        self.assertIn("ZCODE_CLI", str(ctx.exception))


class RoutingTest(unittest.TestCase):
    def test_zcode_is_last_in_text_chains(self):
        for role in ("generator", "repair", "quality_judge", "edit"):
            chain = llm_client.routing_models(role)
            self.assertEqual(chain[-1], "zcode/GLM-5.3", role)

    def test_zcode_slug_resolves(self):
        chain = llm_client._resolve_chain("generator", "zcode/GLM-5.3", None)
        self.assertEqual(chain, [("zcode", "GLM-5.3", llm_client.PROVIDERS["zcode"])])

    def test_text_chains_include_zai_and_grok(self):
        chain = llm_client.routing_models("generator")
        self.assertIn("zai/glm-5.3", chain)
        self.assertIn("grok/grok-4.6", chain)
        self.assertLess(chain.index("zai/glm-5.3"), chain.index("zcode/GLM-5.3"))
        # GLM-5.3-first: Zhipu GLM — основной, прямой Z.AI — запасной той же модели
        self.assertLess(chain.index("glm/glm-5.3"), chain.index("zai/glm-5.3"))
        self.assertEqual(chain[0], "glm/glm-5.3")

    def test_zcode_rejects_hard_unsupported_envelope_fields(self):
        request = llm_client.ChatRequest(
            messages=[{"role": "user", "content": "x"}],
            top_p=0.2,
            provider_options={"zcode": {"foo": True}},
        )
        with self.assertRaises(ValueError) as ctx:
            request.assert_supported("zcode")
        message = str(ctx.exception)
        self.assertIn("top_p", message)
        self.assertIn("provider_options", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
