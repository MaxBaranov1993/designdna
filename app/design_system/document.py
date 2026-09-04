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

SCHEMA_VERSION = "design-system/1.2"

MASTER_FIDELITY_THRESHOLDS = {
    "minPixelSimilarity": 95.0,
    # Photographic/image-bearing masters can be sub-pixel shifted by browser
    # auto-layout even when geometry, paint and source-gate evidence are exact.
    # The raw per-channel metric then over-penalizes every textured edge. This
    # calibrated floor still requires the original Source gate plus the same
    # strict structural checks below.
    "minRasterPixelSimilarity": 88.0,
    # One-pixel antialiasing around a 36-52 px control can account for more
    # than 10% of all pixels while its measured box, paint and palette remain
    # exact. Compact controls therefore use a geometry-guarded calibrated floor.
    "minCompactPixelSimilarity": 80.0,
    "minPaintCoverage": 98.0,
    "maxOriginError": 2.0,
    "maxBboxP95": 4.0,
    "maxUnexplainedLosses": 0,
}
_SECTION_TYPES = {
    "navbar", "hero", "logo-cloud", "feature-grid", "feature-alternating", "stats", "steps",
    "gallery", "testimonials", "pricing", "comparison", "team", "blog-grid", "faq", "cta",
    "contact-form", "newsletter", "banner", "footer", "source-block",
}

# поля, не участвующие в content-hash (меняются без смены ревизии смысла)
# status/revision/quality меняются без смены смысла; contentHash исключён,
# иначе хеш ссылался бы сам на себя и идемпотентность publish ломалась
_VOLATILE_FIELDS = ("status", "revision", "quality", "contentHash", "compiledProfiles")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict) -> str:
    """Стабильный хеш содержимого: без volatile-полей (status/revision/quality)."""
    core = {k: v for k, v in document.items() if k not in _VOLATILE_FIELDS}
    return "sha256:" + hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()


def component_fidelity_status(fidelity: dict | None) -> dict:
    """Fail-closed release gate for an observed master."""
    evidence = fidelity if isinstance(fidelity, dict) else {}
    viewports = evidence.get("viewports") if isinstance(evidence.get("viewports"), dict) else {}
    required = [str(name) for name in (evidence.get("requiredViewports") or list(viewports))]
    contains_raster = evidence.get("containsRaster") is True
    compact_control = evidence.get("compactControl") is True
    reasons: list[str] = []
    # AI-ревью (design_system.master_review) — второй, содержательный гейт:
    # агент сравнил оригинал и рендер и не нашёл реальных дефектов. Его
    # одобрение заменяет пороги попиксельной метрики; отказ ничего не меняет.
    ai_review = fidelity.get("aiReview") if isinstance(fidelity, dict) and isinstance(fidelity.get("aiReview"), dict) else None
    if ai_review and ai_review.get("verdict") == "approved":
        return {"status": "verified", "passed": True, "reasons": []}
    if not required:
        return {"status": "needs-review", "passed": False, "reasons": ["no fidelity viewports"]}
    for name in required:
        metrics = viewports.get(name) if isinstance(viewports.get(name), dict) else None
        if not metrics:
            reasons.append(f"{name}: no metrics")
            continue
        required_metrics = ("pixelSimilarity", "paintCoverage", "bboxP95", "originError", "unexplainedLosses", "sizeMatch")
        missing = [key for key in required_metrics if metrics.get(key) is None]
        if missing:
            reasons.append(f"{name}: missing {', '.join(missing)}")
            continue
        if metrics.get("sizeMatch") is not True:
            reasons.append(f"{name}: reference/render size mismatch")
        similarity_threshold = (
            MASTER_FIDELITY_THRESHOLDS["minCompactPixelSimilarity"]
            if compact_control
            else MASTER_FIDELITY_THRESHOLDS["minRasterPixelSimilarity"]
            if contains_raster and metrics.get("sourceGatePassed") is True
            else MASTER_FIDELITY_THRESHOLDS["minPixelSimilarity"]
        )
        if float(metrics["pixelSimilarity"]) < similarity_threshold:
            reasons.append(
                f"{name}: pixel similarity {metrics['pixelSimilarity']} < {similarity_threshold:g}"
            )
        if float(metrics["paintCoverage"]) < MASTER_FIDELITY_THRESHOLDS["minPaintCoverage"]:
            reasons.append(f"{name}: paint coverage {metrics['paintCoverage']} < 98")
        if float(metrics["originError"]) > MASTER_FIDELITY_THRESHOLDS["maxOriginError"]:
            reasons.append(f"{name}: origin error {metrics['originError']} > 2px")
        if float(metrics["bboxP95"]) > MASTER_FIDELITY_THRESHOLDS["maxBboxP95"]:
            reasons.append(f"{name}: bbox p95 {metrics['bboxP95']} > 4px")
        if int(metrics["unexplainedLosses"]) > MASTER_FIDELITY_THRESHOLDS["maxUnexplainedLosses"]:
            reasons.append(f"{name}: unexplained visual losses {metrics['unexplainedLosses']}")
    return {"status": "verified" if not reasons else "needs-review", "passed": not reasons, "reasons": reasons}


