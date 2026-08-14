"""ChatGPT-managed Codex auth-file and Responses stream smoke test."""
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm_client


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        auth_path = pathlib.Path(directory) / "auth.json"
        auth_path.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {"access_token": "test-access-token", "account_id": "acct-test"},
        }), encoding="utf-8")

        old_auth_file = os.environ.get("CODEX_AUTH_FILE")
        old_api_key = os.environ.pop("CODEX_API_KEY", None)
        old_post = llm_client._post_codex_responses
        old_provider = llm_client.PROVIDERS["codex"]
        os.environ["CODEX_AUTH_FILE"] = str(auth_path)
        llm_client.PROVIDERS["codex"] = {
            "url": "https://api.openai.com/v1",
            "env": "CODEX_API_KEY",
            "model": None,
        }
        calls = []

        def fake_post(payload, key, account_id, timeout):
            calls.append((payload, key, account_id))
            return (
                b'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}\n'
                b'data: {"type":"response.completed"}\n'
                b'data: [DONE]\n'
            )

        llm_client._post_codex_responses = fake_post
        try:
            config = llm_client.public_config()
            assert config["configured"] is True
            assert config["authMode"] == "chatgpt"
            assert config["baseUrlHost"] == "chatgpt.com"
            assert "access_token" not in json.dumps(config)
            result = llm_client.chat(
                "codex",
                [{"role": "system", "content": "Return JSON."},
                 {"role": "user", "content": "ping"}],
                0.2,
                model=llm_client.CODEX_DEFAULT_MODEL,
            )
            assert result == '{"ok":true}'
            assert calls and calls[0][1] == "test-access-token"
            assert calls[0][2] == "acct-test"
            assert calls[0][0]["input"][0]["role"] == "user"
            print("ALL CODEX-AUTH CHECKS PASSED")
        finally:
            llm_client._post_codex_responses = old_post
            llm_client.PROVIDERS["codex"] = old_provider
            if old_auth_file is None:
                os.environ.pop("CODEX_AUTH_FILE", None)
            else:
                os.environ["CODEX_AUTH_FILE"] = old_auth_file
            if old_api_key is not None:
                os.environ["CODEX_API_KEY"] = old_api_key


if __name__ == "__main__":
    main()
