"""LLM-клиент: openai- и gemini-форматы chat()/chat_vision() на локальном mock-сервере.
Запуск: .venv/Scripts/python app/llm_client_test.py (сервер не нужен)
"""
import json
import os
import sys
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
        if self.path.endswith(":generateContent"):
            out = {"candidates": [{"content": {"parts": [{"text": '{"ok": "gemini"}'}]}}]}
        else:
            out = {"choices": [{"message": {"content": '{"ok": "openai"}'}}]}
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
    llm_client.PROVIDERS["mock-openai"] = {
        "url": f"http://127.0.0.1:{port}/openai/chat/completions",
        "env": "MOCK_KEY", "model": "mock",
    }
    llm_client.PROVIDERS["mock-gemini"] = {
        "url": f"http://127.0.0.1:{port}/gemini",
        "env": "MOCK_KEY", "model": "mock-gem",
        "vision_models": ["mock-gem"], "api_format": "gemini",
    }

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "prev"},
        {"role": "user", "content": "next"},
    ]

    # ---------- chat: openai-формат ----------
    r = llm_client.chat("mock-openai", msgs[:2], 0.2)
    check("chat openai: контент", r == '{"ok": "openai"}', r)
    path, body = RECORDED[-1]
    check("chat openai: response_format json_object",
          body.get("response_format") == {"type": "json_object"}, str(body)[:200])

    # ---------- chat: gemini-формат (текст) ----------
    r = llm_client.chat("mock-gemini", msgs, 0.3)
    check("chat gemini: контент из candidates", r == '{"ok": "gemini"}', r)
    path, body = RECORDED[-1]
    check("chat gemini: endpoint generateContent", path.endswith("/models/mock-gem:generateContent"), path)
    check("chat gemini: system_instruction вынесен",
          body.get("system_instruction", {}).get("parts", [{}])[0].get("text") == "sys", str(body)[:300])
    roles = [c.get("role") for c in body.get("contents", [])]
    check("chat gemini: assistant → model", roles == ["user", "model", "user"], str(roles))

    # ---------- chat_vision: gemini ----------
    img = "data:image/png;base64," + "A" * 64
    r = llm_client.chat_vision("mock-gemini", img, "опиши", "system-v", 0.1)
    check("vision gemini: контент", r == '{"ok": "gemini"}', r)
    path, body = RECORDED[-1]
    parts = body["contents"][0]["parts"]
    check("vision gemini: inline_data png + текст",
          parts[0].get("inline_data", {}).get("mime_type") == "image/png"
          and parts[1].get("text") == "опиши", str(parts)[:200])

    # ---------- chat_vision: openai ----------
    r = llm_client.chat_vision("mock-openai", img, "опиши", "", 0.1)
    check("vision openai: контент", r == '{"ok": "openai"}', r)
    path, body = RECORDED[-1]
    uc = body["messages"][-1]["content"]
    check("vision openai: image_url + text",
          uc[0]["type"] == "image_url" and uc[1]["type"] == "text", str(uc)[:200])

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