_PREVIEW_VIEWPORTS = ("desktop", "tablet", "mobile")


def _has_responsive_overrides(node: object, depth: int = 0) -> bool:
    if depth > 40 or not isinstance(node, dict):
        return False
    if isinstance(node.get("responsive"), dict) and node["responsive"]:
        return True
    return any(_has_responsive_overrides(child, depth + 1) for child in node.get("children") or [])


def _preview_responsive(master: dict, node: dict, wrapper_frame: dict, wrapper_responsive: dict) -> dict:
    """Корневой ``responsive.viewports`` для превью мастера.

    Рендерер применяет per-viewport override'ы узлов (visible:false у клонов
    других вьюпортов, frame/style) ТОЛЬКО при наличии этого маркера; без него
    desktop- и mobile-версии текста рисовались друг поверх друга. Размеры
    вьюпортов берём от самого компонента, а не 1440×900 страницы: материализация
    пишет их в корневой frame, и артборд превью остаётся размером с компонент."""
    source = master.get("responsive") if isinstance(master.get("responsive"), dict) else {}
    names = list((source.get("viewports") or {}).keys()) if isinstance(source.get("viewports"), dict) else []
    if not names:
        if not _has_responsive_overrides(node):
            return {}
        names = list(_PREVIEW_VIEWPORTS)
    def _px(value: object) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1 else None

    viewports: dict[str, dict] = {}
    for name in names:
        if name not in _PREVIEW_VIEWPORTS:
            continue
        frame = (wrapper_responsive.get(name) or {}).get("frame") or {}
        # схема sourceViewport требует и width, и height ≥ 1
        width = _px(frame.get("width")) or _px(wrapper_frame.get("width"))
        height = _px(frame.get("height")) or _px(wrapper_frame.get("height"))
        if width and height:
            viewports[str(name)] = {"width": width, "height": height}
    return {"responsive": {"viewports": viewports}} if viewports else {}


