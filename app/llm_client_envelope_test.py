"""Контрактные тесты ChatRequest envelope (provider-нейтральный запрос).

Проверяют: валидацию, round-trip параметров в wire-payload каждого провайдера,
явные ошибки для неподдерживаемых возможностей (никаких молчаливых потерь),
транспортный блок с dropped-полями и таймауты. Сетевых вызовов нет.
"""
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client as lc  # noqa: E402


def _request(**overrides):
    base = dict(messages=[{"role": "user", "content": "hi"}])
    base.update(overrides)
    return lc.ChatRequest(**base)


class ChatRequestValidation(unittest.TestCase):
    def test_reports_all_issues_at_once(self):
        request = _request(
            temperature=5, top_p=2, seed=-1,
            reasoning_effort="extreme",
            response_format="yaml",
        )
        issues = " ".join(request.validate())
        for fragment in ("temperature", "top_p", "seed", "reasoning_effort", "response_format"):
            self.assertIn(fragment, issues)

    def test_check_raises_value_error(self):
        with self.assertRaises(ValueError):
            _request(messages=[]).check()

    def test_stream_is_rejected_explicitly(self):
        self.assertIn("stream", " ".join(_request(stream=True).validate()))

    def test_multimodal_content_and_system_are_kept(self):
        request = _request(
            system="be brief",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "https://example.test/design.png", "detail": "high"}},
            ]}],
        )
        self.assertEqual(request.system, "be brief")
        payload, _ = request.to_openai_payload("openai", "gpt-test")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "be brief"})
        self.assertEqual(payload["messages"][1]["content"], [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "https://example.test/design.png", "detail": "high"}},
        ])
        with self.assertRaises(ValueError):
            request.assert_supported("zcode")

    def test_tool_history_is_preserved_in_wire_messages(self):
        request = _request(messages=[
            {"role": "user", "content": "call echo"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"value":7}'}}
            ]},
            {"role": "tool", "content": '{"value":7}', "tool_call_id": "call_1", "name": "echo"},
        ])
        payload, _ = request.to_openai_payload("openai", "gpt-test")
        assistant = payload["messages"][1]
        tool = payload["messages"][2]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_1")
        self.assertEqual(tool["role"], "tool")
        self.assertEqual(tool["tool_call_id"], "call_1")
        self.assertEqual(tool["name"], "echo")
        self.assertEqual(tool["content"], '{"value":7}')

    def test_two_round_tool_history_passes_full_check(self):
        # Реальный вход chat_envelope: check() не должен отвергать assistant-ход
        # с пустым content и tool_calls (штатная форма второго раунда tool-цикла).
        request = _request(messages=[
            {"role": "user", "content": "call echo"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"value":7}'}}
            ]},
            {"role": "tool", "content": '{"value":7}', "tool_call_id": "call_1", "name": "echo"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "echo", "arguments": '{"value":8}'}}
            ]},
            {"role": "tool", "content": '{"value":8}', "tool_call_id": "call_2", "name": "echo"},
        ])
        self.assertEqual(request.validate(), [])
        request.check()


