
## Результаты прогона (2026-07-26, 42/42 генераций, 0 ошибок API)

Модели: qwen = qwen3.7-max (Bailian Token Plan), kimi = k3 (coding plan, T=1 фикс).

| Прогон | Секций | Валиден сразу | Repair (qwen, 1 попытка) | Структура |
|---|---|---|---|---|
| b1-kimi-r1 | 11 | да | — | navbar > hero ... footer |
| b1-kimi-r2 | 10 | да | — | navbar > hero ... footer |
| b1-kimi-r3 | 10 | да | — | navbar > hero ... footer |
| b1-qwen-t07 | 11 | да | — | navbar > hero ... footer |
| b1-qwen-t09 | 11 | да | — | navbar > hero ... footer |
| b1-qwen-t10 | 11 | да | — | navbar > hero ... footer |
| b2-kimi-r1 | 9 | да | — | navbar > hero ... footer |
| b2-kimi-r2 | 8 | нет | OK | navbar > hero ... footer |
| b2-kimi-r3 | 7 | да | — | navbar > hero ... footer |
| b2-qwen-t07 | 7 | да | — | navbar > hero ... footer |
| b2-qwen-t09 | 11 | да | — | navbar > hero ... footer |
| b2-qwen-t10 | 9 | да | — | navbar > hero ... footer |
| b3-kimi-r1 | 9 | да | — | navbar > hero ... footer |
| b3-kimi-r2 | 11 | да | — | navbar > hero ... footer |
| b3-kimi-r3 | 11 | да | — | navbar > hero ... footer |
| b3-qwen-t07 | 12 | да | — | navbar > hero ... footer |
| b3-qwen-t09 | 13 | да | — | navbar > hero ... footer |
| b3-qwen-t10 | 12 | нет | OK | navbar > hero ... footer |
| b4-kimi-r1 | 9 | да | — | navbar > hero ... footer |
| b4-kimi-r2 | 10 | нет | OK | navbar > hero ... footer |
| b4-kimi-r3 | 8 | да | — | navbar > hero ... footer |
| b4-qwen-t07 | 12 | да | — | navbar > hero ... footer |
| b4-qwen-t09 | 11 | да | — | navbar > hero ... footer |
| b4-qwen-t10 | 9 | да | — | navbar > hero ... footer |
| b5-kimi-r1 | 11 | да | — | navbar > hero ... footer |
| b5-kimi-r2 | 10 | да | — | navbar > hero ... footer |
| b5-kimi-r3 | 10 | да | — | navbar > hero ... footer |
| b5-qwen-t07 | 10 | да | — | navbar > hero ... footer |
| b5-qwen-t09 | 11 | нет | OK | navbar > hero ... footer |
| b5-qwen-t10 | 11 | да | — | navbar > hero ... footer |
| b6-kimi-r1 | 1 | да | — | 1 блок (OK для b6) |
| b6-kimi-r2 | 1 | да | — | 1 блок (OK для b6) |
| b6-kimi-r3 | 1 | да | — | 1 блок (OK для b6) |
| b6-qwen-t07 | 1 | да | — | 1 блок (OK для b6) |
| b6-qwen-t09 | 1 | да | — | 1 блок (OK для b6) |
| b6-qwen-t10 | 1 | да | — | 1 блок (OK для b6) |
| b7-kimi-r1 | 12 | нет | OK | navbar > hero ... footer |
| b7-kimi-r2 | 11 | да | — | navbar > hero ... footer |
| b7-kimi-r3 | 11 | да | — | navbar > hero ... footer |
| b7-qwen-t07 | 12 | да | — | navbar > hero ... footer |
| b7-qwen-t09 | 11 | да | — | navbar > hero ... footer |
| b7-qwen-t10 | 10 | нет | OK | ОТКЛОНЕНИЕ |
