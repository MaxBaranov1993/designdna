# DesignDNA MCP

The stdio MCP server exposes the DesignDNA Generator, design-system registry, Quality Gate, shared rules, saved projects, and the live editor bridge to Claude Code, Codex, Cursor, and other MCP clients.

## Start and configure

Start the DesignDNA HTTP server first, then configure the MCP client to launch:

```text
<repo>/.venv/Scripts/python <repo>/app/designdna_mcp_server.py
```

The MCP process calls `http://127.0.0.1:8420` by default. Set `DESIGNDNA_SERVER_URL` in the MCP server environment to use another local port, for example `http://127.0.0.1:8431`. `DESIGNDNA_DATA_DIR` selects the same project and design-system data directory used by the application.

Example MCP configuration (replace the absolute paths):

```json
{
  "mcpServers": {
    "designdna": {
      "command": "C:/path/to/repo/.venv/Scripts/python.exe",
      "args": ["C:/path/to/repo/app/designdna_mcp_server.py"],
      "env": {
        "DESIGNDNA_SERVER_URL": "http://127.0.0.1:8420",
        "DESIGNDNA_DATA_DIR": "C:/path/to/repo/data"
      }
    }
  }
}
```

Stdout is reserved for newline-delimited JSON-RPC. Diagnostics go to stderr. The server supports MCP `2026-07-28`, `2025-11-25`, and `2024-11-05` clients.

## High-level tools

| Tool | Purpose |
| --- | --- |
| `designdna_generate` | Send `{brief, designSystem, count, referenceIrs?}` to the full `/api/generate` pipeline and return `variants`, `generationLog`, and `qa`. |
| `designdna_list_design_systems` | Read the local registry with `systemId`, status, revision, compact component keys/categories/variants, and `irTokens`. |
| `designdna_review` | Run `/api/quality-gate` with `strictTokens: true`; with a design-system reference, resolve its context and validate the fixed IR against it. Returns `violations`, `journal`, and `fixed_ir`. |
| `designdna_rules_get` | Read the combined built-in and project rules from `GET /api/rules`. |
| `designdna_rules_set` | Replace project rules through `POST /api/rules/project`; built-in rules stay read-only. |

Prefer these tools over manual IR assembly. `designdna_project_put` is deliberately described as a service/transfer primitive: it replaces a complete saved project using compare-and-swap and is not a screen-authoring API.

## Recommended sequence

For a design-system-backed screen:

1. Call `designdna_list_design_systems` and select an exact `systemId`/`revision` plus `usageMode` (`strict`, `extend`, or `style-only`).
2. Call `designdna_generate`. Include up to three existing screens in `referenceIrs` when the new screen belongs to an established flow.
3. If IR is edited outside the generator, preserve `tokens`, exact `componentRef` keys, `_dsMaster`, `sourceMeta`, and `typeRole`.
4. Call `designdna_review` with the same design-system reference. Use its `fixed_ir`; address remaining design-system errors before apply.
5. Preview and apply through `designdna_live_command` when the desktop editor is open.

For manual IR, call `designdna_rules_get` before authoring and `designdna_review` afterward. Do not invent raw style values in strict mode, rename component references, or use `project_put` as a shortcut around generation and review.

## Existing low-level tools

- `designdna_project_get` reads a saved project and its raw-storage SHA-256 revision.
- `designdna_project_put` validates and compare-and-swap replaces a whole saved project; `dryRun` performs validation without writing.
- `designdna_design_ir_validate` runs schema and semantic validation only.
- `designdna_project_summary` returns bounded project counts.
- `designdna_live_command` previews or applies an approved command to the open editor and waits for revision-safe persistence.

HTTP failures are returned as MCP tool errors with a stable code such as `DESIGNDNA_SERVER_UNAVAILABLE`, `HTTP_422`, `DESIGNDNA_RESPONSE_INVALID`, or `DESIGNDNA_RESPONSE_TOO_LARGE`.
