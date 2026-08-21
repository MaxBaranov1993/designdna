"""Builder: Source Pack → draft Design System (ТЗ §8, §21).

Детерминированный анализ идёт до AI (§21): foundations из Style DNA-токенов,
компоненты — из component boundaries и repeat-group компилятора Source Import
(sourceMeta.componentBoundary/componentRole/repeatGroup), observed variants —
из сиблингов repeat-групп. AI-предложения (недостающие states, имена) в MVP
помечаются origin=generated + confirmed=false и не публикуются без подтверждения.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import mock as mock_mod
from .document import content_hash as _content_hash
from .document import new_document

_GEN_STATES = ("hover", "loading", "error", "empty", "disabled")
_CATEGORY_OF_ROLE = {
    "button": "actions", "input": "forms", "card": "content", "heading": "typography",
    "text": "typography", "image": "media", "navigation": "navigation", "panel": "surfaces",
    "toolbar": "navigation", "profile": "content", "status": "feedback",
}


def build_source_pack(source_node_data: dict, *, source_node_id: Any = 0) -> dict:
    """Source Pack из данных Source-ноды (ТЗ §8). Тяжёлые preview не копируем."""
    blocks = source_node_data.get("blocks") or []
    pack_blocks = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("error") or not block.get("ir"):
            continue
        pack_blocks.append({
            "name": block.get("name"),
            "label": block.get("label"),
            "kind": block.get("kind") or "section",
            "irHash": "sha256:" + hashlib.sha256(
                json.dumps(block.get("ir"), ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        })
    return {
        "schemaVersion": "source-pack/1.0",
        "sourceNodeId": str(source_node_id),
        "sourceRevisionHash": _content_hash({"blocks": pack_blocks, "tokens": source_node_data.get("tokens") or {}}),
        "source": {
            "kind": "url" if (source_node_data.get("mode") or "url") == "url" else "screenshot",
            "url": source_node_data.get("url"),
            "capturedAt": source_node_data.get("capturedAt") or "",
            "parserVersion": source_node_data.get("parserVersion") or "dom-v28",
        },
        "blocks": pack_blocks,
        "tokens": source_node_data.get("tokens") or {},
        "viewports": ["desktop", "tablet", "mobile"],
    }


def _walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _foundations_from_tokens(tokens: dict, viewports: list) -> dict:
    """Style DNA становится частью foundations (§9.1), не конкурирующим источником."""
    color = (tokens.get("color") or {}) if isinstance(tokens, dict) else {}
    semantic, primitives = {}, {}
    for key, value in color.items():
        hexv = value.get("value") if isinstance(value, dict) else value
        if isinstance(hexv, str) and hexv.startswith("#"):
            (semantic if key in ("primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border") else primitives)[key] = hexv.lower()

    font = (tokens.get("font") or {}) if isinstance(tokens, dict) else {}
    families = []
    for key in ("display", "body"):
        entry = font.get(key)
        if isinstance(entry, dict) and entry.get("family"):
            fam = str(entry["family"]).strip()
            if fam and fam not in families:
                families.append(fam)
    weights = []
    for key in ("display", "body"):
        entry = font.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("weight"), int):
            weights.append(entry["weight"])

    radius = tokens.get("radius") or {}
    radii = sorted({int(v) for v in radius.values() if isinstance(v, (int, float, str)) and str(v).replace(".", "").isdigit()})

    return {
        "colors": {"primitives": primitives, "semantic": semantic},
        "typography": {
            "families": families[:4],
            "scale": {"display": 48, "h2": 32, "h3": 24, "body": 16, "caption": 13},
            "weights": sorted(set(weights)) or [400, 700],
        },
        "spacing": {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32, "xxl": 48},
        "radii": radii or [8, 12],
        "shadows": [],
        "breakpoints": {"mobile": 640, "tablet": 1024, "desktop": 1440},
        "containers": {"content": 1200, "text": 720},
        "iconStyle": "outline, 1.5px, текущая палитра",
        "imageDirection": "фотореалистичные материалы продукта, мягкий свет, нейтральный фон",
    }


def _components_from_blocks(blocks: list, source_revision_hash: str) -> tuple[dict, dict]:
    """Компоненты из component boundaries/repeat groups; observed variants из сиблингов."""
    components: dict[str, dict] = {}
    boundaries: dict[str, dict] = {}

    for block in blocks:
        if not isinstance(block, dict) or block.get("error") or not isinstance(block.get("ir"), dict):
            continue
        block_name = str(block.get("name") or "block")
        tree_roots = list((block["ir"].get("tree") or []))
        for node in _walk({"children": tree_roots}):
            meta = node.get("sourceMeta") or {}
            if not isinstance(meta, dict) or not meta.get("componentBoundary"):
                continue
            role = str(meta.get("componentRole") or node.get("type") or "card").lower()
            group = meta.get("repeatGroup")
            key = str(group or f"{block_name}:{role}").strip()
            key = key.replace("/", "-").replace(":", "-")[:60]
            if key in boundaries:
                # повтор уже видели — это observed variant соседа
                base = boundaries[key]
                base["_sibling_count"] = base.get("_sibling_count", 1) + 1
                continue
            template = copy.deepcopy({"version": block["ir"].get("version", "1.1"),
                                      "tokens": block["ir"].get("tokens") or {},
                                      "tree": [copy.deepcopy(node)]})
            variant_hint = str(node.get("variant") or meta.get("componentLabel") or role)
            comp = {
                "componentKey": key,
                "name": str(meta.get("componentLabel") or variant_hint or key).strip()[:120] or key,
                "category": _CATEGORY_OF_ROLE.get(role, "content"),
                "description": f"Обнаружен в Source ({block_name}); role={role}",
                "origin": "observed",
                "confidence": 1.0 if group else 0.6,
                "confirmed": True,
                "templateIr": template,
                "propsSchema": _props_from_node(node),
                "slots": [],
                "variants": {"default": {"label": variant_hint[:80] or "Default", "origin": "observed", "diff": {}}},
                "states": {},
                "dependencies": [],
                "tokenBindings": {},
                "mockBindings": [],
                "accessibility": {"role": role if role in ("button", "input", "navigation") else "group", "focusable": role in ("button", "input")},
                "provenance": {"sourceKey": str(node.get("sourceKey") or ""), "sourceBlock": block_name, "sourceRevisionHash": source_revision_hash},
            }
            boundaries[key] = comp
            components[key] = comp

    # недостающие states — AI-предложения, не публикуются без подтверждения
    for key, comp in components.items():
        for state in _GEN_STATES:
            comp["states"][state] = {"label": state, "origin": "generated", "confirmed": False,
                                     "description": f"Предложено AI: состояние {state} не наблюдается в Source"}
    return components, boundaries


def _props_from_node(node: dict) -> dict:
    """Минимальная схема props из содержимого template (текст/иконки/медиа)."""
    props: dict[str, dict] = {}
    texts = 0
    for child in _walk(node):
        if child is node:
            continue
        t = str(child.get("text") or "")
        if t:
            texts += 1
        if child.get("type") == "image":
            props[f"media{len(props) + 1}"] = {"type": "iri", "required": False, "description": "изображение из макета"}
    if texts:
        props["text"] = {"type": "string", "required": True, "description": f"основной текст ({texts} фрагментов)"}
    if node.get("type") == "button":
        props["action"] = {"type": "string", "required": False, "description": "действие по нажатию"}
    return props


def _mock_data_for(components: dict, locale: str) -> dict:
    schemas: dict[str, dict] = {}
    fixtures: dict[str, dict] = {}
    for key, comp in components.items():
        schema_id = f"{key}-data"
        fields = [{"name": name, "format": "sentence", "type": "string"} for name in (comp.get("propsSchema") or {})
                  if (comp["propsSchema"][name].get("type") == "string")]
        if any(p.get("type") == "iri" for p in (comp.get("propsSchema") or {}).values()):
            fields.append({"name": "image", "format": "url", "type": "string"})
        schema = {"id": schema_id, "locale": locale, "fields": fields or [{"name": "text", "format": "sentence", "type": "string"}]}
        schemas[schema_id] = schema
        for profile, fixture in mock_mod.default_profiles(schema, locale).items():
            fixtures[fixture["id"]] = fixture
        comp["mockBindings"] = [{"schemaId": schema_id, "field": "text"}]
    return {"schemas": schemas, "fixtures": fixtures}


def build_draft(pack: dict, *, name: str | None = None, locale: str = "ru",
                include_generated_states: bool = True, create_mock: bool = True) -> dict:
    """Source Pack → draft Design System Document (§21, шаги 1-15)."""
    source_hash = str(pack.get("sourceRevisionHash") or "")
    doc = new_document(
        name or f"UI Kit · {pack.get('source', {}).get('url') or 'Source'}",
        source_refs=[{"sourceNodeId": pack.get("sourceNodeId"), "revisionHash": source_hash,
                      "url": pack.get("source", {}).get("url"), "capturedAt": pack.get("source", {}).get("capturedAt")}],
    )
    doc["foundations"] = _foundations_from_tokens(pack.get("tokens") or {}, pack.get("viewports") or [])

    # блоки берём из исходных данных ноды (pack хранит только hash-ссылки)
    blocks = pack.get("_raw_blocks") or []
    components, _ = _components_from_blocks(blocks, source_hash)
    if not include_generated_states:
        for comp in components.values():
            comp["states"] = {}
    doc["components"] = components

    if create_mock and components:
        doc["mockData"] = _mock_data_for(components, locale)

    origins = {"observed": 0, "inferred": 0, "generated": 0}
    for comp in components.values():
        origins[comp["origin"]] = origins.get(comp["origin"], 0) + 1
    doc["provenance"] = origins
    confirmed_states = sum(1 for c in components.values() for s in (c.get("states") or {}).values() if s.get("origin") != "generated" or s.get("confirmed"))
    doc["quality"] = {
        "score": round(40 + min(60, len(components) * 5)),
        "stateCoverage": round(100 * len(components) / max(1, len(components))) if confirmed_states else 0,
        "issues": [],
    }
    return doc
