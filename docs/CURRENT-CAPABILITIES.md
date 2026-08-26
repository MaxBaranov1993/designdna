# DesignDNA current capability and claims matrix

Verified against the repository on 2026-08-25. This document is the source of
truth for product copy until the next capability review. "Implemented" means a
code path and focused automated verification exist; it does not imply universal
visual quality or support for every editor action.

## Claims that are supported now

| Product claim | Current evidence-backed wording | Boundary |
| --- | --- | --- |
| Controlled AI design | Create and revise designs through canonical Design IR, explicit scope, stable source keys, preview and validation instead of accepting an opaque generated image. | Subjective first-pass quality is evaluated, not guaranteed. |
| Multiple variants | Generate and compare multiple variants while preserving the project structure and Design System constraints supplied to the generation flow. | Results still pass validation and quality review; "perfect in one generation" is not guaranteed. |
| Live harness control | Codex, Claude, Kimi, Z.AI GLM, Grok and other MCP-compatible harnesses can read the saved project and send revision-safe commands to the open Electron editor. | Only the registered command inventory below is live; this is not yet remote control of every button. |
| Reversible mutations | Live mutations use Preview/Apply, native approval, an authoritative base revision, serialized execution, idempotency and an inverse/undo record. | Apply fails closed on stale state, renderer timeout, declined approval or missing persistence acknowledgement. |
| Product walkthrough video | Record/replay product interactions, edit scene timing/settings and locally export MP4/H.264 or WebM/VP9. | This is a product walkthrough editor, not a general After Effects replacement. |
| Quality certification foundation | Build a deterministic, hash-bound Quality Certificate from explicit QA, viewport, lock and scope evidence. | The certification API exists, but mandatory enforcement on every apply/export path is not yet wired. |

## Live editor command inventory

The authoritative runtime inventory is returned by `command.list`. The current
registered commands are:

| Access | Commands | Notes |
| --- | --- | --- |
| Read | `session.get`, `project.get`, `pages.list`, `graph.get`, `command.list`, `changes.since` | Read the authoritative desktop session or bounded command event history. |
| Mutation | `graph.node.create`, `graph.node.delete`, `graph.node.move`, `editor.style.patch`, `history.undo` | Routed into the active Svelte store and completed only after normal CAS persistence. |

`graph.node.create` accepts a known node type and editor position, then applies
the editor's own defaults. It does not accept arbitrary persisted node data.
`graph.node.delete` captures a bounded node-and-edge snapshot before mutation;
if a reversible snapshot is too large, deletion is rejected.
`editor.style.patch` addresses one Design IR object by `sourceKey`, accepts only
the style allowlist, and preserves tree structure, content, component identity
and responsive structure.

Declared contract actions that are not registered must return
`HANDLER_NOT_REGISTERED`. In particular, edge editing, page lifecycle,
selection control, Source capture, generation, Design System lifecycle, motion
editing/export and job cancellation are not yet live harness commands.

## MCP and local security boundary

- Saved-project tools use the SQLite project store and compare-and-swap
  revisions. A database write is not presented as an open-editor edit.
- `designdna_live_command` reaches the running Electron process through a local
  named pipe on Windows or Unix-domain socket on POSIX. It opens no TCP port.
- Electron publishes a per-launch capability in its private data directory.
  The token rotates on every app start, is never returned by the MCP tool and is
  compared in constant time.
- Preview never mutates. Apply is serialized, rechecks the current desktop
  revision immediately before renderer dispatch, requests native approval and
  waits for the ordinary project save to acknowledge the new SHA-256 revision.
- Command ids, intent, scope, arguments, timeouts, messages, results, preview
  retention and event history are bounded. Unknown actions and malformed JSON
  fail closed.

The source checkout has a working stdio server configuration. The packaged app
contains the server source but does not yet ship a standalone external
`designdna-mcp` launcher; an external harness against an installed build still
needs Python 3.11+ pointed at that source. In-app provider tool loops call the
same Electron registry without this launcher.

## Motion status

The current visual Motion Workspace builds and renders Motion IR 1.0 product
walkthroughs. It supports scene materialization, composition size and frame
rate, scene duration/settings, preview, render progress, MP4/H.264 and WebM/VP9
downloads.

Motion IR 2.0 currently has a strict schema/semantic validator, stable content
hash and an explicit fail-closed 1.0-to-2.0 migration endpoint. The migration
requires source mappings and rejects lossy transitions, ambiguous locks and
dangling references. Motion IR 2.0 is not yet consumed by the visual timeline
or the video render endpoint, so documentation and marketing must not call the
2.0 render/export path complete.

## Quality Certificate status

`POST /api/quality/certify` adapts completed deterministic QA reports into a
canonical certificate. Certification is fail closed and binds the decision to
the Design IR hash, Design System id/revision/content hash, asset hashes and
engine version. A passing certificate requires an overall score of at least 85,
each critical subscore and required viewport score of at least 75, plus all
required structural, lock, scope and evidence gates.

An explicit bounded override records its reason and reason hash without turning
a blocked certificate into a certified one. The API returns separate
`applyAllowed` and `exportAllowed` decisions. The remaining product task is to
make this decision mandatory in the live Apply and motion/code export paths.
The complete contract is documented in
[Quality Certificate architecture](architecture/quality-certification.md).

## Claims that remain prohibited

- "Full control of every editor action through Codex/Claude/Kimi/GLM."
- "After Effects replacement."
- "Guaranteed perfect result" or "guaranteed no AI slop in one generation."
- "Motion IR 2.0 video export is complete."
- "Every Apply and export is Quality Certified."

Use instead: **controlled, inspectable and reversible AI design with a growing
live command surface, deterministic quality evidence and a focused product
walkthrough video editor.**
