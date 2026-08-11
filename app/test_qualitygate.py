"""Тесты Quality Gate + Constraints: правила v1, авто-доводка, ограничения.

Проект не использует pytest — самозапускаемый скрипт (сервер не нужен).
Запуск: .venv/Scripts/python app/test_qualitygate.py
"""
import copy
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonschema

import qualitygate
from qualitygate import (check, autofix, check_constraints, contrast_ratio,
                         get_path, RULES_BY_ID)

# не падать на консолях с узкой кодировкой (cp1251 при редиректе)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

FAILS = []
CHECKS = 0


def check_ok(name, cond, extra=""):
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


# Валидный по схеме IR, проходящий ВСЕ правила v1: один h1 (в children hero),
# кнопки ≤ 40, alt у media, короткие заголовки, контраст ≥ 4.5, сетка 8,
# без overflow, два шрифта.
BASE_IR = {
    "version": "1.0",
    "frame": {"width": 960, "height": "hug"},
    "meta": {"name": "Эталон для Quality Gate"},
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
            },
        },
        {
            "id": "hero", "type": "hero", "variant": "centered",
            "frame": {"direction": "column", "align": "center", "gap": 16, "padding": [96, 24]},
            "props": {
                "heading": "Заголовок героя",
                "subheading": "Подзаголовок героя про продукт.",
                "ctaPrimary": {"text": "Попробовать", "variant": "primary"},
                "ctaSecondary": {"text": "Демо", "variant": "outline"},
                "media": {"alt": "Скриншот продукта", "src": "https://cdn.example/shot.png",
                          "aspect": "16:9"},
            },
            "children": [
                {"type": "heading", "text": "Главный заголовок", "level": 1, "size": "display"},
            ],
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


def by_rule(violations, rule_id):
    return [v for v in violations if v["rule"] == rule_id]


# ---------- правило: ровно один h1 ----------

def test_single_h1():
    check_ok("h1: эталон проходит (ровно один h1)", by_rule(check(base_ir()), "single-h1") == [])

    ir = base_ir()
    ir["tree"][1]["children"] = []  # единственный h1 убран
    v = by_rule(check(ir), "single-h1")
    check_ok("h1: нет ни одного — нарушение", len(v) == 1 and v[0]["path"] == "tree", str(v))

    ir = base_ir()
    ir["tree"][2]["children"].append({"type": "heading", "text": "Второй", "level": 1})
    v = by_rule(check(ir), "single-h1")
    check_ok("h1: два h1 — нарушение на каждом",
             len(v) == 2 and all(x["severity"] == "error" for x in v), str(v))


# ---------- правило: кнопки/cta ----------

def test_button_text():
    check_ok("кнопки: эталон проходит", by_rule(check(base_ir()), "button-text") == [])

    ir = base_ir()
    ir["tree"][1]["props"]["ctaPrimary"]["text"] = ""
    v = by_rule(check(ir), "button-text")
    check_ok("кнопки: пустой текст ctaPrimary",
             len(v) == 1 and v[0]["path"] == "tree.1.props.ctaPrimary", str(v))

    ir = base_ir()
    ir["tree"][0]["props"]["cta"]["text"] = "Ы" * 41
    v = by_rule(check(ir), "button-text")
    check_ok("кнопки: текст длиннее 40", len(v) == 1 and "длиннее" in v[0]["message"], str(v))

    ir = base_ir()
    ir["tree"][2]["children"].append({"type": "button"})  # кнопка-элемент без текста
    v = by_rule(check(ir), "button-text")
    check_ok("кнопки: элемент button без текста",
             len(v) == 1 and v[0]["path"] == "tree.2.children.2", str(v))

    ir = base_ir()
    ir["tree"].append({"id": "pricing", "type": "pricing", "variant": "simple",
                       "props": {"heading": "Тарифы",
                                 "tiers": [{"name": "Pro", "price": "$29/mo",
                                            "features": ["Фича"], "cta": ""}]}})
    v = by_rule(check(ir), "button-text")
    check_ok("кнопки: пустой cta тарифа",
             len(v) == 1 and v[0]["path"] == "tree.3.props.tiers.0.cta", str(v))

    ir = base_ir()
    ir["tree"].append({"id": "news", "type": "newsletter", "variant": "inline",
                       "props": {"heading": "Рассылка", "placeholder": "Email",
                                 "submitText": ""}})
    v = by_rule(check(ir), "button-text")
    check_ok("кнопки: пустой submitText",
             len(v) == 1 and v[0]["path"] == "tree.3.props.submitText", str(v))


# ---------- правило: alt у изображений ----------

def test_image_alt():
    check_ok("alt: эталон проходит", by_rule(check(base_ir()), "image-alt") == [])

    ir = base_ir()
    ir["tree"][1]["props"]["media"]["alt"] = ""
    v = by_rule(check(ir), "image-alt")
    check_ok("alt: пустой alt у media",
             len(v) == 1 and v[0]["path"] == "tree.1.props.media", str(v))

    ir = base_ir()
    ir["tree"][2]["children"].append({"type": "image", "src": "https://cdn.example/x.png"})
    v = by_rule(check(ir), "image-alt")
    check_ok("alt: элемент image без alt",
             len(v) == 1 and v[0]["path"] == "tree.2.children.2", str(v))


# ---------- правило: лимиты заголовков ----------

def test_heading_limits():
    check_ok("лимиты: эталон проходит", by_rule(check(base_ir()), "heading-limits") == [])

    ir = base_ir()
    ir["tree"][1]["props"]["heading"] = "X" * 121
    v = by_rule(check(ir), "heading-limits")
    check_ok("лимиты: heading 121 > 120",
             len(v) == 1 and v[0]["path"] == "tree.1.props.heading", str(v))

    ir = base_ir()
    ir["tree"][1]["props"]["subheading"] = "S" * 301
    v = by_rule(check(ir), "heading-limits")
    check_ok("лимиты: subheading 301 > 300",
             len(v) == 1 and v[0]["path"] == "tree.1.props.subheading", str(v))

    ir = base_ir()
    ir["tree"][1]["props"]["heading"] = "X" * 120
    ir["tree"][1]["props"]["subheading"] = "S" * 300
    check_ok("лимиты: граница 120/300 проходит", by_rule(check(ir), "heading-limits") == [])


# ---------- правило: контраст WCAG AA ----------

def test_contrast():
    check_ok("контраст: эталон проходит", by_rule(check(base_ir()), "contrast") == [])
    check_ok("контраст: чёрный/белый = 21", abs(contrast_ratio("#000000", "#ffffff") - 21.0) < 0.01)
    check_ok("контраст: порядок аргументов не важен",
             abs(contrast_ratio("#ffffff", "#0f172a") - contrast_ratio("#0f172a", "#ffffff")) < 1e-9)
    check_ok("контраст: #777777 к белому < 4.5", contrast_ratio("#777777", "#ffffff") < 4.5)
    check_ok("контраст: 3-значный hex", abs(contrast_ratio("#000", "#fff") - 21.0) < 0.01)

    ir = base_ir()
    ir["tokens"]["color"]["text"] = "#777777"  # 4.48 к белому
    v = by_rule(check(ir), "contrast")
    check_ok("контраст: text к background < 4.5",
             len(v) == 1 and v[0]["path"] == "tokens.color.text" and "WCAG" in v[0]["message"],
             str(v))

    ir = base_ir()
    ir["tokens"]["color"]["textMuted"] = "#94a3b8"  # светло-серый, ~2.8
    v = by_rule(check(ir), "contrast")
    check_ok("контраст: textMuted к background < 4.5",
             len(v) == 1 and v[0]["path"] == "tokens.color.textMuted", str(v))


# ---------- правило: сетка 8px ----------

def test_grid():
    check_ok("сетка: эталон проходит", by_rule(check(base_ir()), "grid-8") == [])

    ir = base_ir()
    ir["tree"][1]["frame"]["padding"] = [90, 24]
    v = by_rule(check(ir), "grid-8")
    check_ok("сетка: padding 90 не кратен 8",
             len(v) == 1 and v[0]["path"] == "tree.1.frame.padding.0", str(v))

    ir = base_ir()
    ir["tree"][0]["frame"]["gap"] = 10
    v = by_rule(check(ir), "grid-8")
    check_ok("сетка: gap 10 не кратен 8",
             len(v) == 1 and v[0]["path"] == "tree.0.frame.gap", str(v))

    ir = base_ir()
    ir["tree"][2]["frame"] = {"width": 100}
    v = by_rule(check(ir), "grid-8")
    check_ok("сетка: width 100 секции не кратен 8",
             len(v) == 1 and v[0]["path"] == "tree.2.frame.width", str(v))

    ir = base_ir()
    ir["tree"][0]["frame"]["padding"] = 32  # одиночное значение, кратно
    check_ok("сетка: padding числом 32 проходит", by_rule(check(ir), "grid-8") == [])


# ---------- правило: overflow ----------

def test_overflow():
    check_ok("overflow: эталон проходит", by_rule(check(base_ir()), "frame-overflow") == [])

    ir = base_ir()
    ir["tree"][2]["frame"] = {"width": 1000}
    v = by_rule(check(ir), "frame-overflow")
    check_ok("overflow: ширина 1000 > артборда 960",
             len(v) == 1 and v[0]["path"] == "tree.2.frame.width", str(v))

    ir = base_ir()
    ir["tree"][2]["frame"] = {"x": -8, "width": 480}
    v = by_rule(check(ir), "frame-overflow")
    check_ok("overflow: отрицательный x",
             len(v) == 1 and v[0]["path"] == "tree.2.frame.x", str(v))

    ir = base_ir()
    ir["tree"][2]["frame"] = {"x": 900, "width": 100}
    v = by_rule(check(ir), "frame-overflow")
    check_ok("overflow: x+width=1000 за правым краем",
             len(v) == 1 and "правый" in v[0]["message"], str(v))

    ir = base_ir()
    ir["tree"][2]["frame"] = {"x": 480, "width": 480}  # ровно до края
    check_ok("overflow: впритык x+width=960 проходит",
             by_rule(check(ir), "frame-overflow") == [])

    ir = base_ir()
    ir["frame"] = {"width": 960, "height": 600}
    ir["tree"][2]["frame"] = {"y": 500, "height": 200}
    v = by_rule(check(ir), "frame-overflow")
    check_ok("overflow: y+height=700 за нижним краем (height=600)",
             len(v) == 1 and v[0]["path"] == "tree.2.frame.y", str(v))

    ir = base_ir()  # высота hug — вертикаль не проверяется
    ir["tree"][2]["frame"] = {"y": 99999}
    check_ok("overflow: при height=hug вертикаль не проверяется",
             by_rule(check(ir), "frame-overflow") == [])


# ---------- правило: не более двух шрифтов ----------

def test_fonts():
    check_ok("шрифты: эталон проходит (2 семьи)", by_rule(check(base_ir()), "fonts-limit") == [])

    ir = base_ir()
    ir["tokens"]["font"]["body"] = {"family": "Sora", "weight": 400}  # одна семья
    check_ok("шрифты: одна семья проходит", by_rule(check(ir), "fonts-limit") == [])

    ir = base_ir()
    ir["tokens"]["font"]["mono"] = {"family": "IBM Plex Mono", "weight": 400}
    v = by_rule(check(ir), "fonts-limit")
    check_ok("шрифты: третья семья — нарушение",
             len(v) == 1 and v[0]["path"] == "tokens.font", str(v))


# ---------- авто-доводка (solver) ----------

def test_autofix():
    ir = base_ir()
    ir["tree"][1]["frame"]["padding"] = [90, 24]   # -> 88
    ir["tree"][1]["frame"]["gap"] = 10             # -> 8
    ir["tree"][2]["frame"] = {"width": 1000, "x": -10}  # -> width 960, x 0
    check_ok("solver: до починки есть нарушения grid-8/overflow",
             by_rule(check(ir), "grid-8") != [] and by_rule(check(ir), "frame-overflow") != [])

    snapshot = copy.deepcopy(ir)
    fixed, journal = autofix(ir)
    check_ok("solver: вход не мутирован", ir == snapshot)
    f2 = fixed["tree"][2]["frame"]
    check_ok("solver: padding 90 -> 88", fixed["tree"][1]["frame"]["padding"] == [88, 24])
    check_ok("solver: gap 10 -> 8", fixed["tree"][1]["frame"]["gap"] == 8)
    check_ok("solver: width 1000 -> 960", f2["width"] == 960)
    check_ok("solver: x -10 -> 0", f2["x"] == 0)
    check_ok("solver: журнал по форме 'rule N починило X'",
             len(journal) == 4
             and any(j.startswith("rule grid-8 починило tree.1.frame.padding.0") for j in journal)
             and any(j.startswith("rule frame-overflow починило tree.2.frame.width") for j in journal),
             str(journal))
    check_ok("solver: после починки gate зелёный", check(fixed) == [],
             "; ".join(v["rule"] + ":" + v["path"] for v in check(fixed)))
    check_ok("solver: результат валиден по схеме", schema_errors(fixed) == [],
             "; ".join(schema_errors(fixed)))

    ir = base_ir()
    ir["tree"][1]["frame"]["padding"] = [92, 24]  # эквидистантно 88/96 — половинка вверх
    fixed, _ = autofix(ir)
    check_ok("solver: 92 -> 96 (половинка вверх)",
             fixed["tree"][1]["frame"]["padding"] == [96, 24])

    ir = base_ir()
    ir["frame"] = {"width": 960, "height": 600}
    ir["tree"][2]["frame"] = {"y": 700, "height": 800}
    fixed, journal = autofix(ir)
    check_ok("solver: height 800 -> 600, y 700 -> 0 (вписать в артборд)",
             fixed["tree"][2]["frame"]["height"] == 600 and fixed["tree"][2]["frame"]["y"] == 0,
             str(journal))

    # нечиняемые нарушения остаются
    ir = base_ir()
    ir["tree"][1]["props"]["ctaPrimary"]["text"] = ""
    fixed, journal = autofix(ir)
    check_ok("solver: пустая кнопка не чинится — журнал пуст", journal == [])
    check_ok("solver: нечиняемое нарушение остаётся",
             by_rule(check(fixed), "button-text") != [])
    check_ok("solver: копия без изменений при отсутствии правок", fixed == ir)


# ---------- Constraints ----------

def test_constraints():
    ir = base_ir()
    check_ok("constraints: lock совпадает", check_constraints(ir, [
        {"path": "tokens.color.primary", "lock": "#2563eb"}]) == [])
    v = check_constraints(ir, [{"path": "tokens.color.primary", "lock": "#ff0000"}])
    check_ok("constraints: lock нарушен",
             len(v) == 1 and v[0]["path"] == "tokens.color.primary"
             and v[0]["rule"] == "constraint", str(v))
    v = check_constraints(ir, [{"path": "tokens.color.nope", "lock": 1}])
    check_ok("constraints: залоченное поле отсутствует",
             len(v) == 1 and "отсутствует" in v[0]["message"], str(v))

    check_ok("constraints: min/max в диапазоне", check_constraints(ir, [
        {"path": "tree.0.frame.gap", "min": 8, "max": 64}]) == [])
    v = check_constraints(ir, [{"path": "tree.0.frame.gap", "min": 32}])
    check_ok("constraints: gap 24 < min 32", len(v) == 1 and "меньше" in v[0]["message"], str(v))
    v = check_constraints(ir, [{"path": "tree.0.frame.gap", "max": 16}])
    check_ok("constraints: gap 24 > max 16", len(v) == 1 and "больше" in v[0]["message"], str(v))
    v = check_constraints(ir, [{"path": "tree.0.props.logoText", "min": 5}])
    check_ok("constraints: не-число для min", len(v) == 1 and "число" in v[0]["message"], str(v))

    check_ok("constraints: enum входит", check_constraints(ir, [
        {"path": "tokens.mode", "enum": ["light", "dark"]}]) == [])
    v = check_constraints(ir, [{"path": "tokens.mode", "enum": ["dark"]}])
    check_ok("constraints: enum не входит", len(v) == 1, str(v))

    check_ok("constraints: max_len в норме", check_constraints(ir, [
        {"path": "tree.1.props.heading", "max_len": 120}]) == [])
    v = check_constraints(ir, [{"path": "tree.1.props.heading", "max_len": 5}])
    check_ok("constraints: max_len превышен", len(v) == 1 and "длина" in v[0]["message"], str(v))
    v = check_constraints(ir, [{"path": "tree.0.frame.gap", "max_len": 5}])
    check_ok("constraints: max_len на не-строке", len(v) == 1 and "строка" in v[0]["message"], str(v))

    check_ok("constraints: глубокий путь (лок label ссылки)", check_constraints(ir, [
        {"path": "tree.0.props.links.0.label", "lock": "Продукт"}]) == [])
    check_ok("constraints: комбинированное min+max", check_constraints(ir, [
        {"path": "tree.0.frame.gap", "min": 8, "max": 64},
        {"path": "tree.1.frame.padding.0", "min": 96, "max": 96}]) == [])
    v = check_constraints(base_ir(), [
        {"path": "tree.0.frame.gap", "min": 32, "max": 16, "lock": 99}])
    check_ok("constraints: несколько нарушений из одного ограничения", len(v) == 3, str(v))
    check_ok("constraints: отсутствующее поле пропускается диапазонами",
             check_constraints(ir, [{"path": "tree.9.frame.gap", "min": 8}]) == [])

    check_ok("get_path: список + словарь", get_path(ir, "tree.0.props.links.1.href") == (True, "#pricing"))
    check_ok("get_path: индекс за границей", get_path(ir, "tree.99.x")[0] is False)
    check_ok("get_path: не-цифровой индекс списка", get_path(ir, "tree.x")[0] is False)


def test_constraints_broken():
    ir = base_ir()
    for label, args in [
        ("ir не объект", (None, [])),
        ("constraints не список", (ir, {"path": "x"})),
        ("элемент не объект", (ir, ["строка"])),
        ("нет path", (ir, [{"lock": 1}])),
        ("неизвестный ключ", (ir, [{"path": "tokens.mode", "regex": ".*"}])),
        ("пустое ограничение", (ir, [{"path": "tokens.mode"}])),
        ("enum не список", (ir, [{"path": "tokens.mode", "enum": "dark"}])),
        ("min не число", (ir, [{"path": "tree.0.frame.gap", "min": "8"}])),
        ("max_len не целое", (ir, [{"path": "tokens.mode", "max_len": 2.5}])),
    ]:
        try:
            check_constraints(*args)
            check_ok(f"constraints битый вход ({label}): ValueError", False)
        except ValueError:
            check_ok(f"constraints битый вход ({label}): ValueError", True)
        except Exception as e:
            check_ok(f"constraints битый вход ({label}): ValueError", False, repr(e))


# ---------- битый вход gate ----------

def test_broken_input():
    for label, bad in [("None", None), ("строка", "ir"), ("число", 42), ("список", [])]:
        try:
            check(bad)
            check_ok(f"check({label}): ValueError", False)
        except ValueError:
            check_ok(f"check({label}): ValueError", True)
        try:
            autofix(bad)
            check_ok(f"autofix({label}): ValueError", False)
        except ValueError:
            check_ok(f"autofix({label}): ValueError", True)

    # пустой/дегенеративный IR: не падает; отсутствие h1 детерминированно отмечается
    check_ok("check({}): без падений, отмечено 'нет h1'",
             [v["rule"] for v in check({})] == ["single-h1"])
    check_ok("check(мусор в tree): без падений",
             isinstance(check({"tree": [42, "x", None]}), list))
    check_ok("check(пустой tree): без падений",
             isinstance(check({"tree": []}), list))
    fixed, journal = autofix({})
    check_ok("autofix({}): пусто, без падений", fixed == {} and journal == [])

    ir = base_ir()
    snapshot = copy.deepcopy(ir)
    check(ir)
    check_ok("check: входной IR не мутируется", ir == snapshot)

    v = check(base_ir())
    check_ok("формат нарушений: rule/path/message/severity",
             all(set(x) == {"rule", "path", "message", "severity"} for x in v)
             or v == [])

    # запуск подмножеством правил
    ir = base_ir()
    ir["tree"][1]["props"]["ctaPrimary"]["text"] = ""
    only_h1 = check(ir, rules=[RULES_BY_ID["single-h1"]])
    check_ok("подмножество правил: только single-h1", only_h1 == [])


TESTS = [test_single_h1, test_button_text, test_image_alt, test_heading_limits,
         test_contrast, test_grid, test_overflow, test_fonts, test_autofix,
         test_constraints, test_constraints_broken, test_broken_input]


def main():
    check_ok("эталон: BASE_IR валиден по схеме", schema_errors(BASE_IR) == [],
             "; ".join(schema_errors(BASE_IR)))
    check_ok("эталон: BASE_IR проходит все правила v1", check(BASE_IR) == [],
             "; ".join(f"{v['rule']}:{v['path']}" for v in check(BASE_IR)))
    check_ok("реестр: 10 правил", len(qualitygate.RULES) == 10,
             str([r["id"] for r in qualitygate.RULES]))
    for t in TESTS:
        try:
            t()
        except Exception as e:
            check_ok(f"{t.__name__}: без исключений", False, repr(e))
    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"ALL QUALITY GATE TESTS PASSED ({CHECKS} проверок)")


if __name__ == "__main__":
    main()
