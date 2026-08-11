# ADR-0001: DesignAI IR-first foundation and stage-0 contracts

**Status:** accepted  
**Date:** 2026-08-11  
**Deciders:** DesignAI engineering lead  
**Scope:** stage-0 foundation for the 7-stage CTO plan (IR 1.1, Tailwind projection, Interaction IR, Motion IR, video render, AI Director).

## Context

DesignAI Web already uses an intermediate representation called Design IR as the source of truth for generated and imported designs. The current schema is version 1.0. The CTO plan proposes a larger platform built on three linked models:

- **Design IR 1.1** — structure, layout, exact styles, responsive constraints, Style DNA bindings, Tailwind projection.
- **Interaction IR** — pages, states, events, sanitized user data.
- **Motion IR** — scenes, timeline, tracks, keyframes, camera, overlays.

Before building Tailwind projection, responsive editor, interaction recorder, motion editor or deterministic video render, we must harden the foundation so that:

1. Old projects open without manual migration or visual regressions.
2. Every IR document is versioned, validated and traceable.
3. Element identity is stable across capture, merge, editing and composition.
4. AI can only return validated IR patches, never raw HTML/CSS/video.
5. New subsystems can be introduced behind feature flags without breaking the current editor.

## Decision

We will adopt the following architectural contracts and implement them as stage 0.

### 1. IR-first and versioned Design IR

- `Design IR` remains the single source of truth for design.
- The canonical schema moves from `1.0` to `1.1`. Version `1.1` is a strict superset of `1.0`: every valid 1.0 document is valid 1.1 after migration.
- All persisted IR documents carry a top-level `version` field. Missing version is interpreted as `1.0`.
- A deterministic migrator `app/ir/migrate.py` upgrades `1.0` → `1.1` on ingestion (server API, project load, node execution).
- Downgrade is not supported; the runtime always materializes the latest canonical version internally.

### 2. Design IR 1.1 extensions (non-breaking)

Version 1.1 adds optional sections that do not change the visual output of existing documents:

- `styleBindings` on sections and elements: maps style properties to Style DNA tokens without replacing the exact value.
- `constraints` on sections and elements: deterministic rules (min/max width, spacing ranges, allowed colors, etc.).
- `provenance` on tokens and elements: `imported`, `generated`, `normalized`, `manual`.
- `contentHash` at root: SHA-256 of the normalized canonical JSON (without runtime/preview fields) for identity and cache invalidation.
- `sourceKey` contract formalized (see §4).

These fields are optional; a 1.1 document without them renders exactly like a 1.0 document.

### 3. Tailwind projection is a derivative, not a source

- `TailwindProjection` is a deterministic function `Design IR → {theme, utility classes, arbitrary utilities, responsive classes, diagnostics}`.
- Tailwind output is never written back into canonical Design IR.
- The projection engine lives in `app/ir/tailwind_projection.py` (stage 2), but stage 0 reserves the contract and the namespace.
- Two modes are planned:
  - `Exact` — maximum fidelity with arbitrary utilities.
  - `Normalized` — properties bound to Style DNA and a system scale; requires user confirmation before applying.

### 4. Stable element identity (`sourceKey`)

`sourceKey` is the stable address of an element across capture, merge, editing and composition.

Rules:

- Generated during hybrid DOM capture from a deterministic DOM path plus semantic hints.
- Unique within one document. Collisions during viewport merge are resolved deterministically by appending a zero-padded integer suffix (`#001`, `#002`), never random data.
- During `Page` composition, cross-block collisions are resolved by prefixing the source key with the block name (`block-name/source-key`), preserving the original suffix so that downstream tools can reverse-map.
- The editor uses `sourceKey` for selection state, inspector targets and history entries; paths in `_frames` and `responsiveOverrides` also reference `sourceKey`.
- Removing or changing `sourceKey` is treated as a structural change and breaks identity.

### 5. AI gateway contract: IR patches only

- All AI calls route through `llm_client.py` / OpenRouter.
- AI responses for design operations must be parseable JSON objects that validate against the current Design IR schema (1.1) or a declared IR patch schema.
- Raw HTML, CSS, video or arbitrary prose are rejected at the API boundary.
- `mergeback.py` enforces lock masks after every AI transformation.
- Future Motion IR and Interaction IR will use the same rule: AI returns validated patches, never rendered artifacts.

### 6. Module boundaries (stage-0 package structure)

We introduce the following Python packages so that later stages have a clear home:

- `app/ir/` — ir-core: schema loading, migration, validation, content hash, sourceKey utilities.
- `app/ir/tailwind_projection.py` — style-engine/Tailwind projection (stub in stage 0).
- `app/ir/responsive.py` — responsive-engine: viewport materialization, breakpoint rules, override resolution (stub in stage 0).
- `app/ir/interaction.py` — interaction-runtime: Interaction IR types and sanitizers (stub in stage 0).
- `app/ir/motion.py` — Motion IR build, timeline invariants and validators (implemented in stage 5).
- `app/config/flags.py` — feature flags shared by backend and exposed to frontend.

No broad rewrites of existing code are performed in stage 0; only the new contracts are added and the legacy call sites are updated to use `app/ir` utilities.

### 7. Feature flags

Stage 0 introduces the `irV11` flag, defaulted to `True` for new projects. When enabled:

- All newly created/imported/generated IR is stored as 1.1.
- The validator uses the 1.1 schema.
- Migration is still applied to legacy loads so old projects keep working.

Frontend receives the flag list via a small `/api/config` endpoint.

### 8. Validation and diagnostics

- `app/ir/validate.py` exposes `validate_ir(ir, version=None)` returning a list of structured diagnostics.
- Diagnostics include JSON path, message and severity (`error`, `warning`).
- All server routes that accept or emit IR call validation and return the first errors to the caller.
- Tests must pass without schema regressions.

## Consequences

**Positive:**

- Old projects load transparently.
- New subsystems have a clear contract and namespace.
- Element identity becomes deterministic and testable.
- AI output is constrained to valid IR, reducing hallucinated layout.
- Feature flags let us ship stage-0 changes safely.

**Negative / trade-offs:**

- Every persisted IR document will be rewritten once on first load after deploy (migration 1.0 → 1.1).
- `sourceKey` collisions must be resolved deterministically; non-deterministic suffixes would break tests and cache keys.
- The frontend must receive feature flags before rendering nodes; this adds one small API call on boot.

## Migration plan

1. Deploy schema 1.1 and `app/ir/` utilities.
2. Restart server; existing in-memory state is fresh.
3. On next project load, `load_project` returns legacy payload; each IR node is migrated to 1.1 before being handed to the graph.
4. On next save, migrated IR is persisted as 1.1.
5. No manual user action required.

## Validation criteria

- `source_import_test.py`, `ui_flow_*` tests and editor tests pass after migration.
- A project saved before this ADR opens and renders identically.
- `git diff --check` is clean.
