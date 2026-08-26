"""Deterministic, fail-closed Quality Certified decisions.

The public entry point is :func:`certify_quality`.  It accepts a canonical
request with this shape::

    {
        "designIrHash": "sha256:...",
        "designSystem": {"id": "...", "revision": 1, "contentHash": "sha256:..."},
        "assetHashes": ["sha256:..."],
        "report": {
            "score": 90,
            "criticalSubscores": {"composition": 88},
            "requiredViewports": ["desktop", "mobile"],
            "viewports": {
                "desktop": {"score": 90, "checks": {...}, "warnings": []},
                "mobile": {"score": 88, "checks": {...}, "warnings": []},
            },
            "checks": {...},
            "warnings": [],
            "preservedLocks": ["brand.colors"],
            "changedFacets": ["spacing"],
            "styleOnly": True,
        },
    }

Check entries are small objects with ``code``, ``message`` and optional
``path``.  Warning entries additionally require ``blocking: false`` and a
``severity`` of ``info`` or ``warning``.  The module intentionally stores no
input report, prompt, credentials, or arbitrary metadata in its result.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


ENGINE_VERSION = "quality-certificate/1.0.0"
CERTIFIED_SCORE = 85
CRITICAL_SUBSCORE = 75

MAX_INPUT_BYTES = 1_048_576
MAX_DEPTH = 24
MAX_NODES = 20_000
MAX_STRING_LENGTH = 16_384
MAX_ISSUES_PER_GATE = 1_000
MAX_ASSETS = 4_096
MAX_VIEWPORTS = 32

_GLOBAL_GATES = (
    "schemaErrors",
    "lockViolations",
    "outOfScopeMutations",
    "lostSourceKeys",
    "lostComponentIdentities",
    "hierarchyErrors",
    "overflow",
    "clipping",
    "collisions",
    "brokenAssets",
    "placeholderContent",
    "forbiddenTokens",
    "forbiddenComponents",
    "forbiddenFonts",
    "forbiddenColors",
    "contrastBlockers",
    "accessibilityBlockers",
    "structuralMutations",
)
_VIEWPORT_GATES = (
    "overflow",
    "clipping",
    "collisions",
    "contrastBlockers",
    "accessibilityBlockers",
)
_SENSITIVE_KEYS = {
    "apikey",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "prompt",
    "rawprompt",
    "secret",
}
_SENSITIVE_SUFFIXES = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "privatekey",
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class _Malformed(ValueError):
    """Internal validation error whose text never contains input values."""


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return normalized in _SENSITIVE_KEYS or any(normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _check_bounds(value: Any) -> None:
    nodes = 0
    text_units = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes, text_units
        nodes += 1
        if nodes > MAX_NODES:
            raise _Malformed("input exceeds node limit")
        if depth > MAX_DEPTH:
            raise _Malformed("input exceeds nesting limit")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, (int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                raise _Malformed("input contains a non-finite number")
            return
        if isinstance(item, str):
            if len(item) > MAX_STRING_LENGTH:
                raise _Malformed("input contains an oversized string")
            text_units += len(item)
            if text_units > MAX_INPUT_BYTES:
                raise _Malformed("input exceeds text limit")
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise _Malformed("object keys must be strings")
                if len(key) > 256:
                    raise _Malformed("input contains an oversized key")
                if _is_sensitive_key(key):
                    raise _Malformed("sensitive or raw prompt fields are not accepted")
                text_units += len(key)
                walk(child, depth + 1)
            return
        raise _Malformed("input contains an unsupported value type")

    walk(value, 0)
    # This exact encoding is also what hashing uses.  It provides a final byte
    # bound in addition to the allocation-safe structural checks above.
    if len(_canonical_json(value).encode("utf-8")) > MAX_INPUT_BYTES:
        raise _Malformed("input exceeds encoded size limit")


def _expect_keys(value: dict[str, Any], required: set[str], *, optional: set[str] | None = None) -> None:
    optional = optional or set()
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise _Malformed("input object has missing or unknown fields")


def _short_string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise _Malformed("expected a non-empty bounded string")
    return value.strip()


def _sha256(value: Any) -> str:
    value = _short_string(value)
    if _SHA256_RE.fullmatch(value) is None:
        raise _Malformed("expected a normalized sha256 digest")
    return value


def _score(value: Any) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Malformed("score must be numeric")
    if not math.isfinite(float(value)) or value < 0 or value > 100:
        raise _Malformed("score must be between zero and one hundred")
    return value


def _normalize_issue(value: Any, *, warning: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _Malformed("issue must be an object")
    required = {"code", "message", "blocking", "severity"} if warning else {"code", "message"}
    optional = {"path"}
    _expect_keys(value, required, optional=optional)
    issue = {"code": _short_string(value["code"]), "message": _short_string(value["message"])}
    if "path" in value:
        issue["path"] = _short_string(value["path"])
    if warning:
        if value["blocking"] is not False or value["severity"] not in {"info", "warning"}:
            raise _Malformed("warnings must be explicitly non-blocking")
        issue["blocking"] = False
        issue["severity"] = value["severity"]
    return issue


def _normalize_issues(value: Any, *, warning: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_ISSUES_PER_GATE:
        raise _Malformed("issue collection is invalid or too large")
    items = [_normalize_issue(item, warning=warning) for item in value]
    return sorted(items, key=_canonical_json)


def _normalize_checks(value: Any, gates: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise _Malformed("checks must be an object")
    _expect_keys(value, set(gates))
    return {gate: _normalize_issues(value[gate]) for gate in gates}


def _normalize_string_set(value: Any, *, maximum: int = 1_000) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _Malformed("string collection is invalid or too large")
    items = [_short_string(item) for item in value]
    if len(items) != len(set(items)):
        raise _Malformed("string collection contains duplicates")
    return sorted(items)


def _normalize_request(request: Any) -> dict[str, Any]:
    _check_bounds(request)
    if not isinstance(request, dict):
        raise _Malformed("request must be an object")
    _expect_keys(request, {"designIrHash", "designSystem", "assetHashes", "report"})

    design_system = request["designSystem"]
    if not isinstance(design_system, dict):
        raise _Malformed("design system reference must be an object")
    _expect_keys(design_system, {"id", "revision", "contentHash"})
    revision = design_system["revision"]
    if isinstance(revision, bool) or not isinstance(revision, (str, int)):
        raise _Malformed("design system revision must be a string or integer")
    if isinstance(revision, str):
        revision = _short_string(revision)
    elif revision < 0:
        raise _Malformed("design system revision cannot be negative")

    report = request["report"]
    if not isinstance(report, dict):
        raise _Malformed("report must be an object")
    _expect_keys(report, {
        "score", "criticalSubscores", "requiredViewports", "viewports", "checks",
        "warnings", "preservedLocks", "changedFacets", "styleOnly",
    })
    if not isinstance(report["styleOnly"], bool):
        raise _Malformed("styleOnly must be boolean")

    critical = report["criticalSubscores"]
    if not isinstance(critical, dict) or not critical or len(critical) > 64:
        raise _Malformed("critical subscores must be a non-empty object")
    critical_normalized = {_short_string(name): _score(value) for name, value in critical.items()}

    required_viewports = _normalize_string_set(report["requiredViewports"], maximum=MAX_VIEWPORTS)
    if not required_viewports:
        raise _Malformed("at least one required viewport is needed")
    raw_viewports = report["viewports"]
    if not isinstance(raw_viewports, dict) or len(raw_viewports) > MAX_VIEWPORTS:
        raise _Malformed("viewports must be a bounded object")

    viewports: dict[str, Any] = {}
    for name, viewport in raw_viewports.items():
        name = _short_string(name)
        if not isinstance(viewport, dict):
            raise _Malformed("viewport report must be an object")
        _expect_keys(viewport, {"score", "checks", "warnings"})
        viewports[name] = {
            "score": _score(viewport["score"]),
            "checks": _normalize_checks(viewport["checks"], _VIEWPORT_GATES),
            "warnings": _normalize_issues(viewport["warnings"], warning=True),
        }

    return {
        "designIrHash": _sha256(request["designIrHash"]),
        "designSystem": {
            "id": _short_string(design_system["id"]),
            "revision": revision,
            "contentHash": _sha256(design_system["contentHash"]),
        },
        "assetHashes": sorted(
            _sha256(item)
            for item in _normalize_string_set(request["assetHashes"], maximum=MAX_ASSETS)
        ),
        "report": {
            "score": _score(report["score"]),
            "criticalSubscores": dict(sorted(critical_normalized.items())),
            "requiredViewports": required_viewports,
            "viewports": dict(sorted(viewports.items())),
            "checks": _normalize_checks(report["checks"], _GLOBAL_GATES),
            "warnings": _normalize_issues(report["warnings"], warning=True),
            "preservedLocks": _normalize_string_set(report["preservedLocks"]),
            "changedFacets": _normalize_string_set(report["changedFacets"]),
            "styleOnly": report["styleOnly"],
        },
        "engineVersion": ENGINE_VERSION,
    }


def _blocking(code: str, message: str, path: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if path:
        item["path"] = path
    return item


def _malformed_certificate(reason: str) -> dict[str, Any]:
    # Deliberately hash only the stable validation category.  Malformed input
    # can contain secrets and is never retained, echoed, or hashed verbatim.
    input_hash = _hash({"malformed": reason, "engineVersion": ENGINE_VERSION})
    certificate = {
        "status": "blocked",
        "score": 0,
        "blockingIssues": [_blocking("input.malformed", reason)],
        "warnings": [],
        "preservedLocks": [],
        "changedFacets": [],
        "viewports": {},
        "inputHash": input_hash,
        "engineVersion": ENGINE_VERSION,
    }
    certificate["certificateHash"] = _hash(certificate)
    return certificate


def certify_quality(request: Any) -> dict[str, Any]:
    """Return a deterministic Quality Certified decision without mutating input.

    Invalid, oversized, or sensitive-bearing inputs produce a stable ``blocked``
    certificate instead of raising or partially certifying the result.
    """
    try:
        normalized = _normalize_request(request)
    except (_Malformed, TypeError, ValueError, OverflowError) as exc:
        reason = str(exc) if isinstance(exc, _Malformed) else "input could not be validated"
        return _malformed_certificate(reason)

    report = normalized["report"]
    blockers: list[dict[str, Any]] = []
    warnings = list(report["warnings"])

    for gate, issues in report["checks"].items():
        if gate == "structuralMutations" and not report["styleOnly"]:
            continue
        blockers.extend(issues)

    viewport_results: dict[str, Any] = {}
    required = set(report["requiredViewports"])
    available = set(report["viewports"])
    for missing in sorted(required - available):
        blockers.append(_blocking(
            "viewport.missing",
            "A required viewport report is missing.",
            f"viewports.{missing}",
        ))

    for name, viewport in report["viewports"].items():
        viewport_blockers = [issue for issues in viewport["checks"].values() for issue in issues]
        if name in required and viewport["score"] < CRITICAL_SUBSCORE:
            viewport_blockers.append(_blocking(
                "viewport.score_below_threshold",
                f"Required viewport score must be at least {CRITICAL_SUBSCORE}.",
                f"viewports.{name}.score",
            ))
        viewport_blockers = sorted(viewport_blockers, key=_canonical_json)
        viewport_warnings = viewport["warnings"]
        blockers.extend(viewport_blockers)
        warnings.extend(viewport_warnings)
        viewport_results[name] = {
            "status": "blocked" if viewport_blockers else ("certified_with_warnings" if viewport_warnings else "certified"),
            "score": viewport["score"],
            "blockingIssues": sorted(viewport_blockers, key=_canonical_json),
            "warnings": viewport_warnings,
        }

    if report["score"] < CERTIFIED_SCORE:
        blockers.append(_blocking("score.below_threshold", f"Visual score must be at least {CERTIFIED_SCORE}."))
    for name, value in report["criticalSubscores"].items():
        if value < CRITICAL_SUBSCORE:
            blockers.append(_blocking(
                "critical_subscore.below_threshold",
                f"Critical subscore must be at least {CRITICAL_SUBSCORE}.",
                f"criticalSubscores.{name}",
            ))

    blockers = sorted(blockers, key=_canonical_json)
    warnings = sorted(warnings, key=_canonical_json)
    status = "blocked" if blockers else ("certified_with_warnings" if warnings else "certified")
    input_hash = _hash(normalized)
    certificate = {
        "status": status,
        "score": report["score"],
        "blockingIssues": blockers,
        "warnings": warnings,
        "preservedLocks": report["preservedLocks"],
        "changedFacets": report["changedFacets"],
        "viewports": dict(sorted(viewport_results.items())),
        "inputHash": input_hash,
        "engineVersion": ENGINE_VERSION,
    }
    certificate["certificateHash"] = _hash(certificate)
    return certificate


create_quality_certificate = certify_quality
