# SLSBMB master layout polish (P11)

Live fixture: published revision 1 of `SLSBMB Pricing Kit` (`ds-98d49b55acd6`). The database, captured fonts, and blobs were copied from `%APPDATA%\@designdna\desktop\data` to the isolated directory `%TEMP%\designdna-slsbmb-polish-p11-97c5e2e1a3a94ee083ac677f8b21758d`; the desktop data was not modified.

P11 treats browser/font rounding below `4 px` as measurement noise. Ordinary text overflow must also occupy at least `15%` of the text-frame width; confirmed hidden/clip overflow may bypass only the ratio check. Parent escape starts at `4 px`, while a clipping parent or component-root escape remains immediately actionable. Intentional captured per-line masks such as `::text0l47` are not standalone clipped text frames.

## Clean masters

Both visually clean masters now have zero defects in every independently rendered viewport and record `fidelity.polish.status = ready`.

| Master | Desktop before → after | Tablet before → after | Mobile before → after | Status |
|---|---:|---:|---:|---|
| Sending Engine (`list-item`) | 0 → 0 | 0 → 0 | 0 → 0 | `ready` |
| AI Market Scan (`list-item-review`) | 0 → 0 | 0 → 0 | 0 → 0 | `ready` |

The former 1–3 px overflow/clip reports and the 2–3 px price-glyph escapes (`$3K`, `$5K`, `$10K`, `$500`) are below the documented noise threshold and no longer surface as “Нужна доводка”. Wrap detection is unchanged.

## Injected `$3K` regression

The desktop `$3K` frame was deliberately narrowed from `47.48 px` to `28 px`. Browser measurement reported `15 px` overflow plus `15 px` clip; deterministic polish expanded the frame to `45 px`. The repaired candidate has zero overflow, clip, escape, wrap, or overlap defects on desktop/tablet/mobile and records status `ready`.

| Viewport | Before | After | Escape after | Pixel similarity after | Required floor |
|---|---:|---:|---:|---:|---:|
| Desktop | 2 (`1 overflow`, `1 clip`) | 0 | 0 | 96.57% | 95.53% |
| Tablet | 0 | 0 | 0 | 96.48% | 95.12% |
| Mobile | 0 | 0 | 0 | 94.87% | 94.05% |

The repair passed the existing source-proof fidelity gate on every viewport and introduced no new defect or component escape.

| Before: clipped `$3K` | After: repaired `$3K` |
|---|---|
| ![Narrow $3K frame before polish](slsbmb-polish-before.png) | ![Expanded $3K frame after polish](slsbmb-polish-after.png) |

Clean-master evidence: [Sending Engine before](slsbmb-polish-sending-before.png), [Sending Engine after](slsbmb-polish-sending-after.png), [AI Market Scan before](slsbmb-polish-ai-before.png), [AI Market Scan after](slsbmb-polish-ai-after.png).
