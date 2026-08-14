"""LLM-клиент GPT Codex: chat()/chat_vision() на локальном mock-сервере.
Запуск: .venv/Scripts/python app/llm_client_test.py (сервер не нужен)
"""
import json
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import llm_client

FAILS = []
RECORDED = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECORDED.append((self.path, body))
        if body.get("model") == "mock/first":  # первая модель цепочки недоступна
            self.send_response(404)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        out = {"choices": [{"message": {"content": json.dumps({"ok": body.get("model")})}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["MOCK_KEY"] = "test-key"
    llm_client.PROVIDERS["codex"] = {
        "url": f"http://127.0.0.1:{port}/codex",
        "env": "MOCK_KEY", "model": None,
    }

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "prev"},
        {"role": "user", "content": "next"},
    ]

    # ---------- chat: OpenAI-compatible Codex format ----------
    os.environ["CODEX_MODELS_MECHANICS"] = "mock/text"
    r = llm_client.chat("codex", msgs[:2], 0.2)
    check("chat openai: контент", r == '{"ok": "mock/text"}', r)
    path, body = RECORDED[-1]
    check("chat openai: response_format json_object",
          body.get("response_format") == {"type": "json_object"}, str(body)[:200])

    # ---------- chat_vision: Codex vision format ----------
    img = "data:image/png;base64," + "A" * 64
    os.environ["CODEX_MODELS_VISION"] = "mock/vision"
    r = llm_client.chat_vision("codex", img, "опиши", "", 0.1)
    check("vision codex: контент", r == '{"ok": "mock/vision"}', r)
    path, body = RECORDED[-1]
    uc = body["messages"][-1]["content"]
    check("vision codex: text + image_url",
          uc[0]["type"] == "text" and uc[1]["type"] == "image_url", str(uc)[:200])

    # ---------- codex: routing and fallback chain ----------
    os.environ["CODEX_MODELS_MECHANICS"] = "mock/first,mock/second"
    check("routing_models: env-оверрайд",
          llm_client.routing_models("mechanics") == ["mock/first", "mock/second"])
    for role in ("generator", "clone", "blockparse", "source_semantics", "reskin", "reproduce", "edit", "vision", "taste"):
        os.environ.pop("CODEX_MODELS_" + role.upper(), None)
    expected_model = os.environ.get("CODEX_MODEL") or llm_client.CODEX_DEFAULT_MODEL
    check("routing_models: дефолт taste из таблицы",
          llm_client.routing_models("taste")[0] == expected_model)
    check(
        "routing_models: роли нод закреплены за Codex-моделью",
        all(llm_client.routing_models(role)[0] == expected_model for role in
            ("generator", "motion_director", "clone", "blockparse", "source_semantics", "reskin", "reproduce")),
    )
    n_before = len(RECORDED)
    r = llm_client.chat("codex", msgs[:2], 0.2, role="mechanics")
    check("codex: fallback на вторую модель", json.loads(r) == {"ok": "mock/second"}, r)
    calls = RECORDED[n_before:]
    check("codex: две попытки (404 -> 200)", len(calls) == 2
          and calls[0][1]["model"] == "mock/first" and calls[1][1]["model"] == "mock/second",
          str([c[1].get("model") for c in calls]))
    os.environ.pop("CODEX_MODELS_MECHANICS", None)
    os.environ.pop("CODEX_MODELS_VISION", None)

    # ---------- load_dotenv ----------
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write("# comment\nFOO_TEST_KEY=abc\nQUOTED=\"def\"\n")
        tmp = pathlib.Path(f.name)
    os.environ.pop("FOO_TEST_KEY", None)
    os.environ["QUOTED"] = "keep"
    n = llm_client.load_dotenv(tmp)
    check("load_dotenv: устанавливает отсутствующие", os.environ.get("FOO_TEST_KEY") == "abc")
    check("load_dotenv: не перетирает существующие", os.environ.get("QUOTED") == "keep")
    check("load_dotenv: возвращает число новых", n == 1, str(n))
    tmp.unlink(missing_ok=True)

    # ---------- прочее ----------
    check("таймаут по умолчанию 120с", llm_client.TIMEOUT == 120, str(llm_client.TIMEOUT))
    check("extract_json: markdown-обёртка",
          llm_client.extract_json("```json\n{\"a\": 1}\n```") == '{"a": 1}')
    check("build_system_prompt собирается", "Design IR" in llm_client.build_system_prompt()
          or len(llm_client.build_system_prompt()) > 1000)

    srv.shutdown()
    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL LLM-CLIENT CHECKS PASSED")


if __name__ == "__main__":
    main()