class RoundTripPayloads(unittest.TestCase):
    def test_openai_full_surface(self):
        request = _request(
            model="gpt-test", system="sys", temperature=0.3, top_p=0.8,
            max_output_tokens=512, reasoning_effort="low",
            response_format="json_schema",
            response_json_schema={"name": "out", "schema": {"type": "object"}},
            stop=["END"], seed=42, tool_choice="auto", parallel_tool_calls=False,
        )
        payload, dropped = request.to_openai_payload("openai", "gpt-test")
        self.assertEqual(dropped, [])
        self.assertEqual(payload["max_completion_tokens"], 512)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["stop"], ["END"])
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["top_p"], 0.8)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["parallel_tool_calls"], False)

    def test_non_openai_providers_use_max_tokens(self):
        request = _request(max_output_tokens=128, model="grok-test")
        payload, _ = request.to_openai_payload("grok", "grok-test")
        self.assertEqual(payload["max_tokens"], 128)
        self.assertNotIn("max_completion_tokens", payload)

    def test_seed_zero_survives_to_payload(self):
        payload, dropped = _request(seed=0).to_openai_payload("openai", "gpt-test")
        self.assertEqual(payload["seed"], 0)
        self.assertEqual(dropped, [])

    def test_tool_choice_dict_converts_to_wire_shape(self):
        request = _request(
            tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
            tool_choice={"name": "lookup"},
        )
        payload, _ = request.to_openai_payload("grok", "grok-test")
        self.assertEqual(payload["tool_choice"], {"type": "function", "function": {"name": "lookup"}})

    def test_glm_seed_is_dropped_explicitly(self):
        payload, dropped = _request(seed=42).to_openai_payload("glm", "glm-5.3")
        self.assertNotIn("seed", payload)
        self.assertTrue(any(d["field"] == "seed" for d in dropped))

    def test_glm_maps_reasoning_to_thinking_and_reports_budget_drop(self):
        request = _request(reasoning_effort="high", reasoning_budget_tokens=4096)
        payload, dropped = request.to_openai_payload("glm", "glm-5.3")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertTrue(any(d["field"] == "reasoning.budgetTokens" for d in dropped))
        self.assertNotIn("seed", payload)  # GLM seed не принимает

    def test_glm53_never_disables_thinking_and_normalizes_legacy_efforts(self):
        # GLM-5.3: thinking.type=disabled удалён; reasoning_effort low|high|max.
        for provider in ("glm", "zai"):
            for legacy, mapped in (("minimal", "low"), ("medium", "high")):
                payload, dropped = _request(reasoning_effort=legacy).to_openai_payload(provider, "glm-5.3")
                self.assertEqual(payload["thinking"], {"type": "enabled"}, f"{provider}/{legacy}")
                self.assertEqual(payload["reasoning_effort"], mapped)
                note = next((d for d in dropped if d["field"] == "reasoning.effort"), None)
                self.assertIsNotNone(note, f"{provider}/{legacy}: нормализация должна быть записана")
                self.assertIn(legacy, note["reason"])
                self.assertIn(mapped, note["reason"])
            for effort in ("low", "high", "max"):
                payload, dropped = _request(reasoning_effort=effort).to_openai_payload(provider, "glm-5.3")
                self.assertEqual(payload["thinking"], {"type": "enabled"})
                self.assertEqual(payload["reasoning_effort"], effort)
                self.assertFalse(any(d["field"] == "reasoning.effort" for d in dropped))

    def test_tools_and_forced_response_format_are_mutually_exclusive(self):
        request = _request(
            tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
            tool_choice="auto",
        )
        payload, dropped = request.to_openai_payload("openai", "gpt-test", json_mode=True)
        self.assertNotIn("response_format", payload)
        self.assertTrue(any(d["field"] == "responseFormat" for d in dropped))

    def test_foreign_provider_options_are_dropped_explicitly(self):
        request = _request(provider_options={"openai": {"verbosity": "high"}, "glm": {"do_sample": False}})
        payload, dropped = request.to_openai_payload("openai", "gpt-test")
        self.assertEqual(payload["verbosity"], "high")
        self.assertNotIn("do_sample", payload)
        self.assertTrue(any(d["field"] == "providerOptions.glm" for d in dropped))


