# SLSBMB master layout polish

Live fixture: `SLSBMB Pricing Kit`, component `Sending Engine` (`ds-98d49b55acd6`, draft revision 0). The source database and captured fonts were copied to an isolated `%TEMP%/designdna-slsbmb-polish-p9` data directory; the original desktop data was read-only.

The `$3K` text frame was deliberately narrowed from `47.48px` to `28px` in desktop, tablet, and mobile variants. The production renderer/headless lint reported overflow and clipping of `15px` on all three viewports (six target defects). Deterministic polish expanded each corresponding frame to `45px`; target defects fell from 6 to 0 and total reported defects fell from 103 to 95.

Pixel similarity against the Source crop changed from `96.54%` before repair to `95.93%` after repair, remaining above the fidelity gate threshold of `85%`. The candidate therefore satisfies both acceptance conditions: fewer layout defects and fidelity above the existing gate.

| Before | After |
|---|---|
| ![Narrow $3K frame before polish](slsbmb-polish-before.png) | ![Expanded $3K frame after polish](slsbmb-polish-after.png) |

The remaining lint items are retained in `fidelity.polish.defectsAfter` and surface as “Нужна доводка”; this run intentionally demonstrates the requested injected `$3K` regression rather than claiming the entire captured component is defect-free.
