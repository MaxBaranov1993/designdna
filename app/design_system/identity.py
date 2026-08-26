"""Deterministic Design Identity extraction and validation.

Design IR remains canonical.  Identity is a compact, explainable layer derived
from captured IR and foundations; every non-user field carries provenance and
confidence so inferred taste never masquerades as a measured fact.
"""
from __future__ import annotations

import copy
import math
import re
from collections import Counter
from statistics import median
from typing import Any, Iterable

IDENTITY_VERSION = "design-identity/1.0"


def fact(value: Any, origin: str, confidence: float, *, method: str = "", confirmed: bool = False) -> dict:
    out = {
        "value": value,
        "provenance": origin,
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "confirmed": bool(confirmed or origin == "user"),
    }
    if method:
        out["method"] = method
    return out


def empty_identity() -> dict:
    return {
        "version": IDENTITY_VERSION,
        "status": "not-extracted",
        "soul": {"oneLine": fact("", "default", 0.0)},
        "relationships": {},
        "paletteCoverage": {"roles": {}, "method": "unavailable", "confidence": 0.0},
        "surface": {},
        "signatures": [],
        "signatureException": None,
        "bans": [],
        "archetypes": [],
        "motion": {},
        "voice": {},
        "visualReferences": [],
        "uncertainty": [],
    }


def empty_reconstruction() -> dict:
    return {
        "status": "not-run",
        "sourceProof": None,
        "transferProof": None,
        "updatedAt": None,
    }


def ensure_identity(document: dict) -> dict:
    """In-place forward migration for legacy 1.0 drafts/revisions."""
    if not isinstance(document, dict):
        return document
    document.setdefault("identity", empty_identity())
    document.setdefault("identityTests", [])
    document.setdefault("reconstruction", empty_reconstruction())
    document.setdefault("compiledProfiles", {})
    if str(document.get("schemaVersion") or "") == "design-system/1.0":
        document["schemaVersion"] = "design-system/1.1"
    return document


def _walk(node: dict) -> Iterable[dict]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children") or []:
        if isinstance(child, dict):
            yield from _walk(child)


