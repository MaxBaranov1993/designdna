# DesignDNA stdio MCP server

Bundled, dependency-light JSON-RPC MCP server so Codex, Claude, Kimi, Z.AI GLM, Grok and other harnesses can read the saved project and, while Electron is running, send revision-safe commands to the open editor.

- Entry: `app/designdna_mcp_server.py`
- Database: `$DESIGNDNA_DATA_DIR/projects.db` (same file as `app/project_store.py`)
- Protocol: newline-delimited JSON-RPC 2.0 on stdio. Dual-era: current `2026-07-28` (stateless `_meta`) plus legacy handshake `2025-11-25` and `2024-11-05` (desktop client compatible). The desktop MCP client is not changed in this server.
- Stdout is protocol only (newline-delimited JSON-RPC). Diagnostics go to stderr and never include payloads or secrets.
- Input is decoded as strict UTF-8 (`utf-8`, no replacement). Invalid bytes yield JSON-RPC `-32700`.
- Request and response lines share one exact bound: `MAX_MESSAGE_BYTES` = 2097152 UTF-8 bytes. A put that would make a later get exceed that bound is rejected before mutation. JSON-RPC `id` must be a string or integer; `method` must be a string; `params` if present must be an object (`-32602`, not coerced to `{}`).
- `userId` / `projectId` if sent must match `[A-Za-z0-9._:-]{1,128}` (rejected, never sliced).

## Database / live editor boundary

`designdna_project_get` / `put` remain database tools. `put` requires `expectedRevision` and does not masquerade as an open-editor operation.

`designdna_live_command` connects to the running Electron app through a local capability-gated pipe discovered in `$DESIGNDNA_DATA_DIR/live-command.json`. The capability rotates on every desktop launch, is not returned by MCP, and the pipe rejects invalid tokens and oversized messages. Preview does not mutate. Apply is serialized, rechecks the authoritative desktop revision immediately before renderer dispatch, requires native approval, updates the open Svelte store, and returns only after the normal project CAS save emits `session.persisted`. Currently registered renderer mutations are `graph.node.create`, `graph.node.delete`, `graph.node.move`, `editor.style.patch`, and `history.undo`; unknown actions fail closed. Create uses editor defaults rather than accepting arbitrary node data. Delete captures a bounded node-and-edge snapshot so undo is deterministic and rejects oversized snapshots instead of creating an irreversible command.

The local transport is a Windows named pipe or POSIX Unix-domain socket, not a
TCP listener. The capability document is sensitive local runtime state and must
not be copied into prompts, project files or logs.

### Registered live command inventory

`command.list` is authoritative at runtime. As of 2026-08-25 the Electron host
registers exactly:

| Access | Actions |
| --- | --- |
| Read | `session.get`, `project.get`, `pages.list`, `graph.get`, `command.list`, `changes.since` |
| Mutation | `graph.node.create`, `graph.node.delete`, `graph.node.move`, `editor.style.patch`, `history.undo` |

`project.get` in this table reads the authoritative in-memory desktop session;
it is different from the SQLite-backed `designdna_project_get` MCP tool.
Contract names for edge editing, selection, Source capture, generation, Design
System lifecycle, motion and export are reserved but are not registered renderer
handlers. Calling one fails with `HANDLER_NOT_REGISTERED`; it must not be
advertised as supported live control.

## Compare-and-swap and revision

`revision` is SHA-256 of the **exact raw UTF-8 text** in the `projects.payload` column, not of a migrated or canonicalized object. `get` may return a migrated `payload` (IR timestamps, `contentHash`, schema upgrades). Two gets of the same row must return the same `revision`. `put` after `get` succeeds when `expectedRevision` equals that raw digest, even if the client sends the migrated payload back.

Empty / missing project: `revision` is SHA-256 of the six-character string `{}`.

Writers (`save_project`, `commit_project`) open **one** SQLite connection, `BEGIN IMMEDIATE`, then write `projects`, `taste_profiles`, and `taste_events` in that same transaction. Skip-if-unchanged compares the **exact raw row digest** in that transaction, not a process-local cache. `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL`. Two processes that put the same `expectedRevision` serialize: exactly one commit succeeds, the other returns `stale` and no write is lost. After another process writes Y, a later `save_project(X)` or a CAS put of X against Y's revision writes X; the returned revision equals the raw DB digest.

Corrupt stored JSON (non-UTF-8-JSON, non-object): `get` / `summary` / `put` fail closed (`ok: false`, `corrupt: true`). `load_project` returns `None`. MCP will not repair a corrupt row; a desktop `save_project` can replace it.

## dryRun contract

`designdna_project_put` with `dryRun: true` does not write. The returned `revision` is SHA-256 of `json.dumps(project, ensure_ascii=False)` (Python default separators `, ` / `: `, insertion key order, no migrate). A subsequent non-dry `put` of that same `project` object stores that exact string and returns the same `revision`. There is no `normalizedProject` field; do not hash the migrated get payload and expect it to match `dryRun`.

## Protocol versions (dual-era)