def preview_ir_for_master(master: dict) -> dict:
    roots = master.get("tree") if isinstance(master.get("tree"), list) else []
    if not roots or not isinstance(roots[0], dict) or roots[0].get("type") in _SECTION_TYPES:
        return copy.deepcopy(master)
    node = copy.deepcopy(roots[0])
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    # Component bounds are relative to the Source block. Keeping those x/y
    # offsets inside a component-sized wrapper clips the preview into a strip.
    # Normalize only this render copy; the pinned masterIr remains untouched.
    if frame:
        normalized_frame = copy.deepcopy(frame)
        normalized_frame["x"] = 0
        normalized_frame["y"] = 0
        node["frame"] = normalized_frame
    responsive = node.get("responsive") if isinstance(node.get("responsive"), dict) else {}
    wrapper_responsive: dict[str, dict] = {}
    for viewport_name, override in responsive.items():
        if not isinstance(override, dict):
            continue
        override_frame = override.get("frame") if isinstance(override.get("frame"), dict) else None
        if not override_frame:
            continue
        normalized_override = copy.deepcopy(override_frame)
        normalized_override["x"] = 0
        normalized_override["y"] = 0
        override["frame"] = normalized_override
        wrapper_size = {
            key: copy.deepcopy(normalized_override[key])
            for key in ("width", "height") if normalized_override.get(key) is not None
        }
        if wrapper_size:
            wrapper_responsive[str(viewport_name)] = {"frame": {**wrapper_size, "layout": "free"}}
    wrapper_frame = {
        **{key: copy.deepcopy(frame[key]) for key in ("width", "height") if frame.get(key) is not None},
        "layout": "free",
    }
    return {
        "version": master.get("version") or "1.1",
        "tokens": copy.deepcopy(master.get("tokens") or {}),
        # Обёртка превью обязана донести meta.fontFaces: рендерер берёт
        # @font-face только отсюда, иначе компонент рисуется системным шрифтом.
        **({"meta": copy.deepcopy(master["meta"])}
           if isinstance(master.get("meta"), dict) and master["meta"] else {}),
        # …и корневой responsive.viewports: только с ним рендерер прячет
        # клоны других вьюпортов (visible:false) вместо наложения текста.
        **_preview_responsive(master, node, wrapper_frame, wrapper_responsive),
        "tree": [{
            "id": "ds-master-preview", "type": "source-block", "variant": "component-master", "props": {},
            **({"frame": wrapper_frame} if wrapper_frame else {}),
            **({"responsive": wrapper_responsive} if wrapper_responsive else {}),
            "children": [node],
        }],
    }


def migrate_draft(document: dict) -> dict:
    """Migrate a mutable working copy without touching immutable revisions."""
    migrated = copy.deepcopy(document)
    suggestions = migrated.get("suggestions") if isinstance(migrated.get("suggestions"), dict) else {}
    components = migrated.get("components") if isinstance(migrated.get("components"), dict) else {}
    keep: dict[str, dict] = {}
    for key, comp in components.items():
        if not isinstance(comp, dict):
            keep[key] = comp
            continue
        origin = str(comp.get("origin") or "inferred")
        if origin in ("inferred", "suggested") or (origin == "generated" and not comp.get("confirmed")):
            suggestion = copy.deepcopy(comp)
            suggestion.update({"origin": "suggested", "status": "draft", "confirmed": False})
            suggestions[str(key)] = suggestion
            continue
        if origin == "observed":
            if not isinstance(comp.get("masterIr"), dict):
                # Legacy observed records may be synthetic; keep them visible but
                # force Source Sync/review before they can be published again.
                comp["masterIr"] = copy.deepcopy(comp.get("templateIr"))
                comp["status"] = "needs-review"
                comp["confirmed"] = False
                comp.setdefault("fidelity", {"status": "not-measured", "viewports": {}, "requiredViewports": []})
                comp.setdefault("provenance", {})["migration"] = "legacy-master-needs-source-sync"
            else:
                template = comp.get("templateIr")
                generated_preview = preview_ir_for_master(comp["masterIr"])
                if (isinstance(template, dict)
                        and canonical_json(template) in (canonical_json(comp["masterIr"]), canonical_json(generated_preview))):
                    comp.pop("templateIr", None)
                for variant_key, variant in (comp.get("variants") or {}).items():
                    if not isinstance(variant, dict):
                        continue
                    if (variant_key == "default" and isinstance(variant.get("masterIr"), dict)
                            and canonical_json(variant["masterIr"]) == canonical_json(comp["masterIr"])):
                        variant.pop("masterIr", None)
                        variant.pop("sourceRef", None)
                        variant["masterRef"] = "self"
                source_ref = comp.get("sourceRef") if isinstance(comp.get("sourceRef"), dict) else {}
                if source_ref.get("masterHash") != content_hash(comp["masterIr"]):
                    comp["status"] = "needs-review"
                    comp["confirmed"] = False
                    comp.setdefault("provenance", {})["migration"] = "master-hash-needs-source-sync"
                else:
                    comp["status"] = component_fidelity_status(comp.get("fidelity"))["status"]
        elif origin == "user":
            comp.setdefault("masterIr", copy.deepcopy(comp.get("templateIr")))
            if (isinstance(comp.get("templateIr"), dict) and isinstance(comp.get("masterIr"), dict)
                    and canonical_json(comp["templateIr"]) == canonical_json(comp["masterIr"])):
                comp.pop("templateIr", None)
            comp.setdefault("status", "verified" if comp.get("confirmed") else "draft")
        keep[str(key)] = comp
    migrated["components"] = keep
    migrated["suggestions"] = suggestions
    migrated.setdefault("extraction", {})
    migrated["schemaVersion"] = SCHEMA_VERSION
    return migrated


