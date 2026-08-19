# Phase 2 — DNA editor Svelte port

## What shipped
Full DNA editor UI ported from `HEAD:frontend/src/editor/*.tsx` to Svelte 5. `controller.ts` / `store.ts` / `editor.css` / `wireInspector.ts` left untouched. New adapter: `frontend/src/editor/state.ts` (`editorUi` readable over the existing zustand store).

## Files
- frontend/src/editor/state.ts
- frontend/src/editor/EditorApp.svelte
- frontend/src/editor/TopBar.svelte
- frontend/src/editor/CanvasStage.svelte
- frontend/src/editor/ToolRail.svelte
- frontend/src/editor/LayersPanel.svelte
- frontend/src/editor/DnaPanel.svelte
- frontend/src/editor/SourceLensBar.svelte
- frontend/src/editor/InspectorPanel.svelte
- frontend/src/editor/SmartAxisPanel.svelte
- frontend/src/editor/QualityGatePanel.svelte
- frontend/src/editor/HarmonizerPanel.svelte
- frontend/src/editor/ResponsiveAutopilotPanel.svelte
- frontend/src/editor/IntentLocksPanel.svelte
- frontend/src/editor/SemanticSelectPanel.svelte
- frontend/src/editor/inspector/ColorPicker.svelte
- frontend/src/editor/inspector/FontOptions.svelte
- frontend/src/editor/inspector/SharedInspector.svelte
- frontend/src/editor/inspector/TypeGroups.svelte

## Check
`npm --prefix frontend run check` → **0 errors, 0 warnings**.
`npm --prefix frontend run build` → passed (SvelteKit + engine.js).

Real warnings fixed: ColorPicker hsv is a tuple `$state`, not a function initializer; ToolRail hover/flyout and SV pad have `role="group"`; dialog cards are `div role="dialog"`; semantic-select `autofocus` removed. Dense legacy inspector labels keep React sibling `label`+control markup (`data-pi` / `data-style-*` / `data-el-prop` unchanged); `a11y_label_has_associated_control` is suppressed with scoped `svelte-ignore` on SharedInspector, TypeGroups, and ColorPicker.

## Not run
- Playwright editor suites (`app/ui_editor_*.py`, `app/ui_flow_edit_test.py`) — need a live server + IR fixture; not started here.
- Browser click-through of the overlay (no running frontend in this worker).
