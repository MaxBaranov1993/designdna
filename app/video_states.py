"""Derived video-only page states. Source pages and component identities stay intact."""
from __future__ import annotations

import copy
import re

TEXT_KEYS = {"text", "heading", "subheading", "title", "label", "placeholder", "description", "subtitle", "caption", "body", "value", "alt", "imagePrompt", "ctaPrimary", "ctaSecondary"}
COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def text_fields(ir: dict) -> list[dict]:
    result = []
    def walk(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"style", "frame", "tokens", "meta", "provenance", "componentRef"}:
                    continue
                child_path = f"{path}.{key}"
                if key in TEXT_KEYS and isinstance(child, str):
                    result.append({"path": child_path, "text": child})
                elif isinstance(child, (dict, list)):
                    walk(child, child_path)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, f"{path}.{i}")
    walk(ir.get("tree", []), "tree")
    return result


def overlay_targets(overlays: list) -> list[dict]:
    result = []
    for overlay in overlays:
        root = "overlay." + overlay["id"]
        result.append({"id": root, "label": overlay.get("title") or "Меню", "kind": "card"})
        result.extend({"id": root + "." + item["id"], "label": item["text"], "kind": "button"} for item in overlay["items"])
    return result


def validate_overlays(page: dict, known_targets: set[str]) -> None:
    overlays = page.get("overlays", [])
    if not isinstance(overlays, list) or len(overlays) > 8:
        raise ValueError("В состоянии может быть до восьми окон")
    seen = set()
    for overlay in overlays:
        if not isinstance(overlay, dict) or set(overlay) - {"id", "anchorTarget", "title", "items", "width", "background", "color", "accent", "radius"}:
            raise ValueError("Недопустимое описание окна состояния")
        ident = overlay.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", ident) or ident in seen:
            raise ValueError("У окон должны быть уникальные ID")
        seen.add(ident)
        if overlay.get("anchorTarget") not in known_targets:
            raise ValueError("Не найден элемент, рядом с которым нужно открыть окно")
        if not isinstance(overlay.get("title", ""), str) or len(overlay.get("title", "")) > 200:
            raise ValueError("Слишком длинный заголовок окна")
        for key in ("background", "color", "accent"):
            if key in overlay and (not isinstance(overlay[key], str) or not COLOR.fullmatch(overlay[key])):
                raise ValueError("Цвет окна должен быть HEX")
        for key, low, high in (("width", 160, 640), ("radius", 0, 40)):
            if key in overlay and (isinstance(overlay[key], bool) or not isinstance(overlay[key], (int, float)) or not low <= overlay[key] <= high):
                raise ValueError("Недопустимый размер окна")
        items = overlay.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            raise ValueError("В окне нужны 1–12 пунктов")
        item_ids = set()
        for item in items:
            if not isinstance(item, dict) or set(item) - {"id", "text", "selected"}:
                raise ValueError("Недопустимый пункт окна")
            item_id = item.get("id")
            if not isinstance(item_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", item_id) or item_id in item_ids:
                raise ValueError("У пунктов окна должны быть уникальные ID")
            item_ids.add(item_id)
            if not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > 500:
                raise ValueError("Нужен текст пункта окна")
            if "selected" in item and not isinstance(item["selected"], bool):
                raise ValueError("Некорректное выделение пункта")


def derive_states(story: dict, states: list) -> dict:
    from video_story import targets
    result = copy.deepcopy(story)
    if not isinstance(states, list) or len(states) > 12:
        raise ValueError("За один запрос можно создать до 12 состояний")
    seen = set()
    for state in states:
        if not isinstance(state, dict) or set(state) - {"id", "name", "fromPageId", "text", "overlays"}:
            raise ValueError("Недопустимое описание состояния страницы")
        ident, source_id = state.get("id"), state.get("fromPageId")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", ident) or ident in seen or ident == source_id:
            raise ValueError("Состоянию нужен отдельный уникальный ID")
        seen.add(ident)
        source = next((p for p in result["pages"] if p["id"] == source_id), None)
        existing = next((p for p in result["pages"] if p["id"] == ident), None)
        if not source or (existing and not existing.get("generatedFrom")):
            raise ValueError("Нельзя заменять исходную подключённую страницу")
        if existing and existing["generatedFrom"] != source_id:
            raise ValueError("Нельзя менять источник существующего состояния")
        # Refuse cycles, including a new revision derived from its own descendant.
        ancestor = source
        visited = {ident}
        while ancestor:
            if ancestor["id"] in visited:
                raise ValueError("Циклическая зависимость состояний")
            visited.add(ancestor["id"])
            ancestor = next((p for p in result["pages"] if p["id"] == ancestor.get("generatedFrom")), None)
        name = state.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("Укажите название состояния")
        # Revisions extend the saved state; unspecified manual edits survive.
        page = copy.deepcopy(existing or source)
        page.update(id=ident, name=name, generatedFrom=source_id)
        changes = state.get("text", {})
        available = {field["path"] for field in text_fields(page["ir"])}
        if not isinstance(changes, dict) or len(changes) > 2000:
            raise ValueError("Некорректный список текстовых изменений")
        for path, text in changes.items():
            if path not in available or not isinstance(text, str) or len(text) > 8000:
                raise ValueError(f"Нельзя изменить текст по пути {str(path)[:120]}")
            parts = path.split(".")
            node = page["ir"]
            for part in parts[:-1]:
                node = node[int(part)] if isinstance(node, list) else node[part]
            node[parts[-1]] = text
        if "overlays" in state:
            page["overlays"] = copy.deepcopy(state["overlays"])
        validate_overlays(page, {target["id"] for target in targets(page["ir"])})
        if existing:
            result["pages"][result["pages"].index(existing)] = page
        else:
            result["pages"].append(page)
    if len(result["pages"]) > 24:
        raise ValueError("В ролике может быть до 24 страниц и состояний")
    return result


def state_layers(timeline: dict, story: dict, duration: int) -> list[dict]:
    from video_story import build_pages
    existing = {layer["id"] for layer in timeline["layers"]}
    added = []
    for page in story["pages"]:
        if not page.get("generatedFrom"):
            continue
        document = build_pages([{"id": page["id"], "name": page["name"], "ir": page["ir"]}], {**timeline["composition"], "duration": duration})
        for layer in document["layers"]:
            layer["id"] = page["id"] + ":" + layer["id"]
            layer["parent"] = timeline["groups"][0]["id"]
            if layer["id"] not in existing:
                added.append(layer)
        for target in overlay_targets(page.get("overlays", [])):
            ident = page["id"] + ":" + target["id"]
            if ident not in existing:
                added.append({"id": ident, "type": "component", "ref": target["id"], "pageId": page["id"],
                    "storyTarget": target["id"], "parent": timeline["groups"][0]["id"], "name": page["name"] + " · " + target["label"], "in": 0, "out": duration,
                    "transform": {"anchor": {"x": .5, "y": .5}, "properties": {}}})
    return added
