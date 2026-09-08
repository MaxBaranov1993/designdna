# Consolidation verification — 2026-09-08

The working branch is `codex/unified-motion-design` in `MaxBaranov1993/designdna`.
All 21 inspected local and remote branch tips are ancestors of the consolidated
history. Historical unpublished worktree drafts are retained in
`archive/branch-consolidation-2026-09-08`; original worktrees remain intact.
The historical merge deliberately retained the current implementation instead of
reintroducing obsolete React code. Existing branch refs were not deleted.

## Validation

- Frontend and desktop Node suites: 455 passed before the CI follow-up fix.
- Python suite: 883 passed, 1 skipped, 50 subtests passed.
- Production frontend/engine rebuild after the follow-up: passed;
  Svelte diagnostics: 0 errors, 0 warnings.
- Import/lifecycle suite after the fix: 19 passed, including a new regression
  covering automatic publication, review gating, and manual publication mode.
- All 17 maintained browser scripts passed locally (the timeline script was
  rerun after correcting its repeat-message interaction).
- The 72-node drag scenario retains the full graph and its frame budget:
  observed p95 16.7 ms, 0% frames over 34 ms.

## CI follow-up

The first consolidated GitHub run passed all three platform builds and Python
tests but exposed browser contract drift and a real import bug. The import's
`else` bound to an inner ownership check, so review-free token documents never
entered automatic publication. Explicit braces restore the intended branches.

Browser tests now cover the current 15-node palette, Astra provider option,
mounted custom-node measurement policy, Russian video actions and chat retry.
The Motion Design mock is installed after browser boot because it only supplies
a provider, not the complete Electron preload interface. Paid video transport
remains mocked and its explicit-confirmation gate remains tested.

Storage checks distinguish disposable presentation screenshots from canonical
IR. Large presentation images are compacted; editable images, canonical evidence
and geometry are compared exactly after save and reload. Tests no longer expect
canonical hash inputs to be removed during generic autosave.

The UI Kit result is documented in `ui-kit-fix-2026-09-08.md`: 8/8 accepted
masters and published revision 1.
