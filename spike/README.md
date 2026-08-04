# Spike (Фаза 0) — go/no-go проверка

Цель: убедиться, что Kimi/Qwen стабильно генерируют **валидный Design IR** по нашей схеме, до начала разработки продукта.

## Что в папке
- `../schema/design-ir.schema.json` — JSON Schema представления дизайна (токены + дерево секций).
- `../docs/BLOCKS.md` — каталог блоков и правила композиции.
- `system-prompt.md` — системный промпт Generator-ноды (шаблон с плейсхолдерами).
- `test-briefs.md` — 7 тестовых брифов и критерии прохождения.
- `run_test.py` — прогон брифа через Kimi/Qwen (stdlib, без зависимостей).
- `validate.py` — валидация результата по схеме (`pip install jsonschema`).

## Как прогнать

```bash
# 1. Ключи
set MOONSHOT_API_KEY=sk-...
set DASHSCOPE_API_KEY=sk-...

# 2. Виртуальное окружение для валидатора
python -m venv .venv && .venv/Scripts/activate
pip install jsonschema

# 3. Генерация (пример: бриф B1 на Kimi, температура 0.7)
python spike/run_test.py --provider kimi --temperature 0.7 \
  --brief "Лендинг для SaaS-платформы аналитики маркетинга..." \
  --out results/b1-kimi-t07.json

# 4. Валидация
python spike/validate.py results/b1-kimi-t07.json
python spike/validate.py results/        # все сразу

# 5. Repair-режим (починка невалидного результата qwen3-coder-plus)
python spike/run_test.py --provider qwen --repair results/b1-kimi-t07.json \
  --out results/b1-kimi-t07-fixed.json
```

## Порядок работы
1. Прогнать брифы B1–B7 (см. `test-briefs.md`) на обеих моделях, 3 температуры — всего 42 генерации. Заполнять матрицу результатов.
2. Сверить с критериями go/no-go в `test-briefs.md`.
3. Если валидность <90% — итерировать system-prompt / схему (упростить enum'ы, убрать additionalProperties там, где модель ошибается), НЕ начинать разработку продукта.
4. Следующий шаг после спайка: рендерер IR → HTML/Tailwind (нужен для скоринга качества и critic-прохода).

## Заметки
- `run_test.py` использует OpenAI-совместимый `response_format: json_object`; если модель ругaется — убрать этот параметр, extract_json всё равно вытащит JSON из markdown.
- Имя модели Kimi в `PROVIDERS` проверить в консоли Moonshot — k2.5/k2.6 могут появляться под новыми id.