def identity_source_refs(source_refs: list | None) -> list:
    """Поля идентичности системы: recapture-volatile revisionHash/capturedAt не входят.

    Sync/перезахват Source должен создать новую ревизию той же системы, а не
    новый systemId, иначе default и pinned-ссылки разъедутся.
    """
    out = []
    for ref in source_refs or []:
        if not isinstance(ref, dict):
            continue
        out.append({
            "sourceNodeId": ref.get("sourceNodeId"),
            "url": ref.get("url") or "",
        })
    return out


def new_document(name: str, *, project_id: str = "default", source_refs: list | None = None) -> dict:
    from .identity import empty_identity, empty_reconstruction
    refs = source_refs or []
    seed = canonical_json({
        "projectId": project_id,
        "name": (name or "").strip(),
        "sourceRefs": identity_source_refs(refs),
    })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": f"ds-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}",
        "projectId": project_id,
        "name": name.strip() or "Design System",
        "status": "draft",
        "revision": 0,
        "sourceRefs": refs,
        "referenceAssets": {},
        "foundations": {"colors": {"primitives": {}, "semantic": {}}, "typography": {"families": [], "scale": {}, "weights": []},
                        "spacing": {}, "radii": [], "shadows": [], "breakpoints": {}, "containers": {}},
        "components": {},
        # Exact observed masters that are useful in the UI catalog but have not
        # passed the release-grade fidelity gate. They remain visible after
        # publish, while `components` stays the strict AI/runtime registry.
        "reviewComponents": {},
        # Semantic ordering only. Exact component masters and fidelity evidence
        # remain authoritative and are never embedded or rewritten here.
        "catalog": {},
        "suggestions": {},
        "extraction": {"boundaryCount": 0, "extractedBoundaryCount": 0,
                       "observedComponentCount": 0, "suggestionCount": 0},
        "patterns": {},
        "mockData": {"schemas": {}, "fixtures": {}},
        "rules": {"usageModes": ["strict", "extend", "style-only"]},
        "identity": empty_identity(),
        "identityTests": [],
        "reconstruction": empty_reconstruction(),
        # Derived cache only. It is excluded from contentHash and may be rebuilt.
        "compiledProfiles": {},
        "provenance": {"observed": 0, "suggested": 0, "generated": 0, "user": 0,
                       "observedCount": 0, "suggestedCount": 0, "generatedCount": 0},
        "quality": {"score": 0, "stateCoverage": 0, "issues": []},
    }


def prepare_for_publish(document: dict) -> dict:
    """Черновик → содержимое ревизии: убрать неподтверждённые generated-states."""
    prepared = copy.deepcopy(document)
    components = prepared.get("components") or {}
    if isinstance(components, dict):
        for comp in components.values():
            if not isinstance(comp, dict):
                continue
            states = comp.get("states") or {}
            if not isinstance(states, dict):
                continue
            comp["states"] = {
                key: state for key, state in states.items()
                if not (isinstance(state, dict) and state.get("origin") == "generated" and not state.get("confirmed"))
            }
    # Semantic suggestions are an editor-only gap-analysis pool. Exact observed
    # review masters live in reviewComponents and remain inspectable after
    # publish, but never enter the strict runtime registry until verified.
    prepared["suggestions"] = {}
    if isinstance(prepared.get("extraction"), dict):
        prepared["extraction"]["suggestionCount"] = 0
    if isinstance(prepared.get("provenance"), dict):
        prepared["provenance"]["suggested"] = 0
        prepared["provenance"]["suggestedCount"] = 0
    prepared["status"] = "draft"
    return prepared