def _irs_from_blocks(blocks: list) -> list[dict]:
    return [b.get("ir") for b in blocks or [] if isinstance(b, dict) and isinstance(b.get("ir"), dict)]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _hex(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value[:7] if re.fullmatch(r"#[0-9a-f]{6}(?:[0-9a-f]{2})?", value) else None


def _role_for_color(color: str, foundations: dict) -> str:
    semantic = ((foundations.get("colors") or {}).get("semantic") or {})
    for role, value in semantic.items():
        if _hex(value) == color:
            return str(role)
    return color


def measure_ir(ir: dict, foundations: dict | None = None) -> dict:
    """Measure only values available in IR; missing geometry stays missing."""
    foundations = foundations or {}
    font_sizes: list[float] = []
    radii: list[float] = []
    families: list[str] = []
    shadows = 0
    styled = 0
    nodes = 0
    palette_area: Counter[str] = Counter()
    palette_frequency: Counter[str] = Counter()
    total_area = 0.0
    top_level_count = 0

    for section in ir.get("tree") or []:
        if not isinstance(section, dict):
            continue
        top_level_count += 1
        style = section.get("style") if isinstance(section.get("style"), dict) else {}
        frame = section.get("frame") if isinstance(section.get("frame"), dict) else {}
        color = _hex(style.get("background") or style.get("backgroundColor") or style.get("fill"))
        width, height = _number(frame.get("width")), _number(frame.get("height"))
        area = (width * height) if width and height and width > 0 and height > 0 else 0.0
        if color and area:
            palette_area[_role_for_color(color, foundations)] += area
            total_area += area
        for node in _walk(section):
            nodes += 1
            node_style = node.get("style") if isinstance(node.get("style"), dict) else {}
            if node_style:
                styled += 1
            size = _number(node_style.get("fontSize"))
            if size and 5 <= size <= 300:
                font_sizes.append(size)
            radius = _number(node_style.get("borderRadius"))
            if radius is not None and 0 <= radius <= 999:
                radii.append(radius)
            family = str(node_style.get("fontFamily") or "").split(",")[0].strip(" '\"")
            if family:
                families.append(family)
            if node_style.get("boxShadow") or node_style.get("shadow"):
                shadows += 1
            for key in ("background", "backgroundColor", "fill", "color", "borderColor"):
                found = _hex(node_style.get(key))
                if found:
                    palette_frequency[_role_for_color(found, foundations)] += 1

    coverage_method = "top-level-box-area" if total_area > 0 else "style-frequency-fallback"
    coverage_source = palette_area if total_area > 0 else palette_frequency
    coverage_total = total_area if total_area > 0 else float(sum(coverage_source.values()))
    coverage = {
        role: round(float(value) / max(1.0, coverage_total), 4)
        for role, value in coverage_source.most_common(12)
    }
    sizes = sorted(set(round(v, 2) for v in font_sizes))
    body_candidates = [v for v in font_sizes if 12 <= v <= 20]
    body = median(body_candidates) if body_candidates else (median(font_sizes) if font_sizes else None)
    display = max(font_sizes) if font_sizes else None
    return {
        "nodeCount": nodes,
        "styledNodeCount": styled,
        "topLevelCount": top_level_count,
        "fontSizes": sizes,
        "fontSizeCount": len(sizes),
        "bodySize": round(body, 2) if body else None,
        "displaySize": round(display, 2) if display else None,
        "displayBodyRatio": round(display / body, 3) if display and body else None,
        "families": list(dict.fromkeys(families))[:8],
        "radii": sorted(set(round(v, 2) for v in radii))[:12],
        "shadowCount": shadows,
        "paletteCoverage": coverage,
        "paletteCoverageMethod": coverage_method,
        "paletteCoverageConfidence": 0.86 if total_area > 0 and top_level_count >= 2 else (0.62 if coverage else 0.0),
    }


def _aggregate_measurements(irs: list[dict], foundations: dict) -> dict:
    measured = [measure_ir(ir, foundations) for ir in irs]
    if not measured:
        return measure_ir({}, foundations)
    sizes = sorted({v for item in measured for v in item["fontSizes"]})
    bodies = [item["bodySize"] for item in measured if item["bodySize"]]
    displays = [item["displaySize"] for item in measured if item["displaySize"]]
    coverage: Counter[str] = Counter()
    for item in measured:
        for role, value in item["paletteCoverage"].items():
            coverage[role] += float(value)
    samples = max(1, len(measured))
    roles = {role: round(value / samples, 4) for role, value in coverage.most_common(12)}
    body = median(bodies) if bodies else None
    display = max(displays) if displays else None
    return {
        "nodeCount": sum(item["nodeCount"] for item in measured),
        "styledNodeCount": sum(item["styledNodeCount"] for item in measured),
        "fontSizes": sizes,
        "fontSizeCount": len(sizes),
        "bodySize": round(body, 2) if body else None,
        "displaySize": round(display, 2) if display else None,
        "displayBodyRatio": round(display / body, 3) if display and body else None,
        "families": list(dict.fromkeys(v for item in measured for v in item["families"]))[:8],
        "radii": sorted({v for item in measured for v in item["radii"]})[:12],
        "shadowCount": sum(item["shadowCount"] for item in measured),
        "paletteCoverage": roles,
        "paletteCoverageMethod": "multi-block-" + measured[0]["paletteCoverageMethod"],
        "paletteCoverageConfidence": round(sum(item["paletteCoverageConfidence"] for item in measured) / samples, 3),
    }


def _archetypes(blocks: list) -> list[dict]:
    counts: Counter[str] = Counter()
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        key = str(block.get("kind") or block.get("name") or "section").strip().lower()
        key = re.sub(r"[^a-z0-9а-яё]+", "-", key).strip("-") or "section"
        counts[key] += 1
    return [
        {
            "id": f"archetype-{key}",
            "name": key.replace("-", " ").title(),
            "structure": [key],
            "provenance": "measured",
            "confidence": 0.9 if count > 1 else 0.72,
            "confirmed": False,
        }
        for key, count in counts.most_common(8)
    ]


def build_identity_tests(identity: dict, measurements: dict) -> list[dict]:
    tests: list[dict] = []
    ratio = measurements.get("displayBodyRatio")
    if ratio:
        tests.append({
            "id": "identity.type.display-body-ratio", "kind": "font-ratio", "severity": "soft",
            "description": "Сохранить характерный контраст display/body",
            "expected": {"min": round(max(1.1, ratio * 0.82), 2), "max": round(ratio * 1.22, 2)},
            "provenance": "measured", "confidence": 0.82,
        })
    count = measurements.get("fontSizeCount") or 0
    if count:
        tests.append({
            "id": "identity.type.scale-size-count", "kind": "font-size-count", "severity": "soft",
            "description": "Не раздувать типографическую шкалу",
            "expected": {"min": max(2, count - 2), "max": max(3, count + 2)},
            "provenance": "measured", "confidence": 0.78,
        })
    coverage = (identity.get("paletteCoverage") or {}).get("roles") or {}
    if coverage:
        top = dict(list(sorted(coverage.items(), key=lambda pair: pair[1], reverse=True))[:4])
        tests.append({
            "id": "identity.palette.role-coverage", "kind": "palette-coverage", "severity": "soft",
            "description": "Сохранить иерархию цветовых ролей, а не только hex-палитру",
            "expected": {"roles": top, "tolerance": 0.16},
            "provenance": "measured", "confidence": (identity.get("paletteCoverage") or {}).get("confidence", 0.6),
        })
    if measurements.get("styledNodeCount", 0) >= 20 and measurements.get("shadowCount") == 0:
        tests.append({
            "id": "identity.surface.no-shadow", "kind": "absent-style", "severity": "hard",
            "description": "Не использовать тени: в источнике они устойчиво отсутствуют",
            "expected": {"property": "shadow", "max": 0},
            "provenance": "measured", "confidence": 0.94,
        })
    return tests


def extract_identity(blocks: list, foundations: dict, *, patterns: dict | None = None) -> tuple[dict, list[dict], dict]:
    irs = _irs_from_blocks(blocks)
    measured = _aggregate_measurements(irs, foundations)
    identity = empty_identity()
    identity["status"] = "extracted" if irs else "not-extracted"
    coverage = measured.get("paletteCoverage") or {}
    ratio = measured.get("displayBodyRatio")
    radius_values = measured.get("radii") or (foundations.get("radii") or [])
    shadows_absent = measured.get("shadowCount") == 0

    traits: list[str] = []
    if ratio and ratio >= 2.2:
        traits.append("выразительный контраст крупной и основной типографики")
    if coverage:
        dominant = next(iter(coverage))
        traits.append(f"доминирующая роль {dominant} с дозированными акцентами")
    if shadows_absent:
        traits.append("плоские поверхности без декоративных теней")
    if radius_values:
        traits.append("последовательная геометрия скруглений")
    one_line = "; ".join(traits[:3]) or "Сдержанная система, построенная на токенах и повторяемой композиционной иерархии"
    identity["soul"]["oneLine"] = fact(one_line, "inferred", 0.72 if irs else 0.35, method="deterministic-trait-summary")
    identity["relationships"] = {
        "displayToBody": fact(ratio, "measured", 0.86, method="max-display/median-body") if ratio else fact(None, "default", 0.0),
        "fontSizeCount": fact(measured.get("fontSizeCount"), "measured", 0.84, method="distinct-ir-font-sizes"),
    }
    identity["paletteCoverage"] = {
        "roles": coverage,
        "method": measured.get("paletteCoverageMethod"),
        "confidence": measured.get("paletteCoverageConfidence", 0.0),
        "provenance": "measured" if coverage else "default",
    }
    identity["surface"] = {
        "radii": fact(radius_values, "measured" if measured.get("radii") else "inferred", 0.8 if radius_values else 0.2, method="distinct-border-radius"),
        "shadows": fact("none" if shadows_absent else "present", "measured", 0.92 if measured.get("styledNodeCount", 0) >= 20 else 0.68, method="style-property-scan"),
    }
    signatures: list[dict] = []
    if ratio:
        signatures.append({"id": "sig-type-contrast", "name": "Display/body contrast", "rule": f"Display около {ratio:.2f}× body", "provenance": "measured", "confidence": 0.86, "confirmed": False})
    if coverage:
        role, value = next(iter(coverage.items()))
        signatures.append({"id": "sig-palette-dominance", "name": "Palette dominance", "rule": f"Роль {role} занимает около {round(value * 100)}% измеренной поверхности", "provenance": "measured", "confidence": measured.get("paletteCoverageConfidence", 0.6), "confirmed": False})
    signatures.append({"id": "sig-token-discipline", "name": "Token discipline", "rule": "Цвет, типографика, интервалы и радиусы берутся из foundations", "provenance": "inferred", "confidence": 0.72, "confirmed": False})
    if shadows_absent:
        signatures.append({"id": "sig-flat-surface", "name": "Flat surface", "rule": "Иерархия строится без декоративных теней", "provenance": "measured", "confidence": 0.92 if measured.get("styledNodeCount", 0) >= 20 else 0.68, "confirmed": False})
    if radius_values:
        signatures.append({"id": "sig-radius-system", "name": "Radius system", "rule": "Использовать только наблюдаемую шкалу скруглений", "provenance": "measured" if measured.get("radii") else "inferred", "confidence": 0.8, "confirmed": False})
    identity["signatures"] = signatures[:9]
    identity["bans"] = []
    if shadows_absent:
        confidence = 0.94 if measured.get("styledNodeCount", 0) >= 20 else 0.68
        identity["bans"].append({"id": "ban-decorative-shadows", "rule": "Не добавлять декоративные тени", "severity": "hard" if confidence >= 0.9 else "soft", "provenance": "measured", "confidence": confidence, "confirmed": False})
    identity["archetypes"] = _archetypes(blocks)
    identity["motion"] = {"character": fact("quiet and functional", "default", 0.25), "reducedMotionRequired": True}
    identity["voice"] = {"density": fact("concise", "inferred", 0.45), "case": fact("sentence", "inferred", 0.45)}
    identity["uncertainty"] = [
        {"field": "motion", "reason": "Статический Source не доказывает характер motion", "requiresConfirmation": True},
        {"field": "voice", "reason": "Контента недостаточно для надёжного brand voice", "requiresConfirmation": True},
    ]
    tests = build_identity_tests(identity, measured)
    return identity, tests, measured


def _result(test: dict, passed: bool, actual: Any, message: str) -> dict:
    return {
        "id": test.get("id"), "severity": test.get("severity", "soft"),
        "passed": bool(passed), "actual": actual, "expected": test.get("expected"),
        "message": message,
    }


def evaluate_identity(ir: dict, identity: dict, tests: list[dict], foundations: dict | None = None) -> dict:
    measured = measure_ir(ir, foundations or {})
    results: list[dict] = []
    for test in tests or []:
        kind = test.get("kind")
        expected = test.get("expected") or {}
        if kind == "font-ratio":
            actual = measured.get("displayBodyRatio")
            passed = actual is not None and float(expected.get("min", 0)) <= actual <= float(expected.get("max", 999))
            results.append(_result(test, passed, actual, "Соотношение display/body"))
        elif kind == "font-size-count":
            actual = measured.get("fontSizeCount", 0)
            passed = int(expected.get("min", 0)) <= actual <= int(expected.get("max", 999))
            results.append(_result(test, passed, actual, "Количество размеров шрифта"))
        elif kind == "absent-style" and expected.get("property") == "shadow":
            actual = measured.get("shadowCount", 0)
            results.append(_result(test, actual <= int(expected.get("max", 0)), actual, "Количество теней"))
        elif kind == "palette-coverage":
            actual_roles = measured.get("paletteCoverage") or {}
            tolerance = float(expected.get("tolerance", 0.16))
            deltas = {role: round(abs(float(actual_roles.get(role, 0)) - float(value)), 4) for role, value in (expected.get("roles") or {}).items()}
            passed = bool(deltas) and max(deltas.values()) <= tolerance
            results.append(_result(test, passed, {"roles": actual_roles, "deltas": deltas}, "Покрытие цветовых ролей"))
        else:
            results.append(_result(test, True, None, "Advisory test is not machine-enforced"))
    hard = [item for item in results if not item["passed"] and item["severity"] == "hard"]
    soft = [item for item in results if not item["passed"] and item["severity"] == "soft"]
    enforced = [item for item in results if item["actual"] is not None]
    score = round(100 * sum(1 for item in enforced if item["passed"]) / max(1, len(enforced)))
    return {
        "passed": not hard,
        "score": score,
        "hardFailures": hard,
        "softFailures": soft,
        "results": results,
        "measurements": measured,
    }


def validate_identity_schema(document: dict) -> list[dict]:
    identity = document.get("identity") or {}
    if not identity or identity.get("status") == "not-extracted":
        return []
    errors: list[dict] = []
    signatures = identity.get("signatures") or []
    if not 3 <= len(signatures) <= 9:
        errors.append({"code": "identity-signature-count", "message": "Identity должен содержать от 3 до 9 signature-правил"})
    ids: set[str] = set()
    for item in signatures + (identity.get("bans") or []) + (document.get("identityTests") or []):
        item_id = str(item.get("id") or "") if isinstance(item, dict) else ""
        if not item_id:
            errors.append({"code": "identity-missing-id", "message": "У identity-правила отсутствует стабильный id"})
        elif item_id in ids:
            errors.append({"code": "identity-duplicate-id", "message": f"Дублируется identity id: {item_id}"})
        ids.add(item_id)
    for ban in identity.get("bans") or []:
        if ban.get("severity") == "hard" and float(ban.get("confidence") or 0) < 0.9 and not ban.get("confirmed"):
            errors.append({"code": "identity-unconfirmed-hard-ban", "message": f"Hard-ban {ban.get('id')} требует confidence ≥ 0.9 или подтверждения пользователя"})
    return errors


def reconstruction_report(document: dict, candidate_ir: dict, *, proof: str = "source") -> dict:
    ensure_identity(document)
    evaluation = evaluate_identity(candidate_ir, document.get("identity") or {}, document.get("identityTests") or [], document.get("foundations") or {})
    return {
        "proof": "transfer" if proof == "transfer" else "source",
        "status": "passed" if evaluation["passed"] and evaluation["score"] >= 70 else "failed",
        "identityScore": evaluation["score"],
        "hardFailures": evaluation["hardFailures"],
        "softFailures": evaluation["softFailures"],
        "measurements": evaluation["measurements"],
    }

