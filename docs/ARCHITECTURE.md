# Architecture

## Mental model

DesignAI Web has six cooperating layers:

```text
Node Graph
  → Design IR
  → Interaction IR
  → Motion IR
  → DNA Editor
  → AI Operations through OpenRouter
```

The graph controls process. Design IR controls design. The editor controls manual visual work. OpenRouter executes AI roles.

## Design IR

Design IR is the source of truth. The current schema version is **1.1**; see
`docs/adr/ADR-0001-ir-first-foundation.md` for the versioning, migration,
`sourceKey`, Tailwind-projection and AI-contract decisions introduced in
stage 0 of the long-term plan.

It contains:

- `tokens`: color, font, radius, spacing, shadow and theme values;
- `tree`: semantic page/component blocks;
- `frame`: Figma-like layout geometry;
- `_frames`: per-element overrides for manual edits;
- `meta`: name, description, style tags and provenance;
- `styleBindings` (1.1): maps style properties to Style DNA tokens without
  replacing the exact measured value;
- `constraints` (1.1): deterministic rules enforced before/after AI operations;
- `provenance` (1.1): origin metadata (`imported`, `generated`, `normalized`,
  `manual`).

AI nodes should return or transform IR. Manual edits should mutate IR. Mix and
quality operations should operate on IR. The backend migrates legacy 1.0
documents to 1.1 automatically on load or ingestion, so old projects open
without manual migration.

### Style normalization and Tailwind

Source Import remains exact by default. `/api/style/normalize/preview` returns
a normalized IR candidate plus a property-level patch and risk summary; the
editor applies it only after explicit confirmation. Normalization snaps design
rhythm properties such as gap, padding, font size and radius, while arbitrary
geometry remains exact.

`/api/export/tailwind` deterministically projects Design IR into theme variables
and per-viewport utility classes. Exact mode emits arbitrary utilities;
normalized mode uses semantic Style DNA utilities where bindings exist. The
projection carries the IR content hash and can be regenerated at any time, so
Tailwind never competes with Design IR as a second source of truth.

### Fluid responsive editing

The canonical anchors remain 390, 768 and 1440 px. DNA Editor also accepts any
preview width from 320 to 2560 px and resolves mobile below 640, tablet from 640
through 1023, and desktop from 1024. Within a range, `fill`, `hug`, min/max,
auto-layout and wrap continue to control fluid geometry. Inspector badges show
whether frame/style comes from shared data or the active device override, with
explicit Reset override, Apply to all and Copy to breakpoint operations.

### Interaction IR

Interaction IR is a versioned, derived workflow artifact. It references an
immutable Design IR content hash and stores events plus replayable JSON patches
for named scenes. Patch roots are restricted to renderable Design IR fields;
the backend validates scene references before replay.

The graph Recorder captures actions from a rendered Design IR preview or replays
a transient script against an owned live URL in Chromium. Live capture is
same-origin, guarded by the public-URL validator and requires explicit ownership
confirmation. Typed values stay in component memory for one request and never
enter graph persistence; the backend then performs a second recursive cleanup
for emails, phones, credentials and tokens. CSS selectors are execution-only
and are not included in Interaction IR.

### Motion IR

Motion IR is a versioned montage artifact derived from Interaction IR. It owns
composition size, frame rate, contiguous scene timing, transitions, tracks and
markers, but never embeds copies of Design IR scenes. Each motion scene points
to an Interaction IR scene; `/api/motion/build` materializes preview Design IR
through deterministic replay and returns those previews outside the canonical
Motion IR document.

The fullscreen Motion Editor edits scene duration, transition type/duration and
easing, supports 16:9, 9:16 and 1:1 compositions, and provides transport,
scrubbing and proportional scene clips. Applying changes rebuilds and validates
Motion IR on the backend.

### Deterministic video render

