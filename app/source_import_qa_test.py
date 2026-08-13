"""Unit-тест QA-пасса парсера Source Import (_qa_pixel_pass):
детерминированная сверка flow-арифметики auto-контейнеров с захваченным
размером и автофикс (free + пиннинг детей по захваченным x/y).
Запуск: .venv/Scripts/python app/source_import_qa_test.py
"""
import pathlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import scraper  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def kid(x, y, w, h, **kw):
    f = {"x": x, "y": y, "width": w, "height": h}
    f.update(kw)
    return {"type": "text", "text": "t", "frame": f}


def main():
    # 1. здоровый auto-column: сумма детей + gap + padding == height → без правок
    nodes = [
        kid(20, 20, 300, 40),
        kid(20, 72, 300, 40),
    ]
    frame = {"width": 340, "height": 132, "layout": "auto", "direction": "column",
             "gap": 12, "padding": 20}
    w = scraper._qa_pixel_pass(nodes, dict(frame))
    check("здоровый auto: без предупреждений", w == [], str(w))
    check("здоровый auto: layout не тронут", frame["layout"] == "auto")
    check("здоровый auto: дети не absolute", not nodes[0]["frame"].get("absolute"))

    # 2. дрейф 20px (рендерер завернул лишнюю строку) → free + пиннинг
    nodes2 = [
        kid(20, 20, 300, 60),   # текст «вырос» против захваченных 40
        kid(20, 92, 300, 40),
    ]
    frame2 = {"width": 340, "height": 132, "layout": "auto", "direction": "column",
              "gap": 12, "padding": 20}
    w2 = scraper._qa_pixel_pass(nodes2, frame2)
    check("дрейф: предупреждение записано", len(w2) == 1 and "flow drift" in w2[0], str(w2))
    check("дрейф: контейнер переведён в free", frame2["layout"] == "free")
    check("дрейф: дети запиннены absolute",
          nodes2[0]["frame"].get("absolute") and nodes2[1]["frame"].get("absolute"))
    check("дрейф: захваченные x/y сохранены",
          nodes2[0]["frame"]["x"] == 20 and nodes2[1]["frame"]["y"] == 92)

    # 2b. отрицательный дрейф (свободное место, row во всю ширину) → НЕ пинним
    nodes2b = [kid(0, 0, 100, 40), kid(118, 0, 100, 40)]
    frame2b = {"width": 1440, "height": 40, "layout": "auto", "direction": "row",
               "gap": 18, "padding": 0}
    w2b = scraper._qa_pixel_pass(nodes2b, frame2b)
    check("отрицательный дрейф: auto сохранён", w2b == [] and frame2b["layout"] == "auto", str(w2b))

    # 3. space-between: большая «дыра» — это норма, не пинним
    nodes3 = [kid(0, 0, 100, 40), kid(240, 0, 100, 40)]
    frame3 = {"width": 340, "height": 40, "layout": "auto", "direction": "row",
              "gap": 0, "padding": 0, "justify": "space-between"}
    w3 = scraper._qa_pixel_pass(nodes3, dict(frame3))
    check("space-between не пиннится", w3 == [] and frame3["layout"] == "auto", str(w3))

    # 4. wrap-контейнер не проверяется (flow-сумма не сходится по дизайну)
    nodes4 = [kid(0, 0, 100, 40), kid(0, 44, 100, 40), kid(0, 88, 100, 40)]
    frame4 = {"width": 220, "height": 40, "layout": "auto", "direction": "row",
              "gap": 4, "padding": 0, "wrap": True}
    w4 = scraper._qa_pixel_pass(nodes4, dict(frame4))
    check("wrap не пиннится", w4 == [] and frame4["layout"] == "auto", str(w4))

    # 5. вложенность: дрейф во внутреннем контейнере пиннит только его
    inner = {"type": "card", "frame": {"width": 300, "height": 100, "layout": "auto",
                                       "direction": "column", "gap": 8, "padding": 10,
                                       "x": 20, "y": 20},
             "children": [kid(10, 10, 280, 50), kid(10, 68, 280, 40)]}
    outer_kids = [inner, kid(20, 130, 300, 30)]
    frame5 = {"width": 340, "height": 180, "layout": "auto", "direction": "column",
              "gap": 10, "padding": 20}
    w5 = scraper._qa_pixel_pass(outer_kids, dict(frame5))
    check("вложенный дрейф: один warning", len(w5) == 1, str(w5))
    check("вложенный дрейф: inner в free", inner["frame"]["layout"] == "free")
    check("вложенный дрейф: outer остался auto", frame5["layout"] == "auto")

    if FAILS:
        print("\nFAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("\nALL QA-PASS CHECKS PASSED")


if __name__ == "__main__":
    main()
