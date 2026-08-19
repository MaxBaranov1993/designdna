# DesignDNA

A local-first AI web-design studio. A node-graph pipeline generates, imports, edits and
animates web designs around a canonical, schema-validated **Design IR** — the LLM never
owns the truth, the schema does.

Runs fully on `127.0.0.1:8420`. No external services except the OpenAI / Kimi APIs for
generation roles.

## Desktop runtime

DesignDNA now has a single desktop runtime: the SvelteKit editor and Project Map run in one Electron window, while the existing Python ASGI application and Repo Canvas execute as internal stdio workers. Production desktop mode opens no local HTTP ports.

```bash
npm run frontend:install
npm run repo-canvas:install
npm run desktop:install
npm run desktop:start
```

The standalone FastAPI and Repo Canvas server commands are retained only for browser development/compatibility. See [desktop runtime architecture](docs/architecture/desktop-runtime.md).

## What it does

- **Flow graph UI** (Svelte Flow): prompt → generate → edit → reskin → quality-pass →
  motion → video-render nodes wired on a canvas; projects persist in SQLite.
- **Design IR** (`schema/`): versioned JSON schema for semantic web documents
  (sections, tokens, style bindings, responsive viewports). Every AI output is
  validated, repaired and merged back through deterministic code.
- **LLM generation** directly via the OpenAI and Kimi APIs with role-based model routing
  (fallback chains, env-overridable; chain entries without a configured key are skipped,
  so whichever account is connected is used) and a token-saving cache (`/api/cache/stats`).
- **Quality pipeline**: deterministic Quality Gate (autofix without an LLM) plus an
  LLM judge pass with a repair/re-judge loop.
- **Source Import** (pixel-faithful DOM capture of real sites):
  - captures computed styles, geometry and the site's own `@font-face` fonts into a
    local font base (`data/fonts`, served at `/fonts/{name}`) so text metrics match
    the source;
  - collapses inline-flow paragraphs (`<p>` + `<strong>/<a>`) into single text runs;
  - margin-aware layout: measured gaps for block containers, free-layout pinning when
    margins are uneven or a flex row uses child margins;
  - a deterministic QA pass pins containers to absolute coordinates whenever reflow
    drift would overflow the captured size (`meta.qaWarnings` journal).
- **Style DNA**: design-token panel with semantic bindings, normalize preview and
  Tailwind projection/export.
- **DNA Editor** (fullscreen canvas editor, Figma-grade): marquee & shift/ctrl
  multi-select, smart guides with equal-spacing labels, constraints, groups,
  z-order, clipboard (Ctrl+A/C/X/V, Ctrl+D duplicate), right-click context menu,
  color picker (SV area + hue + HEX + IR token swatches), flyout tool rail,
  nudge undo-batching, rulers, responsive viewport switching, layers panel with
  search/hide/lock, undo/redo history.
- **Motion**: live interaction capture on a source site → Interaction IR →
  deterministic Motion IR → local video render (hash-linked integrity between IRs).

## Repository layout

```
app/            FastAPI backend
  server.py     all API routes (port 8420; serves /static and the font base at /fonts)
  scraper.py    Source Import: DOM capture, font base, QA pass
  blockparse.py block detection / LLM clone pipeline
  llm_client.py OpenAI/Kimi client, role routing, system prompts
  qualitygate.py, mergeback.py, reproduce.py, motion_render.py, ...
  static/flow/  built SvelteKit app + engine.js (IIFE engine bundle for headless renders)
frontend/       Svelte 5 + TS + Vite source (flow graph, DNA editor, inspector)
  src/engine/   Design-IR engines as TS modules: renderer (IR→DOM), geoedit
                (Figma geometry), irhistory (undo/redo), fontCatalog
  src/editor/   DNA editor: session controller + Svelte panels
schema/         Design IR / Interaction IR / Motion IR JSON schemas
spike/          generation spike scripts + system prompt template
app/*_test.py   Playwright UI suite (needs a running server)
```

## Quick start

Requirements: Python 3.11+, Node 18+, Playwright Chromium.

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

Unit / IR tests (no server needed):

```bash
.venv\Scripts\python -m pytest app/llm_client_test.py app/test_mergeback.py \
  app/test_qualitygate.py app/interaction_ir_test.py app/motion_ir_test.py \
  app/typography_test.py app/designkb_test.py app/urlguard_test.py
.venv\Scripts\python app/source_import_qa_test.py
```

Pixel / UI suite (start the server first, `app/server.py`):

```bash
.venv\Scripts\python app/source_import_pixel_test.py   # capture fidelity <= 3px
.venv\Scripts\python app/ui_editor_test.py             # DNA editor basics
.venv\Scripts\python app/ui_editor_parity_test.py      # rulers/viewports/flyout/DNA
.venv\Scripts\python app/ui_eq_marquee_test.py         # multi-select, guides, marquee
# ...see app/ui_*_test.py for the full set
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

- Binds to localhost only; scrape endpoints are behind an SSRF guard
  (`urlguard.validate_public_url`); live interaction capture requires an explicit
  "this is my site / I have permission" confirmation in the UI.
- `.env` (API keys) and `data/` (projects, caches, font base) are gitignored.

## Acknowledgements

Editor UX patterns (nudge batching, context menu, color picker, flyout tools) adapted
from [OpenPencil](https://github.com/open-pencil/open-pencil) (MIT) and Figma
conventions; the website-import pipeline was informed by
[html.to.design](https://html.to.design).

## Status

Personal R&D project, active development. Schemas are versioned (`design-ir 1.0/1.1`)
and migrations live in `app/ir/migrate.py`.
