# DesignDNA

**Local-first AI design studio for building, importing, editing, and animating production-ready web interfaces.**

DesignDNA combines a visual node graph, a Figma-like editor, deterministic rendering, and LLM-assisted generation around a schema-validated **Design IR**. The model proposes changes; the structured document remains the source of truth.

> Active R&D project focused on AI-native design workflows, controllable generation, and editable design-to-code systems.

## Why DesignDNA

Most AI design tools generate a one-shot result that becomes difficult to control once the first prompt is finished. DesignDNA takes a different approach: every design is represented as structured, versioned data that can be inspected, edited, transformed, validated, and rendered deterministically.

The goal is to combine the speed of generative AI with the precision of professional design tools.

## Core capabilities

- **Node-based workflow** — compose generation, import, editing, reskinning, quality, motion, and video-render steps visually.
- **Design IR** — versioned JSON schemas define sections, layout, tokens, responsive behavior, and semantic bindings.
- **DNA Editor** — fullscreen visual editor with multi-select, smart guides, constraints, layers, rulers, color tools, clipboard actions, z-order, and undo/redo.
- **Source Import** — capture existing web interfaces with computed styles, geometry, fonts, and deterministic QA checks.
- **Style DNA** — extract and edit reusable design tokens and semantic style bindings.
- **AI model routing** — role-based routing across OpenAI and Kimi models with fallback chains and caching.
- **Quality pipeline** — deterministic validation and autofix followed by optional model-based review and repair.
- **Motion pipeline** — convert captured interactions into structured Interaction IR and Motion IR for reproducible animation and video output.
- **Local-first desktop runtime** — the editor and project map run as a single Electron application without exposing production HTTP ports.

## Architecture

```text
Prompt / Imported Website
          │
          ▼
     Node Graph
          │
          ▼
   Schema-validated
      Design IR
     ┌────┼────┐
     ▼    ▼    ▼
  Editor Style Motion
     │    DNA    │
     └────┼──────┘
          ▼
 Deterministic Renderer
          │
          ▼
   Web / Video Output
```

### Repository structure

```text
app/            Python backend, import pipeline, quality gates, rendering
frontend/       Svelte 5 + TypeScript visual editor and node graph
desktop/        Electron desktop runtime
schema/         Design IR / Interaction IR / Motion IR schemas
tools/          Project Map / repository intelligence tooling
spike/          Generation experiments and evaluation scripts
```

## Technology

**Frontend**
- Svelte 5
- TypeScript
- Vite
- Svelte Flow

**Runtime & backend**
- Python
- FastAPI
- Electron
- SQLite

**AI**
- OpenAI API
- Kimi API
- Role-based model routing
- Structured generation and validation

**Quality & testing**
- Playwright
- Pytest
- Pixel-fidelity checks
- Schema validation
- Deterministic repair pipelines

## Desktop development

Requirements: Python 3.11+, Node.js 22+, Playwright Chromium.

```bash
npm run frontend:install
npm run repo-canvas:install
npm run desktop:install
npm run desktop:start
```

For browser development, the standalone FastAPI runtime remains available for compatibility.

## Testing

```bash
.venv\Scripts\python -m pytest app/llm_client_test.py app/test_mergeback.py \
  app/test_qualitygate.py app/interaction_ir_test.py app/motion_ir_test.py \
  app/typography_test.py app/designkb_test.py app/urlguard_test.py
```

The repository also contains browser, editor, interaction, and pixel-fidelity test suites.

## Design principles

1. **The schema owns the truth** — not the language model.
2. **Generation must remain editable** — AI output should become a design system, not a dead image.
3. **Deterministic operations first** — use model calls where they add value, not where normal code is more reliable.
4. **Local-first by default** — project data and editing workflows stay on the user's machine.
5. **One workflow from reference to production** — import, generate, edit, validate, animate, and export from the same structured representation.

## Security

- Localhost-only development server.
- SSRF protection for import endpoints.
- API keys and local project data are excluded from Git.
- Live-site interaction capture requires explicit permission confirmation.

## Status

**Active development.** Design IR schemas are versioned and migration logic is maintained in the repository.

## Acknowledgements

Some editor interaction patterns are inspired by Figma conventions and OpenPencil. The website-import workflow was informed by tools such as html.to.design.

---

Built as an independent product experiment exploring the future of AI-native interface design.
