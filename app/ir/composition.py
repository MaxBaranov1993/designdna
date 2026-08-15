"""Typed Design IR 2.0 composition and semantic edit contracts.

The render tree remains compatible with Design IR 1.1. Multi-source state is
kept out-of-line in composition.nodeStates so parser provenance, layout axes,
locks, and source refresh metadata do not pollute visual props.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._:-]{0,127}$")]
NodeRef = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Confidence = Annotated[float, Field(ge=0, le=1)]
NonNegative = Annotated[float, Field(ge=0)]


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ContractModel(BaseModel):
    """Strict immutable base used by persisted contracts."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class SourceKind(str, Enum):
    URL = "url"
    IMAGE = "image"
    FIGMA = "figma"
    CODE = "code"
    LIBRARY = "library"
    MANUAL = "manual"
    AI = "ai"


class OriginFacet(str, Enum):
    STRUCTURE = "structure"
    APPEARANCE = "appearance"
    CONTENT = "content"
    ASSETS = "assets"
    INTERACTION = "interaction"


class Viewport(str, Enum):
    DESKTOP = "desktop"
    TABLET = "tablet"
    MOBILE = "mobile"


class AxisRole(str, Enum):
    PAGE_CONTENT = "page-content"
    FULL_BLEED = "full-bleed"
    TEXT_COLUMN = "text-column"
    CUSTOM = "custom"


class AxisAnchor(str, Enum):
    OUTER = "outer"
    INNER_CONTENT = "inner-content"
    TEXT = "text"
    GRID = "grid"
    START = "start"
    CENTER = "center"
    END = "end"


class Alignment(str, Enum):
    START = "start"
    CENTER = "center"
    END = "end"


class IntentLock(str, Enum):
    CONTENT = "content"
    STRUCTURE = "structure"
    APPEARANCE = "appearance"
    ASSETS = "assets"
    INTERACTION = "interaction"
    BRAND = "brand"
    LAYOUT = "layout"
    SOURCE_LINK = "source-link"


class NodeStatus(str, Enum):
    LINKED = "linked"
    MODIFIED = "modified"
    GENERATED = "generated"
    STALE_SOURCE = "stale-source"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low-confidence"


ResponsiveLength = NonNegative | dict[Viewport, NonNegative]


class Revision(ContractModel):
    id: Identifier
    base_revision_id: Identifier | None = None
    created_at: datetime
    actor: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=500)


class SourceRecord(ContractModel):
    id: Identifier
    kind: SourceKind
    label: str = Field(min_length=1, max_length=160)
    ref: str | None = Field(default=None, max_length=2048)
    source_node_id: str | None = Field(default=None, max_length=160)
    fingerprint: str = Field(min_length=8, max_length=256)
    upstream_hash: str | None = Field(default=None, max_length=256)
    color_token: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=8)
    thumbnail_asset_id: str | None = Field(default=None, max_length=256)
    captured_at: datetime
    parser_version: str = Field(min_length=1, max_length=80)
    confidence: Confidence
    license: str | None = Field(default=None, max_length=160)


class OriginRef(ContractModel):
    source_id: Identifier
    source_path: str | None = Field(default=None, max_length=2048)
    confidence: Confidence
    transformation_ids: tuple[Identifier, ...] = ()

    @field_validator("transformation_ids")
    @classmethod
    def unique_transformations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("transformationIds must be unique")
        return value


class NodeProvenance(ContractModel):
    primary_source_id: Identifier | None = None
    facets: dict[OriginFacet, OriginRef] = Field(default_factory=dict)
    property_overrides: dict[str, OriginRef] = Field(default_factory=dict)
    transformations: tuple[Identifier, ...] = ()

    @field_validator("property_overrides")
    @classmethod
    def json_pointer_keys(cls, value: dict[str, OriginRef]) -> dict[str, OriginRef]:
        invalid = [path for path in value if not path.startswith("/")]
        if invalid:
            raise ValueError(f"propertyOverrides must use JSON Pointer paths: {invalid}")
        return value

    @field_validator("transformations")
    @classmethod
    def unique_transformations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("transformations must be unique")
        return value

    def source_ids(self) -> set[str]:
        ids = {ref.source_id for ref in self.facets.values()}
        ids.update(ref.source_id for ref in self.property_overrides.values())
        if self.primary_source_id:
            ids.add(self.primary_source_id)
        return ids


class LayoutAxisMember(ContractModel):
    node_ref: NodeRef
    anchor: AxisAnchor