class ZaiGrokContract(unittest.TestCase):
    """Прямой Z.AI (zai) и xAI (grok): отдельные провайдеры/ключи/хосты."""

    def test_zai_maps_reasoning_to_thinking_and_drops_seed(self):
        request = _request(reasoning_effort="high", seed=42)
        payload, dropped = request.to_openai_payload("zai", "glm-5.3")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertNotIn("seed", payload)
        self.assertTrue(any(d["field"] == "seed" for d in dropped))
        # max — рекомендованный для coding уровень GLM-5.3 — доходит как есть
        payload_max, dropped_max = _request(reasoning_effort="max").to_openai_payload("zai", "glm-5.3")
        self.assertEqual(payload_max["reasoning_effort"], "max")
        self.assertEqual(payload_max["thinking"], {"type": "enabled"})
        self.assertEqual(dropped_max, [])

    def test_zai_parallel_tool_calls_fail_loudly(self):
        request = _request(parallel_tool_calls=True)
        with self.assertRaises(ValueError):
            request.assert_supported("zai")

    def test_zai_official_value_constraints_fail_loudly(self):
        # Официальный Z.AI v4 контракт (GLM-5.3): ошибки ДО сети, не молчаливые
        # снятия и не форвардинг заведомого 400.
        cases = [
            ({"temperature": 1.5}, "temperature"),       # [0, 1]
            ({"top_p": 0.005}, "top_p"),                 # [0.01, 1]
            ({"max_output_tokens": 200_000}, "max_output_tokens"),  # ≤ 131072
            ({"tool_choice": "required"}, "tool_choice"),           # только auto
            ({"tool_choice": {"name": "t"}}, "tool_choice"),
            ({"response_format": "json_schema",
              "response_json_schema": {"name": "o", "schema": {"type": "object"}}}, "response_format"),
            ({"stop": ["A", "B"]}, "stop"),              # одно stop-слово
        ]
        for overrides, field in cases:
            with self.assertRaises(ValueError, msg=f"{field} должен падать громко") as ctx:
                _request(**overrides).assert_supported("zai")
            self.assertIn(field, str(ctx.exception))

    def test_zai_valid_fields_pass_and_reach_payload(self):
        request = _request(
            temperature=1, top_p=0.95, max_output_tokens=131_072,
            tool_choice="auto", response_format="json_object", stop=["END"],
        )
        request.assert_supported("zai")  # не должно кидать
        payload, _ = request.to_openai_payload("zai", "glm-5.3")
        self.assertEqual(payload["temperature"], 1)
        self.assertEqual(payload["top_p"], 0.95)
        self.assertEqual(payload["max_tokens"], 131_072)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["stop"], ["END"])

    def test_zhipu_glm_keeps_its_own_value_contract(self):
        # Zhipu bigmodel.cn constraints не сверены с его актуальной документацией —
        # glm сознательно НЕ наследует Z.AI-диапазоны (scoped separately).
        request = _request(temperature=1.5, tool_choice={"name": "t"},
                           tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}])
        request.assert_supported("glm")  # не должно кидать

    def test_grok_payload_is_openai_compatible(self):
        request = _request(
            model="grok-4.6", max_output_tokens=128, seed=0,
            tool_choice={"name": "lookup"},
            tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        )
        payload, dropped = request.to_openai_payload("grok", "grok-4.6")
        self.assertEqual(payload["max_tokens"], 128)
        self.assertEqual(payload["seed"], 0)
        self.assertEqual(payload["tool_choice"], {"type": "function", "function": {"name": "lookup"}})
        self.assertEqual(dropped, [])

    def test_grok_reasoning_xhigh_passthrough_and_legacy_normalization(self):
        # grok-4.6: low|medium|high|xhigh как есть; minimal/max — явная
        # нормализация с записью (reasoning отключить нельзя).
        for effort in ("low", "medium", "high", "xhigh"):
            payload, dropped = _request(reasoning_effort=effort).to_openai_payload("grok", "grok-4.6")
            self.assertEqual(payload["reasoning_effort"], effort)
            self.assertFalse(any(d["field"] == "reasoning.effort" for d in dropped))
        for legacy, mapped in (("minimal", "low"), ("max", "xhigh")):
            payload, dropped = _request(reasoning_effort=legacy).to_openai_payload("grok", "grok-4.6")
            self.assertEqual(payload["reasoning_effort"], mapped)
            note = next((d for d in dropped if d["field"] == "reasoning.effort"), None)
            self.assertIsNotNone(note)
            self.assertIn(legacy, note["reason"])
            self.assertIn(mapped, note["reason"])

    def test_grok_stop_fails_loudly_before_network(self):
        with self.assertRaises(ValueError) as ctx:
            _request(stop=["END"]).assert_supported("grok")
        self.assertIn("stop", str(ctx.exception))

    def test_grok_conv_id_header_is_stable_and_secret_free(self):
        captured = []

        def fake_post(url, payload, key, timeout, extra_headers=None):
            captured.append({"url": url, "headers": extra_headers})
            return {"choices": [{"message": {"content": "ok"}}]}

        original_post = lc._post_json
        lc._post_json = fake_post
        try:
            request = _request(provider="grok")
            lc._post_openai_payload(lc.PROVIDERS["grok"], "test-grok-key", "grok", "grok-4.6", request, 10)
            lc._post_openai_payload(lc.PROVIDERS["grok"], "test-grok-key", "grok", "grok-4.6", request, 10)
            lc._post_openai_payload(lc.PROVIDERS["openai"], "test-openai-key", "openai", "gpt-test", _request(), 10)
        finally:
            lc._post_json = original_post
        self.assertEqual(captured[0]["url"], "https://api.x.ai/v1/chat/completions")
        conv = captured[0]["headers"].get("x-grok-conv-id")
        self.assertTrue(conv)
        self.assertEqual(captured[1]["headers"]["x-grok-conv-id"], conv)  # стабильность
        self.assertNotIn("test-grok-key", json.dumps(captured[0]["headers"]))
        self.assertIsNone(captured[2]["headers"])  # openai без conv-id

    def test_hosts_never_mix(self):
        zai_cfg = lc.PROVIDERS["zai"]
        glm_cfg = lc.PROVIDERS["glm"]
        grok_cfg = lc.PROVIDERS["grok"]
        self.assertIn("api.z.ai", zai_cfg["url"])
        self.assertIn("bigmodel.cn", glm_cfg["url"])
        self.assertIn("api.x.ai", grok_cfg["url"])
        # разные ключи: Z.AI ключ никогда не уходит на bigmodel.cn и наоборот
        self.assertEqual(zai_cfg["env"], "ZAI_API_KEY")
        self.assertEqual(glm_cfg["env"], "GLM_API_KEY")
        self.assertEqual(grok_cfg["env"], "XAI_API_KEY")

    def test_zai_coding_endpoint_only_by_explicit_opt_in(self):
        import os
        zai_cfg = lc.PROVIDERS["zai"]
        old_endpoint = os.environ.pop("ZAI_ENDPOINT", None)
        old_base = os.environ.pop("ZAI_BASE_URL", None)
        try:
            self.assertEqual(lc._provider_url(zai_cfg),
                             "https://api.z.ai/api/paas/v4/chat/completions")
            os.environ["ZAI_ENDPOINT"] = "coding"
            self.assertEqual(lc._provider_url(zai_cfg),
                             "https://api.z.ai/api/coding/paas/v4/chat/completions")
            # явный полный override базы побеждает оба варианта
            os.environ["ZAI_BASE_URL"] = "https://proxy.example.com/v1"
            self.assertEqual(lc._provider_url(zai_cfg),
                             "https://proxy.example.com/v1/chat/completions")
        finally:
            os.environ.pop("ZAI_ENDPOINT", None)
            os.environ.pop("ZAI_BASE_URL", None)
            if old_endpoint is not None:
                os.environ["ZAI_ENDPOINT"] = old_endpoint
            if old_base is not None:
                os.environ["ZAI_BASE_URL"] = old_base


