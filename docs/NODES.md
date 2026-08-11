# Nodes

## Current nodes

### Prompt

Text task source.

Use for:

- “make a SaaS hero”;
- “turn this header into a footer”;
- “make this more premium”.

Output: `text`.

### Reference

Light style hint source.

Use when the user wants to guide a generation with visual/text reference context.

Input: `ir`.
Output: `text`.

### Generator

Prompt → multiple Design IR variants through OpenRouter.

Default model route: `generator` → Claude Opus 5 → Claude Sonnet 5 → GPT-5.6 Sol.

Inputs:

- `prompt: text`
- `style: text`
- `tokens: style DNA` — wired tokens (from Source Import / Style DNA) are locked: the prompt instructs the model to use them exactly and the server deterministically writes them into every variant's `ir.tokens`. Variation stays in composition and content, not in tokens.

Output: `ir`.

Typography engine (`app/typography.py`): when no DNA font is wired, a curated
Cyrillic-safe Google Fonts pair (display + body) is picked — by the selected
style preset first, otherwise by brief mood keywords — and locked into
`tokens.font`; sizes come from a modular type scale, not from the model's
imagination. Style preset chips on the node: Minimal, Bento, Editorial,
Brutal, Glass (payload field `preset`).

Taste layer (`app/designkb.py`): the brief is classified into a product type
(marketplace, SaaS, editorial, ecommerce, fintech, portfolio, edtech,
healthcare, event, food, landing). Each type carries curated light/dark
palettes, font-pair recommendations and UX rules distilled from public
design-knowledge sources; every variant gets its own palette locked into
`tokens.color`, plus an anti-"AI-design" cliché block in the prompt. DNA wire
still overrides everything. The detected type rides in the `design` response
field (shown in the node status).

Auto quality gate: every variant passes deterministic `qualitygate.autofix`
(WCAG AA contrast repair in OKLCH, 8px grid snap, frame overflow clamp,
tap-target ≥24px and font-size ≥12px per WCAG 2.2) before it reaches the
canvas; per-variant QA summary rides in the `qa` response field.

Responsive: variants carry `responsive.viewports` (1440/768/390) and template
sections render with fluid grids (`auto-fit/minmax`) — columns stack
automatically on narrow artboards (verified: 3-col pricing → 1 col at 390px),
so generated blocks adapt on Tablet/Mobile in Page and the DNA Editor without
any manual overrides.

Control direction:

- add seed;
- add count;
- add quality tier;
- ~~add project DNA input~~ — done: `tokens` input.

### Source Import

URL/screenshot → selectable blocks + Style DNA.

Default model routes:

- deterministic rendered DOM capture for compact hierarchy, auto-layout, colors and editable layers;
- `source_semantics` (only ambiguous blocks) → Claude Sonnet 5 → Claude Opus 5;
- `blockparse` repair fallback → Claude Sonnet 5 → Qwen3 Coder Plus;
- `vision` / `reproduce` → Claude Opus 5 → Gemini 3.6 Flash → Qwen3.8 Max.

Outputs:

- dynamic block ports: `ir`;
- `tokens: tokens`.

This is the primary bridge from inspiration to editable design.

Desktop, tablet and mobile are captured by default and merged by stable DOM
keys into one responsive `source-block` tree. The viewport switch changes the
Source preview without creating extra output ports. Source can show the browser
reference screenshot, reconstructed editable IR, or a compact comparison view.
Button, input and select layers own their text/value children; screenshots remain
QA references and are never rendered as DNA Editor canvas backgrounds. URL import
shows DOM coverage diagnostics; visual fidelity must come from geometry/pixel
checks, not a guessed percentage.

URL outputs are semantic page sections rather than raw HTML tags. Repeated products, services, slides or FAQ rows stay inside one block and expose repeat metadata such as `3× card → 1 block`. The node preview uses the exact browser screenshot; the connected port outputs editable `source-block` Design IR.

### Style DNA

Extracts project style tokens from IR/tokens.

Default model route: `tokens` / `style_analysis` → Claude Opus 5 → Claude Sonnet 5.

Inputs:

- `ir`
- `tokens`

Outputs:

- `tokens`
- `summary`

The fullscreen DNA Editor provides the visual Style DNA Inspector: semantic
palette, typography, spacing/radius primitives, binding counts and linked-layer
highlighting. It also owns the opt-in design-system workflow:

- `Preview Normalize` shows every proposed property change before mutation;
- `Apply Normalize` writes the previewed IR as one undoable editor operation;
- `Exact Tailwind` preserves measured values with arbitrary utilities;
- `Normalized Tailwind` prefers semantic Style DNA utilities and standard scales.

Tailwind is derived output and is never stored as the canonical design state.

### Derive

Creates a related component from selected block + Style DNA + prompt.

Default model route: `derive` → Claude Opus 5 → Claude Sonnet 5.

Example:

```text
Header IR + Style DNA + "make footer"
  → Footer in same project style
```

Inputs:

- `prompt: text`
- `reference: ir`
- `tokens: tokens`

Output: `ir`.

### Edit

Thin graph node.

Inside graph:

- read-only preview;
- open DNA Editor.