class LayoutAxis(ContractModel):
    id: Identifier
    role: AxisRole
    max_width: ResponsiveLength
    inline_gutter: ResponsiveLength
    alignment: Alignment
    members: tuple[LayoutAxisMember, ...] = ()
    locked: bool = False

    @field_validator("members")
    @classmethod
    def unique_members(cls, value: tuple[LayoutAxisMember, ...]) -> tuple[LayoutAxisMember, ...]:
        identities = [(member.node_ref, member.anchor) for member in value]
        if len(identities) != len(set(identities)):
            raise ValueError("layout axis members must be unique")
        return value


class AxisBinding(ContractModel):
    axis_id: Identifier
    anchor: AxisAnchor


class NodeState(ContractModel):
    provenance: NodeProvenance | None = None
    axis_bindings: tuple[AxisBinding, ...] = ()
    locks: frozenset[IntentLock] = frozenset()
    status: frozenset[NodeStatus] = frozenset()

    @field_validator("axis_bindings")
    @classmethod
    def unique_axis_bindings(cls, value: tuple[AxisBinding, ...]) -> tuple[AxisBinding, ...]:
        identities = [(binding.axis_id, binding.anchor) for binding in value]
        if len(identities) != len(set(identities)):
            raise ValueError("axisBindings must be unique")
        return value


class CompositionContract(ContractModel):
    schema_version: Literal["composition/1.0"]
    revision: Revision
    source_registry: dict[Identifier, SourceRecord]
    layout_axes: dict[Identifier, LayoutAxis] = Field(default_factory=dict)
    node_states: dict[NodeRef, NodeState]
    document_locks: frozenset[IntentLock] = frozenset()

    @model_validator(mode="after")
    def validate_registry_and_references(self) -> "CompositionContract":
        if not self.source_registry:
            raise ValueError("sourceRegistry must contain at least one source")
        if not self.node_states:
            raise ValueError("nodeStates must contain at least one node")

        for key, record in self.source_registry.items():
            if key != record.id:
                raise ValueError(f"sourceRegistry key {key!r} does not match record id {record.id!r}")
        for key, axis in self.layout_axes.items():
            if key != axis.id:
                raise ValueError(f"layoutAxes key {key!r} does not match axis id {axis.id!r}")

        known_sources = set(self.source_registry)
        known_axes = set(self.layout_axes)
        for node_ref, state in self.node_states.items():
            if state.provenance:
                unknown_sources = state.provenance.source_ids() - known_sources
                if unknown_sources:
                    raise ValueError(
                        f"nodeStates[{node_ref!r}] references unknown sources: {sorted(unknown_sources)}"
                    )
            unknown_axes = {binding.axis_id for binding in state.axis_bindings} - known_axes
            if unknown_axes:
                raise ValueError(
                    f"nodeStates[{node_ref!r}] references unknown layout axes: {sorted(unknown_axes)}"
                )
        return self


class PreconditionKind(str, Enum):
    REVISION_MATCH = "revision-match"
    DOCUMENT_HASH_MATCH = "document-hash-match"
    NODE_EXISTS = "node-exists"
    PROPERTY_EQUALS = "property-equals"
    LOCK_ABSENT = "lock-absent"


class OperationKind(str, Enum):
    BIND_LAYOUT_AXIS = "bind-layout-axis"
    UNBIND_LAYOUT_AXIS = "unbind-layout-axis"
    CREATE_CONTAINER = "create-container"
    REMOVE_CONTAINER = "remove-container"
    SET_RESPONSIVE_CONSTRAINT = "set-responsive-constraint"
    APPLY_TOKEN = "apply-token"
    REPLACE_STYLE_FACET = "replace-style-facet"
    REORDER_SECTION = "reorder-section"
    INSERT_NODE = "insert-node"
    REMOVE_NODE = "remove-node"
    SET_PROPERTY = "set-property"
    REMOVE_PROPERTY = "remove-property"
    GENERATE_STATE = "generate-state"
    SET_INTENT_LOCK = "set-intent-lock"
    REMOVE_INTENT_LOCK = "remove-intent-lock"


class ValidationKind(str, Enum):
    SCHEMA = "schema"
    REFERENCES = "references"
    LOCKS = "locks"
    RESPONSIVE = "responsive"
    OVERFLOW = "overflow"
    VISUAL = "visual"
    ACCESSIBILITY = "accessibility"
    EXPORT = "export"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class ChangeSetStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPLIED = "applied"
    REJECTED = "rejected"