class UnsupportedCapabilities(unittest.TestCase):
    def test_zcode_hard_fields_fail_loudly(self):
        request = _request(tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}])
        with self.assertRaises(ValueError) as ctx:
            request.assert_supported("zcode")
        self.assertIn("tools", str(ctx.exception))

    def test_kimi_now_supports_tools_and_tool_choice(self):
        request = _request(
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        # Should not raise: Kimi coding API supports tool calling.
        request.assert_supported("kimi")
        payload, _ = request.to_openai_payload("kimi", "k3")
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["parallel_tool_calls"], False)

    def test_kimi_value_drops_are_reported_with_reasons(self):
        request = _request(temperature=0.4, top_p=0.9, stop=["END"], seed=7)
        adapted, dropped = request.adapt_for_provider("kimi")
        self.assertIsNone(adapted.temperature)
        fields = {d["field"] for d in dropped}
        self.assertEqual(fields, {"temperature", "topP", "stop", "seed"})
        for entry in dropped:
            self.assertGreater(len(entry["reason"]), 10)

    def test_kimi_keeps_temperature_one(self):
        adapted, dropped = _request(temperature=1).adapt_for_provider("kimi")
        self.assertEqual(adapted.temperature, 1)
        self.assertEqual(dropped, [])


class ChatEnvelopeTransport(unittest.TestCase):
    def test_transport_block_reports_provider_model_and_dropped(self):
        original_post = lc._post_json
        captured = {}

        def fake_post(url, payload, key, timeout):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "{\"ok\":1}"}}]}

        lc._post_json = fake_post
        try:
            old_key = os_environ_get("OPENAI_API_KEY")
            import os
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            request = _request(model="openai/gpt-test", temperature=0.7, provider="openai")
            result = lc.chat_envelope(request)
            self.assertEqual(result["content"], '{"ok":1}')
            self.assertEqual(result["transport"]["provider"], "openai")
            self.assertEqual(result["transport"]["model"], "gpt-test")
            self.assertEqual(result["transport"]["request_id"], request.request_id)
            self.assertEqual(result["transport"]["dropped"], [])
            self.assertNotIn("test-openai-key", json.dumps(captured["payload"]))
            if old_key is None:
                del os.environ["OPENAI_API_KEY"]
            else:
                os.environ["OPENAI_API_KEY"] = old_key
        finally:
            lc._post_json = original_post

    def test_http_400_retry_records_the_removed_field(self):
        import os
        attempts = []

        class FakeHTTPError400(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://x", 400, "Bad Request", None, None)
                self.reads = 0

            def read(self, amt=-1):
                body = b'{"error":{"message":"response_format is not supported"}}'
                self.reads += 1
                return body

        def fake_post(url, payload, key, timeout):
            attempts.append(dict(payload))
            if "response_format" in payload:
                raise FakeHTTPError400()
            return {"choices": [{"message": {"content": "ok"}}]}

        original_post = lc._post_json
        lc._post_json = fake_post
        old_key = os_environ_get("OPENAI_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            request = _request(model="openai/gpt-test", provider="openai")
            result = lc.chat_envelope(request)
            self.assertEqual(result["content"], "ok")
            dropped = result["transport"]["dropped"]
            self.assertTrue(any(d["field"] == "response_format" for d in dropped))
            self.assertTrue(any("HTTP 400" in d["reason"] for d in dropped))
        finally:
            lc._post_json = original_post
            if old_key is None:
                del os.environ["OPENAI_API_KEY"]
            else:
                os.environ["OPENAI_API_KEY"] = old_key

    def test_legacy_chat_signature_still_works(self):
        original_post = lc._post_json

        def fake_post(url, payload, key, timeout):
            return {"choices": [{"message": {"content": "legacy-ok"}}]}

        import os
        lc._post_json = fake_post
        old_key = os_environ_get("OPENAI_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            content = lc.chat("openai", [{"role": "user", "content": "x"}], 0.5)
            self.assertEqual(content, "legacy-ok")
        finally:
            lc._post_json = original_post
            if old_key is None:
                del os.environ["OPENAI_API_KEY"]
            else:
                os.environ["OPENAI_API_KEY"] = old_key


def os_environ_get(name):
    import os
    return os.environ.get(name)


class ToolArgumentsContract(unittest.TestCase):
    """Зеркало JS-контракта: Z.AI отдаёт function.arguments объектом."""

    def _payload_with(self, arguments):
        request = _request(messages=[
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": arguments}}
            ]},
            {"role": "tool", "content": "{}", "tool_call_id": "c1", "name": "f"},
        ])
        payload, _ = request.to_openai_payload("zai", "glm-5.3")
        return payload["messages"][1]["tool_calls"][0]["function"]["arguments"], payload

    def test_object_arguments_canonicalize_deterministically(self):
        args_a, _ = self._payload_with({"b": 1, "a": {"d": 2, "c": [3, 4]}})
        args_b, _ = self._payload_with({"a": {"c": [3, 4], "d": 2}, "b": 1})
        self.assertEqual(args_a, args_b)
        self.assertEqual(args_a, '{"a":{"c":[3,4],"d":2},"b":1}')

    def test_string_arguments_pass_verbatim_and_never_truncate(self):
        raw = '{ "z": 1,  "a":2 }'
        args, _ = self._payload_with(raw)
        self.assertEqual(args, raw)
        long_valid = '{"pad":"' + "x" * 15_000 + '"}'
        args, _ = self._payload_with(long_valid)
        self.assertEqual(args, long_valid)

    def test_round_two_resubmits_exact_bytes_and_correlation(self):
        args, payload = self._payload_with({"value": 7, "path": "."})
        tool = payload["messages"][2]
        self.assertEqual(args, '{"path":".","value":7}')
        self.assertEqual(tool["tool_call_id"], "c1")
        self.assertEqual(tool["name"], "f")

    def test_malformed_arguments_fail_closed(self):
        with self.assertRaises(ValueError):
            self._payload_with(None)
        with self.assertRaises(ValueError):
            self._payload_with(42)
        with self.assertRaises(ValueError):
            self._payload_with(True)
        with self.assertRaises(ValueError):
            self._payload_with("x" * 16_001)
        cyclic = {"a": 1}
        cyclic["self"] = cyclic
        with self.assertRaises(ValueError):
            self._payload_with(cyclic)
        with self.assertRaises(ValueError):
            self._payload_with({"fn": object()})
        with self.assertRaises(ValueError):
            self._payload_with({"nan": float("nan")})


class ToolArgumentsHardening(unittest.TestCase):
    """UTF-8 байт-лимиты, parse-валидация строк, структурная валидация вызовов."""

    def _payload(self, messages):
        request = _request(messages=messages)
        payload, _ = request.to_openai_payload("zai", "glm-5.3")
        return payload

    def _history(self, tool_calls):
        return [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": tool_calls},
        ]

    def test_string_arguments_are_parse_validated(self):
        # malformed JSON и закодированные null/примитивы отвергаются
        for bad in ("{bad json", "null", "42", '"just a string"'):
            with self.assertRaises(ValueError, msg=bad):
                self._payload(self._history([
                    {"id": "c1", "type": "function", "function": {"name": "f", "arguments": bad}}
                ]))
        # массив — валидная форма, дословно
        payload = self._payload(self._history([
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "[1,2]"}}
        ]))
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["function"]["arguments"], "[1,2]")

    def test_limits_are_utf8_bytes_not_code_points(self):
        # 5333 трёхбайтовых символа (~16 КБ байт) отвергаются при < 16000 chars
        too_many_bytes = '{"k":"' + "€" * 5333 + '"}'
        self.assertLess(len(too_many_bytes), 16_000)
        with self.assertRaises(ValueError):
            self._payload(self._history([
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": too_many_bytes}}
            ]))
        ok_multibyte = '{"k":"' + "€" * 4000 + '"}'
        payload = self._payload(self._history([
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": ok_multibyte}}
        ]))
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["function"]["arguments"], ok_multibyte)

    def test_wire_tool_call_structure_is_validated_loudly(self):
        valid = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": {}}}
        # более 32 вызовов
        with self.assertRaises(ValueError):
            self._payload(self._history([{**valid, "id": f"c{i}"} for i in range(33)]))
        # не-объект, битый type/function/id/name, дубли id
        for bad_calls in (
            ["not-an-object"],
            [{**valid, "type": "retrieval"}],
            [{**valid, "function": None}],
            [{**valid, "id": ""}],
            [{**valid, "id": "x" * 200}],
            [{**valid, "function": {"name": 7, "arguments": {}}}],
            [valid, dict(valid)],
        ):
            with self.assertRaises(ValueError, msg=str(bad_calls)[:80]):
                self._payload(self._history(bad_calls))


