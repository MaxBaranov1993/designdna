# Motion Design node

Motion Design is the generative-video step after the deterministic Motion Editor
or Video Editor. It does not replace either editor: local editors keep exact,
editable timing, while Seedance creates or transforms pixels.

## Inputs and modes

- `prompt` — a standalone video brief.
- `motion` — compact Motion IR timing/composition metadata.
- `timeline` — compact Timeline IR layer/keyframe metadata.
- `video` — a completed local render (`video-artifact/1.0`).

`Prompt` mode sends no reference video. `Video` mode requires a completed render.
`Auto` uses the video when present and otherwise behaves as prompt-to-video. A
local render is read only after paid confirmation and is sent as an OpenRouter
`video_url` data reference; its bytes are never sent to GPT or Claude.

## Planner and generation boundary

`Direct` deterministically combines the user's brief with preservation rules.
`GPT-5.6 Sol` and `Claude Code` receive only a bounded digest (composition,
scene/layer counts, timing and render parameters) and return one Seedance prompt.
They do not call Seedance and do not receive video pixels.

The final generation is pinned to `bytedance/seedance-2.5` at the Python
OpenRouter boundary. The UI and API both require explicit paid confirmation.
The OpenRouter job id is persisted immediately; failed status polls retry the
same id and never resubmit a paid generation. Completed content is proxied by
the backend and leaves the node as a reusable `video` output.

## Operational limits

- 4–30 seconds, 480p or 720p.
- Ratios: 16:9, 9:16, 1:1, 4:3, 3:4, 21:9.
- Optional synchronized audio and deterministic seed.
- Inline local reference limit: 48 MiB.
- OpenRouter video generation is surfaced as not supporting zero-data-retention.
- The OpenRouter key is stored with Electron `safeStorage` and is supplied only
  to the Python worker; it is never exposed to the renderer.
