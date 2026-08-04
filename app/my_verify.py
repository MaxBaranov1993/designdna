#!/usr/bin/env python3
"""Независимая проверка app/ (не доверяем REPORT.md, гоняем сами)."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8420"


def post(path, payload, timeout=240):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, time.time() - t0, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0, e.read().decode()[:300]


results = []

# 1. analyze-header (кэш)
st, dt, d = post("/api/analyze-header", {})
results.append(("analyze-header (cache)", st, f"{dt:.2f}s", bool(d.get("headerBrief"))))
brief = d.get("headerBrief", "")

# 2. generate 1 вариант (qwen)
st, dt, d = post("/api/generate", {"brief": brief or "Шапка маркетплейса объявлений с поиском", "count": 1, "provider": "qwen"})
v = d.get("variants", []) if isinstance(d, dict) else []
results.append(("generate 1 (qwen)", st, f"{dt:.1f}s",
                f"variants={len(v)}, sections={[s['type'] for s in v[0]['tree']] if v else '-'}"))

# 3. validate сгенерированного
if v:
    st, dt, d2 = post("/api/validate", {"ir": v[0]})
    results.append(("validate(generated)", st, f"{dt:.2f}s", d2))

# 4. refine
if v:
    st, dt, d3 = post("/api/refine", {"ir": v[0], "instruction": "Поменяй текст кнопки CTA на '+ Подать объявление' и сделай её variant primary", "provider": "qwen"})
    ir2 = d3.get("ir") if isinstance(d3, dict) else None
    cta = ir2["tree"][0]["props"].get("cta", {}).get("text") if ir2 else None
    results.append(("refine CTA", st, f"{dt:.1f}s", f"cta={cta!r}"))

    # 5. mix сгенерированного с b1
    b1 = json.load(open("results/b1-qwen-t07.json", encoding="utf-8"))
    st, dt, d4 = post("/api/mix", {"irs": [ir2 or v[0], b1], "weights": [0.7, 0.3]})
    mix = d4.get("ir") if isinstance(d4, dict) else None
    results.append(("mix 0.7/0.3", st, f"{dt:.2f}s",
                    f"primary={mix['tokens']['color']['primary']}, mixOf={mix.get('meta', {}).get('mixOf')}" if mix else d4))
    if mix:
        st, dt, d5 = post("/api/validate", {"ir": mix})
        results.append(("validate(mix)", st, f"{dt:.2f}s", d5))

# 6. edge: пустой brief
st, dt, d = post("/api/generate", {"brief": "", "count": 1})
results.append(("generate empty brief", st, f"{dt:.2f}s", str(d)[:80]))

# 7. edge: несовпадение длин
st, dt, d = post("/api/mix", {"irs": [b1], "weights": [0.5, 0.5]})
results.append(("mix length mismatch", st, f"{dt:.2f}s", str(d)[:80]))

print("\n=== МОЯ НЕЗАВИСИМАЯ ПРОВЕРКА ===")
for name, st, dt, info in results:
    print(f"[{st}] {name} ({dt}): {info}")