The server is **dual-era** per the 2026-07-28 spec.

| Era | How the client opens | Server behavior |
| --- | --- | --- |
| Modern `2026-07-28` | Each request carries `params._meta["io.modelcontextprotocol/protocolVersion"]` | Stateless. No `initialize`. `server/discover` is the stdio probe. Results include `resultType: "complete"`, `_meta["io.modelcontextprotocol/serverInfo"]`, and cache hints where required. |
| Legacy `2025-11-25` / `2024-11-05` | `initialize` then `notifications/initialized` | Handshake session for this stdio process. Results omit `resultType`. `ping` remains. |

`initialize` only negotiates the two legacy versions. If a client sends `initialize` with `2026-07-28`, the server answers `2025-11-25` (legacy preferred) and does not switch the process to the modern era.

Both eras may be used on the same stdio process: a modern `_meta` request is served statelessly even after a legacy handshake.

### `server/discover`

Implemented and usable as the first message (with or without `_meta`). A version in `_meta` that is not `2026-07-28` returns `UnsupportedProtocolVersionError` (`-32022`) with `data.supported` and `data.requested` — a recognized modern error, so dual-era clients must not fall back to `initialize`.

**Request**

```json
{"jsonrpc":"2.0","id":"discover-1","method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"ExampleClient","version":"1.0.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}
```

**Response** (`ttlMs` is 3600000)

```json
{"jsonrpc":"2.0","id":"discover-1","result":{"resultType":"complete","supportedVersions":["2026-07-28","2025-11-25","2024-11-05"],"capabilities":{"tools":{}},"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"designdna-project","version":"1.2.0"}},"instructions":"DesignDNA saved-project database. Use designdna_project_get, then designdna_project_put with expectedRevision from get. Validate Design IR with designdna_design_ir_validate. While Electron is running, use designdna_live_command for approved Preview/Apply against the open editor.","ttlMs":3600000,"cacheScope":"public"}}
```

Modern `tools/list` and `tools/call` also accept that `_meta` object and do not require `initialize`. `tools/call` allows `_meta` (and MRTR `inputResponses` / `requestState`) next to `name` / `arguments`. `ping` is removed for `2026-07-28` (`-32601`); it still works after a legacy handshake.

A `tools/list` with no `_meta` and no prior `initialize` still returns `-32600` `initialize required` so handshake-only clients keep working.

## Validation and arguments

- Project shape (page/node ids) plus **every** Design IR anywhere in the JSON tree (recursive walk; not a fixed key list).
- Tool `arguments` must be a JSON object. Extra keys, missing required keys, non-object `project`/`ir`, non-string ids, empty strings, and non-boolean `dryRun` are JSON-RPC `-32602` (not coerced).

## Tools

| Tool | Access | Notes |
| --- | --- | --- |
| `designdna_project_get` | read-only | Migrated `payload`; `revision` is SHA-256 of the raw stored JSON |
| `designdna_project_put` | mutating | `project`, `expectedRevision`, optional `dryRun`; fail-closed on stale/corrupt/invalid IR |
| `designdna_design_ir_validate` | read-only | All schema/semantic errors |
| `designdna_project_summary` | read-only | Bounded page/node/edge/type counts |
| `designdna_live_command` | preview/mutating | Open-editor command bus; Electron must be running; native approval + CAS persistence for Apply |

## One-line client configurations

Set `DESIGNDNA_DATA_DIR` to the desktop data directory (packaged default: `%APPDATA%/DesignDNA/data` on Windows, `~/Library/Application Support/DesignDNA/data` on macOS, `~/.config/DesignDNA/data` on Linux).

The commands below are source-checkout configurations and use the repository
`.venv`. The installed desktop bundles the server source and its internal
PyInstaller ASGI worker, but that worker is not a general Python interpreter and
the installer does not yet publish a separate `designdna-mcp` executable.
External harness configuration against an installed build therefore currently
requires a Python 3.11+ interpreter pointed at the bundled/server checkout, or a
source checkout. In-app Codex/provider tool loops do not require this external
launcher.

**Codex-compatible**

```text
codex mcp add designdna --env DESIGNDNA_DATA_DIR=PATH/TO/data -- .venv/Scripts/python app/designdna_mcp_server.py
```

**Kimi**

```text
kimi mcp add designdna --env DESIGNDNA_DATA_DIR=PATH/TO/data -- .venv/Scripts/python app/designdna_mcp_server.py
```

**Z.AI / ZCode (generic stdio)**

```text
command=.venv/Scripts/python args=app/designdna_mcp_server.py env.DESIGNDNA_DATA_DIR=PATH/TO/data
```

**Generic MCP stdio (Claude/Cursor/other JSON config)**

```json
{"mcpServers":{"designdna":{"command":".venv/Scripts/python","args":["app/designdna_mcp_server.py"],"env":{"DESIGNDNA_DATA_DIR":"PATH/TO/data"}}}}
```

On POSIX replace `.venv/Scripts/python` with `.venv/bin/python`.
