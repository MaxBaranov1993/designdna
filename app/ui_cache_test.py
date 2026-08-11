"""Кэш reproduce/clone: повторы отдаются из sqlite без траты токенов.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_cache_test.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx

import cache_store

BASE = "http://127.0.0.1:8420"
FAILS = []

IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    # ---------- unit: round-trip ----------
    cache_store.put("unit", "k1", {"a": 1, "текст": "привет"})
    got = cache_store.get("unit", "k1")
    check("cache_store: round-trip", got and got["a"] == 1 and got["текст"] == "привет", str(got))
    check("cache_store: miss → None", cache_store.get("unit", "nope") is None)
    check("cache_store: key_url нормализует",
          cache_store.key_url("https://Example.com/X/") == cache_store.key_url("https://example.com/x"))

    # ---------- HTTP ----------
    with httpx.Client(timeout=30) as http:
        for _ in range(30):
            try:
                http.get(BASE + "/")
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        # reproduce: seeded по хэшу изображения — провайдер не дёргается
        cache_store.put("reproduce_img", cache_store.key_image(IMG),
                        {"ir": {"tree": []}, "structure": {"cached": 1}, "colors": {},
                         "measurements": {}, "icons_count": 0, "contents_count": 0,
                         "html": "<div></div>", "diff": {"overall_pct": 1.2},
                         "repro_png": "", "provider_used": "cache"})
        r = http.post(BASE + "/api/reproduce", json={"image": IMG})
        check("reproduce: hit из кэша", r.status_code == 200 and r.json().get("cached") is True,
              f"{r.status_code} {r.text[:120]}")
        check("reproduce: payload из кэша", r.json().get("provider_used") == "cache", r.text[:200])

        # reproduce: SSRF по url всё ещё работает
        r = http.post(BASE + "/api/reproduce", json={"url": "http://127.0.0.1:8420/"})
        check("reproduce: SSRF-гард по url", r.status_code == 422, f"{r.status_code}")

        # clone: seeded по url — без fetch и LLM
        cache_store.put("clone_url", cache_store.key_url("https://example.com/cached-page"),
                        {"ir": {"tree": [{"type": "hero"}]}})
        r = http.post(BASE + "/api/clone",
                      json={"url": "https://example.com/cached-page", "component": "hero"})
        check("clone: hit из кэша", r.status_code == 200 and r.json().get("cached") is True,
              f"{r.status_code} {r.text[:120]}")
        check("clone: ir из кэша", r.json().get("ir", {}).get("tree", [{}])[0].get("type") == "hero",
              r.text[:200])

        # clone: SSRF не сломан
        r = http.post(BASE + "/api/clone", json={"url": "http://localhost:8420/", "component": "x"})
        check("clone: SSRF-гард", r.status_code == 422, f"{r.status_code}")

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL CACHE CHECKS PASSED")


if __name__ == "__main__":
    main()
