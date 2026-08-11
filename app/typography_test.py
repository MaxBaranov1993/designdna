"""Typography engine + contrast autofix + generate wiring checks (no LLM)."""
from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qualitygate
import typography


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        raise AssertionError(f"{name}: {detail}")
    print("OK", name)


def main() -> None:
    # --- библиотека пар ---
    check("все пары помечены кириллическими семействами",
          all(p["display"]["family"] and p["body"]["family"] for p in typography.FONT_PAIRS))
    for pair in typography.FONT_PAIRS:
        check(f"пара {pair['name']}: веса 300..900",
              300 <= pair["display"]["weight"] <= 900 and 300 <= pair["body"]["weight"] <= 900)

    # --- pick_pair ---
    check("prefer из пресета побеждает", typography.pick_pair({"tech"}, prefer="bebas")["name"] == "bebas")
    check("настроение editorial → serif-пара",
          typography.pick_pair({"editorial"})["name"] in ("playfair", "tenor"))
    check("пустые настроения → inter", typography.pick_pair(set())["name"] == "inter")
    check("неизвестный prefer игнорируется", typography.pick_pair({"brutal"}, prefer="nope")["name"] == "bebas")

    # --- brief_moods ---
    check("бриф про журнал → editorial", "editorial" in typography.brief_moods("Журнал о дизайне, статьи"))
    check("бриф про SaaS → tech", "tech" in typography.brief_moods("SaaS платформа для API"))
    check("пустой бриф → без настроений", typography.brief_moods("") == set())

    # --- type_scale ---
    scale = typography.type_scale()
    check("шкала монотонна", scale["display"] > scale["h1"] > scale["h2"] > scale["h3"] > scale["body"] > scale["small"])
    check("body = base 16", scale["body"] == 16)
    check("small не ниже 12", scale["small"] >= 12)

    # --- пресеты ---
    check("5 пресетов", set(typography.PRESETS) == {"minimal", "bento", "editorial", "brutal", "glass"})
    for pid, preset in typography.PRESETS.items():
        check(f"пресет {pid}: font ссылается на существующую пару",
              preset["font"] in typography.PAIRS_BY_NAME)
    check("font_tokens по схеме", typography.font_tokens(typography.PAIRS_BY_NAME["sora"]) ==
          {"display": {"family": "Sora", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"})

    # --- contrast autofix ---
    ir = {"tokens": {"color": {"text": "#cccccc", "textMuted": "#eeeeee", "background": "#ffffff"}}, "tree": []}
    fixed, journal = qualitygate.autofix(ir)
    check("contrast autofix пишет журнал", any("contrast" in j for j in journal), str(journal))
    check("contrast autofix убирает нарушения",
          not qualitygate.check(fixed, rules=[qualitygate.RULES_BY_ID["contrast"]]))
    dark = {"tokens": {"color": {"text": "#333333", "background": "#0a0a0a"}}, "tree": []}
    fixed_dark, _ = qualitygate.autofix(dark)
    check("тёмный фон: текст светлеет до AA",
          qualitygate.contrast_ratio(fixed_dark["tokens"]["color"]["text"], "#0a0a0a") >= qualitygate.WCAG_AA)
    check("autofix не мутирует вход", ir["tokens"]["color"]["text"] == "#cccccc")

    # --- проводка в /api/generate (без LLM) ---
    import llm_client
    import server

    fake_ir = {"version": "1.0",
               "tokens": {"mode": "light",
                          "color": {"primary": "#000000", "background": "#ffffff",
                                    "text": "#dddddd", "textMuted": "#eeeeee"}},
               "tree": []}
    llm_client.chat = lambda *a, **k: json.dumps(fake_ir)

    resp = server.generate(server.GenerateReq(brief="лендинг журнала о моде", count=1, preset="editorial"))
    v = resp["variants"][0]
    check("preset editorial → serif-пара залочена в tokens.font",
          v["tokens"]["font"]["display"]["family"] in ("Playfair Display", "Tenor Sans"),
          str(v["tokens"]["font"]))
    check("qa присутствует в ответе", bool(resp.get("qa")) and resp["qa"][0]["index"] == 1)
    check("авто-gate починил контраст сгенерированного варианта",
          qualitygate.contrast_ratio(v["tokens"]["color"]["text"], "#ffffff") >= qualitygate.WCAG_AA,
          v["tokens"]["color"]["text"])

    resp2 = server.generate(server.GenerateReq(brief="дашборд метрик", count=1))
    check("без пресета пара подбирается по брифу (bento/tech)",
          resp2["variants"][0]["tokens"]["font"]["body"]["family"] in ("Manrope", "Inter", "Sora", "IBM Plex Sans"),
          str(resp2["variants"][0]["tokens"]["font"]))

    print()
    print("ALL TYPOGRAPHY CHECKS PASSED")


if __name__ == "__main__":
    main()
