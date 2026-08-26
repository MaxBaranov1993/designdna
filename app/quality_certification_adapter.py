"""Fail-closed adapter from DesignDNA reports to Quality Certified."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from quality_certificate import certify_quality

MAX_BYTES = 1_048_576
MAX_ITEMS = 1_000
MIN_OVERRIDE_REASON = 8
MAX_OVERRIDE_REASON = 500

ENGINE_GATES = (
    "schemaErrors", "lockViolations", "outOfScopeMutations", "lostSourceKeys",
    "lostComponentIdentities", "hierarchyErrors", "overflow", "clipping",
    "collisions", "brokenAssets", "placeholderContent", "forbiddenTokens",
    "forbiddenComponents", "forbiddenFonts", "forbiddenColors", "contrastBlockers",
    "accessibilityBlockers", "structuralMutations",
)
EVIDENCE_GATES = (
    "schemaErrors", "lostSourceKeys", "lostComponentIdentities", "hierarchyErrors",
    "brokenAssets", "placeholderContent", "forbiddenTokens", "forbiddenComponents",
    "forbiddenFonts", "forbiddenColors", "accessibilityBlockers", "clipping", "collisions",
)
VIEWPORT_GATES = ("overflow", "clipping", "collisions", "contrastBlockers", "accessibilityBlockers")
_SENSITIVE_EXACT = {
    "prompt", "rawprompt", "password", "secret", "credentials", "authorization", "cookie",
    "asset", "assets", "rawasset", "rawassets", "designir", "ir",
}
_SENSITIVE_SUFFIXES = (
    "apikey", "accesstoken", "refreshtoken", "authtoken", "bearertoken",
    "clientsecret", "privatekey",
)
_CODE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_PATH_RE = re.compile(r"[a-zA-Z0-9_./:\[\]-]{1,512}\Z")


class AdapterError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sensitive(key: str) -> bool:
    key = "".join(c for c in key.lower() if c.isalnum())
    return key in _SENSITIVE_EXACT or any(key.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def _guard(value: Any) -> None:
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 20_000 or depth > 24:
            raise AdapterError("input exceeds structural limits")
        if item is None or isinstance(item, (bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise AdapterError("non-finite number")
            return
        if isinstance(item, str):
            if len(item) > 16_384:
                raise AdapterError("oversized string")
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise AdapterError("non-string key")
                if _sensitive(key):
                    raise AdapterError("raw prompts and credentials are not accepted")
                walk(child, depth + 1)
            return
        raise AdapterError("unsupported input value")

    walk(value, 0)
    if len(_canonical(value).encode("utf-8")) > MAX_BYTES:
        raise AdapterError("input exceeds encoded size limit")


def _items(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise AdapterError(f"{label} must be a bounded list")
    return value


def _code(value: Any, fallback: str) -> str:
    value = _CODE_RE.sub("-", str(value or fallback)).strip("-.")[:120]
    return value or fallback


def _issue(source: str, value: Any, fallback: str = "failure") -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    result = {
        "code": f"{source}.{_code(raw.get('rule') or raw.get('code') or raw.get('category'), fallback)}",
        "message": f"Blocking evidence was reported by {source}.",
    }
    path = str(raw.get("path") or "")
    if _PATH_RE.fullmatch(path):
        result["path"] = path
    return result


def _warning(source: str, value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    result = {
        "code": f"{source}.{_code(raw.get('rule') or raw.get('code') or raw.get('category'), 'warning')}",
        "message": f"Non-blocking evidence was reported by {source}.",
        "blocking": False,
        "severity": "warning",
    }
    path = str(raw.get("path") or "")
    if _PATH_RE.fullmatch(path):
        result["path"] = path
    return result


def _missing(checks: dict[str, list[dict[str, Any]]], source: str, gate: str = "schemaErrors") -> None:
    checks[gate].append({
        "code": f"evidence.missing.{source}",
        "message": "Required certification evidence is missing.",
    })


def _quality_target(rule: str) -> str:
    return {
        "frame-overflow": "overflow", "contrast": "contrastBlockers",
        "fonts-limit": "forbiddenFonts", "image-alt": "accessibilityBlockers",
        "tap-target": "accessibilityBlockers", "min-font-size": "accessibilityBlockers",
        "single-h1": "hierarchyErrors", "button-text": "placeholderContent",
        "heading-limits": "schemaErrors", "grid-8": "hierarchyErrors",
    }.get(rule, "schemaErrors")


def _viewport_target(rule: str) -> str:
    rule = rule.lower()
    if "overflow" in rule:
        return "overflow"
    if "clip" in rule:
        return "clipping"
    if "collision" in rule or "overlap" in rule:
        return "collisions"
    if "contrast" in rule:
        return "contrastBlockers"
    if any(word in rule for word in ("access", "tap", "focus", "alt")):
        return "accessibilityBlockers"
    return "clipping"


def _malformed() -> dict[str, Any]:
    certificate = certify_quality({})
    return {"certificate": certificate, "decision": {
        "applyAllowed": False, "exportAllowed": False, "overrideRequired": True,
        "certificationStatus": "blocked",
        "override": {"used": False, "error": "Adapter input could not be validated."},
    }}


def certify_from_reports(request: Any) -> dict[str, Any]:
    """Convert current reports, certify them, and return enforcement policy."""
    try:
        _guard(request)
        if not isinstance(request, dict):
            raise AdapterError("request must be an object")
        allowed = {
            "designIrHash", "designSystem", "assetHashes", "qualityGate", "visualJudge",
            "lockReport", "scopeReport", "viewportReport", "evidence", "override",
        }
        if not {"designIrHash", "designSystem", "assetHashes"}.issubset(request):
            raise AdapterError("hash references are missing")
        if not set(request).issubset(allowed):
            raise AdapterError("unknown fields")

        checks = {gate: [] for gate in ENGINE_GATES}
        warnings: list[dict[str, Any]] = []

        gate = request.get("qualityGate")
        if not isinstance(gate, dict) or not isinstance(gate.get("passed"), bool):
            _missing(checks, "qualityGate")
        else:
            violations = _items(gate.get("violations"), "qualityGate.violations")
            if gate["passed"] != (not violations):
                checks["schemaErrors"].append(_issue("qualityGate", {}, "inconsistent-result"))
            for value in violations:
                rule = _code(value.get("rule") if isinstance(value, dict) else "", "unknown")
                checks[_quality_target(rule)].append(_issue("qualityGate", value, "unknown"))

        visual = request.get("visualJudge")
        score: float | int = 0
        critical: dict[str, Any] = {"visualJudge": 0}
        if not isinstance(visual, dict) or isinstance(visual.get("score"), bool) or not isinstance(visual.get("score"), (int, float)):
            _missing(checks, "visualJudge")
        else:
            score = visual["score"]
            critical = visual.get("criticalSubscores") or {"visualJudge": score}
            if not isinstance(critical, dict) or not critical:
                _missing(checks, "visualJudgeCriticalSubscores")
                critical = {"visualJudge": 0}
            issues = _items(visual.get("issues"), "visualJudge.issues")
            if visual.get("verdict") not in {"pass", "needs_repair"}:
                checks["schemaErrors"].append(_issue("visualJudge", {}, "invalid-verdict"))
            if visual.get("verdict") == "pass" and any(
                isinstance(item, dict) and item.get("severity") in {"critical", "major"} for item in issues
            ):
                checks["schemaErrors"].append(_issue("visualJudge", {}, "inconsistent-verdict"))
            for item in issues:
                if isinstance(item, dict) and item.get("severity") == "minor":
                    warnings.append(_warning("visualJudge", item))
                else:
                    category = str(item.get("category") if isinstance(item, dict) else "")
                    target = "accessibilityBlockers" if category == "accessibility" else (
                        "placeholderContent" if category == "content" else "hierarchyErrors"
                    )
                    checks[target].append(_issue("visualJudge", item, "major-issue"))

        preserved_locks: list[Any] = []
        lock = request.get("lockReport")
        if not isinstance(lock, dict) or lock.get("checked") is not True:
            _missing(checks, "lockReport", "lockViolations")
        else:
            for item in _items(lock.get("violations"), "lockReport.violations"):
                checks["lockViolations"].append(_issue("lockReport", item, "violation"))
            preserved_locks = _items(lock.get("preservedLocks"), "lockReport.preservedLocks")

        changed_facets: list[Any] = []
        style_only = True
        scope = request.get("scopeReport")
        if not isinstance(scope, dict) or scope.get("checked") is not True:
            _missing(checks, "scopeReport", "outOfScopeMutations")
        else:
            for item in _items(scope.get("violations"), "scopeReport.violations"):
                checks["outOfScopeMutations"].append(_issue("scopeReport", item, "violation"))
            for item in _items(scope.get("structuralMutations"), "scopeReport.structuralMutations"):
                checks["structuralMutations"].append(_issue("scopeReport", item, "structural-mutation"))
            changed_facets = _items(scope.get("changedFacets"), "scopeReport.changedFacets")
            style_only = scope.get("styleOnly")
            if not isinstance(style_only, bool):
                _missing(checks, "scopeReportStyleOnly", "outOfScopeMutations")
                style_only = True

        evidence = request.get("evidence")
        for evidence_gate in EVIDENCE_GATES:
            if not isinstance(evidence, dict) or evidence_gate not in evidence:
                _missing(checks, f"evidence.{evidence_gate}", evidence_gate)
            else:
                for item in _items(evidence[evidence_gate], f"evidence.{evidence_gate}"):
                    checks[evidence_gate].append(_issue("evidence", item, evidence_gate))

        required_viewports: list[Any] = []
        viewports: dict[str, Any] = {}
        viewport_report = request.get("viewportReport")
        if not isinstance(viewport_report, dict):
            _missing(checks, "viewportReport")
            required_viewports = ["desktop"]
        else:
            required_viewports = _items(viewport_report.get("required"), "viewportReport.required")
            results = viewport_report.get("results")
            if not required_viewports or not isinstance(results, dict):
                _missing(checks, "viewportReport")
                required_viewports = required_viewports or ["desktop"]
                results = results if isinstance(results, dict) else {}
            for name, viewport in results.items():
                if not isinstance(viewport, dict) or isinstance(viewport.get("score"), bool) or not isinstance(viewport.get("score"), (int, float)):
                    continue
                viewport_checks = {gate_name: [] for gate_name in VIEWPORT_GATES}
                for item in _items(viewport.get("violations"), f"viewport.{name}.violations"):
                    rule = _code(item.get("rule") if isinstance(item, dict) else "", "unknown")
                    viewport_checks[_viewport_target(rule)].append(_issue("viewportReport", item))
                viewport_warnings = [_warning("viewportReport", item) for item in _items(
                    viewport.get("warnings"), f"viewport.{name}.warnings"
                )]
                viewports[name] = {"score": viewport["score"], "checks": viewport_checks, "warnings": viewport_warnings}

        certificate = certify_quality({
            "designIrHash": request["designIrHash"],
            "designSystem": request["designSystem"],
            "assetHashes": request["assetHashes"],
            "report": {
                "score": score, "criticalSubscores": critical,
                "requiredViewports": required_viewports, "viewports": viewports,
                "checks": checks, "warnings": warnings,
                "preservedLocks": preserved_locks, "changedFacets": changed_facets,
                "styleOnly": style_only,
            },
        })

        malformed = any(item.get("code") == "input.malformed" for item in certificate["blockingIssues"])
        override = request.get("override")
        audit = None
        override_used = False
        if override is not None:
            if not isinstance(override, dict) or set(override) != {"requested", "reason"} or override.get("requested") is not True:
                audit = {"used": False, "error": "Override request is malformed."}
            else:
                reason = override.get("reason")
                if not isinstance(reason, str) or not MIN_OVERRIDE_REASON <= len(reason.strip()) <= MAX_OVERRIDE_REASON:
                    audit = {"used": False, "error": "Override reason must be bounded and explicit."}
                elif certificate["status"] != "blocked":
                    audit = {"used": False, "error": "Override is unnecessary for a certified result."}
                elif malformed:
                    audit = {"used": False, "error": "Malformed certification input cannot be overridden."}
                else:
                    reason = reason.strip()
                    override_used = True
                    audit = {"used": True, "reason": reason, "reasonHash": "sha256:" + hashlib.sha256(reason.encode()).hexdigest()}

        certified = certificate["status"] in {"certified", "certified_with_warnings"}
        action_allowed = certified or override_used
        return {"certificate": certificate, "decision": {
            "applyAllowed": action_allowed,
            "exportAllowed": action_allowed,
            "overrideRequired": certificate["status"] == "blocked" and not override_used,
            "certificationStatus": certificate["status"],
            "override": audit,
        }}
    except (AdapterError, TypeError, ValueError, OverflowError):
        return _malformed()


adapt_quality_certification = certify_from_reports
