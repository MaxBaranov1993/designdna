# Roadmap

## CTO implementation milestones

Completed:

- Stage 0: Design IR 1.1, migration, validation, stable `sourceKey`, content
  hash, provenance and feature flags;
- Stage 1: measured Style DNA primitives, semantic tokens, recursive
  `styleBindings`, visual inspector and responsive token application;
- Stage 2: opt-in Normalize preview/apply and deterministic Exact/Normalized
  Tailwind projection;
- Stage 3: arbitrary 320-2560 px canvas widths, automatic mobile/tablet/desktop
  resolution, property-source indicators and reset/apply/copy override controls;
- Stage 4A: Design IR preview recorder, local PII/secret cleanup, versioned
  Interaction IR, safe scene patches, validation and deterministic replay;
- Stage 4B: owned-site Chromium runner, same-origin navigation guard, transient
  action scripts and sanitized live form-state capture.

Next vertical slice: Stage 5 Motion Editor over Interaction IR scenes. Video
render and AI Director remain future stages and must not be marked implemented
until their end-to-end acceptance scenarios pass.

## Phase 0 — Clean product foundation

Goal: remove confusion and align code/docs around controlled AI.

Done/target:

- remove old UI nodes;
- OpenRouter-only AI routing;
- thin Edit node;
- fullscreen DNA Editor as the only manual editing surface;
- Design IR 1.1 foundation: versioning, migrator, validator, stable
  `sourceKey`, content hash and feature flags (see
  `docs/adr/ADR-0001-ir-first-foundation.md`);
- new clean documentation;
- current graph tests green.

## Phase 1 — Controlled AI MVP

Goal: make control visible in every AI operation.

Build:

- Layout Lock node;
- Constraints node;
- Compare/Diff node;
- stronger Reskin masks;
- Quality Pass report UI;
- visible model role and estimated cost per AI node;
- accept/reject generated variants.

Killer demo:

```text
Import reference hero
  → lock layout
  → reskin in another style
  → compare diff
  → Quality Pass
```

## Phase 2 — Project DNA

Goal: the project learns from accepted work.

Build:

- Project DNA node;
- accepted/rejected variant tracking;
- selected block library;
- token memory;
- layout rhythm memory;
- manual edit memory;
- project-level rules.

Killer demo:

```text
Make header
  → user edits spacing/colors
  → Project DNA learns
  → Derive footer/pricing/cards in same style
```

## Phase 3 — Procedural design graph

Goal: become ComfyUI/Houdini for web design, but easier.

Build:

- Wedge node;
- Timeline;
- Attr Extract;
- Attr Transfer;
- Scoped Gen;
- Token Override;
- Script node;
- Subgraph/Asset node.

Killer demo:

```text
One product style
  → 9 controlled variations
  → pick best
  → package as reusable asset
```

## Phase 4 — Page/system output

Goal: go from components to usable pages and design systems.

Build:

- Compose Page;
- responsive breakpoint editor;
- design system doc export;
- component library export;
- HTML/React/Svelte export;
- Figma export/import bridge.

Killer demo:

```text
Reference + prompt + Project DNA
  → full landing page
  → edit
  → export code/design doc
```

## Phase 5 — Studio and market layer

Goal: make it useful for paid workflows.

Build:

- accounts/projects;
- cloud save;
- client review links;
- comments/approvals;
- asset marketplace;
- paid credits;
- free viewers;
- team style libraries.

Killer demo:

```text
Studio creates reusable design workflows
  → publishes internal assets
  → clients review controlled variants
```

## Pricing direction

Think in two meters:

1. subscription for product/workspace;
2. AI credits for expensive operations.

Possible tiers:

- Solo AI Builder;
- Freelance Designer;
- Studio;
- Team/Agency.

Important: users should see cost before Wedge/batch/Quality Pass operations.

## Strategic bet

The product wins if users say:

> “I can use AI without surrendering my design.”

That means the roadmap must prioritize control, memory, reuse and quality over raw feature count.
