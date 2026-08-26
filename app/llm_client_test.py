"""LLM-клиент (прямые вызовы OpenAI/Kimi): chat()/chat_vision() на локальном mock-сервере.
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


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


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
        if body.get("model") == "first":  # первая модель цепочки недоступна
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

    os.environ["MOCK_OPENAI_KEY"] = "test-openai-key"
    os.environ["MOCK_KIMI_KEY"] = "test-kimi-key"
    llm_client.PROVIDERS["openai"] = {
        "url": f"http://127.0.0.1:{port}/openai/chat/completions",
        "env": "MOCK_OPENAI_KEY",
    }
    llm_client.PROVIDERS["kimi"] = {
        "url": f"http://127.0.0.1:{port}/kimi/chat/completions",
        "env": "MOCK_KIMI_KEY",
    }
    os.environ["MOCK_GLM_KEY"] = "test-glm-key"
    llm_client.PROVIDERS["glm"] = {
        "url": f"http://127.0.0.1:{port}/glm/chat/completions",
        "env": "MOCK_GLM_KEY",
    }

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "prev"},
        {"role": "user", "content": "next"},
    ]

    # ---------- chat: OpenAI-совместимый формат, композитный slug ----------
    os.environ["LLM_MODELS_MECHANICS"] = "openai/mock-text"
    r = llm_client.chat("auto", msgs[:2], 0.2)
    check("chat openai: контент", r == '{"ok": "mock-text"}', r)
    path, body = RECORDED[-1]
    check("chat openai: provider/model разобран по первому '/'",
          path.startswith("/openai/") and body.get("model") == "mock-text", str(body)[:200])
    check("chat openai: response_format json_object",
          body.get("response_format") == {"type": "json_object"}, str(body)[:200])

    # ---------- chat_vision: OpenAI-совместимый формат ----------
    img = "data:image/png;base64," + "A" * 64
    os.environ["LLM_MODELS_VISION"] = "openai/mock-vision"
    r = llm_client.chat_vision("auto", img, "опиши", "", 0.1)
    check("vision: контент", r == '{"ok": "mock-vision"}', r)
    path, body = RECORDED[-1]
    uc = body["messages"][-1]["content"]
    check("vision: text + image_url",
          uc[0]["type"] == "text" and uc[1]["type"] == "image_url", str(uc)[:200])

    # ---------- роутинг и fallback-цепочка ----------
    os.environ["LLM_MODELS_MECHANICS"] = "openai/first,kimi/second"
    check("routing_models: env-оверрайд LLM_MODELS_<ROLE>",
          llm_client.routing_models("mechanics") == ["openai/first", "kimi/second"])
    for role in ("generator", "clone", "blockparse", "source_semantics", "reskin", "reproduce", "edit", "vision", "taste"):
        os.environ.pop("LLM_MODELS_" + role.upper(), None)
    check("routing_models: дефолт taste",
          llm_client.routing_models("taste")[0] == "glm/glm-5.3")
    check(
        "routing_models: дефолтные роли на прямых провайдерах",
        llm_client.routing_models("generator")[0] == "glm/glm-5.3"
        and llm_client.routing_models("motion_director")[0] == "glm/glm-5.3"
        and llm_client.routing_models("clone")[0] == "glm/glm-5.3"
        and llm_client.routing_models("blockparse")[0] == "glm/glm-5.3"
        and llm_client.routing_models("source_semantics")[0] == "glm/glm-5.3"
        and llm_client.routing_models("reskin")[0] == "glm/glm-5.3"
        and llm_client.routing_models("reproduce")[0] == "glm/glm-5.3"
        and llm_client.routing_models("vision") == ["glm/glm-5.3", "openai/gpt-5.6-sol", "kimi/k3"],
    )
    check("routing_models: все роли — композитные slug'и известных провайдеров",
          all(slug.partition("/")[0] in llm_client.PROVIDERS and slug.partition("/")[2]
              for slugs in llm_client.ROUTING.values() for slug in slugs))
    n_before = len(RECORDED)
    r = llm_client.chat("auto", msgs[:2], 0.2, role="mechanics")
    check("fallback на вторую модель цепочки", json.loads(r) == {"ok": "second"}, r)
    calls = RECORDED[n_before:]
    check("две попытки (404 -> 200), разные провайдеры", len(calls) == 2
          and calls[0][0].startswith("/openai/") and calls[0][1]["model"] == "first"
          and calls[1][0].startswith("/kimi/") and calls[1][1]["model"] == "second",
          str([(c[0], c[1].get("model")) for c in calls]))

    # ---------- skip записи без ключа провайдера ----------
    llm_client.PROVIDERS["openai"]["env"] = "MOCK_MISSING_KEY"
    os.environ.pop("MOCK_MISSING_KEY", None)
    os.environ["LLM_MODELS_MECHANICS"] = "openai/mock-text,kimi/mock-kimi"
    n_before = len(RECORDED)
    r = llm_client.chat("auto", msgs[:2], 0.2, role="mechanics")
    check("skip без ключа: дошли до kimi", json.loads(r) == {"ok": "mock-kimi"}, r)
    calls = RECORDED[n_before:]
    check("skip без ключа: openai даже не вызывался", len(calls) == 1
          and calls[0][0].startswith("/kimi/"), str([(c[0], c[1].get("model")) for c in calls]))
    try:
        llm_client.chat("openai", msgs[:2], 0.2, role="mechanics")
        check("все записи без ключа → понятная ошибка", False)
    except RuntimeError as e:
        check("все записи без ключа → понятная ошибка", "MOCK_MISSING_KEY" in str(e), str(e)[:200])
    llm_client.PROVIDERS["openai"]["env"] = "MOCK_OPENAI_KEY"

    # ---------- фильтр предпочтительного провайдера ----------
    n_before = len(RECORDED)
    r = llm_client.chat("kimi", msgs[:2], 0.2, role="mechanics")
    check("фильтр provider=kimi: сразу kimi", json.loads(r) == {"ok": "mock-kimi"}, r)
    calls = RECORDED[n_before:]
    check("фильтр provider=kimi: openai не вызывался", len(calls) == 1
          and calls[0][0].startswith("/kimi/"), str([(c[0], c[1].get("model")) for c in calls]))

    # ---------- slug без известного провайдера отклоняется ----------
    os.environ["LLM_MODELS_MECHANICS"] = "unknown/mock"
    try:
        llm_client.chat("auto", msgs[:2], 0.2, role="mechanics")
        check("неизвестный провайдер в slug → ValueError", False)
    except ValueError as e:
        check("неизвестный провайдер в slug → ValueError", "unknown/mock" in str(e), str(e)[:200])
    os.environ.pop("LLM_MODELS_MECHANICS", None)
    os.environ.pop("LLM_MODELS_VISION", None)

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

    # ---------- glm: прямой провайдер, slug в цепочке, пропуск без ключа ----------
    glm_out = llm_client.chat("glm", msgs, 0.2, timeout=10)
    check("chat напрямую через glm-провайдера", json.loads(glm_out) == {"ok": "glm-5.3"}, glm_out)
    from llm_client import _resolve_chain
    from llm_client import _resolve_chain as _chain
    glm_chain = _chain("generator", None, "glm")
    check("glm/glm-5.3 входит в цепочку generator и резолвится провайдером glm",
          [f"{p_}/{m}" for p_, m, _cfg in glm_chain] == ["glm/glm-5.3"])
    glm_env = llm_client.PROVIDERS["glm"]["env"]
    saved_glm = os.environ.pop(glm_env, None)
    try:
        check("без GLM-ключа прямой glm-вызов даёт понятную ошибку",
              _raises(lambda: llm_client.chat("glm", msgs, 0.2, timeout=10)))
    finally:
        if saved_glm:
            os.environ[glm_env] = saved_glm

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
