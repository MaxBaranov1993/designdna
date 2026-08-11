"""Тест SSRF-гарда: unit + HTTP-уровень (/api/clone, /api/scrape).
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/urlguard_test.py
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

from urlguard import validate_public_url

BASE = "http://127.0.0.1:8420"
FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def raises(url):
    try:
        validate_public_url(url)
        return None
    except ValueError as e:
        return str(e)


def main():
    # ---------- unit ----------
    for bad in ["http://127.0.0.1:8420/", "http://localhost:8420/", "http://[::1]/",
                "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/x",
                "http://192.168.1.1/", "http://0.0.0.0/", "ftp://example.com/",
                "file:///C:/Windows/win.ini", "not-a-url", ""]:
        e = raises(bad)
        check(f"гард блокирует {bad!r}", e is not None, "не бросил ValueError")

    ok = raises("http://8.8.8.8/")
    check("гард пропускает публичный IP", ok is None, str(ok))

    # ---------- HTTP ----------
    with httpx.Client(timeout=15) as http:
        for _ in range(30):
            try:
                http.get(BASE + "/")
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        r = http.post(BASE + "/api/clone",
                      json={"url": "http://127.0.0.1:8420/", "component": "header"})
        check("/api/clone loopback -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")
        check("/api/clone loopback: человекочитаемая причина",
              "внутреннюю сеть" in r.text or "не разрешена" in r.text, r.text[:200])

        r = http.post(BASE + "/api/clone",
                      json={"url": "file:///C:/Windows/win.ini", "component": "x"})
        check("/api/clone file:// -> 422", r.status_code == 422, f"{r.status_code}")

        r = http.post(BASE + "/api/scrape", json={"url": "http://localhost:8420"})
        check("/api/scrape localhost -> 422", r.status_code == 422, f"{r.status_code} {r.text[:120]}")

        r = http.post(BASE + "/api/scrape", json={"url": "http://169.254.169.254/latest"})
        check("/api/scrape metadata-IP -> 422", r.status_code == 422, f"{r.status_code}")

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL SSRF CHECKS PASSED")


if __name__ == "__main__":
    main()
