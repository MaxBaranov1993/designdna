"""Design System Document: контракты, content-hash, ревизии, валидация.

ТЗ §9, §23, §25.1: документ — единица редактирования (draft); публикация
создаёт immutable revision с contentHash; одинаковый контент не создаёт
дубликат ревизии; валидация блокирует publish при структурных ошибках.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

SCHEMA_VERSION = "design-system/1.0"

# поля, не участвующие в content-hash (меняются без смены ревизии смысла)
# status/revision/quality меняются без смены смысла; contentHash исключён,
# иначе хеш ссылался бы сам на себя и идемпотентность publish ломалась
_VOLATILE_FIELDS = ("status", "revision", "quality", "contentHash")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict) -> str:
    """Стабильный хеш содержимого: без volatile-полей (status/revision/quality)."""
    core = {k: v for k, v in document.items() if k not in _VOLATILE_FIELDS}
    return "sha256:" + hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()


def new_document(name: str, *, project_id: str = "default", source_refs: list | None = None) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": f"ds-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]}",
        "projectId": project_id,
        "name": name.strip() or "Design System",
        "status": "draft",
        "revision": 0,
        "sourceRefs": source_refs or [],
        "foundations": {"colors": {"primitives": {}, "semantic": {}}, "typography": {"families": [], "scale": {}, "weights": []},
                        "spacing": {}, "radii": [], "shadows": [], "breakpoints": {}, "containers": {}},
        "components": {},
        "patterns": {},
        "mockData": {"schemas": {}, "fixtures": {}},
        "rules": {"usageModes": ["strict", "extend", "style-only"]},
        "provenance": {"observedCount": 0, "inferredCount": 0, "generatedCount": 0},
        "quality": {"score": 0, "stateCoverage": 0, "issues": []},
    }


def next_revision(document: dict, previous_revisions: list[str]) -> dict:
    """Новая published-ревизия: bump номера, пересчёт хеша; тот же contentHash
    среди существующих ревизий не создаёт новую (§31 — идемпотентность publish)."""
    digest = content_hash(document)
    if digest in previous_revisions:
        return copy.deepcopy(document)
    published = copy.deepcopy(document)
    published["status"] = "published"
    published["revision"] = int(document.get("revision") or 0) + 1
    published["contentHash"] = digest
    return published


def _walk_ir(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk_ir(child)


def validate_document(document: dict) -> list[dict]:
    """Структурная валидация (§25.1). Возвращает список blocking-ошибок."""
    errors: list[dict] = []
    components = document.get("components") or {}
    if not isinstance(components, dict) or not components:
        errors.append({"code": "no-components", "message": "Дизайн-система не содержит ни одного компонента"})
        return errors

    keys = set()
    for key, comp in components.items():
        if not isinstance(comp, dict):
            errors.append({"code": "bad-component", "message": f"Компонент {key} не является объектом"})
            continue
        if comp.get("componentKey") and comp["componentKey"] in keys:
            errors.append({"code": "duplicate-key", "message": f"Дубликат componentKey: {comp['componentKey']}"})
        keys.add(comp.get("componentKey") or key)
        template = comp.get("templateIr")
        if not isinstance(template, dict) or not isinstance(template.get("tree"), list):
            errors.append({"code": "bad-template", "message": f"Компонент {key}: templateIr не является Design IR"})

    # зависимости существуют + отсутствие циклов
    deps_graph = {k: [d for d in (c.get("dependencies") or []) if isinstance(c, dict)] for k, c in components.items() if isinstance(c, dict)}
    for key, deps in deps_graph.items():
        for dep in deps:
            if dep not in components and dep not in keys:
                errors.append({"code": "missing-dependency", "message": f"Компонент {key} зависит от несуществующего {dep}"})
    visiting, done = set(), set()

    def has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        for dep in deps_graph.get(node, []):
            if dep in components and has_cycle(dep):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    for key in deps_graph:
        if has_cycle(key):
            errors.append({"code": "dependency-cycle", "message": f"Циклическая зависимость с участием {key}"})
            break

    # generated-компоненты не публикуются без подтверждения (§10)
    for key, comp in components.items():
        if isinstance(comp, dict) and comp.get("origin") == "generated" and not comp.get("confirmed"):
            errors.append({"code": "unconfirmed-generated", "message": f"Компонент {key} сгенерирован и не подтверждён — подтвердите или удалите перед публикацией"})

    # token bindings ссылаются на существующие foundations-токены
    semantic = ((document.get("foundations") or {}).get("colors") or {}).get("semantic") or {}
    primitives = ((document.get("foundations") or {}).get("colors") or {}).get("primitives") or {}
    known_tokens = set(semantic) | set(primitives)
    for key, comp in components.items():
        if not isinstance(comp, dict):
            continue
        for binding in (comp.get("tokenBindings") or {}):
            if known_tokens and binding not in known_tokens:
                errors.append({"code": "unknown-token-binding", "message": f"Компонент {key}: привязка к неизвестному токену {binding}"})
    return errors


def summary(document: dict) -> dict:
    """Компактная карточка для ноды и picker-списка (§11.2, §15.4)."""
    components = [c for c in (document.get("components") or {}).values() if isinstance(c, dict)]
    variants = sum(len(c.get("variants") or {}) for c in components)
    states_total = sum(len(c.get("states") or {}) for c in components)
    coverage = round(100 * sum(1 for c in components if c.get("states")) / max(1, len(components)))
    origins = {"observed": 0, "inferred": 0, "generated": 0}
    for c in components:
        origins[str(c.get("origin") or "inferred")] = origins.get(str(c.get("origin") or "inferred"), 0) + 1
    return {
        "name": document.get("name"),
        "systemId": document.get("id"),
        "status": document.get("status"),
        "revision": document.get("revision"),
        "contentHash": document.get("contentHash"),
        "components": len(components),
        "variants": variants,
        "stateCoverage": coverage,
        "states": states_total,
        "mockSchemas": len((document.get("mockData") or {}).get("schemas") or {}),
        "qualityScore": round(float((document.get("quality") or {}).get("score") or 0)),
        "origins": origins,
    }