`app/motion_render.py` maps each output frame number to an exact Motion IR time,
renders materialized scenes with the existing `renderer.js`, and composes
cut/fade/slide/zoom transitions without wall-clock animation. PNG frames are
streamed to a bundled FFmpeg binary with fixed single-threaded settings for
repeatable MP4/H.264 or WebM/VP9 output.

`POST /api/motion/render` verifies the Design/Interaction/Motion hash chain and
queues one local render at a time. Status and progress are read through the job
endpoint; downloads resolve only artifacts registered by that server process.
The video is a derived artifact and is never written into Motion IR or project
graph persistence.

## Graph

The graph is a procedural design workflow.

Current wire kinds:

- `text` — prompts, summaries, instructions;
- `ir` — full editable Design IR;
- `tokens` — Style DNA without the full tree;
- `interaction` — sanitized events and replayable Design IR scenes;
- `motion` — validated timeline and render composition metadata.

Rules:

- ports are typed;
- cycles are rejected;
- one input has one active wire;
- compatible node snap helps connect wires quickly;
- graph state autosaves to SQLite as the durable project store, with compact
  localStorage kept as a fast browser cache/fallback.

## OpenRouter-only AI gateway

The UI must not expose direct provider selection.

All AI calls go through OpenRouter. Model choice is internal role routing:

- `generator`
- `reskin`
- `blockparse`
- `reproduce`
- `quality_judge`
- `quality_repair`
- `style_analysis`
- `repair`

The user buys product operations, not raw models.

Default model strategy is quality-first:

- Claude Opus 5 is the primary model for design generation, reskin, edit, style analysis and design judging.
- Claude Opus 5 is reserved for the future Motion Director role that will emit
  validated Motion IR patches; enabling the route does not mark AI Director complete.
- Claude Sonnet 5 is the fallback/default for faster structured design operations such as block parsing.
- Claude Opus 5 is also the default Quality Pass judge; avoid ultra-expensive judge models in the default subscription path.
- Gemini 3.6 Flash is a vision fallback for screenshot/reference parsing.
- Qwen3 Coder Plus is reserved for IR/JSON/schema repair and mechanical optimization.
- Kimi is not a default route; it can be tested through `OPENROUTER_MODELS_<ROLE>` if needed, but should not drive product quality by default.

OpenRouter Videos is a separate asynchronous gateway for optional generative
assets. Product tiers map to `Seedance 2.0 Fast` (Draft), `Seedance 2.0`
(Studio) and `Veo 3.1` (Cinematic). These models are for B-roll and visual
inserts. UI walkthroughs continue to use deterministic Motion IR rendering so
text, controls and layout do not drift between frames. Paid submissions require
an explicit confirmation at the API boundary.

The default routing lives in `app/llm_client.py`. Keep it invisible to end users; later the product can expose quality tiers such as Draft, Studio and Max without exposing raw providers.

## Source Import

Source Import is the single user-facing import node.

URL import is a hybrid pipeline. No LLM is allowed to invent geometry:

1. Chromium renders the real page, including client-side JS.
2. Block detection runs on the live rendered DOM (never on raw fetched HTML), so selectors always resolve in the capture document. DOM semantics, headings, id/class signals and visual order define section candidates.
3. Repeated cards/slides/categories are grouped under their parent section; they never become duplicate output ports.
4. Significant DOM containers, controls, images, SVG and direct text nodes compile into a compact editable tree.
5. Flex/grid geometry becomes nested auto-layout; absolute positioning is reserved for actual overlays and transforms.
6. Desktop, tablet and mobile captures merge by stable DOM keys into one tree with breakpoint frame/style/visibility overrides; sourceKey uniqueness is enforced after the merge.
7. Exact screenshots remain visual QA references for Source node previews; editable IR is the only editor canvas artifact.
8. Style tokens are measured from the rendered page (colors, font families/weights, radii, shadows, spacing, container width) and mapped onto the schema token contract — imported blocks carry the site's real Style DNA, not generic defaults.
9. Each block reports a `fidelity` score: the reconstructed IR is re-rendered by `renderer.js` and pixel-compared against the reference screenshot, so reconstruction drift is a number, not a guess.