class ProviderOptionsAndAdversarialContract(unittest.TestCase):
    """Fail-loud lossless: provider_options, request_id, captured two-round wire."""

    def test_reserved_wire_overrides_fail_loudly(self):
        reserved = [
            "model", "messages", "tools", "tool_choice", "response_format",
            "reasoning", "thinking", "stream", "temperature", "max_tokens",
            "seed", "stop", "parallel_tool_calls", "request_id",
        ]
        for field in reserved:
            issues = " ".join(_request(provider_options={"openai": {field: "x"}}).validate())
            self.assertIn("reserved canonical wire field", issues, field)
            self.assertIn(field, issues)

    def test_unknown_provider_key_and_unsafe_values_fail(self):
        self.assertIn("unknown provider key", " ".join(
            _request(provider_options={"not-a-provider": {"x": 1}}).validate()))
        self.assertIn("prototype-pollution", " ".join(
            _request(provider_options={"openai": json.loads('{"__proto__":{"polluted":true}}')}).validate()))
        cyclic = {"a": 1}
        cyclic["self"] = cyclic
        self.assertIn("cyclic", " ".join(_request(provider_options={"openai": cyclic}).validate()))
        self.assertIn("non-finite", " ".join(
            _request(provider_options={"openai": {"nan": float("nan")}}).validate()))
        self.assertIn("non-serializable", " ".join(
            _request(provider_options={"openai": {"fn": object()}}).validate()))
        deep = {"h": 1}
        for key in "gfedcba":
            deep = {key: deep}
        self.assertIn("nesting", " ".join(_request(provider_options={"openai": {"deep": deep}}).validate()))
        self.assertIn("UTF-8 bytes", " ".join(
            _request(provider_options={"openai": {"pad": "x" * 9000}}).validate()))

    def test_accepted_extras_remain_exact_on_captured_payload(self):
        extras = {"verbosity": "high", "custom": {"nested": [1, 2]}}
        request = _request(provider_options={"openai": extras, "glm": {"do_sample": False}})
        self.assertEqual(request.validate(), [])
        self.assertIs(request.provider_options["openai"], extras)
        captured = {}

        def fake_post(url, payload, key, timeout, extra_headers=None):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}]}

        original = lc._post_json
        lc._post_json = fake_post
        import os
        old = os.environ.get("OPENAI_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            result = lc.chat_envelope(_request(
                model="openai/gpt-test", provider="openai",
                provider_options={"openai": extras, "glm": {"do_sample": False}},
            ))
            payload = captured["payload"]
            self.assertEqual(payload["verbosity"], "high")
            self.assertEqual(payload["custom"], {"nested": [1, 2]})
            self.assertNotIn("do_sample", payload)
            self.assertTrue(any(d["field"] == "providerOptions.glm" for d in result["transport"]["dropped"]))
            self.assertNotIn("test-openai-key", json.dumps(payload))
        finally:
            lc._post_json = original
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old

    def test_tool_role_requires_id_and_rejects_unknown_keys(self):
        missing = _request(messages=[
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "{}", "name": "f"},
        ])
        self.assertTrue(any("tool_call_id" in item for item in missing.validate()))
        extra = _request(messages=[{"role": "user", "content": "hi", "foo": 1}])
        self.assertTrue(any("unknown field" in item for item in extra.validate()))

    def test_request_id_is_not_silently_truncated(self):
        issues = _request(request_id="bad id!").validate()
        self.assertTrue(any("request_id" in item for item in issues))
        long_id = "a" * 65
        self.assertTrue(any("request_id" in item for item in _request(request_id=long_id).validate()))
        with self.assertRaises(ValueError):
            lc._grok_conv_headers(_request(request_id="unicode-ид"))

    def test_request_id_reaches_grok_header_verbatim(self):
        captured = []

        def fake_post(url, payload, key, timeout, extra_headers=None):
            captured.append(extra_headers)
            return {"choices": [{"message": {"content": "ok"}}]}

        original = lc._post_json
        lc._post_json = fake_post
        try:
            request = _request(provider="grok", request_id="conv-Exact-ID-42")
            self.assertEqual(request.validate(), [])
            lc._post_openai_payload(lc.PROVIDERS["grok"], "k", "grok", "grok-4.6", request, 10)
            self.assertEqual(captured[0]["x-grok-conv-id"], "conv-Exact-ID-42")
        finally:
            lc._post_json = original

    def test_stop_utf8_bound_and_non_string_fail(self):
        issues = " ".join(_request(stop=["s" * 300]).validate())
        self.assertIn("UTF-8 bytes", issues)
        self.assertTrue(any("stop[0]" in item for item in _request(stop=[1]).validate()))

    def test_two_round_utf8_tool_history_captured_payload(self):
        euro_args = '{"k":"' + "€" * 4000 + '"}'
        request = _request(messages=[
            {"role": "user", "content": "call"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": euro_args}}
            ]},
            {"role": "tool", "content": euro_args, "tool_call_id": "call_1", "name": "echo"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_2", "name": "echo", "arguments": {"round": 2}}
            ]},
            {"role": "tool", "content": '{"round":2}', "tool_call_id": "call_2", "name": "echo"},
        ])
        self.assertEqual(request.validate(), [])
        request.check()
        captured = {}

        def fake_post(url, payload, key, timeout, extra_headers=None):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "done"}}]}

        original = lc._post_json
        lc._post_json = fake_post
        import os
        old = os.environ.get("OPENAI_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            result = lc.chat_envelope(lc.ChatRequest(
                messages=request.messages, model="openai/gpt-test", provider="openai",
            ))
            payload = captured["payload"]
            assistant1 = payload["messages"][1]
            tool1 = payload["messages"][2]
            assistant2 = payload["messages"][3]
            tool2 = payload["messages"][4]
            self.assertEqual(assistant1["tool_calls"][0]["id"], "call_1")
            self.assertEqual(assistant1["tool_calls"][0]["function"]["arguments"], euro_args)
            self.assertEqual(tool1["tool_call_id"], "call_1")
            self.assertEqual(tool1["name"], "echo")
            self.assertEqual(tool1["content"], euro_args)
            self.assertEqual(assistant2["tool_calls"][0]["id"], "call_2")
            self.assertEqual(assistant2["tool_calls"][0]["function"]["arguments"], '{"round":2}')
            self.assertEqual(tool2["tool_call_id"], "call_2")
            self.assertEqual(result["content"], "done")
        finally:
            lc._post_json = original
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old

    def test_zcode_hard_fails_provider_options_and_top_p(self):
        with self.assertRaises(ValueError) as ctx:
            _request(provider_options={"zcode": {"foo": 1}}).assert_supported("zcode")
        self.assertIn("provider_options", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            _request(top_p=0.5).assert_supported("zcode")
        self.assertIn("top_p", str(ctx.exception))

    def test_role_specific_fields_content_parts_and_tools_fail_loudly(self):
        cases = [
            (_request(messages=[{"role": "user", "content": "x", "tool_call_id": "c"}]), "tool_call_id"),
            (_request(messages=[{"role": "user", "content": "x", "tool_calls": []}]), "only assistant"),
            (_request(messages=[{"role": "user", "content": [{"type": "text", "text": 7}]}]), ".text"),
            (_request(messages=[{"role": "user", "content": [{"type": "text", "text": "x", "ignored": True}]}]), "unknown field"),
            (_request(messages=[{"role": "tool", "content": "x", "tool_call_id": "c", "tool_calls": []}]), "cannot contain"),
            (_request(tools=[{"type": "retrieval", "function": {"name": "t", "parameters": {}}}]), "tool type"),
            (_request(tools=[{"type": "function", "function": {"name": "t", "description": 7, "parameters": []}}]), "description"),
            (_request(stream=0), "stream"),
        ]
        for request, fragment in cases:
            self.assertIn(fragment, " ".join(request.validate()), fragment)

    def test_message_name_and_flat_tool_are_normalized_without_loss(self):
        request = _request(
            messages=[{"role": "user", "name": "designer", "content": "x"}],
            tools=[{"name": "lookup", "description": "exact", "parameters": {"type": "object"}}],
        )
        self.assertEqual(request.validate(), [])
        payload, _ = request.to_openai_payload("openai", "gpt-test")
        self.assertEqual(payload["messages"][0]["name"], "designer")
        self.assertEqual(payload["tools"], [{
            "type": "function",
            "function": {"name": "lookup", "description": "exact", "parameters": {"type": "object"}},
        }])


if __name__ == "__main__":
    unittest.main()
