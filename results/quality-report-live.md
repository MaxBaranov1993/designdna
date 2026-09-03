# Design Studio v3 — quality report

Generated: 2026-09-03 17:00 UTC. Render width: 1440 px. Exemplar target: vision score ≥90.

## Fixed five-brief benchmark

`before` is a controlled ablation of exemplar context; `after` uses the same current prompt and the two named product exemplars. This is not presented as a historical score.

| Product | Before PNG | Before score | After PNG | After score | Delta |
|---|---|---:|---|---:|---:|
| SaaS | [PNG](quality-report-assets-live/briefs/saas-before.png) | 55 | [PNG](quality-report-assets-live/briefs/saas-after.png) | 84 | +29 |
| Маркетплейс | [PNG](quality-report-assets-live/briefs/marketplace-before.png) | 55 | [PNG](quality-report-assets-live/briefs/marketplace-after.png) | 58 | +3 |
| Ресторан | [PNG](quality-report-assets-live/briefs/restaurant-before.png) | 72 | [PNG](quality-report-assets-live/briefs/restaurant-after.png) | 62 | -10 |
| Портфолио | [PNG](quality-report-assets-live/briefs/portfolio-before.png) | 62 | [PNG](quality-report-assets-live/briefs/portfolio-after.png) | 72 | +10 |
| Финтех | [PNG](quality-report-assets-live/briefs/fintech-before.png) | 66 | [PNG](quality-report-assets-live/briefs/fintech-after.png) | 48 | -18 |

Median: **62 → 62** (пар с оценкой: 5 из 5).

## Exemplar library

Count: **10**. Live score cells remain `not run` until a configured vision provider executes the default mode.

| Exemplar | PNG | Schema | Sanitize stable | Quality gate | Slop checklist | Vision score |
|---|---|---|---|---|---|---:|
| ecommerce | [PNG](quality-report-assets-live/exemplars/ecommerce.png) | pass | pass | pass | pass | 72 |
| education | [PNG](quality-report-assets-live/exemplars/education.png) | pass | pass | pass | pass | 66 |
| fintech | [PNG](quality-report-assets-live/exemplars/fintech.png) | pass | pass | pass | pass | 78 |
| healthcare | [PNG](quality-report-assets-live/exemplars/healthcare.png) | pass | pass | pass | pass | failed: Error: Page.goto: net::ERR_ABORTED at https://render.ir.invalid/document
Call log:
  - navigating to "https://render.ir.invalid/document", waiting until "load"
 |
| marketplace | [PNG](quality-report-assets-live/exemplars/marketplace.png) | pass | pass | pass | pass | 72 |
| portfolio | [PNG](quality-report-assets-live/exemplars/portfolio.png) | pass | pass | pass | pass | 68 |
| real-estate | [PNG](quality-report-assets-live/exemplars/real-estate.png) | pass | pass | pass | pass | 89 |
| restaurant | [PNG](quality-report-assets-live/exemplars/restaurant.png) | pass | pass | pass | pass | failed: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://render.ir.invalid/document", waiting until "load"
 |
| saas-landing | [PNG](quality-report-assets-live/exemplars/saas-landing.png) | pass | pass | pass | pass | 68 |
| travel | [PNG](quality-report-assets-live/exemplars/travel.png) | pass | pass | pass | pass | 84 |

## Verification contract

Dry-run guarantees valid Design IR, byte-stable sanitize, an empty deterministic quality gate, bounded PNG evidence, and a mechanical check for the RUBRIC slop tropes (empty imagery, excessive pills/cards, repeated copy). Visual hierarchy, rhythm, density, typography and brief fit remain the vision judge's responsibility.

Operator command with credentials:

```powershell
.venv\Scripts\python tools/quality_report.py
```

The live command exits non-zero if an exemplar scores below 90, a local check fails, or a report PNG exceeds 400 KiB.