The measured block size is written to both the IR artboard frame and the
`source-block` frame for each viewport. DNA Editor never renders the screenshot
as a background: users select and move the reconstructed components themselves.
Unsupported local canvas/video elements may use an explicitly warned raster
fallback for that element only. Saved free-layout source nodes remain supported
by inferring the artboard from their single measured `source-block`.

Expected output is page-level meaning: header, carousel/hero, categories, product/service grids, trust/features, journal, how-it-works, CTA, FAQ and footer. A grid of multiple product cards is one block with repeat metadata, not many unrelated `article` outputs.

The AI role `source_semantics` runs only for ambiguous containers. Claude Sonnet 5 labels existing candidates; Claude Opus 5 is the fallback. Selectors, order, dimensions, colors and layout remain deterministic. Using Opus to guess pixels would be slower, more expensive and less accurate than browser measurement.

Internal backend operations:

- URL import via `/api/block-parse`;
- screenshot reproduction via `/api/reproduce`.

Old UI nodes `Clone`, `Reproduce`, `BlockParse` are removed because they duplicated the same conceptual job.

## DNA Editor

The Edit node in the graph is intentionally thin:

- preview only;
- open fullscreen DNA Editor;
- save IR back to graph;
- propagate downstream.

The fullscreen editor owns the Figma/Pen.dev-like work:

- layers;
- selection;
- inspector;
- drag/resize;
- hand pan;
- rect/text/frame tools;
- undo;
- lock/hide;
- math inputs and scrub.

This avoids two competing editors and keeps architecture clean.

## Controlled AI mechanisms

### Locks

A node should be able to lock:

- structure/tree topology;
- layout/frame geometry;
- colors;
- fonts;
- spacing;
- radii;
- text;
- images;
- component count;
- section order.

### Merge-back

AI output is not trusted blindly.

For protected fields:

```text
input IR + model output + lock mask
  → merge-back
  → valid controlled IR
```

The model can suggest changes only in unlocked areas.

### Constraints

Constraints are deterministic rules over IR:

- width ranges;
- spacing ranges;
- allowed colors;
- max text length;
- required contrast;
- required block types;
- no overflow.

Constraints should run before/after AI operations.

### Quality Pass

Quality Pass should combine:

- deterministic checks;
- AI judge;
- targeted repair;
- rejudge;
- scorecard.

It is the “anti-slop” layer.

## Project memory

Project memory should be per-project and opt-in.

It should learn from:

- selected Source Import blocks;
- accepted generated variants;
- manual DNA Editor edits;
- repeated token choices;
- rejected variants;
- Quality Pass outcomes.

Suggested memory layers:

1. **Style DNA** — tokens and visual rhythm.
2. **Component DNA** — accepted blocks and reusable patterns.
3. **Layout DNA** — grid, spacing, density, section order.
4. **Taste Memory** — subjective likes/dislikes inside the project.
5. **Rules Memory** — constraints the user repeatedly applies.

Memory should never silently override the graph. It should be visible as nodes/tokens/rules.

Current implementation:

- `/api/project/save` persists the compact pages project to local SQLite
  (`data/projects.db`);
- `/api/project/load` restores the user's project even after browser storage is
  cleared;
- SQLite stores the full pages project, including Source Import screenshot
  previews; localStorage keeps only a compact browser cache with screenshot
  previews removed;
- a first `Taste Memory` profile is rebuilt from prompt text, accepted/generated
  IR, Source Import blocks and style tokens;
- `/api/generate` appends that taste profile as soft prompt guidance. Explicit
  user instructions and connected Style DNA remain higher priority.

## Future export layer

Important future outputs:

- HTML/CSS;
- React/Svelte components;
- Figma export;
- design system docs;
- shareable review links;
- headless API for assets.

Export should consume IR, not bypass it.
