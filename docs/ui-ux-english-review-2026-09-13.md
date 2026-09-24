# English interface and independent Grok review

Scope: the installed-style Windows Electron application, UI/UX, node inputs and outputs, editors, and English product text. PostgreSQL work is deferred. Source content, user text, immutable design-system masters, provider isolation, and saved project semantics remain intact.

## Independent review

Grok reviewed the public `codex/unified-motion-design` branch at `bb8ff2c23d07960996c3e1a717e3c9db15095035` and five actual packaged-app screenshots: Generator, Source Import, Design System, Video and Motion Design. The screenshots used synthetic empty projects. The first response used an older default-branch snapshot; a second brief corrected the branch and the 19-type catalog. Findings below use the corrected review and direct local verification.

[Grok conversation](https://grok.com/c/0c899e1a-b885-4ef5-a385-c4d722edf0c1)

Grok is an external reviewer, not the implementation or acceptance authority. Its code access was partial. Its screenshots establish visible states, not every runtime path or a WCAG conformance result. Codex checked recommendations against current code and the packaged application.

| Finding | Decision and result |
| --- | --- |
| Reference accepts IR but gives no usable IR output or preview | Added a separate Reference IR output and an IR preview when there is no image. Existing style and image outputs remain. Regression and native tests preserve the exact incoming IR. |
| Generator and Derive output says “variants”, but carries only the selected variant | Label now says “active variant”. Selection and wire semantics remain unchanged. |
| Quality Pass output implies an unconditional successful verification | Changed to “reviewed IR”; validation status remains separate from the existence of an output. |
| Generator/Mix can start with missing data | Generator, Mix and Page now explain missing inputs and disable Run until actual data is available. An empty connected wire does not satisfy readiness. |
| Empty output dots look populated | Empty outputs use a dashed ring; populated outputs are filled. Tooltips and accessible names explain readiness. Preconnecting a wire remains supported; no port disappears on an empty result. |
| Disabled primary actions look active | Disabled buttons use a neutral surface and remain neutral on hover. |
| Bright white empty previews overpower the task controls | Empty previews use the application's dark surface and readable muted text. Actual rendered IR keeps its own colors. |
| Mixed Russian/English chrome and clipped draft label | Product labels, statuses, errors and export chrome are English. The Design System draft label is fully visible in the packaged screenshot. |
| Motion Design “VIDEO — / PARAMS —” is ambiguous | Explicit “No video input” and “No motion input” states replace the unexplained dashes. |
| Reference “Split into components” is a placeholder action | Removed the unimplemented checkbox. The saved compatibility field is retained. |

Recommendations not treated as confirmed defects:

- Dynamic ports intentionally differ from the static catalog: Source blocks and Mix/Page/Edit/Video inputs are data-dependent. The runtime uses `portsOfNode`.
- Legacy Recorder/Motion/Design UI types remain loadable; the current creation flow uses Video and Design System. Reintroducing legacy palette entries would undo the accepted product direction.
- Queued, partial and failed states already have runtime support. They were not absent merely because the screenshots showed idle nodes.
- Design System token fallbacks support older documents; different stored formats alone are not proof of a broken wire.
- Port labels already appear on hover, selection and wiring. Added persistent accessible names and readiness tooltips; labels are not forced over every card at idle.

## English-language boundary

English covers frontend chrome, all 19 node types and their inspectors, desktop-owned messages, Python API diagnostics/progress, default labels, styleguide/UI Kit exports, and locale/date formatting. An AST-based regression test checks product strings while excluding code comments, internal AI instructions and Russian keyboard-layout aliases.

User-authored Russian text, imported source labels, project names and canonical IR are not translated or stripped. A packaged-app save/reload test explicitly verifies Russian text survives unchanged. Provider-generated content and upstream operating-system/provider error details can follow their original language.

## Validation

All UI tests use isolated profiles under `artifacts/english-ui-2026-09-13/`, not the user's Electron profile or databases. Subscription AI and paid video generation were not invoked. Image-provider responses in functional QA are deterministic fixtures; preparation, blob storage, application, reconciliation and persistence use the real backend.

- Frontend: 193 tests passed, including language regression, Reference forwarding, input readiness, asynchronous ownership and existing graph behavior.
- Desktop: 366 tests passed.
- Svelte: zero errors and warnings; desktop build completed.
- Ruff: zero findings.
- Python: all 1,018 unique tests in the required set passed across the final staged runs; one test was skipped and 50 subtests passed. The general run had 960 passes and one remaining Russian-message assertion; after correcting that expectation, all 17 timeline-guard tests passed. The separate fidelity suite passed all 57 tests. The slow isolated golden run also passed. Three non-failing dependency/Windows certificate-store warnings were recorded; see the logs.
- Packaged Electron: all 19 node types and inspectors checked for English text, no page errors; exact Reference IR forwarding/preview; Russian user text saved to SQLite and reloaded unchanged.
- Final packaged renderer: 94 files matched the built files by SHA-256. Disabled hover stayed neutral; a video wire survived empty/running/complete states while its output readiness changed only on completion.
- Packaged functional paths: local chroma removal with mask/edge views; three-image processing and exact undo in Derive/Mix/Reskin; Source and UI Kit component inventories without canonical mutations; Video layer playback and exact timeline undo.
- Packaged asynchronous paths: real mouse drag, undo/redo after a delayed image response, hidden-sheet result ownership, transient reconciliation failure, verification-only retry without regenerating images, save/reload, and asset undo after reload.

Local evidence:

- [English UI evidence](../artifacts/english-ui-2026-09-13/english-evidence.json)
- [Functional node evidence](../artifacts/english-ui-2026-09-13/nodes-desktop-evidence.json)
- [Async, persistence and undo evidence](../artifacts/english-ui-2026-09-13/fixed-desktop-evidence.json)
- [General Python run](../artifacts/english-ui-2026-09-13/python-rest.txt), [final timeline guard](../artifacts/english-ui-2026-09-13/python-guard-final.txt), [fidelity suite](../artifacts/english-ui-2026-09-13/python-fidelity.txt)
- [Final native UI run](../artifacts/english-ui-2026-09-13/english-qa-final.txt)
- [Generator screenshot](../artifacts/english-ui-2026-09-13/english/generator.png)
- [Design System screenshot](../artifacts/english-ui-2026-09-13/english/designsystem.png)
- [Reference connection screenshot](../artifacts/english-ui-2026-09-13/english/reference-connected.png)

The updated English screenshots were prepared for a second Grok visual check, but the browser connection stopped responding during upload. No final Grok approval of the English build is claimed. The recorded independent review is the corrected code review plus the initial five-screen visual review; acceptance of the implemented changes uses local tests and actual Electron behavior.

Coverage does not prove every combination of generated content, every model response, or every third-party website. No full paid generation quality benchmark or keyboard/screen-reader accessibility certification is claimed. No database migration, commit or GitHub push was performed in this change.
