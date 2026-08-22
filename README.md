# DesignDNA

A local-first AI web-design studio. A node-graph pipeline generates, imports, edits and
animates web designs around a canonical, schema-validated **Design IR** — the LLM never
owns the truth, the schema does.

Runs fully on `127.0.0.1:8420`. No external services except the OpenAI / Kimi APIs for
generation roles.

## Desktop runtime

DesignDNA has a single desktop runtime: the SvelteKit editor and Project Map run in one
Electron window, while the Python ASGI application and Repo Canvas execute as internal
stdio workers. Production desktop mode opens no local HTTP ports. A second interactive
Python worker keeps fast editor requests from queueing behind long Source Import jobs.

```bash
npm run frontend:install
npm run repo-canvas:install
npm run desktop:install
npm run desktop:start
```

The standalone FastAPI and Repo Canvas server commands are retained only for browser
development/compatibility. See [desktop runtime architecture](docs/architecture/desktop-runtime.md).

## What it does

- **Flow graph UI** (Svelte Flow): prompt → generate → edit → reskin → quality-pass →
  motion → video-render nodes wired on a canvas; projects persist in SQLite.
- **Design IR** (`schema/`): versioned JSON schema for semantic web documents.
  Runtime version is 1.1; the opt-in 2.0 contract adds multi-source composition
  (`docs/DESIGN-IR-V2.md`). Every AI output is validated, repaired and merged back
  through deterministic code.
- **LLM generation** directly via the OpenAI and Kimi APIs with role-based model routing
  (fallback chains, env-overridable) and a token-saving cache (`/api/cache/stats`).
- **ZCode provider (no API key)**: if no API account is connected, generation
  automatically runs through the locally installed, logged-in ZCode CLI
  (Z.AI coding plan) — `provider: "zcode"` is also selectable explicitly in the
  node pickers. Text roles only; vision roles stay on direct APIs. First call
  bootstraps `~/.zcode/cli/config.json` from the ZCode app config.
- **Quality pipeline**: deterministic Quality Gate (autofix without an LLM) plus an
  LLM judge pass with a repair/re-judge loop.
- **Source Import** (pixel-faithful DOM capture of real sites):
  - one page load per URL; viewports are re-captured by resize with deterministic
    settle (fonts/images/rAF), CSS Grid becomes measured free layout with pinned
    children;
  - honest per-viewport coverage: `visited/emitted/dropped` counters, area-based
    paint coverage, and coverage capped below 100% whenever a visual channel is lost;
  - capture of transforms, z-index, `background-image`/gradient stacks,
    `::before`/`::after`, `clip-path`/`mask-image`, variable fonts and
    `unicode-range` subsets; the site's `@font-face` fonts go into a local font base
    (`data/fonts`, served at `/fonts/{name}`) so text metrics match the source;
  - non-editable surfaces (canvas/WebGL, cross-origin iframes, closed shadow DOM,
    complex transforms, url() masks) become **locked raster layers** — visible,
    selectable, never editable, with an explicit reason;
  - stable per-block `sourceKey` addressing: imported pages are fully editable
    (move/resize/reorder/group/duplicate remap by key); the Page node composes
    blocks into an auto-height artboard;
  - authenticated import: in the desktop app, "Source Login" opens an isolated
    session window and passes host-scoped cookies to the capture request;
  - a fail-closed **fidelity harness** gates the capture cache: the captured IR is
    re-rendered by the same engine the editor uses and compared at exact viewport
    size (no resampling) — see Tests below.
- **Style DNA**: design-token panel with semantic bindings, normalize preview and
  Tailwind projection/export.
- **DNA Editor** (fullscreen canvas editor, Figma-grade): marquee & shift/ctrl
  multi-select, smart guides, constraints, groups, z-order, clipboard, context menu,
  color picker, flyout tool rail, nudge undo-batching, rulers, responsive viewports,
  layers panel with search/hide/lock, undo/redo history.
- **AI editor actions** (preview → atomic apply → undo, never invisible mutations):
  Smart Axis width alignment, Style DNA Harmonizer, Quality Copilot, Responsive
  Autopilot, Intent Locks, semantic selection, selection-scoped AI edits
  (`docs/AI-EDITOR-ROADMAP.md`).
- **Motion**: live interaction capture on a source site → Interaction IR →
  deterministic Motion IR → local video render (hash-linked integrity between IRs).

## Repository layout

