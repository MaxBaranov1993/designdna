"""Тесты merge-back (Reskin): залоченные поля всегда из входного IR.

Проект не использует pytest — самозапускаемый скрипт (сервер не нужен).
Запуск: .venv/Scripts/python app/test_mergeback.py
"""
import copy
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonschema

import mergeback
from mergeback import merge_back, normalize_mask

# не падать на консолях с узкой кодировкой (cp1251 при редиректе)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

FAILS = []
CHECKS = 0


def check(name, cond, extra=""):
    global CHECKS
    CHECKS += 1
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = jsonschema.Draft7Validator(
    json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8")))


def schema_errors(ir):
    return sorted(f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
                  for e in VALIDATOR.iter_errors(ir))


ALL_ON = {k: True for k in mergeback.MASK_KEYS}

# Валидный по схеме входной IR: navbar + hero + feature-grid с children
BASE_IR = {
    "version": "1.0",
    "frame": {"width": 960, "height": "hug"},
    "meta": {"name": "Тестовый блок"},
    "tokens": {
        "mode": "light",
        "color": {
            "primary": "#2563eb", "secondary": "#0f172a", "accent": "#f59e0b",
            "background": "#ffffff", "surface": "#f8fafc",
            "text": "#0f172a", "textMuted": "#64748b", "border": "#e2e8f0",
        },
        "font": {
            "display": {"family": "Sora", "weight": 700},
            "body": {"family": "Inter", "weight": 400},
            "scale": "default",
        },
        "radius": {"card": "lg", "button": "md", "input": "md"},
        "spacing": {"section": "lg", "container": "default"},
        "shadow": "sm",
    },
    "tree": [
        {
            "id": "nav", "type": "navbar", "variant": "classic",
            "frame": {"direction": "row", "justify": "space-between", "align": "center",
                      "gap": 24, "padding": [16, 24]},
            "props": {
                "logoText": "Acme",
                "links": [{"label": "Продукт", "href": "#product"},
                          {"label": "Цены", "href": "#pricing"}],
                "cta": {"text": "Начать", "variant": "primary", "href": "#start"},
                "sticky": True,
            },
        },
        {
            "id": "hero", "type": "hero", "variant": "centered",
            "frame": {"direction": "column", "align": "center", "gap": 16, "padding": [96, 24]},
            "props": {
                "badge": "Новинка",
                "heading": "Заголовок героя",
                "subheading": "Подзаголовок героя про продукт.",
                "ctaPrimary": {"text": "Попробовать", "variant": "primary"},
                "ctaSecondary": {"text": "Демо", "variant": "outline"},
                "media": {"alt": "Скриншот продукта", "src": "https://cdn.example/shot.png",
                          "aspect": "16:9"},
                "align": "center",
            },
        },
        {
            "id": "features", "type": "feature-grid", "variant": "grid-3",
            "props": {},
            "children": [
                {"type": "heading", "text": "Наши возможности", "level": 2,
                 "size": "xl", "align": "center"},
                {"type": "card", "icon": "zap", "title": "Быстро", "text": "Очень быстро.",
                 "frame": {"width": 300, "padding": 24}},
            ],
        },
    ],
}


def base_ir():
    return copy.deepcopy(BASE_IR)


# ---------- тесты ----------

def test_topology():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    mo["tree"] = [mo["tree"][1]]  # модель выкинула две секции из трёх
    mo["tree"].append({"id": "x", "type": "stats", "variant": "v", "props": {"items": []}})
    merged, journal = merge_back(ir_in, mo, ALL_ON)
    check("топология: секции из входа (nav, hero, features)",
          [(s["id"], s["type"]) for s in merged["tree"]] ==
          [("nav", "navbar"), ("hero", "hero"), ("features", "feature-grid")])
    check("топология: попытка модели записана в журнал",
          any(j.startswith("tree:") for j in journal), str(journal))

    # подмена типа секции — секция целиком из входа
    mo2 = copy.deepcopy(ir_in)
    mo2["tree"][0]["type"] = "footer"
    merged2, journal2 = merge_back(ir_in, mo2, ALL_ON)
    check("топология: секция с чужим типом взята из входа",
          merged2["tree"][0] == ir_in["tree"][0])
    check("топология: валиден по схеме", schema_errors(merged2) == [],
          "; ".join(schema_errors(merged2)))


def test_frame_locked():
    ir_in = base_ir()
    snapshot = copy.deepcopy(ir_in)
    mo = copy.deepcopy(ir_in)
    mo["frame"] = {"width": 1440, "height": 2000}
    mo["tree"][0]["frame"] = {"direction": "column", "gap": 99}
    mo["tree"][1]["frame"] = {}
    merged, journal = merge_back(ir_in, mo, ALL_ON)
    check("frame: артборд из входа", merged["frame"] == ir_in["frame"])
    check("frame: frame секций из входа",
          merged["tree"][0]["frame"] == ir_in["tree"][0]["frame"]
          and merged["tree"][1]["frame"] == ir_in["tree"][1]["frame"])
    check("frame: попытки записаны в журнал",
          sum("frame" in j for j in journal) >= 3, str(journal))
    check("frame: входной IR не мутирован", ir_in == snapshot)


def test_mask_colors_fonts():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    mo["tokens"]["mode"] = "dark"
    mo["tokens"]["color"]["primary"] = "#ff0000"
    mo["tokens"]["color"]["text"] = "#111111"
    mo["tokens"]["font"]["display"] = {"family": "Space Grotesk", "weight": 600}
    mo["tokens"]["font"]["scale"] = "spacious"
    mo["tokens"]["radius"]["button"] = "full"
    mo["tokens"]["shadow"] = "lg"
    mo["tokens"]["spacing"]["section"] = "sm"

    merged, journal = merge_back(ir_in, mo, {"colors": True, "fonts": True})
    t = merged["tokens"]
    check("маска: цвета применены (primary/text/mode)",
          t["color"]["primary"] == "#ff0000" and t["color"]["text"] == "#111111"
          and t["mode"] == "dark")
    check("маска: шрифты применены (display/scale)",
          t["font"]["display"] == {"family": "Space Grotesk", "weight": 600}
          and t["font"]["scale"] == "spacious")
    check("маска: радиусы залочены", t["radius"] == ir_in["tokens"]["radius"])
    check("маска: тени залочены", t["shadow"] == "sm")
    check("маска: spacing залочен", t["spacing"] == ir_in["tokens"]["spacing"])
    check("маска: попытки в залоченные категории в журнале",
          any("tokens.radius" in j for j in journal)
          and any("tokens.spacing" in j for j in journal)
          and any("tokens.shadow" in j for j in journal), str(journal))
    check("маска: результат валиден по схеме", schema_errors(merged) == [],
          "; ".join(schema_errors(merged)))

    # цвета залочены — значения модели молча перезаписаны
    merged2, journal2 = merge_back(ir_in, mo, {"fonts": True})
    check("маска: цвета залочены — значения из входа",
          merged2["tokens"]["color"] == ir_in["tokens"]["color"]
          and merged2["tokens"]["mode"] == "light")
    check("маска: перезапись цвета записана в журнал",
          any("tokens.color.primary" in j for j in journal2), str(journal2))


def test_texts_images():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    mo["tree"][1]["props"]["heading"] = "Новый заголовок"
    mo["tree"][1]["props"]["ctaPrimary"]["text"] = "Старт"
    mo["tree"][0]["props"]["links"][0]["href"] = "#hacked"
    mo["tree"][0]["props"]["cta"]["variant"] = "ghost"
    mo["tree"][1]["props"]["media"]["src"] = "https://cdn.example/new.png"
    mo["tree"][1]["props"]["media"]["alt"] = "Новый скриншот"

    merged, _ = merge_back(ir_in, mo, {"texts": True})
    hp = merged["tree"][1]["props"]
    check("тексты: heading применён", hp["heading"] == "Новый заголовок")
    check("тексты: текст кнопки применён", hp["ctaPrimary"]["text"] == "Старт")
    check("тексты: href залочен", merged["tree"][0]["props"]["links"][0]["href"] == "#product")
    check("тексты: variant залочен", merged["tree"][0]["props"]["cta"]["variant"] == "primary")
    check("тексты: src без маски images залочен",
          hp["media"]["src"] == "https://cdn.example/shot.png")

    merged2, _ = merge_back(ir_in, mo, {"images": True})
    hp2 = merged2["tree"][1]["props"]
    check("картинки: src/alt применены",
          hp2["media"]["src"] == "https://cdn.example/new.png"
          and hp2["media"]["alt"] == "Новый скриншот")
    check("картинки: heading без маски texts залочен", hp2["heading"] == "Заголовок героя")


def test_children_locked():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    fe = mo["tree"][2]["children"]
    fe[0]["text"] = "Другой заголовок"
    fe[0]["level"] = 4
    fe[1]["frame"] = {"width": 999}
    fe[1]["icon"] = "star"
    fe[1]["type"] = "image"
    merged, journal = merge_back(ir_in, mo, {"texts": True})
    ch = merged["tree"][2]["children"]
    check("children: текст элемента применён", ch[0]["text"] == "Другой заголовок")
    check("children: level залочен", ch[0]["level"] == 2)
    check("children: frame элемента залочен", ch[1]["frame"] == {"width": 300, "padding": 24})
    check("children: icon залочен", ch[1]["icon"] == "zap")
    check("children: type элемента залочен", ch[1]["type"] == "card")
    check("children: валиден по схеме", schema_errors(merged) == [],
          "; ".join(schema_errors(merged)))


def test_props_structure():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    mo["tree"][0]["props"]["links"].append({"label": "Лишняя", "href": "#x"})
    mo["tree"][0]["props"]["hacked"] = True
    mo["tree"][0]["id"] = "other-id"
    mo["tree"][0]["variant"] = "glass"
    del mo["tree"][1]["props"]["badge"]
    merged, journal = merge_back(ir_in, mo, ALL_ON)
    p = merged["tree"][0]["props"]
    check("разметка: длина links из входа (2)", len(p["links"]) == 2)
    check("разметка: новый ключ props отброшен", "hacked" not in p)
    check("разметка: id секции залочен", merged["tree"][0]["id"] == "nav")
    check("разметка: variant секции залочен", merged["tree"][0]["variant"] == "classic")
    check("разметка: удалённый моделью ключ восстановлен",
          "badge" in merged["tree"][1]["props"])
    check("разметка: валиден по схеме", schema_errors(merged) == [],
          "; ".join(schema_errors(merged)))


def test_broken_model():
    ir_in = base_ir()
    for broken in (None, "строка", 42, ["список"], {"tree": "не список", "tokens": 5}):
        merged, journal = merge_back(ir_in, broken, ALL_ON)
        label = type(broken).__name__ if broken is not None else "None"
        check(f"битый ответ ({label}): IR == входному", merged == ir_in and merged is not ir_in)
        check(f"битый ответ ({label}): журнал не пуст", bool(journal))
        check(f"битый ответ ({label}): валиден по схеме", schema_errors(merged) == [])
    merged, _ = merge_back(ir_in, {"tokens": {}}, ALL_ON)
    check("битый ответ (пустые токены): токены из входа", merged["tokens"] == ir_in["tokens"])


def test_invalid_values_rejected():
    ir_in = base_ir()
    mo = copy.deepcopy(ir_in)
    mo["tokens"]["color"]["primary"] = "red"
    mo["tokens"]["font"]["body"] = {"family": "", "weight": 999}
    mo["tokens"]["radius"]["card"] = "huge"
    mo["tree"][1]["props"]["heading"] = "X" * 200  # длиннее лимита схемы 120
    mo["tree"][1]["props"]["ctaPrimary"]["text"] = "Y" * 60  # кнопка ≤ 40
    merged, journal = merge_back(ir_in, mo, ALL_ON)
    check("мусор: не-hex цвет не применён", merged["tokens"]["color"]["primary"] == "#2563eb")
    check("мусор: некорректный fontFace не применён",
          merged["tokens"]["font"]["body"] == ir_in["tokens"]["font"]["body"])
    check("мусор: не-enum радиус не применён", merged["tokens"]["radius"]["card"] == "lg")
    check("мусор: слишком длинный текст не применён",
          merged["tree"][1]["props"]["heading"] == "Заголовок героя"
          and merged["tree"][1]["props"]["ctaPrimary"]["text"] == "Попробовать")
    check("мусор: результат валиден по схеме", schema_errors(merged) == [],
          "; ".join(schema_errors(merged)))


def test_normalize_mask():
    check("маска: по умолчанию всё залочено",
          all(v is False for v in normalize_mask(None).values()))
    check("маска: не-словарь -> всё залочено", all(v is False for v in normalize_mask(42).values()))
    m = normalize_mask({"color": True, "Font": True, "radius": 1,
                        "texts": "yes", "unknown": True})
    check("маска: алиасы и приведение типов",
          m["colors"] and m["fonts"] and m["radii"] and m["texts"]
          and not m["images"] and not m["shadows"])


TESTS = [test_topology, test_frame_locked, test_mask_colors_fonts, test_texts_images,
         test_children_locked, test_props_structure, test_broken_model,
         test_invalid_values_rejected, test_normalize_mask]


def main():
    check("эталон: BASE_IR валиден по схеме", schema_errors(BASE_IR) == [],
          "; ".join(schema_errors(BASE_IR)))
    for t in TESTS:
        try:
            t()
        except Exception as e:
            check(f"{t.__name__}: без исключений", False, repr(e))
    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"ALL MERGE-BACK TESTS PASSED ({CHECKS} проверок)")


if __name__ == "__main__":
    main()
