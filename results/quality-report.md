# Design Studio v3 — quality report

Generated: 2026-09-03 10:52 UTC. Render width: 1440 px. Exemplar target: vision score ≥90.

## Fixed five-brief benchmark

`before` is a controlled ablation of exemplar context; `after` uses the same current prompt and the two named product exemplars. This is not presented as a historical score.

| Product | Before PNG | Before score | After PNG | After score | Delta |
|---|---|---:|---|---:|---:|
| SaaS | not run | not run | not run | not run | not run |
| Маркетплейс | not run | not run | not run | not run | not run |
| Ресторан | not run | not run | not run | not run | not run |
| Портфолио | not run | not run | not run | not run | not run |
| Финтех | not run | not run | not run | not run | not run |

Live generation and vision scoring: **not run / ожидает ключей**.

## Exemplar library

Count: **10**. Live score cells remain `not run` until a configured vision provider executes the default mode.

| Exemplar | PNG | Schema | Sanitize stable | Quality gate | Slop checklist | Vision score |
|---|---|---|---|---|---|---:|
| ecommerce | [PNG](quality-report-assets/exemplars/ecommerce.png) | pass | pass | pass | pass | not run |
| education | [PNG](quality-report-assets/exemplars/education.png) | pass | pass | pass | pass | not run |
| fintech | [PNG](quality-report-assets/exemplars/fintech.png) | pass | pass | pass | pass | not run |
| healthcare | [PNG](quality-report-assets/exemplars/healthcare.png) | pass | pass | pass | pass | not run |
| marketplace | [PNG](quality-report-assets/exemplars/marketplace.png) | pass | pass | pass | pass | not run |
| portfolio | [PNG](quality-report-assets/exemplars/portfolio.png) | pass | pass | pass | pass | not run |
| real-estate | [PNG](quality-report-assets/exemplars/real-estate.png) | pass | pass | pass | pass | not run |
| restaurant | [PNG](quality-report-assets/exemplars/restaurant.png) | pass | pass | pass | pass | not run |
| saas-landing | [PNG](quality-report-assets/exemplars/saas-landing.png) | pass | pass | pass | pass | not run |
| travel | [PNG](quality-report-assets/exemplars/travel.png) | pass | pass | pass | pass | not run |

## Verification contract

Dry-run guarantees valid Design IR, byte-stable sanitize, an empty deterministic quality gate, bounded PNG evidence, and a mechanical check for the RUBRIC slop tropes (empty imagery, excessive pills/cards, repeated copy). Visual hierarchy, rhythm, density, typography and brief fit remain the vision judge's responsibility.

Operator command with credentials:

```powershell
.venv\Scripts\python tools/quality_report.py
```

The live command exits non-zero if an exemplar scores below 90, a local check fails, or a report PNG exceeds 400 KiB.
