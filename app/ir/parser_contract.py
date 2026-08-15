"""Deterministic Parser v2 envelope for source-aware composition.

The parser keeps emitting render-compatible Design IR 1.1 documents. This
sidecar envelope carries the stable source identity, facet provenance,
confidence diagnostics and measured layout-axis candidates needed by the
multi-source editor without forcing an early runtime migration to IR 2.0.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, ValidationError as PydanticValidationError, field_validator, model_validator

from .composition import (
    AxisAnchor,
    AxisRole,
    Confidence,
    ContractModel,
    Identifier,
    NodeProvenance,
    NodeRef,
    NodeState,
    NodeStatus,
    OriginFacet,
    OriginRef,
    SourceKind,
    SourceRecord,
    Viewport,
)
from .hash import content_hash

PARSER_CONTRACT_VERSION = "parser-source-envelope/1.0"


class EvidenceBasis(str, Enum):
    MEASURED = "measured"
    INFERRED = "inferred"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ViewportMeasurement(ContractModel):
    width: float = Field(ge=0)
    height: float | None = Field(default=None, ge=0)
    layers: int | None = Field(default=None, ge=0)
    coverage: Confidence | None = None
    fidelity: Confidence | None = None


class LayoutEvidence(ContractModel):
    id: Identifier
    node_ref: NodeRef
    role: AxisRole
    anchor: AxisAnchor
    viewport: Viewport
    max_width: float = Field(ge=0)
    inline_gutter: float = Field(ge=0)
    confidence: Confidence
    basis: EvidenceBasis


class ParserDiagnostic(ContractModel):
    code: Identifier
    severity: DiagnosticSeverity
    message: str = Field(min_length=1, max_length=1000)
    node_ref: NodeRef | None = None
    viewport: Viewport | None = None


class ParserSourceEnvelope(ContractModel):
    version: Literal["parser-source-envelope/1.0"]
    source_record: SourceRecord
    node_states: dict[NodeRef, NodeState]
    layout_evidence: tuple[LayoutEvidence, ...]
    viewports: dict[Viewport, ViewportMeasurement] = Field(default_factory=dict)
    diagnostics: tuple[ParserDiagnostic, ...] = ()

    @field_validator("node_states")
    @classmethod
    def non_empty_nodes(cls, value: dict[str, NodeState]) -> dict[str, NodeState]:
        if not value:
            raise ValueError("nodeStates must contain at least one stable node reference")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "ParserSourceEnvelope":
        source_id = self.source_record.id
        for node_ref, state in self.node_states.items():
            if state.provenance and state.provenance.source_ids() - {source_id}:
                raise ValueError(f"nodeStates[{node_ref!r}] references a different source")
        unknown_nodes = {item.node_ref for item in self.layout_evidence} - set(self.node_states)
        if unknown_nodes:
            raise ValueError(f"layoutEvidence references unknown nodes: {sorted(unknown_nodes)}")
        return self


def normalize_source_ref(url: str) -> str:
    """Normalize URL identity without changing meaningful query parameters."""
    value = url.strip()
    parts = urlsplit(value)
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def stable_source_id(source_ref: str, selector: str, kind: SourceKind | str = SourceKind.URL) -> str:
    source_kind = SourceKind(kind)
    normalized_ref = normalize_source_ref(source_ref) if source_kind == SourceKind.URL else source_ref.strip()
    identity = f"{source_kind.value}\n{normalized_ref}\n{selector.strip()}"
    return "source-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _score(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number > 1:
        number /= 100
    return max(0.0, min(1.0, number))


def _capture_confidence(capture: dict[str, Any]) -> float:
    samples: list[float] = []
    for field in ("coverage", "fidelity"):
        value = capture.get(field)
        if isinstance(value, dict):
            samples.extend(score for item in value.values() if (score := _score(item)) is not None)
        elif (score := _score(value)) is not None:
            samples.append(score)
    baseline = sum(samples) / len(samples) if samples else 0.92
    warnings = capture.get("warnings") if isinstance(capture.get("warnings"), list) else []
    return round(max(0.0, min(1.0, baseline - min(len(warnings), 10) * 0.025)), 4)


def _node_ref(node: dict[str, Any]) -> str | None:
    for key in ("sourceKey", "id"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _has_content(node: dict[str, Any]) -> bool:
    if isinstance(node.get("text"), str) and node["text"].strip():
        return True
    props = node.get("props")
    return isinstance(props, dict) and any(value not in (None, "", [], {}) for value in props.values())


def _has_assets(node: dict[str, Any]) -> bool:
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    return any(key in props for key in ("src", "image", "imageUrl", "icon", "video", "poster"))


def _has_interaction(node: dict[str, Any]) -> bool:
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    return node.get("type") in {"button", "input", "form", "link"} or any(
        key in props for key in ("href", "action", "onClick", "target")
    )


def _node_states(ir: dict[str, Any], source_id: str, confidence: float) -> dict[str, NodeState]:
    states: dict[str, NodeState] = {}

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        ref = _node_ref(node)
        if ref:
            facets = {
                OriginFacet.STRUCTURE: OriginRef(sourceId=source_id, sourcePath=ref, confidence=confidence),
            }
            if isinstance(node.get("style"), dict) or isinstance(node.get("frame"), dict):
                facets[OriginFacet.APPEARANCE] = OriginRef(
                    sourceId=source_id, sourcePath=ref, confidence=confidence
                )
            if _has_content(node):
                facets[OriginFacet.CONTENT] = OriginRef(
                    sourceId=source_id, sourcePath=ref, confidence=confidence
                )
            if _has_assets(node):
                facets[OriginFacet.ASSETS] = OriginRef(
                    sourceId=source_id, sourcePath=ref, confidence=confidence
                )
            if _has_interaction(node):
                facets[OriginFacet.INTERACTION] = OriginRef(
                    sourceId=source_id, sourcePath=ref, confidence=confidence
                )
            status = {NodeStatus.LINKED}
            if confidence < 0.75:
                status.add(NodeStatus.LOW_CONFIDENCE)
            states[ref] = NodeState(
                provenance=NodeProvenance(primarySourceId=source_id, facets=facets),
                status=status,
            )
        for child in node.get("children") or []:
            visit(child)

    for section in ir.get("tree") or []:
        visit(section)
    return states


def _viewport_measurements(capture: dict[str, Any]) -> dict[Viewport, ViewportMeasurement]:
    sizes = capture.get("sizes") if isinstance(capture.get("sizes"), dict) else {}
    coverages = capture.get("coverage") if isinstance(capture.get("coverage"), dict) else {}
    fidelities = capture.get("fidelity") if isinstance(capture.get("fidelity"), dict) else {}
    layers = capture.get("layersByViewport") if isinstance(capture.get("layersByViewport"), dict) else {}
    measurements: dict[Viewport, ViewportMeasurement] = {}
    for viewport in Viewport:
        size = sizes.get(viewport.value)
        if not isinstance(size, dict) or not isinstance(size.get("width"), (int, float)):
            continue
        measurements[viewport] = ViewportMeasurement(
            width=float(size["width"]),
            height=float(size["height"]) if isinstance(size.get("height"), (int, float)) else None,
            layers=int(layers[viewport.value]) if isinstance(layers.get(viewport.value), int) else None,
            coverage=_score(coverages.get(viewport.value)),
            fidelity=_score(fidelities.get(viewport.value)),
        )
    if not measurements:
        size = capture.get("size") if isinstance(capture.get("size"), dict) else {}
        width = size.get("width") if isinstance(size.get("width"), (int, float)) else capture.get("width")
        height = size.get("height") if isinstance(size.get("height"), (int, float)) else capture.get("height")
        if isinstance(width, (int, float)):
            measurements[Viewport.DESKTOP] = ViewportMeasurement(
                width=float(width),
                height=float(height) if isinstance(height, (int, float)) else None,
                layers=int(capture["layers"]) if isinstance(capture.get("layers"), int) else None,
            )
    return measurements


def _layout_evidence(
    ir: dict[str, Any], source_id: str, confidence: float, measurements: dict[Viewport, ViewportMeasurement]
) -> list[LayoutEvidence]:
    sections = [node for node in ir.get("tree") or [] if isinstance(node, dict)]
    if not sections:
        return []
    section = sections[0]
    section_ref = _node_ref(section)
    if not section_ref:
        return []
    evidence: list[LayoutEvidence] = []
    short = source_id.removeprefix("source-")[:8]
    for viewport, measurement in measurements.items():
        evidence.append(
            LayoutEvidence(
                id=f"axis-{short}-outer-{viewport.value}",
                nodeRef=section_ref,
                role=AxisRole.FULL_BLEED,
                anchor=AxisAnchor.OUTER,
                viewport=viewport,
                maxWidth=measurement.width,
                inlineGutter=0,
                confidence=confidence,
                basis=EvidenceBasis.MEASURED,
            )
        )

    desktop = measurements.get(Viewport.DESKTOP)
    if not desktop or desktop.width <= 0:
        return evidence
    bounds: list[tuple[float, float]] = []
    for child in section.get("children") or []:
        if not isinstance(child, dict) or not isinstance(child.get("frame"), dict):
            continue
        frame = child["frame"]
        x, width = frame.get("x"), frame.get("width")
        if isinstance(x, (int, float)) and isinstance(width, (int, float)) and width > 0:
            bounds.append((float(x), float(x + width)))
    if bounds:
        left = max(0.0, min(start for start, _ in bounds))
        right = min(desktop.width, max(end for _, end in bounds))
        span = max(0.0, right - left)
        gutter = min(left, max(0.0, desktop.width - right))
        if span >= desktop.width * 0.3 and 8 <= gutter <= desktop.width * 0.25:
            evidence.append(
                LayoutEvidence(
                    id=f"axis-{short}-content-desktop",
                    nodeRef=section_ref,
                    role=AxisRole.PAGE_CONTENT,
                    anchor=AxisAnchor.INNER_CONTENT,
                    viewport=Viewport.DESKTOP,
                    maxWidth=round(span, 2),
                    inlineGutter=round(gutter, 2),
                    confidence=round(confidence * 0.85, 4),
                    basis=EvidenceBasis.INFERRED,
                )
            )
    return evidence


def build_parser_envelope(
    ir: dict[str, Any],
    *,
    url: str,
    selector: str,
    label: str,
    parser_version: str,
    kind: SourceKind | str = SourceKind.URL,
    capture: dict[str, Any] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Build and type-check the Parser v2 sidecar for one parsed block."""
    capture = dict(capture or {})
    if not isinstance(capture.get("sizes"), dict) and not isinstance(capture.get("size"), dict):
        frame = ir.get("frame") if isinstance(ir.get("frame"), dict) else {}
        if isinstance(frame.get("width"), (int, float)):
            capture["size"] = {
                "width": frame["width"],
                "height": frame.get("height") if isinstance(frame.get("height"), (int, float)) else None,
            }
    source_kind = SourceKind(kind)
    normalized_ref = normalize_source_ref(url) if source_kind == SourceKind.URL else url.strip()
    source_id = stable_source_id(normalized_ref, selector, source_kind)
    identity = f"{source_kind.value}\n{normalized_ref}\n{selector.strip()}"
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    confidence = _capture_confidence(capture)
    preview = capture.get("preview") if isinstance(capture.get("preview"), str) else ""
    source = SourceRecord(
        id=source_id,
        kind=source_kind,
        label=label,
        ref=normalized_ref,
        sourceNodeId=selector,
        fingerprint=f"sha256:{identity_hash}",
        upstreamHash=f"sha256:{content_hash(ir)}",
        colorToken=f"source.{identity_hash[:8]}",
        symbol=f"S{identity_hash[:2].upper()}",
        thumbnailAssetId=(
            "sha256:" + hashlib.sha256(preview.encode("utf-8")).hexdigest() if preview else None
        ),
        capturedAt=captured_at or datetime.now(timezone.utc),
        parserVersion=parser_version,
        confidence=confidence,
    )
    node_states = _node_states(ir, source_id, confidence)
    measurements = _viewport_measurements(capture)
    diagnostics = [
        ParserDiagnostic(
            code="capture-warning",
            severity=DiagnosticSeverity.WARNING,
            message=str(message)[:1000],
        )
        for message in capture.get("warnings", [])
        if str(message).strip()
    ]
    for viewport, measurement in measurements.items():
        if measurement.coverage is not None and measurement.coverage < 0.75:
            diagnostics.append(
                ParserDiagnostic(
                    code="low-coverage",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Captured coverage is {round(measurement.coverage * 100)}%",
                    viewport=viewport,
                )
            )
    envelope = ParserSourceEnvelope(
        version=PARSER_CONTRACT_VERSION,
        sourceRecord=source,
        nodeStates=node_states,
        layoutEvidence=_layout_evidence(ir, source_id, confidence, measurements),
        viewports=measurements,
        diagnostics=diagnostics,
    )
    return envelope.model_dump(mode="json", by_alias=True, exclude_none=True)


def validate_parser_envelope_semantics(value: dict[str, Any]) -> list[str]:
    """Validate typed and cross-reference invariants for a parser envelope."""
    try:
        ParserSourceEnvelope.model_validate(value)
    except PydanticValidationError as exc:
        return [
            ".".join(str(part) for part in error["loc"]) + ": " + error["msg"]
            for error in exc.errors()
        ]
    return []
