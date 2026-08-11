"""Design KB + generate wiring checks (no LLM)."""
from __future__ import annotations

import json
import re
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import designkb
import typography

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_KEYS = {"primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"}


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        raise AssertionError(f"{name}: {detail}")
    print("OK", name)


def main() -> None:
    # --- структура KB ---
    for type_id, info in designkb.PRODUCT_TYPES.items():
        check(f"{type_id}: ≥2 палитры, все 8 ключей hex",
              len(info["palettes"]) >= 2
              and all(set(p) == COLOR_KEYS and all(HEX.match(v) for v in p.values())
                      for p in info["palettes"]))
        check(f"{type_id}: шрифты/пресеты существуют",
              all(f in typography.PAIRS_BY_NAME for f in info["fonts"])
              and all(pr in typography.PRESETS for pr in info["presets"]))
        check(f"{type_id}: ≥3 UX-правила", len(info["rules"]) >= 3)

    # --- detect_product ---
    check("маркетплейс объявлений", designkb.detect_product("Маркетплейс объявлений, каталог товаров")[0] == "marketplace")
    check("SaaS дашборд", designkb.detect_product("SaaS платформа с дашбордом аналитики")[0] == "saas")
    check("журнал", designkb.detect_product("Журнал о дизайне, статьи и лонгриды")[0] == "editorial")
    check("клиника", designkb.detect_product("Сайт стоматологической клиники, запись к врачу")[0] == "healthcare")
    check("пустой бриф → landing", designkb.detect_product("")[0] == "landing")

    # --- design_direction ---
    text, palette = designkb.design_direction("saas", designkb.PRODUCT_TYPES["saas"], 1)
    check("direction: палитра в тексте", palette["primary"] in text)
    check("direction: анти-клише присутствуют", "AI-стиль" in text and "эмодзи" in text)
    text2, palette2 = designkb.design_direction("saas", designkb.PRODUCT_TYPES["saas"], 2)
    check("вариант 2 получает другую палитру", palette2 != palette)

    # --- проводка в /api/generate (без LLM) ---
    import llm_client
    import server

    fake_ir = {"version": "1.0",
               "tokens": {"mode": "light",
                          "color": {"primary": "#000000", "background": "#ffffff",
                                    "text": "#dddddd"}},
               "tree": []}
    llm_client.chat = lambda *a, **k: json.dumps(fake_ir)

    resp = server.generate(server.GenerateReq(brief="маркетплейс объявлений", count=2))
    v1, v2 = resp["variants"]
    check("design в ответе", resp.get("design", {}).get("type") == "marketplace")
    check("вариант — responsive-документ (вьюпорты 1440/768/390)",
          [v["width"] for k, v in v1.get("responsive", {}).get("viewports", {}).items()]
          == [1440, 768, 390], str(v1.get("responsive")))
    check("палитра варианта 1 — кураторская (marketplace light)",
          v1["tokens"]["color"]["primary"] == "#E85D26", str(v1["tokens"]["color"]))
    check("варианты получают разные палитры",
          v1["tokens"]["color"]["primary"] != v2["tokens"]["color"]["primary"])
    check("шрифт из рекомендации типа (manrope: Manrope+Inter)",
          v1["tokens"]["font"]["display"]["family"] == "Manrope", str(v1["tokens"]["font"]))

    # DNA побеждает KB
    dna = {"color": {"primary": "#123456"}, "font": {"display": {"family": "Golos Text", "weight": 700}}}
    resp3 = server.generate(server.GenerateReq(brief="маркетплейс", count=1, tokens=dna))
    v3 = resp3["variants"][0]
    check("DNA побеждает KB-палитру и шрифт",
          v3["tokens"]["color"]["primary"] == "#123456"
          and v3["tokens"]["font"]["display"]["family"] == "Golos Text")

    print()
    print("ALL DESIGN-KB CHECKS PASSED")


if __name__ == "__main__":
    main()
