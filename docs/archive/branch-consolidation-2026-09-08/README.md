# Historical branch consolidation snapshots

Captured 2026-09-08 before consolidating into `codex/unified-motion-design`.
These are historical design notes and unapplied drafts, not current runtime instructions.

- `claude-selection-uncommitted.patch.gz` and the accompanying test preserve the remaining Claude worktree edits. Current FlowCanvas already uses untracked binding reads, hydration gating and page-aware synchronization; current selection tests cover the replacement implementation.
- `ds-t1-uncommitted.patch.gz` preserves staged design notes and the old orchestration script. The current script is newer and is retained.
- `DESIGN-STUDIO-V3.md` and `ORCA-ORCHESTRATION.md` are the original historical planning documents.
- Runtime `.tmp-data` in dse-p1 is local test data, excluded from source publication.
- The old `codex/generation-quality-pipeline` and `claude/vigilant-khorana-e7d37a` branch tips are retained as merge parents. Their obsolete React implementation and WIP baseline are superseded by the current implementation; history consolidation intentionally preserves the current tree.

Original worktrees have not been reset, removed, or overwritten.
