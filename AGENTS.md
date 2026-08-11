# AGENTS.md

This repository is DesignAI Web: a controlled AI web-design editor.

Read first:

1. `docs/PRODUCT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/NODES.md`
4. `docs/DEVELOPMENT.md`

## Product direction

The product is **Figma + controlled AI** with a ComfyUI/Houdini/Substance-style graph.

Primary users:

- vibe coders / AI builders;
- freelance web designers.

Core promise:

- AI proposes, the user controls;
- Design IR is the source of truth;
- structure, layout, tokens and style can be locked;
- project style memory should emerge from selected references, generated blocks and manual edits;
- graph workflows should be reusable like Houdini Digital Assets.

## Current frontend contract

- React + TypeScript app lives in `frontend/src`.
- Built app is emitted into `app/static/flow`.
- Graph UI uses React Flow + Zustand.
- Legacy rendering/editor runtime is vanilla JS in `app/static`:
  - `renderer.js`
  - `geoedit.js`
  - `inspector.js`
  - `irhistory.js`
  - `editor.js`
- Do not rewrite the editor runtime unless the task explicitly requires it.
- Edit node is a thin node: preview only + open fullscreen DNA Editor.
- All AI UI nodes must route through OpenRouter, not direct provider selection.

## Current nodes

Prompt, Reference, Generator, Source Import, Style DNA, Derive, Edit, Mix, Page, Reskin, Quality Pass, Page Bridge.

Old UI nodes `Clone`, `Reproduce`, `BlockParse` are removed. Backend operations may remain as internal engines for Source Import/cache.

## Development rules

- Use PowerShell commands on Windows.
- Use `rg` for search.
- Use `apply_patch` for edits.
- Keep docs aligned with product direction.
- Do not commit or push unless the user explicitly asks.
- Avoid broad rewrites unless the user asks for architecture cleanup.
- Preserve user changes in the dirty worktree.

## Verification

Frontend:

```powershell
cd frontend
npm run build
```

Core UI tests:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -u app\ui_flow_graph_test.py
.venv\Scripts\python.exe -u app\ui_flow_nodes_test.py
.venv\Scripts\python.exe -u app\ui_flow_page_test.py
.venv\Scripts\python.exe -u app\ui_flow_edit_test.py
.venv\Scripts\python.exe -u app\ui_editor_test.py
```

Editor quality tests:

```powershell
.venv\Scripts\python.exe -u app\ui_p1_insp_test.py
.venv\Scripts\python.exe -u app\ui_p1_layers_test.py
.venv\Scripts\python.exe -u app\ui_fill_drag_test.py
```

Final sanity:

```powershell
git diff --check
```
