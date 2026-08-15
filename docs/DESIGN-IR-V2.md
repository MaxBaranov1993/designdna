# Design IR 2.0 composition foundation

Design IR 2.0 is an opt-in contract for assembling one editable page from
multiple parser, manual, library, code, and AI sources. The current runtime
version remains 1.1 until parser and editor migration is complete.

## Why composition metadata is out-of-line

The 1.1 render tree stays unchanged. New multi-source state lives under the
top-level `composition` object and is keyed by stable section `id` or
`sourceKey`. This gives the editor constant-time provenance and layout-axis
lookups without adding editor-only properties to every render node.

The composition is split into four layers:

1. Immutable parser/source records in `sourceRegistry`.
2. Shared responsive geometry in `layoutAxes`.
3. Per-node provenance, locks, status and axis bindings in `nodeStates`.
4. A resolved 1.1-compatible `tree` consumed by the current renderer.

## Source Registry

Every source has a stable id, kind, upstream fingerprint, parser version,
confidence, source-lens color token, and non-color symbol. The registry is a
map rather than a list so selection and filtering do not require a scan.

Runtime validation enforces:

- registry key equals `SourceRecord.id`;
- all provenance facet references exist;
- confidence is in the 0–1 range;
- records are strict and reject unknown persisted properties.

Provenance is facet-level. Structure, appearance, content, assets and
interaction can come from different sources. Sparse `propertyOverrides`
stores only exceptions and uses JSON Pointer paths.

## Layout Axis

A Layout Axis describes semantic alignment rather than copied pixel widths.
The first supported roles are:

- `page-content`;
- `full-bleed`;
- `text-column`;
- `custom`.

`maxWidth` and `inlineGutter` can be scalar or responsive values. Members
bind using anchors such as `inner-content`, allowing a full-width header
background and a contained hero body to share the same visual rails.

Runtime validation rejects axes and members that reference unknown ids.

## SemanticChangeSet

AI and deterministic tools must not mutate a live document directly. They
produce a separate `semantic-change-set/1.0` contract containing:

- base revision and optional document hash;
- visible intent and scope;
- preconditions;
- typed operations;
- non-empty inverse operations with explicit `inverseOf` coverage for every
  forward operation;
- validation results;
- `atomic: true`.

The apply pipeline is:

`plan → isolated patch → schema/reference/lock validation → responsive render → preview → atomic commit`

The initial operation vocabulary includes layout-axis binding, semantic
container creation, responsive constraints, token application, style-facet
replacement, section reordering, node insertion/removal and intent locks.

## Compatibility policy

- `CURRENT_SCHEMA_VERSION` remains `1.1`.
- `LATEST_SCHEMA_VERSION` is `2.0`.
- `load_schema("2.0")` enables explicit validation and experiments.
- No existing 1.0/1.1 project is migrated automatically in this phase.
- Parser migration must populate stable identities before 2.0 becomes the
  runtime default.

## Parser v2 sidecar

Parser v2 keeps its render payload on IR 1.1 and emits a strict
`parser-source-envelope/1.0` sidecar per block. The sidecar contains a stable
URL + selector source id, source fingerprint and upstream hash, facet-level
node provenance, per-viewport measurements, full-bleed/content-axis evidence,
confidence and structured diagnostics. This boundary avoids silently
downgrading a live IR 2.0 document through legacy `ensure_current` paths.

`SOURCE_COMPILER_VERSION` is bumped whenever the envelope or deterministic DOM
compiler changes, so cached parse results cannot hide a contract migration.

## Next implementation boundary

The next P1 phase consumes parser sidecars during page composition and adds
Source Lens highlighting, source filters and conflict/status affordances to the
Edit node. It is the first phase that changes the visible editing workflow.