Fullscreen DNA Editor:

- manual Figma/Pen.dev-style editing;
- saves IR back to graph.

Input: `ir`.
Output: `ir`.

### Mix

Combines multiple IR inputs by weights.

Inputs:

- dynamic `ir` inputs `a`, `b`, `c`, `d`.

Output: `ir`.

Future: should expose “mix channels”:

- colors from A, layout from B;
- typography from A, components from B;
- 70/30 visual rhythm blend.

### Reskin

Changes selected visual aspects while preserving locked structure/layout.

Default model route: `reskin` → Claude Opus 5 → Claude Sonnet 5 → GPT-5.6 Sol.

Inputs:

- `ir`
- `tokens`

Output: `ir`.

Current mask:

- colors;
- fonts;
- radii;
- shadows;
- texts;
- images.

Future mask should include:

- layout;
- spacing;
- section order;
- component density;
- motion;
- responsive behavior.

### Page

Composer: assembles connected blocks (Generator / Source Import / Edit) into
one page. Deterministic, no LLM (`frontend/src/flow/compose.ts`).

Inputs:

- `tokens: style DNA` — wins over block tokens;
- dynamic `a..h: ir` (max 8) — row order = section order (drag rows or ↑/↓).

Output: `ir` — one page document: sections concatenated with unique ids and
sourceKeys, `width:"fill"` on a 1440 artboard, per-section responsive
overrides preserved. Tokens: style DNA wire > first block.

Responsive: the page carries document-level `responsive.viewports`
(desktop 1440 / tablet 768 / mobile 390) so per-node overrides from Source
Import keep working — mobile-only layers never leak into the desktop render.
Desktop/Tablet/Mobile switcher on the node re-materializes the preview and
propagates `meta.activeViewport` downstream (DNA Editor opens the same
viewport).

### Quality Pass

Evaluates and repairs IR.

Default model routes:

- `quality_judge` → Claude Opus 5 → Claude Sonnet 5 → GPT-5.6 Sol Pro;
- `quality_repair` → Claude Opus 5 → Claude Sonnet 5 → Qwen3 Coder Plus.

Input: `ir`.
Output: checked `ir`.

Should become the main trust layer:

- score;
- issues;
- deterministic checks;
- AI judge;
- repair log;
- before/after diff.

## Proposed killer nodes

### Project DNA

Collects accepted blocks, tokens and edits into project memory.

Inputs:

- `ir`
- `tokens`
- `feedback`

Outputs:

- `project_dna`
- `tokens`
- `rules`

Why it matters: this is the “AI learns my project style” node.

### Layout Lock

Freezes structure and geometry.

Inputs:

- `ir`

Outputs:

- `ir`
- `constraints`

Controls:

- lock section order;
- lock element count;
- lock frames;
- lock responsive rules.

### Constraints

Declarative rule node.

Examples:

- max headline length 48 chars;
- card radius 16-24px;
- no text below contrast AA;
- section gap 80-120px;
- preserve 12-column grid.

Output: `constraints`.

### Scoped Gen

Generate or replace only a selected part of IR.

Example:

```text
Page IR + selection "pricing.cards[1]" + prompt
  → only selected pricing card changes
```

This is critical for control.

### Attr Extract

Extract numeric parameters from a design:

- container width;
- spacing scale;
- card density;
- section rhythm;
- border widths;
- image aspect ratios.

Output: `attrs`.

### Attr Transfer

Transfer extracted parameters from one IR to another.

Example:

```text
Layout rhythm from Apple page
  → apply to SaaS landing page
```

### Token Override

Manual token edits as a node.

Example:

```text
primary = #6D5EF6
radius.card = 24
spacing.section = 96
```

### Wedge

Parameter sweep.

Example:

```text
Generate 3 densities × 3 moods = 9 controlled variants
```

Must show cost before running.

### Timeline

Version history as a node/side panel.

Use for:

- compare variants;
- restore accepted state;
- branch;
- explain what changed.

### Compare / Diff

Compare two IRs:

- visual diff;
- token diff;
- layout diff;
- tree diff;
- score diff.

This helps users trust transformations.

### Compose Page

Combine selected components into a full page.

Inputs:

- header;
- hero;
- feature;
- pricing;
- footer;
- Project DNA.

Output: page IR.

### Asset / HDA

Package a subgraph as a reusable asset.

Inspired by Houdini Digital Assets.

Should expose:

- public parameters;
- inputs/outputs;
- version;
- preview;
- license/author metadata.

### Data

CSV/JSON/API → real content in props.

Killer for vibe coders: goodbye lorem ipsum.

### Script

Deterministic JS transform over IR in a sandbox.

Use for:

- batch rename;
- map data to cards;
- enforce custom rules;
- procedural variations.

### Export

IR → production artifact:

- HTML/CSS;
- React/Svelte;
- Figma;
- design tokens;
- design documentation.

### Client Review

View-only link with comments, variants and approvals.

Important for freelancers/studios.

## Node design rule

Every node should answer:

1. What does it consume?
2. What does it produce?
3. What can be locked?
4. What is deterministic?
5. What costs tokens?
6. How does the user inspect the result?