```
app/            FastAPI backend
  server.py     all API routes (port 8420; serves /static and the font base at /fonts)
  scraper.py    Source Import: DOM capture, font base, QA pass
  source_import_compiler.js  in-page DOM→IR compiler (embedded by scraper.py)
  blockparse.py block detection / LLM clone pipeline
  llm_client.py OpenAI/Kimi client, role routing, system prompts
  fidelity_harness.py  honest IR-vs-source pixel/layout gate (CLI)
  fixtures/     golden HTML fixtures for capture/fidelity tests
  static/flow/  built SvelteKit app + engine.js (IIFE engine bundle for headless renders)
frontend/       Svelte 5 + TS + Vite source (flow graph, DNA editor, inspector)
  src/engine/   Design-IR engines as TS modules: renderer (IR→DOM), geoedit
                (Figma geometry), locked (locked-layer contract), sourcepath
                (sourceKey addressing), irhistory (undo/redo), fontCatalog
  src/editor/   DNA editor: session controller + Svelte panels
  tests/        engine regression tests (node, no browser)
desktop/        Electron host: JSONL workers, provider credentials, source auth
schema/         Design IR (1.0/1.1/2.0) / Interaction IR / Motion IR JSON schemas
spike/          generation spike scripts + system prompt template
app/*_test.py   pytest unit suite + standalone Playwright scripts (UI ones need a server)
desktop/tests/  Electron main-process tests (node:test)
```

## Quick start

Requirements: Python 3.11+, Node 22+, Playwright Chromium.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows
.venv\Scripts\python -m playwright install chromium

cd frontend && npm ci && npm run build && cd ..      # builds app/static/flow

echo OPENAI_API_KEY=... > .env                     # and/or KIMI_API_KEY=...
start.bat                                            # or: .venv\Scripts\python app\server.py
```

Open http://127.0.0.1:8420 — the flow graph is at `/flow`.

Feature flags: `DESIGNAI_FLAG_<NAME>=0|1` environment variables
(see `app/config/flags.py`). Model routing overrides: `LLM_MODELS_<ROLE>` env vars.

## Tests

Python unit / IR tests (no app server needed; same command as CI — covers the
2.0 composition contract, the capture pipeline and the golden `chess_arena`
fidelity fixture; requires the built `app/static/flow/engine.js` and Playwright
Chromium):

```bash
.venv\Scripts\python -m pytest -q app
```

Pixel / UI suite (standalone scripts — start the server first, `app/server.py`):

```bash
.venv\Scripts\python app/source_import_pixel_test.py        # capture fidelity <= 3px
.venv\Scripts\python app/ui_page_artboard_editability_test.py
.venv\Scripts\python app/ui_editor_test.py                  # ...see app/ui_*_test.py
```

Fidelity harness against any live URL or fixture (exit 1 when the gate fails):

```bash
.venv\Scripts\python app/fidelity_harness.py https://example.com --out results/run-1
.venv\Scripts\python app/fidelity_harness.py --fixture chess_arena.html --out results/fixture
```

Engine and desktop (Node, no browser/server):

```bash
cd frontend && npm run test:engine
npm run desktop:test
```

## Project Map (Repo Canvas)

Repo Canvas is integrated as the **Project Map** surface inside the DesignDNA desktop
window. Its event store and architect remain under `tools/repo-canvas/`, but the
desktop app runs them through an internal stdio worker—there is no second production
server or port.

```bash
npm run repo-canvas:install
npm run repo-canvas:setup
npm run desktop:start
```

Use the root Repo Canvas CLI commands for diagnostics and maintenance. See
[docs/repo-canvas.md](docs/repo-canvas.md) for provenance and operational details.

## Security notes

- Binds to localhost only; scrape endpoints and font downloads are behind an SSRF
  guard (`urlguard.validate_public_url`); live interaction capture requires an
  explicit "this is my site / I have permission" confirmation in the UI.
- Source Login cookies live in an isolated Electron session partition, are
  host-scoped and sanitized before injection into the capture request.
- `.env` (API keys) and `data/` (projects, caches, font base) are gitignored.

## Acknowledgements

Editor UX patterns (nudge batching, context menu, color picker, flyout tools) adapted
from [OpenPencil](https://github.com/open-pencil/open-pencil) (MIT) and Figma
conventions; the website-import pipeline was informed by
[html.to.design](https://html.to.design).

## Status

Personal R&D project, active development. Supported schema versions: `1.0`, `1.1`
(runtime) and `2.0` (composition contract, opt-in). Migrations live in
`app/ir/migrate.py`.
