# DesignAI Web

A local-first AI web-design studio. A node-graph pipeline generates, imports, edits and
animates web designs around a canonical, schema-validated **Design IR** — the LLM never
owns the truth, the schema does.

Runs fully on `127.0.0.1:8420`. No external services except the OpenRouter API for
generation roles.

## What it does

- **Flow graph UI** (React Flow): prompt → generate → edit → reskin → quality-pass →
  motion → video-render nodes wired on a canvas; projects persist in SQLite.
- **Design IR** (`schema/`): versioned JSON schema for semantic web documents
  (sections, tokens, style bindings, responsive viewports). Every AI output is
  validated, repaired and merged back through deterministic code.
- **LLM generation** via OpenRouter with role-based model routing (fallback chains,
  env-overridable) and a token-saving cache (`/api/cache/stats`).
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
  llm_client.py OpenRouter client, role routing, system prompts
  qualitygate.py, mergeback.py, reproduce.py, motion_render.py, ...
  static/flow/  built React app + engine.js (IIFE engine bundle for headless renders)
frontend/       React + TS + Vite source (flow graph, DNA editor, inspector)
  src/engine/   Design-IR engines as TS modules: renderer (IR→DOM), geoedit
                (Figma geometry), irhistory (undo/redo), fontCatalog
  src/editor/   DNA editor: session controller + React panels
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

echo OPENROUTER_API_KEY=... > .env                   # your key
start.bat                                            # or: .venv\Scripts\python app\server.py
```

Open http://127.0.0.1:8420 — the flow graph is at `/flow`.

Feature flags: `DESIGNAI_FLAG_<NAME>=0|1` environment variables
(see `app/config/flags.py`). Model routing overrides: `ROUTING_*` env vars.

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

## Repository Canvas

The semantic repository map and live AI-agent session navigator are included in this
repository under `tools/repo-canvas/`.

```bash
npm run repo-canvas:install
npm run repo-canvas:setup
npm run repo-canvas:start
```

Repo Canvas opens on a protected loopback URL (port 4173) and maps the complete
DesignDNA Git root. See [docs/repo-canvas.md](docs/repo-canvas.md) for architecture,
provenance and all commands.

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
