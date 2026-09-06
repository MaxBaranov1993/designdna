"""Synthetic announcement pages, explicitly separate from user projects."""
from __future__ import annotations


def page_fixture(success=False):
    def element(ident, kind, x, y, width, height, **values):
        return {"id": ident, "sourceKey": ident, "type": kind,
                "frame": {"x": x, "y": y, "width": width, "height": height}, **values}
    if success:
        children = [
            element("done-title", "heading", 80, 140, 780, 70, text="Объявление опубликовано", level=1),
            element("done-copy", "text", 80, 230, 760, 70, text="Ваш товар уже виден покупателям."),
        ]
    else:
        children = [
            element("title", "heading", 80, 55, 780, 70, text="Новое объявление", level=1),
            element("intro", "text", 80, 128, 760, 40, text="Расскажите о товаре. Это займёт пару минут."),
            element("name-label", "text", 80, 210, 400, 30, text="Название товара"),
            element("name-input", "input", 80, 248, 780, 56, placeholder="Например: Диван"),
            element("price-label", "text", 80, 335, 400, 30, text="Цена, ₽"),
            element("price-input", "input", 80, 373, 780, 56, placeholder="Укажите цену"),
            element("city-label", "text", 80, 460, 400, 30, text="Город"),
            element("city-input", "input", 80, 498, 780, 56, placeholder="Город продажи"),
            element("hint", "text", 80, 680, 760, 60, text="Проверьте данные перед публикацией."),
            element("publish", "button", 80, 850, 400, 60, text="Разместить объявление"),
        ]
    return {"version": "1.1", "frame": {"width": 960}, "tree": [{
        "id": "result" if success else "form", "sourceKey": "result" if success else "form",
        "type": "generic", "variant": "free", "frame": {"layout": "free", "width": 960, "height": 640 if success else 1080},
        "style": {"background": "#ffffff"}, "children": children,
    }]}


def pages_fixture():
    return [{"id": "ir", "name": "Форма", "ir": page_fixture()}, {"id": "page2", "name": "Готово", "ir": page_fixture(True)}]


def plan_fixture():
    return {"summary": "Заполнить и разместить объявление", "edits": [{"op": "insert", "afterId": None, "actions": [
        {"id": "intro", "type": "wait", "pageId": "ir", "duration": 600},
        {"id": "name", "type": "type", "pageId": "ir", "target": "s0.children.3", "text": "Диван", "duration": 1800},
        {"id": "price", "type": "type", "pageId": "ir", "target": "s0.children.5", "text": "15000", "duration": 1800},
        {"id": "city", "type": "type", "pageId": "ir", "target": "s0.children.7", "text": "Москва", "duration": 1800},
        {"id": "scroll", "type": "scroll", "pageId": "ir", "y": 430, "duration": 1000},
        {"id": "publish", "type": "click", "pageId": "ir", "target": "s0.children.9", "duration": 800},
        {"id": "next", "type": "navigate", "pageId": "ir", "toPageId": "page2", "transition": "fade", "duration": 650},
        {"id": "end", "type": "wait", "pageId": "page2", "duration": 1200},
    ]}], "animations": []}


PROMPT = 'Сделай инструкцию по размещению объявления. На странице «Форма» введи название «Диван», цену «15000» и город «Москва» как человек. Прокрути к кнопке «Разместить объявление», нажми её, затем плавно перейди к странице «Готово» и покажи результат. Без звука.'
