# Design Studio v3 — quality report

Generated: 2026-09-03 17:48 UTC. Render width: 1440 px. Exemplar target: vision score ≥90.

## Fixed five-brief benchmark

`before` is a controlled ablation of exemplar context; `after` uses the same current prompt and the two named product exemplars. This is not presented as a historical score.

| Product | Before PNG | Before score | After PNG | After score | Delta |
|---|---|---:|---|---:|---:|
| SaaS | [PNG](quality-report-assets-live/briefs/saas-before.png) | 52 | [PNG](quality-report-assets-live/briefs/saas-after.png) | 72 | +20 |
| Маркетплейс | [PNG](quality-report-assets-live/briefs/marketplace-before.png) | 66 | [PNG](quality-report-assets-live/briefs/marketplace-after.png) | 73 | +7 |
| Ресторан | [PNG](quality-report-assets-live/briefs/restaurant-before.png) | 88 | [PNG](quality-report-assets-live/briefs/restaurant-after.png) | 76 | -12 |
| Портфолио | [PNG](quality-report-assets-live/briefs/portfolio-before.png) | 56 | [PNG](quality-report-assets-live/briefs/portfolio-after.png) | 76 | +20 |
| Финтех | [PNG](quality-report-assets-live/briefs/fintech-before.png) | 76 | [PNG](quality-report-assets-live/briefs/fintech-after.png) | 76 | +0 |

Median: **66 → 76** (пар с оценкой: 5 из 5).

## Exemplar library

Count: **10**. Live score cells remain `not run` until a configured vision provider executes the default mode.

| Exemplar | PNG | Schema | Sanitize stable | Quality gate | Slop checklist | Vision score |
|---|---|---|---|---|---|---:|
| ecommerce | [PNG](quality-report-assets-live/exemplars/ecommerce.png) | pass | pass | pass | pass | 76 |
| education | [PNG](quality-report-assets-live/exemplars/education.png) | pass | pass | pass | pass | 68 |
| fintech | [PNG](quality-report-assets-live/exemplars/fintech.png) | pass | pass | pass | pass | 84 |
| healthcare | [PNG](quality-report-assets-live/exemplars/healthcare.png) | pass | pass | pass | pass | 72 |
| marketplace | [PNG](quality-report-assets-live/exemplars/marketplace.png) | pass | pass | pass | pass | 76 |
| portfolio | [PNG](quality-report-assets-live/exemplars/portfolio.png) | pass | pass | pass | pass | 68 |
| real-estate | [PNG](quality-report-assets-live/exemplars/real-estate.png) | pass | pass | pass | pass | 88 |
| restaurant | [PNG](quality-report-assets-live/exemplars/restaurant.png) | pass | pass | pass | pass | 81 |
| saas-landing | [PNG](quality-report-assets-live/exemplars/saas-landing.png) | pass | pass | pass | pass | 64 |
| travel | [PNG](quality-report-assets-live/exemplars/travel.png) | pass | pass | pass | pass | 88 |

## Verification contract

Dry-run guarantees valid Design IR, byte-stable sanitize, an empty deterministic quality gate, bounded PNG evidence, and a mechanical check for the RUBRIC slop tropes (empty imagery, excessive pills/cards, repeated copy). Visual hierarchy, rhythm, density, typography and brief fit remain the vision judge's responsibility.

Operator command with credentials:

```powershell
.venv\Scripts\python tools/quality_report.py
```

The live command exits non-zero if an exemplar scores below 90, a local check fails, or a report PNG exceeds 400 KiB.
