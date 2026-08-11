# Development

## Run

```powershell
cd C:\Users\iamma\Documents\desingaiweb
.venv\Scripts\python.exe app\server.py
```

Open:

```text
http://127.0.0.1:8420/flow
```

## Build frontend

```powershell
cd frontend
npm run build
```

The build writes to:

```text
app/static/flow
```

Vite warnings about legacy scripts are expected:

- `/static/renderer.js`
- `/static/geoedit.js`
- `/static/inspector.js`
- `/static/irhistory.js`
- `/static/editor.js`

They are intentionally loaded as globals.

## AI key

All AI goes through OpenRouter.

```powershell
$env:OPENROUTER_API_KEY="..."
```

`.env` is loaded by `app/llm_client.py` when present.

## Important files

Frontend:

- `frontend/src/App.tsx` — React Flow shell.
- `frontend/src/flow/ports.ts` — node definitions, ports, menu.
- `frontend/src/flow/store.ts` — graph state and node execution.
- `frontend/src/nodes/*` — React node UI.
- `frontend/src/nodes/EditNode.tsx` — thin preview + open DNA Editor.

Backend:

- `app/server.py` — FastAPI routes.
- `app/llm_client.py` — OpenRouter routing.
- `app/blockparse.py` — URL block import.
- `app/reproduce.py` — screenshot/site reproduction.
- `app/mergeback.py` — protected-field merge-back.
- `app/qualitygate.py` — deterministic quality checks.

Editor runtime:

- `app/static/renderer.js`
- `app/static/geoedit.js`
- `app/static/inspector.js`
- `app/static/irhistory.js`
- `app/static/editor.js`

Schema:

- `schema/design-ir.schema.json`

Prompt/block catalog:

- `spike/system-prompt.md`
- `docs/BLOCKS.md`

## Core tests

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -u app\ui_flow_graph_test.py
.venv\Scripts\python.exe -u app\ui_flow_nodes_test.py
.venv\Scripts\python.exe -u app\ui_flow_edit_test.py
.venv\Scripts\python.exe -u app\ui_editor_test.py
.venv\Scripts\python.exe -u app\source_import_test.py
.venv\Scripts\python.exe -u app\ui_source_import_editor_test.py
```

`source_import_test.py` captures the responsive header fixture in Chromium and
checks compact nesting, control ownership, three linked viewports and schema
validity. `ui_source_import_editor_test.py` checks viewport switching, the absence
of a screenshot underlay, component-first selection and auto-layout drag detach.

Editor tests:

```powershell
.venv\Scripts\python.exe -u app\ui_edit_test.py
.venv\Scripts\python.exe -u app\ui_p1_insp_test.py
.venv\Scripts\python.exe -u app\ui_p1_layers_test.py
.venv\Scripts\python.exe -u app\ui_fill_drag_test.py
.venv\Scripts\python.exe -u app\style_projection_test.py
.venv\Scripts\python.exe -u app\ui_style_projection_test.py
.venv\Scripts\python.exe -u app\ui_fluid_responsive_test.py
```

Style-system API:

```text
POST /api/style-dna/extract
POST /api/style-dna/apply
POST /api/style/normalize/preview
POST /api/export/tailwind
```

Normalize returns a candidate IR and never persists it. The DNA Editor owns the
explicit apply step. Tailwind responses are derived artifacts and must not be
written back into Design IR.

Sanity:

```powershell
git diff --check
```

## Product architecture rules

### 1. Design IR first

Do not build features that bypass IR.

Bad:

```text
AI → random HTML → hidden state
```

Good:

```text
AI → Design IR → preview/editor/export
```

### 2. Edit node stays thin

The graph node should not become a mini-Figma.

It should:

- show preview;
- open fullscreen DNA Editor;
- save IR;
- propagate.

All manual design work belongs in fullscreen DNA Editor.

### 3. OpenRouter only

No UI provider dropdowns.

The user chooses product operation. The system chooses role/model internally.

### 4. Controlled AI over raw AI

Every AI feature should expose:

- lock mask;
- constraints;
- quality report;
- diff or log;
- cost awareness when expensive.

### 5. Project memory must be visible

Project learning should be represented as nodes/assets/tokens/rules, not hidden magic.

## Documentation rule

If behavior changes, update one of:

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/NODES.md`
- `docs/ROADMAP.md`
- `docs/DEVELOPMENT.md`
- `docs/BLOCKS.md`