class ChangePrecondition(ContractModel):
    kind: PreconditionKind
    target: str | None = Field(default=None, max_length=500)
    path: str | None = None
    expected: Any = None

    @field_validator("path")
    @classmethod
    def pointer_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("path must be a JSON Pointer")
        return value


class SemanticOperation(ContractModel):
    id: Identifier
    inverse_of: Identifier | None = None
    kind: OperationKind
    target: NodeRef
    path: str | None = None
    value: Any = None
    payload: dict[str, Any] | None = None

    @field_validator("path")
    @classmethod
    def pointer_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("path must be a JSON Pointer")
        return value


class ChangeValidation(ContractModel):
    kind: ValidationKind
    status: ValidationStatus
    message: str | None = Field(default=None, max_length=1000)
    viewport: Viewport | None = None


class SemanticChangeSet(ContractModel):
    version: Literal["semantic-change-set/1.0"]
    id: Identifier
    base_revision_id: Identifier
    target_revision_id: Identifier | None = None
    base_document_hash: str | None = Field(default=None, min_length=16, max_length=256)
    intent: str = Field(min_length=1, max_length=500)
    scope: tuple[NodeRef, ...] = Field(min_length=1)
    preconditions: tuple[ChangePrecondition, ...] = ()
    operations: tuple[SemanticOperation, ...] = Field(min_length=1)
    inverse_operations: tuple[SemanticOperation, ...] = Field(min_length=1)
    validations: tuple[ChangeValidation, ...] = ()
    atomic: Literal[True] = True
    status: ChangeSetStatus = ChangeSetStatus.DRAFT
    actor: str | None = Field(default=None, max_length=120)
    created_at: datetime
    explanation: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_unique_identity(self) -> "SemanticChangeSet":
        if len(self.scope) != len(set(self.scope)):
            raise ValueError("scope must contain unique node references")
        operation_ids = [operation.id for operation in self.operations]
        inverse_ids = [operation.id for operation in self.inverse_operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operation ids must be unique")
        if len(inverse_ids) != len(set(inverse_ids)):
            raise ValueError("inverse operation ids must be unique")
        if any(operation.inverse_of is not None for operation in self.operations):
            raise ValueError("forward operations must not declare inverseOf")
        uncovered = set(operation_ids)
        for inverse in self.inverse_operations:
            if inverse.inverse_of is None:
                raise ValueError("every inverse operation must declare inverseOf")
            if inverse.inverse_of not in operation_ids:
                raise ValueError(
                    f"inverse operation {inverse.id!r} references unknown operation {inverse.inverse_of!r}"
                )
            uncovered.discard(inverse.inverse_of)
        if uncovered:
            raise ValueError(f"operations without inverse coverage: {sorted(uncovered)}")
        return self


def _known_node_refs(ir: dict[str, Any]) -> set[str]:
    refs: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key in ("id", "sourceKey"):
            value = node.get(key)
            if isinstance(value, str) and value:
                refs.add(value)
        for child in node.get("children") or []:
            visit(child)

    for section in ir.get("tree") or []:
        visit(section)
    return refs


def validate_v2_semantics(ir: dict[str, Any]) -> list[str]:
    """Validate cross-reference rules that Draft-07 cannot express."""
    try:
        composition = CompositionContract.model_validate(ir.get("composition"))
    except PydanticValidationError as exc:
        return [
            ".".join(str(part) for part in error["loc"]) + ": " + error["msg"]
            for error in exc.errors()
        ]

    errors: list[str] = []
    known_nodes = _known_node_refs(ir)
    for node_ref in composition.node_states:
        if node_ref not in known_nodes:
            errors.append(f"nodeStates.{node_ref}: node reference does not exist in tree")
    for axis_id, axis in composition.layout_axes.items():
        for member in axis.members:
            if member.node_ref not in known_nodes:
                errors.append(
                    f"layoutAxes.{axis_id}.members.{member.node_ref}: node reference does not exist in tree"
                )
    return sorted(errors)


def validate_change_set_semantics(value: dict[str, Any]) -> list[str]:
    """Validate typed change-set invariants and return stable diagnostics."""
    try:
        SemanticChangeSet.model_validate(value)
    except PydanticValidationError as exc:
        return [
            ".".join(str(part) for part in error["loc"]) + ": " + error["msg"]
            for error in exc.errors()
        ]
    return []
