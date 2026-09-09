---
name: designdna
description: Generate, review, and safely apply DesignDNA screens through the DesignDNA MCP server. Use when an agent in Claude Code, Codex, or Cursor needs to create Design IR, select a project design system, preserve tokens and componentRef links, inspect shared design rules, or transfer a reviewed result into a DesignDNA project.
---

# DesignDNA

Use the high-level MCP tools as the source of truth. Do not assemble a screen through `designdna_project_put`; that tool is only for transferring a complete, already reviewed project document.

## Choose the workflow

1. Call `designdna_rules_get` when the task involves manual IR authoring or when project-specific guidance may matter.
2. Call `designdna_list_design_systems` before selecting a design system. Pin the returned `systemId` and `revision`, choose `usageMode`, and keep that reference for generation and review.
3. Call `designdna_generate` for a new screen. Supply the brief, count, pinned `designSystem`, and optional `referenceIrs` when adjacent screens should share patterns.
4. Call `designdna_review` after any manual IR change and immediately before preview or apply. Continue with `fixed_ir`, not the unreviewed input.
5. Use `designdna_live_command` in `preview` mode first and `apply` only after the preview is accepted. Use `designdna_project_get`/`put` only for whole-project transfer or recovery where the live editor is unavailable.

Use `designdna_rules_set` only when the user explicitly asks to replace project rules. It does not modify the built-in DESIGN, RUBRIC, or BLOCKS guidance.

## Preserve design-system identity

- Treat `ir.tokens` as a locked vocabulary. Reuse token references and values emitted by the selected design system; do not invent raw colors, font families, radii, spacing, or shadows in strict mode.
- Never rename, remove, or fabricate `componentRef`. Copy the exact component key returned by `designdna_list_design_systems`; preserve it through edits and nested moves.
- Preserve `_dsMaster`, `sourceMeta`, `typeRole`, responsive overrides, and component variant metadata unless the requested edit specifically targets them.
- In `strict` mode, build from design-system masters. In `extend`, reuse a master where one fits and add only the missing structure. In `style-only`, reuse tokens and typography without claiming a master through `componentRef`.
- Use returned variant keys as variants of one component; do not turn each state or size into a new component key.

## Review discipline

Always call `designdna_review` when IR was written or edited outside `designdna_generate`, when tokens changed, when a component was inserted or moved, or before presenting a result as ready. The tool runs deterministic autofix with strict token enforcement and, when `designSystem` is supplied, validates the fixed IR against the resolved pinned design-system context.

Read `violations` and `journal`, inspect the optional `designSystem.errors` and `designSystem.warnings`, and use `fixed_ir` for the next step. Do not silently discard component-reuse errors. If strict validation still reports errors, revise the composition or select an exact master and review again.

## Tool inputs

- `designdna_generate`: `{brief, count, designSystem: {systemId, revision?, usageMode}, referenceIrs?}`.
- `designdna_list_design_systems`: `{projectId?}`.
- `designdna_review`: `{ir, designSystem?: {systemId, revision?, usageMode}}`.
- `designdna_rules_get`: `{}`.
- `designdna_rules_set`: `{text}`.
- `designdna_llm_calls`: `{limit?, source?: "python" | "electron"}`. Read-only metadata of recent model calls (provider, model, effort, agent-contract version, durations, sizes, errors); never prompt or answer text. Use it to explain which model and effort produced a result or why a call failed before retrying.

The local DesignDNA server must be running. If a tool reports `DESIGNDNA_SERVER_UNAVAILABLE`, ask the user to start it or point `DESIGNDNA_SERVER_URL` at the correct local instance; do not fall back to hand-built IR and low-level project writes.