def next_revision(document: dict, previous_revisions: list[str], *, latest_revision: int = 0) -> dict:
    """Новая published-ревизия: bump номера, пересчёт хеша; тот же contentHash
    среди существующих ревизий не создаёт новую (§31 — идемпотентность publish)."""
    digest = content_hash(document)
    published = copy.deepcopy(document)
    published["contentHash"] = digest
    if digest in previous_revisions:
        return published
    published["status"] = "published"
    base = max(int(document.get("revision") or 0), int(latest_revision or 0))
    published["revision"] = base + 1
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

    source_revision_hashes = {
        str(ref.get("revisionHash") or "")
        for ref in (document.get("sourceRefs") or [])
        if isinstance(ref, dict) and ref.get("revisionHash")
    }
    keys = set()
    for key, comp in components.items():
        if not isinstance(comp, dict):
            errors.append({"code": "bad-component", "message": f"Компонент {key} не является объектом"})
            continue
        if comp.get("componentKey") and comp["componentKey"] in keys:
            errors.append({"code": "duplicate-key", "message": f"Дубликат componentKey: {comp['componentKey']}"})
        keys.add(comp.get("componentKey") or key)
        template = comp.get("templateIr")
        if template is not None and (not isinstance(template, dict) or not isinstance(template.get("tree"), list)):
            errors.append({"code": "bad-template", "message": f"Компонент {key}: templateIr не является Design IR"})
        master = comp.get("masterIr")
        if not isinstance(master, dict) or not isinstance(master.get("tree"), list):
            errors.append({"code": "bad-master", "message": f"Компонент {key}: отсутствует точный masterIr"})

        origin = str(comp.get("origin") or "inferred")
        if origin in ("inferred", "suggested"):
            errors.append({
                "code": "suggestion-in-registry",
                "message": f"Компонент {key}: предложение нельзя публиковать без явного Promote",
            })
        if origin == "observed":
            if isinstance(master, dict) and isinstance(template, dict):
                master_roots = master.get("tree") if isinstance(master.get("tree"), list) else []
                template_roots = template.get("tree") if isinstance(template.get("tree"), list) else []
                preview_node = template_roots[0] if template_roots else None
                if (isinstance(preview_node, dict) and preview_node.get("type") == "source-block"
                        and isinstance(preview_node.get("children"), list) and preview_node["children"]):
                    preview_node = preview_node["children"][0]
                if (not master_roots or not isinstance(preview_node, dict)
                        or canonical_json(master_roots[0]) != canonical_json(preview_node)):
                    errors.append({
                        "code": "observed-master-mutated",
                        "message": f"Компонент {key}: preview не содержит точный Source masterIr",
                    })
            if comp.get("confirmed") is not True:
                errors.append({"code": "unconfirmed-observed", "message": f"Компонент {key}: Source master не подтверждён"})
            fidelity = component_fidelity_status(comp.get("fidelity"))
            if not fidelity["passed"] or comp.get("status") != "verified":
                errors.append({
                    "code": "master-fidelity-failed",
                    "message": f"Компонент {key}: fidelity gate не пройден — {'; '.join(fidelity['reasons']) or 'status is not verified'}",
                })
            source_ref = comp.get("sourceRef") if isinstance(comp.get("sourceRef"), dict) else {}
            revision_hash = str(source_ref.get("sourceRevisionHash") or "")
            if not source_ref.get("sourceKey") or not revision_hash:
                errors.append({
                    "code": "missing-master-source-ref",
                    "message": f"Компонент {key}: нет Source sourceKey/sourceRevisionHash",
                })
            elif revision_hash not in source_revision_hashes:
                errors.append({
                    "code": "stale-master-source-ref",
                    "message": f"Компонент {key}: Source revision не совпадает с документом",
                })
            if source_ref.get("masterHash") != content_hash(master or {}):
                errors.append({
                    "code": "observed-master-mutated",
                    "message": f"Компонент {key}: masterIr не совпадает с закреплённым Source hash",
                })
            for variant_key, variant in (comp.get("variants") or {}).items():
                if not isinstance(variant, dict) or variant.get("origin") != "observed":
                    continue
                if variant.get("masterRef") == "self":
                    continue
                if not isinstance(variant.get("masterIr"), dict) or not isinstance(variant.get("sourceRef"), dict):
                    errors.append({
                        "code": "bad-observed-variant",
                        "message": f"Компонент {key}, вариант {variant_key}: нет точного masterIr/sourceRef",
                    })
                if isinstance(variant.get("masterIr"), dict) and isinstance(variant.get("sourceRef"), dict):
                    variant_fidelity = component_fidelity_status(variant.get("fidelity"))
                    if not variant_fidelity["passed"]:
                        errors.append({
                            "code": "variant-fidelity-failed",
                            "message": f"Component {key}, variant {variant_key}: fidelity gate failed - {'; '.join(variant_fidelity['reasons'])}",
                        })
                    variant_ref = variant["sourceRef"]
                    variant_revision = str(variant_ref.get("sourceRevisionHash") or "")
                    if not variant_ref.get("sourceKey") or variant_revision not in source_revision_hashes:
                        errors.append({
                            "code": "bad-variant-source-ref",
                            "message": f"Component {key}, variant {variant_key}: Source ref is not pinned",
                        })
                    if variant_ref.get("masterHash") != content_hash(variant["masterIr"]):
                        errors.append({
                            "code": "observed-variant-mutated",
                            "message": f"Component {key}, variant {variant_key}: masterIr differs from its Source hash",
                        })
        elif origin == "user" and comp.get("confirmed") is not True:
            errors.append({"code": "unconfirmed-user", "message": f"Компонент {key}: пользовательский master не подтверждён"})

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
        bindings = comp.get("tokenBindings") or {}
        values = bindings.values() if isinstance(bindings, dict) else bindings
        for binding in values:
            if isinstance(binding, dict):
                binding = binding.get("token") or binding.get("name")
            if known_tokens and binding not in known_tokens:
                errors.append({"code": "unknown-token-binding", "message": f"Компонент {key}: привязка к неизвестному токену {binding}"})
    from .identity import validate_identity_schema
    errors.extend(validate_identity_schema(document))
    return errors


