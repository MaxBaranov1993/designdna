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
- `app/motion_render.py` — frame-exact Chromium compositor and FFmpeg encoder.
- `app/video_client.py` — confirmed asynchronous OpenRouter Videos gateway.

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
.venv\Scripts\python.exe -u app\interaction_ir_test.py
.venv\Scripts\python.exe -u app\interaction_capture_test.py
.venv\Scripts\python.exe -u app\ui_interaction_recorder_test.py
.venv\Scripts\python.exe -u app\motion_ir_test.py
.venv\Scripts\python.exe -u app\motion_render_test.py
.venv\Scripts\python.exe -u app\ui_motion_editor_test.py
.venv\Scripts\python.exe -u app\video_client_test.py
.venv\Scripts\python.exe -u app\video_routing_test.py
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

Interaction API:

```text
POST /api/interaction/build
POST /api/interaction/validate
POST /api/interaction/replay
POST /api/interaction/capture
```

The browser Recorder must redact typed PII before updating Zustand. The backend
sanitizer is a second boundary, not a replacement for local cleanup.
Hybrid capture additionally requires `mine=true`, validates every document
navigation, rejects cross-origin transitions and caps scripts at 50 actions.

Motion API:

```text
POST /api/motion/build
POST /api/motion/validate
POST /api/motion/render
GET  /api/motion/render/{id}
GET  /api/motion/render/{id}/download
```

Motion build validates both source IR layers, produces canonical Motion IR and
returns materialized Design IR scenes only as preview data.
Video render revalidates the complete hash chain, queues a single local encoder
job and never accepts a client filesystem path. `imageio-ffmpeg` supplies the
pinned FFmpeg binary on every supported development machine.

Generative video API:

```text
POST /api/ai-video/generate
GET  /api/ai-video/{job_id}
```

This gateway uses OpenRouter's asynchronous Videos API. `confirmed=true` is
required because submission spends credits. Reference images are transient,
limited to public HTTPS URLs and are not stored in project state.

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
