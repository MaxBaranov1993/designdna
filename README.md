# DesignAI Web

DesignAI Web — это controlled AI-инструмент для веб-дизайна: **Figma + AI, но контролируемая**, с графом как в ComfyUI/Houdini и параметрами как в Substance Designer.

Главная идея: AI не должен быть лотереей. Он предлагает варианты, а дизайнер управляет структурой, layout, стилем, весами, масками, constraints, качеством и историей проекта.

## Для кого

Первый фокус продукта:

- **вайбкодер / AI-builder** — хочет быстро собрать сайт, но не потерять контроль над структурой и качеством;
- **веб-дизайнер-фрилансер** — хочет брать референсы, вытаскивать стиль, править руками и генерировать новые блоки в рамках проекта.

Второй фокус:

- дизайн-студии, которым нужны повторяемость, style memory, клиентские варианты и командный workflow;
- обычные дизайнеры, которым нужна скорость AI без ощущения, что “машина всё решила за них”.

## Killer loop

```text
Референс / сайт / скрин / промпт
  → Source Import / Generator
  → выбрать удачный блок
  → Style DNA: палитра, шрифты, отступы, радиусы, ритм
  → Edit: открыть DNA Editor и поправить как в Figma/Pen.dev
  → Reskin / Derive / Mix с lock structure/layout/style
  → Quality Pass: judge + repair + scorecard
  → сохранить как проектный стиль / asset / reusable node
```

Примеры:

- загрузил сайт, выбрал hero, сохранил его Style DNA;
- сделал header, подключил Derive и получил footer в том же стиле;
- взял карточку из генерации, подключил Reskin и сменил визуальный стиль без изменения layout;
- смешал два варианта по весам, как procedural graph;
- открыл блок в DNA Editor, руками поправил spacing/layout/text и продолжил генерацию от этой версии.

## Что уже есть

- React Flow-граф с 12 актуальными нодами.
- Typed wires: `text`, `ir`, `tokens`.
- Snap проводов при наведении на совместимую ноду.
- OpenRouter-only AI gateway: UI не выбирает прямые провайдеры.
- Design IR как source of truth.
- Source Import: URL/скрин → блоки + Style DNA.
- Style DNA: извлечение токенов проекта.
- Derive: родственный компонент по выбранному блоку и style DNA.
- Reskin: рестайл с mask и merge-back.
- Mix: смешивание IR по весам.
- Edit-нода как thin preview + вход в fullscreen DNA Editor.
- DNA Editor: layers, inspector, selection, drag, resize, hand pan, rect/text/frame tools, undo.
- Quality Pass: AI judge + repair + scorecard.

## Документация

- [docs/PRODUCT.md](docs/PRODUCT.md) — продукт, аудитории, use-cases, позиционирование.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Design IR, граф, OpenRouter, editor, project memory.
- [docs/NODES.md](docs/NODES.md) — актуальные и предлагаемые ноды.
- [docs/ROADMAP.md](docs/ROADMAP.md) — поэтапный путь к controlled AI design platform.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — запуск, тесты, правила разработки.
- [docs/BLOCKS.md](docs/BLOCKS.md) — каталог IR-блоков для генератора.

## Быстрый запуск

```powershell
cd C:\Users\iamma\Documents\desingaiweb
.venv\Scripts\python.exe app\server.py
```

Открыть:

```text
http://127.0.0.1:8420/flow
```

Сборка фронта:

```powershell
cd frontend
npm run build
```

Ключ AI:

```powershell
$env:OPENROUTER_API_KEY="..."
```

## Северная звезда

Сделать инструмент, где AI-дизайн становится не генератором случайных картинок, а **контролируемым procedural workflow**:

- дизайнер задаёт правила;
- AI предлагает;
- граф фиксирует решения;
- стиль проекта обучается на выбранных блоках и правках;
- layout и структура сохраняются, если пользователь их залочил;
- каждый результат можно объяснить, сравнить, откатить и развить дальше.