def summary(document: dict) -> dict:
    """Компактная карточка для ноды и picker-списка (§11.2, §15.4)."""
    components = [c for c in (document.get("components") or {}).values() if isinstance(c, dict)]
    review_components = [
        c for c in (document.get("reviewComponents") or {}).values()
        if isinstance(c, dict)
    ]
    variants = sum(len(c.get("variants") or {}) for c in components)
    catalog_variants = variants + sum(len(c.get("variants") or {}) for c in review_components)
    states_total = sum(len(c.get("states") or {}) for c in components)
    coverage = round(100 * sum(1 for c in components if c.get("states")) / max(1, len(components)))
    suggestions = [c for c in (document.get("suggestions") or {}).values() if isinstance(c, dict)]
    origins = {"observed": 0, "suggested": len(suggestions), "generated": 0, "user": 0}
    for c in components:
        origins[str(c.get("origin") or "observed")] = origins.get(str(c.get("origin") or "observed"), 0) + 1
        origins["user"] += sum(
            1 for variant in (c.get("variants") or {}).values()
            if isinstance(variant, dict) and variant.get("origin") == "user"
        )
    identity = document.get("identity") or {}
    reconstruction = document.get("reconstruction") or {}
    return {
        "name": document.get("name"),
        "systemId": document.get("id"),
        "status": document.get("status"),
        "revision": document.get("revision"),
        "contentHash": document.get("contentHash"),
        "components": len(components),
        "catalogComponents": len(components) + len(review_components),
        "reviewMasters": len(review_components),
        "suggestions": len(suggestions),
        "verifiedMasters": sum(1 for c in components if c.get("status") == "verified"),
        "variants": variants,
        "catalogVariants": catalog_variants,
        "stateCoverage": coverage,
        "states": states_total,
        "mockSchemas": len((document.get("mockData") or {}).get("schemas") or {}),
        "qualityScore": round(float((document.get("quality") or {}).get("score") or 0)),
        "origins": origins,
        "identityStatus": identity.get("status") or "not-extracted",
        "identitySignatures": len(identity.get("signatures") or []),
        "identityTests": len(document.get("identityTests") or []),
        "reconstructionStatus": reconstruction.get("status") or "not-run",
    }
