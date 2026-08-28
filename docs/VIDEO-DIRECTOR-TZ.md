# ТЗ: нода «Режиссёр» — ИИ собирает видеоролик из наших компонентов

**Исполнитель:** GLM 5.3. **Ветка:** от `main`, имя `glm/video-director`.

Цель одной фразой: пользователь кидает в ноду страницу/компоненты и короткий
бриф, ИИ собирает из них осмысленный ролик уровня «скринкаст сайта, доведённый
в After Effects», пользователь правит его руками на таймлайне и жмёт «Рендер» —
на выходе mp4.

---

## 0. Правила работы

**Читай этот раздел до начала.**

1. **Не ломать существующее.** Нода `motion` в текущем виде (Motion IR 1.0 из
   Interaction IR) обязана продолжать работать. Все старые проекты должны
   открываться. Ветка `build_motion` не трогается.
2. **Язык комментариев** — русский, как в `frontend/src/flow/ports.ts` и
   `app/server.py`. Docstring в Python-модулях — английский, как в
   `app/ir/motion_v2.py`. Смотри соседние файлы и повторяй их стиль.
3. **Тесты** — рядом с модулем, суффикс `_test.py` (конвенция репозитория:
   `app/ir/motion_v2_test.py`, `app/fidelity_repair_test.py`).
4. **Прогон:**
   ```bash
   python -m pytest app -q
   ```
   ```bash
   npm --prefix frontend run check
   ```
   Оба должны быть зелёными на каждом коммите.
5. **Схемы** — в `schema/`, валидация через `jsonschema.Draft7Validator`,
   `additionalProperties: false` везде. Образец — `schema/motion-ir-2.0.schema.json`.
6. **Fail-closed.** Невалидный артефакт — ошибка 422 с внятным текстом, никогда
   не «починим на следующем шаге».
7. **Коммиты** — по одному на этап из раздела 15, сообщение на русском в стиле
   существующих (`feat(motion): ...`, `fix(render): ...`).
8. **Не изобретать.** Если в репозитории уже есть решение (конверт LLM,
   `err()`, `content_hash`, `IrPreview`, `NodeShell`) — использовать его.

---

## 1. Пользовательский сценарий (то, что должно заработать)

1. `Source Import` разбирает сайт → появляются реальные компоненты и токены.
2. Пользователь ставит ноду **`Режиссёр`**, тянет провода: `artifact` от Source
   Import, `ir` от страницы, `tokens` от Design System.
3. Пишет бриф одной строкой: *«30-секундный ролик для лендинга: показать, как
   создаётся счёт за один клик»*. Выбирает пресет (`Промо 16:9`, `Реклама 9:16`,
   `Онбординг`) и провайдера — **GPT-5.6 Sol / Codex / Claude Opus**.
4. Жмёт «Собрать ролик». ИИ раскладывает бриф на сцены: что показать (конкретный
   наш компонент) и каким приёмом (из каталога).
5. Провод `storyboard` идёт в ноду `Motion` → таймлайн. Пользователь двигает
   границы сцен, меняет приём в выпадающем списке, таскает рамку камеры прямо по
   превью, отключает лишнее.
6. «Рендер» → mp4.

---

## 2. Архитектурное решение

**ИИ не пишет анимацию. ИИ выбирает приёмы и цели.**

| Слой | Кто делает | Артефакт |
|---|---|---|
| **ЧТО показываем** | уже есть | Design IR / Source Artifact — реальные компоненты, состояния, токены |
| **КАК показываем** | детерминированный Python | **Каталог приёмов** — библиотека motion-приёмов с выверенными кривыми |
| **ЧТО чем и в каком порядке** | ИИ | **Storyboard IR** — список сцен: приём + цель + вес |

Если дать модели писать keyframes напрямую — получится дёрганое месиво: модель
не чувствует ритм, ставит линейные кривые, промахивается по таймингам. Если она
выбирает из каталога, где каждый приём сделан с правильными `spring`/`bezier` и
стаггером, результат выглядит профессионально **независимо от качества модели**.

Это тот же контракт, что уже работает в `app/fidelity_repair.py`: LLM предлагает,
детерминированный код проверяет и исполняет.

```
Source Artifact ─┐
Design IR ───────┼─► Режиссёр (ИИ) ─storyboard─► compile.py ─► Motion IR 2.1 ─► Таймлайн ─► mp4
Бриф (текст) ────┤     приём+цель      (детерминированно)        (правится руками)
Design System ───┘                            ↑
                                     shots/ + rhythm.py
```

---

## 3. Что уже есть в коде (не переписывать, использовать)

| Что | Где | Замечание |
|---|---|---|
| Реальные компоненты продукта | `SourceArtifact` в `frontend/src/flow/types.ts`, `app/blockparse.py` | `SourceArtifactComponent` содержит `componentKey`, `name`, `role`, `states`, `master.selector` |
| Design IR + рендерер | `app/static/flow/engine.js` (`window.IRRenderer.renderIR`) | Используется рендером кадров |
| Motion IR 2.0 схема и валидатор | `schema/motion-ir-2.0.schema.json`, `app/ir/motion_v2.py` | Слои, клипы, property-треки, `markers`, `captions`, `assets`, `safeAreas` нет |
| Motion IR 1.0 + `build_motion` | `app/ir/motion.py` | **Не трогать** |
| Рендер видео | `app/motion_render.py` | Playwright + ffmpeg, `MAX_RENDER_FRAMES = 10_800`, умеет только сцены 1.0 |
| Таймлайн | `frontend/src/nodes/MotionNode.svelte`, `MotionWorkspace.svelte` | 203 строки, `rAF`-плейхед готов |
| Цикл починки с судьёй | `app/fidelity_repair.py`, `app/fidelity_harness.py` | Образец для `motion/repair.py` |
| Контраст цветов | `app/colorutils.py` | Для судьи |
| Хеш документа | `app/ir/hash.py:content_hash` | Для `source.*Hash` |
| Флаг | `app/config/flags.py:24` — `"aiDirector": False` | Включить на этапе 3 |
| LLM-роль | `app/llm_client.py:26` — `"motion_director"` в `_ROLES` | Уже зарезервирована |
| Ошибки API | `app/server.py:189` — `err(status, message)` → `{"detail": ...}` | Фронт бросает `Error(detail)` |

### 3.1 Как в этом проекте работает выбор провайдера — повторить точно

Web-режим: сервер сам зовёт `llm.chat(...)`. Desktop-режим: сервер только
**готовит промпт**, ответ приносит фронт через локальный CLI-аккаунт. Паттерн
`prepareOnly` — `app/server.py:1174` и `frontend/src/flow/store.ts:1386-1401`:

```ts
// frontend/src/flow/store.ts, ветка reskin — копировать один-в-один
const desktop = window.designDNA;
if (!desktop) {
  res = await api<DirectorResp>("/api/director/storyboard", payload);
} else {
  const prepared = await api<{ prompts: Array<{ messages: ApiChatMessage[] }> }>(
    "/api/director/storyboard", { ...payload, prepareOnly: true },
  );
  if (!prepared.prompts?.length) throw new Error("Не удалось подготовить промпт режиссёра");
  const answer = await desktop.providers.chatRequest({
    ...chatRoute(nodeProvider(data.provider), effort),
    messages: prepared.prompts[0].messages,
  });
  res = await api<DirectorResp>("/api/director/storyboard", { ...payload, rawOutput: answer.content });
}
```

`chatRoute` (`store.ts:85`) уже разводит провайдеров:
`claude → {provider:"claude", model:"opus", reasoning:{effort}}`,
`codex → {provider:"codex", model:null}`,
`openai → {provider:"openai", model:"gpt-5.6-sol", reasoning:{effort}}`.

**Ничего в маршрутизации провайдеров не менять.** Просто использовать.

---

## 4. Контракт: Storyboard IR 1.0

Файлы: `schema/storyboard-ir-1.0.schema.json`, `app/ir/storyboard.py`,
`app/ir/storyboard_test.py`.

Это **единственный** артефакт, который пишет модель. Намеренно маленький: чем
меньше свободы, тем стабильнее результат.

### 4.1 Документ

```jsonc
{
  "version": "1.0",
  "source": {
    "baseDesignIrHash": "…",          // content_hash(design_ir)
    "sourceArtifactHash": "…"         // content_hash(source_artifact) или null
  },
  "brief": "30-секундный ролик для лендинга: счёт за один клик",
  "format": "promo-16x9",
  "scenes": [
    {
      "id": "sc-01",
      "shot": "establish",
      "target": null,
      "weight": 1.0,
      "note": "открываем сайт",
      "text": null,
      "params": {},
      "enabled": true
    },
    {
      "id": "sc-02",
      "shot": "zoom-to-region",
      "target": { "kind": "component", "ref": "cmp_invoice_table" },
      "weight": 1.4,
      "note": "вот где живут счета",
      "text": null,
      "params": { "region": [0.08, 0.12, 0.55, 0.46] },
      "enabled": true
    }
  ]
}
```

### 4.2 Поля сцены

| Поле | Тип | Обязательно | Кто заполняет |
|---|---|---|---|
| `id` | `^sc-[0-9]{2,3}$` | да | модель |
| `shot` | id из реестра приёмов | да | модель |
| `target` | `{kind: "component"\|"sourceKey"\|"block", ref: string}` либо `null` | да | модель |
| `weight` | number `0.5..2.0` | да | модель (относительная важность) |
| `note` | string ≤ 200 | да | модель (для UI, на рендер не влияет) |
| `text` | string ≤ 200 либо `null` | да | модель (титр/CTA, только для `title-card` и `cta-outro`) |
| `params` | object | да | модель (частично) и пользователь (правкой) |
| `enabled` | boolean | да | пользователь |

Модель **не задаёт**: длительности, кривые, переходы, координаты слоёв, цвета.
Всё это — `rhythm.py` и каталог приёмов.

### 4.3 Валидация (`app/ir/storyboard.py`)

```python
def validate(
    document: dict,
    base_ir: dict,
    source_artifact: dict | None,
    preset: dict,
) -> list[str]:
    """Return human-readable errors; empty list means the storyboard is compilable."""
```

Проверки, каждая — отдельный кейс в тесте:

1. схема Draft-7 проходит;
2. `id` сцен уникальны;
3. `shot` есть в `app/motion/shots/registry.py:SHOTS` — иначе
   `sc-03/shot: unknown shot "foo"`;
4. `shot` разрешён пресетом (`preset["shots"]`);
5. **`target.ref` существует**: для `kind: "component"` — среди
   `source_artifact["components"][*]["componentKey"]`; для `kind: "sourceKey"` —
   среди `sourceKey` узлов `base_ir`; для `kind: "block"` — среди имён блоков.
   Несуществующая ссылка — **ошибка**, не предупреждение. Это главная точка,
   где ломается «модель придумала экран»;
6. приём совместим с типом цели по таблице `SHOTS[shot].target_requirement`:
   - `none` — `target` обязан быть `null`;
   - `any` — любой непустой;
   - `container` — у цели ≥ 2 детей в IR;
   - `interactive` — у цели есть наблюдённое состояние в
     `SourceArtifactComponent.states` (`hover` либо `active`);
   - `text-numeric` — текст цели матчит `^[^\d]*\d[\d\s.,]*[^\d]*$`;
7. число сцен в `preset["sceneRange"]`;
8. если `preset["requireOpening"]` — первая включённая сцена из группы `opening`;
   если `preset["requireClosing"]` — последняя из группы `closing`;
9. `text` непустой ровно у тех приёмов, у которых `SHOTS[shot].needs_text`;
10. `params` проходит `SHOTS[shot].params_schema`.

### 4.4 Одна переспроска

Если валидация упала, сервер формирует ремонтный промпт (текст ошибок + прошлый
ответ) и делает **ровно один** повторный вызов — как в `/api/reskin`
(`app/server.py:1188-1204`). Если и он не прошёл — `err(422, ...)` со списком
ошибок; нода показывает их в статусе.

---

## 5. Контракт: Motion IR 2.1

Файлы: `schema/motion-ir-2.1.schema.json`, дополнить `app/ir/motion_v2.py`,
дополнить `app/ir/motion_v2_test.py`.

Схема 2.0 закрыта (`additionalProperties: false`), поэтому нужна версия.
Расширение **аддитивное**: любой валидный 2.0-документ валиден как 2.1 после
подмены `version`.

Добавить:

| Путь | Тип | Смысл |
|---|---|---|
| `version` | `const "2.1"` | — |
| `composition.safeAreas[]` | `{id, role: "talking-head"\|"caption"\|"logo", rect: [x,y,w,h] в долях 0..1}` | Зарезервированные зоны; контент туда не лезет |
| `layer.shotId` | `identifier` | Какой сценой раскадровки порождён слой |
| `layer.detached` | boolean | Слой правили руками — перекомпиляция его не трогает |
| `marker.kind` | `"scene" \| "accent"` | default `"scene"` |
| `source.storyboardHash` | `hash` | — |

Функции (по образцу `migrate_motion_v1_to_v2`):

```python
def validate_motion_v21(document: dict) -> list[str]: ...
def migrate_motion_v2_to_v21(document: dict) -> dict: ...
```

Семантические проверки 2.1 (в дополнение к унаследованным от 2.0):
`safeAreas[].rect` внутри `[0,1]`, `id` уникальны, `shotId` ссылается на
существующую сцену раскадровки (если передан storyboard).

---

## 6. Каталог приёмов — сердце качества

Каталог: `app/motion/shots/`, реестр `app/motion/shots/registry.py`, тест
`app/motion/shots/registry_test.py`. Числовые параметры каждого приёма — в
JSON рядом с модулем (`establish.json`), чтобы дизайнер крутил их без кода.

### 6.1 Контракт приёма

```python
@dataclasses.dataclass(frozen=True)
class ShotContext:
    duration: int                 # мс, уже назначено rhythm.py
    composition: dict             # width, height, fps
    tokens: dict                  # токены Design System
    target_rect: tuple[float, float, float, float] | None  # доли 0..1 в кадре
    target_ir: dict | None        # поддерево Design IR цели
    preset: dict
    previous_shot: str | None
    next_shot: str | None
    params: dict                  # из storyboard.scenes[].params

@dataclasses.dataclass(frozen=True)
class ShotSpec:
    id: str
    group: str                    # "opening" | "camera" | "screencast" | "accent" | "closing"
    title: str                    # для UI, по-русски
    target_requirement: str       # none | any | container | interactive | text-numeric
    needs_text: bool
    min_duration: int
    max_duration: int
    base_duration: int
    params_schema: dict
    build: Callable[[ShotContext], ShotResult]

@dataclasses.dataclass(frozen=True)
class ShotResult:
    layers: list[dict]            # слои Motion IR 2.1 (без id префикса — его ставит compile)
    markers: list[dict]           # акценты внутри сцены
    camera: dict | None           # property-треки камеры для этой сцены
```

Жёсткие требования к каждому приёму:

- keyframes только по разрешённым `propertyPath` схемы 2.0
  (`transform.position|scale|rotation|anchorPoint`, `opacity`, `crop`, `blur`,
  `mask.path`, `mask.opacity`);
- цвета, радиусы, шрифты — **только** из `ctx.tokens`, хардкод запрещён;
- корректно ужимается и растягивается в `[min_duration, max_duration]` без
  ломки кривых (проверяется тестом на обоих концах диапазона);
- `build` — чистая функция: одинаковый `ctx` → побитово одинаковый результат
  (проверяется через `content_hash`);
- время keyframes отсчитывается **от нуля сцены**, смещение ставит `compile.py`.

### 6.2 Набор этапа 1 — 6 приёмов

| id | group | Цель | Что делает |
|---|---|---|---|
| `establish` | opening | `none` | Полная страница в кадре, медленный zoom-in `scale 1.0 → 1.04`, `bezier` ease-out, opacity `0 → 1` за 400 мс |
| `zoom-to-region` | camera | `any` | Камера наезжает на `params.region` (доли кадра): `scale` до вписывания региона, `position` до его центра. Кривая — `bezier` с ручками `[0.22,1,0.36,1]`, хвост-hold 25% длительности. Фон уходит в `blur 0 → 3px` |
| `spotlight` | accent | `any` | Всё, кроме цели, затемняется (`overlay`-слой `opacity 0 → 0.55`, цвет из токена `neutral.900`) с вырезом-маской по bbox цели + `blur 0 → 4px`; цель приподнимается `scale 1.0 → 1.03` |
| `stagger-reveal` | accent | `container` | Дети цели появляются каскадом: шаг `min(90, duration/count/2.2)` мс, каждый `opacity 0→1` + `position.y +16px→0`, интерполяция `spring` (`stiffness 180, damping 22`) |
| `title-card` | opening | `none`, `needs_text` | Титр `scene.text` на фоне из токенов; типографика — `tokens.typography.display`; текст собирается по словам стаггером 70 мс |
| `cta-outro` | closing | `none`, `needs_text` | Финал: лого (если есть в `tokens.brand.logo`) + `scene.text` + кнопка из Design System; всё стаггером 120 мс, финальный hold 800 мс |

### 6.3 Набор этапа 5 — ещё 8

| id | group | Цель | Что делает |
|---|---|---|---|
| `pan-scroll` | camera | `any` | Прокрутка страницы: `position.y` с инерцией, лёгкий оверскролл 12 px на концах |
| `orbit-card` | camera | `any` | Въезд карточки: `rotation -6° → 0`, `scale 0.94 → 1`, `spring` |
| `cursor-click` | screencast | `interactive` | Курсор приезжает `spring`-траекторией к центру цели, замирает 180 мс, клик: ripple-круг `scale 0→1`/`opacity 0.4→0`, цель переходит в состояние `active` |
| `cursor-hover` | screencast | `interactive` | Курсор наводится, цель переключается в наблюдённое состояние `hover` |
| `type-into` | screencast | `any` | Печать `params.text` по символам, интервал `70 мс ± 25 мс` детерминированным джиттером (seed = `scene.id`), мигающая каретка 530 мс |
| `state-swap` | screencast | `any` | Цель меняет состояние по `params.states` (`default → loading → success`) кроссфейдом 220 мс + подскок `scale 1→1.04→1` |
| `callout` | accent | `any` | Выноска: линия рисуется через `mask.path` за 350 мс, затем подпись `params.label` стаггером; стиль из токенов |
| `number-count` | accent | `text-numeric` | Число докручивается `0 → значение`, ease-out, 60 шагов |

### 6.4 Превью приёмов

Тест `registry_test.py` рендерит каждый приём в 2-секундный webm на синтетической
цели и кладёт в `app/static/shots/<id>.webm`. Эти файлы отдаёт `/api/shots` и
показывает выпадающий список в инспекторе сцены. Файлы коммитятся.

---

## 7. Ритм — тоже код, не модель

Файлы: `app/motion/rhythm.py`, `app/motion/rhythm_test.py`.

```python
def apply_rhythm(storyboard: dict, preset: dict) -> list[SceneTiming]:
    """Assign start, duration and transition to every enabled scene."""
```

Алгоритм, строго в этом порядке:

1. Отбросить сцены с `enabled: false`.
2. Сырая длительность сцены = `SHOTS[shot].base_duration * scene.weight *
   preset["tempo"]`.
3. Клипировать каждую в `[min_duration, max_duration]` приёма.
4. Нормировать сумму под `preset["targetDuration"]` (середина диапазона):
   масштабировать пропорционально, затем повторно клипировать; до 3 итераций,
   потом принять как есть.
5. Округлить каждую до целого кадра при `composition.fps`; невязку добавить в
   самую длинную сцену.
6. **Разведение дублей:** если `shot[i] == shot[i-1]`, вставить между ними
   переход `fade 220 мс` вместо `cut`; если это третий подряд — пометить
   ошибкой (её ловит судья, но раскадровку не блокирует).
7. **Переход** выбирается таблицей `TRANSITIONS[(prev_group, next_group)]`,
   не моделью. Дефолты:
   `(opening, camera) → cut`; `(camera, camera) → fade 200`;
   `(camera, accent) → cut`; `(accent, accent) → fade 220`;
   `(screencast, *) → cut`; `(*, closing) → fade 320`.
8. **Микропауза** 120–200 мс (по `preset["tempo"]`) добавляется в начало каждой
   сцены группы `accent` — это то, что делает ролик «дышащим».

`SceneTiming` — `{scene_id, start, duration, transition: {type, duration, easing}}`.

---

## 8. Пресеты

Файл: `app/config/video_formats.py` — данные, не код.

```python
VIDEO_FORMATS: dict[str, dict] = {
    "promo-16x9": {
        "title": "Промо 16:9",
        "aspect": "16:9",
        "resolution": {"width": 1920, "height": 1080},
        "fps": 30,
        "targetDuration": 30_000,
        "durationRange": [20_000, 40_000],
        "sceneRange": [5, 9],
        "tempo": 1.0,
        "requireOpening": True,
        "requireClosing": True,
        "browserChrome": "macos",       # macos | windows | none
        "shots": [...],                 # разрешённые id приёмов
        "safeAreas": [],
    },
    "ad-9x16":       {... 1080x1920, 15 000 мс, [10 000, 20 000], сцен 3–6, tempo 1.35, closing обязателен ...},
    "ad-1x1":        {... 1080x1080, 22 000 мс, [15 000, 30 000], сцен 4–7, tempo 1.25, closing обязателен ...},
    "onboarding-16x9": {... 1920x1080, 90 000 мс, [40 000, 180 000], сцен 8–20, tempo 0.85, opening обязателен ...},
    "feature-loop":  {... 1920x1080,  9 000 мс, [6 000, 12 000], сцен 2–3, tempo 1.4, без opening/closing ...},
}
```

---

## 9. Компилятор

Файлы: `app/motion/compile.py`, `app/motion/compile_test.py`.

```python
def compile_storyboard(
    storyboard: dict,
    base_ir: dict,
    source_artifact: dict | None,
    tokens: dict,
    preset: dict,
    detached: dict[str, dict] | None = None,
) -> tuple[dict, list[dict]]:
    """Return (motion_ir_2_1, layer_irs). Never calls an LLM."""
```

Порядок:

1. `storyboard.validate(...)` → при ошибках `ValueError` со списком.
2. `rhythm.apply_rhythm(...)` → тайминги.
3. Для каждой сцены: разрешить цель (`componentKey`/`sourceKey`/`block` → узел
   Design IR + его `target_rect` в долях кадра), собрать `ShotContext`, вызвать
   `SHOTS[shot].build(ctx)`.
4. Собрать композицию:
   - `design`-слой на каждую сцену, `sourceKey` = ключ цели, `clips` по таймингу;
   - `camera`-слой один на всю композицию, треки склеены из `ShotResult.camera`;
   - слои из `ShotResult.layers` с префиксом id `<scene_id>:<local_id>`
     и `shotId = scene_id`;
   - опциональная рамка браузера (`preset["browserChrome"]`) — `overlay`-слой
     с inline-SVG;
   - `markers`: по одному `kind: "scene"` на старт сцены + все `kind: "accent"`
     из `ShotResult.markers`;
   - `safeAreas` из пресета;
   - `renderSettings` из пресета (`audio.enabled: false` — см. раздел 16);
   - `source`: хеши base IR, storyboard.
5. **Detached-слои:** если `detached` передан, слои с этими id берутся из него
   как есть, а не из `build()`. Их `detached: true` сохраняется.
6. `validate_motion_v21(motion)` → при ошибках `ValueError`.
7. Вернуть `(motion, layer_irs)`, где `layer_irs = [{"layerId": ..., "ir": ...}]`
   только для слоёв типа `design`.

**Тест на детерминизм обязателен:** один и тот же вход даёт одинаковый
`content_hash(motion)` при 10 повторах.

---

## 10. Сэмплер и рендер 2.1

### 10.1 Сэмплер — интерполяция в Python, не в JS

Файлы: `app/motion/sample.py`, `app/motion/sample_test.py`.

```python
def sample_frame(motion: dict, frame_index: int) -> dict:
    """Return {layerId: {visible, opacity, transform, blur, crop, maskPath}} for one frame."""
```

Почему в Python, а не в браузере: судье нужны те же значения, тесту нужен
детерминизм, а страница остаётся тупым применятором CSS.

Реализовать интерполяции схемы: `hold`, `linear`, `bezier` (кубическая по
`bezierHandles`, поиск `t` по x — бинарный, 12 итераций), `spring` (численно,
шаг = 1/fps, по `stiffness`/`damping`/`mass` из схемы). Значения между
keyframes и за их пределами — зажим по краям.

### 10.2 Рендер

Дополнить `app/motion_render.py`, не ломая существующий путь:

1. Вынести подготовку Playwright в контекст-менеджер `_MotionStage`, чтобы им
   пользовались и рендер, и судья (сейчас код инлайн в `render_video`,
   строки 104-200).
2. Добавить:
   ```python
   def render_video_v21(motion, layer_irs, output, on_progress=None) -> dict: ...
   def render_frames_v21(motion, layer_irs, times_ms: list[int]) -> list[bytes]: ...
   ```
3. `validate_render_input_v21(motion, layer_irs)`: лимит `MAX_RENDER_FRAMES`,
   чётность `width`/`height`, совпадение id `design`-слоёв с `layer_irs`.
4. Разметка страницы:
   ```
   #stage > #camera > .motion-layer[data-layer-id] > .motion-ir
   ```
   `#camera` несёт трансформ камеры; остальные слои — свои. `overlay`, `text`,
   `shape`, `cursor` строятся из данных слоя, без `IRRenderer`.
5. Курсор — inline-SVG в `app/static/flow/cursor.svg`, вставляется как слой.
6. Кадровый цикл: `page.evaluate("s => window.__motionApplyFrame(s)",
   sample_frame(motion, i))`. Функция `__motionApplyFrame` только раскладывает
   значения по `style`, **никакой логики анимации в JS**.
7. `render_video` (1.0) остаётся как есть. Роутер выбирает по `motion["version"]`.

---

## 11. Автопроверка качества

Файлы: `app/motion/judge.py`, `app/motion/repair.py` + тесты.

```python
def judge_motion(motion: dict, layer_irs: list[dict], storyboard: dict) -> dict:
    """Deterministic report: score 0..100 and findings anchored to scenes."""
```

Рендерит кадры в середине каждой сцены и на границах переходов через
`render_frames_v21`, проверяет:

| Проверка | Метрика | Порог |
|---|---|---|
| Цель сцены видна | доля bbox цели в кадре | ≥ 60% своей площади |
| Цель не в safe-area | пересечение | ≤ 5% |
| Текст не обрезан и не у края | клиппинг / отступ | 0 / ≥ 24 px |
| Контраст титров и выносок | `app/colorutils.py` | ≥ 4.5:1 |
| Сцена не короче минимума приёма | — | 0 нарушений |
| Три одинаковых приёма подряд | — | 0 |
| Статичный кадр дольше 3 с | попиксельная разница соседних сэмплов | 0 |
| Кадр не пустой | покрытие непрозрачным контентом | ≥ 15% |

Находка: `{code, severity, sceneId, metric, threshold, actual, message}`.
`score` = 100 минус штрафы по severity.

```python
def repair_storyboard(storyboard, base_ir, artifact, tokens, preset, report,
                      propose, max_iterations=3) -> dict:
    """Ask `propose` for a fixed storyboard; accept only when the measured score grows."""
```

`propose(messages) -> str` — та же инъекция, что в `app/fidelity_repair.py`
(см. `app/server.py:1084`), чтобы desktop мог подставить свой CLI-аккаунт.
**Правка принимается только при росте `score`**, иначе откат. Всё в лог.

---

## 12. Промпт режиссёра

Файл: `app/prompts/DIRECTOR.md` (рядом с `BLOCKS.md`, `DESIGN.md`).

В контекст подаётся:

- бриф пользователя;
- пресет: хронометраж, число сцен, обязательные группы, список разрешённых приёмов;
- **инвентарь целей**: компактный список компонентов из Source Artifact —
  `componentKey`, `name`, `role`, наблюдённые состояния, размер. Полный IR не
  подавать, он весит мегабайты (тот же приём, что в `REFINE_ROLES`,
  `store.ts:95`);
- **каталог приёмов**: `id`, `title`, `group`, требование к цели, нужен ли текст,
  одно предложение «когда применять»;
- токены Design System — чтобы модель поняла характер бренда;
- если подключён Interaction IR — записанная последовательность шагов, которой
  надо следовать.

Ответ — **только Storyboard IR**, один JSON без markdown. Парсить существующим
`llm.extract_json` (`app/llm_client.py:346`).

---

## 13. HTTP API

Всё в `app/server.py`, за флагом `aiDirector`. Модели запросов — Pydantic рядом с
существующими (`app/server.py:345-360`). Ошибки — `err(...)`.

| Метод | Ручка | Запрос | Ответ |
|---|---|---|---|
| GET | `/api/shots` | — | `{shots: [{id, group, title, targetRequirement, needsText, minDuration, maxDuration, preview}], formats: {...}}` |
| POST | `/api/director/storyboard` | `{brief, preset, ir, source_artifact?, tokens?, interaction?, effort, prepareOnly?, rawOutput?}` | `{storyboard, errors}` либо `{prompts:[{messages}]}` при `prepareOnly` |
| POST | `/api/director/scene` | `{storyboard, scene_id, brief, ir, source_artifact?, effort, prepareOnly?, rawOutput?}` | `{scene}` — перегенерация одной сцены |
| POST | `/api/storyboard/validate` | `{storyboard, ir, source_artifact?, preset}` | `{valid, errors}` |
| POST | `/api/motion/compile` | `{storyboard, ir, source_artifact?, tokens?, preset, detached?}` | `{motion, layerIrs, errors}` |
| POST | `/api/motion/judge` | `{motion, layer_irs, storyboard}` | `{report}` |
| POST | `/api/motion/repair` | `{storyboard, ir, source_artifact?, tokens?, preset, report, max_iterations, prepareOnly?, rawOutputs?}` | `{storyboard, iterations, accepted, log}` |

`/api/motion/render` (`app/server.py:1814`) дополнить: если
`motion["version"] == "2.1"` — принимать `layer_irs` из тела и звать
`render_video_v21`; иначе прежний путь без изменений.

`/api/config` (`app/server.py:1617`) уже отдаёт `flags` и `models.motionDirector` —
ничего не менять.

---

## 14. Фронтенд

**Дизайн-референс:** `desktop/Video-Director-Node.rev0.html` — самодостаточный
HTML-прототип ноды «Режиссёр» и её студии (открывается в браузере). Дизайн-язык —
Rsale DS из бандла «Редизайн нодового редактора»: тёмные токены (`bg #0A0A0C`,
`node #131317`, хайрлайн `#26262D`), Manrope 500/600/700, акцент ноды —
motion-pink `#E05FB0`, провода kind-цветами из `portKind.ts`. В prototype нода
одна, и весь конвейер (бриф → пресет → провайдер → раскадровка → таймлайн →
судья → рендер) живёт внутри неё; компактная карточка на канвасе раскрывается в
студию. Воспроизводить средствами `frontend/src/index.css` и существующих
компонентов (`NodeShell`, `InPorts`/`OutPorts`, `ProviderPicker`), логику прототипа
не переносить.

### 14.1 Типы — `frontend/src/flow/types.ts`

```ts
export type PortKind = "text" | "ir" | "tokens" | "artifact" | "interaction" | "motion"
                     | "storyboard";

export type NodeType = /* …существующие… */ | "director";

export type VideoPreset = "promo-16x9" | "ad-9x16" | "ad-1x1" | "onboarding-16x9" | "feature-loop";

export type StoryboardScene = {
  id: string;
  shot: string;
  target: { kind: "component" | "sourceKey" | "block"; ref: string } | null;
  weight: number;
  note: string;
  text: string | null;
  params: Record<string, unknown>;
  enabled: boolean;
};

export type DirectorNodeData = {
  brief: string;
  preset: VideoPreset;
  provider: NodeProvider;
  effort: "medium" | "high" | "max";
  storyboard: IRObject | null;
  ir: IRObject | null;
  artifact: SourceArtifact | null;
  interaction: InteractionObject | null;
  selectedScene: number;
  log: string[];
  lastError?: string;
};

export type MotionJudgeFinding = {
  code: string;
  severity: "info" | "warning" | "error";
  sceneId: string;
  metric: string;
  threshold: number;
  actual: number;
  message: string;
};
export type MotionJudgeReport = { score: number; findings: MotionJudgeFinding[] };
```

`MotionNodeData` дополнить:

```ts
storyboard: IRObject | null;
layerIrs: Array<{ layerId: string; ir: IRObject }>;
version: "1.0" | "2.1";
judge: MotionJudgeReport | null;
detachedLayers: string[];
```

Добавить `DirectorFlowNode` и включить его в `AnyNodeData` и `FlowNode`.

### 14.2 Порты — `frontend/src/flow/ports.ts`

```ts
NODE_DEFS.director = { title: "Режиссёр", icon: "▶", w: 380 };

PORTS.director = {
  in: [
    { name: "ir", label: "Design IR", kind: "ir" },
    { name: "artifact", label: "Source Artifact", kind: "artifact" },
    { name: "tokens", label: "style DNA", kind: "tokens" },
    { name: "brief", label: "бриф", kind: "text" },
    { name: "interaction", label: "Interaction IR", kind: "interaction" },
  ],
  out: [{ name: "storyboard", label: "раскадровка", kind: "storyboard" }],
};

PORTS.motion.in.push({ name: "storyboard", label: "раскадровка", kind: "storyboard" });
```

Плюс `defaultData("director")` и
`CTX_ITEMS += { type: "director", note: "бриф + компоненты → ролик" }`.

### 14.3 Остальная регистрация — не забыть ни одного файла

| Файл | Что добавить |
|---|---|
| `frontend/src/flow/dataflow.ts` | `WIRE_COLORS.storyboard = "#f0883e"`; ветка `case "director": return n.data.storyboard \|\| null;` в `outValue` |
| `frontend/src/flow/serialize.ts` | `"director"` в `NODE_TYPES` |
| `frontend/src/FlowCanvas.svelte` | импорт и `director: DirectorNode` в `nodeTypes` (строка 37) |
| `frontend/src/flow/store.ts` | `runNode`: `else if (n.type === "director") void get().runDirector(id);`; ветка `propagate` для `director`; ветка `motion` в `propagate` учитывает вход `storyboard` |

### 14.4 Нода `DirectorNode.svelte`

`frontend/src/nodes/DirectorNode.svelte`, по образцу `ReskinNode`/`MotionNode`:
`NodeShell`, `InPorts`, `OutPorts`, `NodeStatus`, `ProviderPicker`.

Содержимое: textarea брифа, селект пресета, `ProviderPicker`, кнопка «Собрать
ролик», под ней — горизонтальная лента сцен (миниатюра цели + иконка приёма +
длительность). Клик по сцене — `setNodeData(id, {selectedScene: index})`.

### 14.5 `store.ts:runDirector`

По образцу `runReskin` (`store.ts:1360-1413`): тянуть входы через `pullInput`,
ветка web/desktop по `prepareOnly` (раздел 3.1), результат в `storyboard`,
`setStatus`, `propagate`. Ошибки — `friendlyProviderError` + `toast`.

### 14.6 `store.ts:runMotion` — расширить

```ts
const storyboard = (pullInput(st.nodes, st.edges, n, "storyboard") || data.storyboard) as IRObject | null;
if (storyboard) {
  const res = await api<MotionCompileResp>("/api/motion/compile", {
    storyboard, ir: designIr, source_artifact: artifact, tokens,
    preset: presetOf(storyboard), detached: detachedOf(data),
  });
  // motion 2.1 + layerIrs
} else if (interaction) {
  /* существующий путь /api/motion/build — не менять */
}
```

---

## 15. Таймлайн и ручное редактирование

`frontend/src/nodes/MotionWorkspace.svelte`.

### 15.1 Правило источника правды

**Storyboard — источник правды. Motion IR — производный.**
Ручная правка keyframes ставит слою `detached: true` и добавляет его id в
`MotionNodeData.detachedLayers`. Перекомпиляция такие слои не перезаписывает;
в UI у слоя бейдж «правлено вручную» и кнопка «вернуть к приёму».
Без этого правила следующая перекомпиляция молча затрёт ручную работу.

### 15.2 Что чем правится

| Правка | Уровень | Действие |
|---|---|---|
| Границы сцены (драг) | Storyboard | меняется `weight`, перекомпиляция |
| Смена приёма (селект с превью) | Storyboard | перекомпиляция |
| Смена цели (клик по компоненту на превью) | Storyboard | перекомпиляция |
| Порядок сцен (драг блока) | Storyboard | пересчёт ритма, перекомпиляция |
| Вкл/выкл, удалить, дублировать сцену | Storyboard | перекомпиляция |
| Добавить сцену | Storyboard | выбор приёма и цели из списка |
| Рамка камеры (тянуть по превью) | Storyboard | `params.region`, перекомпиляция |
| Текст титра / CTA | Storyboard | `scene.text`, перекомпиляция |
| Keyframes слоя | **Motion IR** | `detached: true` |

### 15.3 Три синхронные дорожки

1. **Сцены** — блоки, цвет по `group` приёма, внутри иконка приёма и миниатюра
   цели. Границы тянутся. 90% работы пользователя тут.
2. **Акценты** — маркеры `kind: "accent"`. Ритм ролика виден одним взглядом.
3. **Слои** — скомпилированные слои Motion IR, свёрнуты по умолчанию;
   `detached` помечены.

Плейхед общий, `rAF`-цикл уже есть (`MotionWorkspace.svelte:60`).
Undo/redo — через `frontend/src/engine/irhistory.ts`.

### 15.4 Safe-area и находки судьи

Поверх `IrPreview` — полупрозрачные прямоугольники `composition.safeAreas` с
подписью роли; красная штриховка, если судья зафиксировал вторжение.

Находки судьи — булавки на дорожке сцен, цвет по `severity`. Клик раскрывает
`metric`/`threshold`/`actual`. Кнопка «Починить» — общая сверху; после прогона
показать дельту `score` до/после.

### 15.5 Инспектор сцены (панель справа)

Приём (селект с превью-webm), цель (миниатюра + «выбрать на превью»),
длительность, `weight`, переход, параметры приёма из `params_schema`, `note`,
кнопка «Перегенерировать эту сцену» (`/api/director/scene`).

---

## 16. Этапы и Definition of Done

Каждый этап — отдельный коммит, оба прогона тестов зелёные.

| # | Содержание | Флаг | DoD |
|---|---|---|---|
| **1** | `app/motion/shots/` — 6 приёмов раздела 6.2, реестр, `params_schema`, превью-webm, `registry_test.py` | off | Каждый приём строит валидные треки на синтетической цели, ужимается и растягивается по краям диапазона, детерминирован |
| **2** | Storyboard IR: схема, `app/ir/storyboard.py`, все 10 проверок раздела 4.3 | off | Каждый инвариант — отдельный красный кейс, ставший зелёным |
| **3** | `rhythm.py`, `video_formats.py`, `compile.py`, Motion IR 2.1 + миграция | off | Рукописный storyboard → валидный Motion IR 2.1; `content_hash` стабилен на 10 повторах |
| **4** | `sample.py`, `render_video_v21`, `_MotionStage`, `render_frames_v21` | off | Рукописный storyboard → mp4, который открывается и плавно играет |
| **5** | `DIRECTOR.md`, `/api/shots`, `/api/director/storyboard`, `/api/storyboard/validate`, `/api/motion/compile`, нода `Режиссёр`, `runDirector` | **on** | На реальном Source Artifact бриф → раскадровка без несуществующих целей, все три провайдера работают |
| **6** | Таймлайн: дорожка сцен, смена приёма, драг границ, инспектор сцены, detached | on | Ролик правится руками без перегенерации остального |
| **7** | Остальные 8 приёмов раздела 6.3 | on | Ролик неотличим от скринкаста |
| **8** | `judge.py`, `repair.py`, `/api/motion/judge`, `/api/motion/repair`, булавки в UI | on | Балл растёт на всех фикстурах, откат при падении работает |

**Порядок обязателен.** Этапы 1–4 делаются **без единого вызова LLM**: сначала
научиться делать красиво по рукописной раскадровке, потом подключать модель.
Обратный порядок гарантированно даёт «ИИ сделал кашу, и непонятно, кто виноват».

---

## 17. Тесты

| Файл | Что покрывает |
|---|---|
| `app/motion/shots/registry_test.py` | Каждый приём: валидность треков, края диапазона длительности, детерминизм, отсутствие хардкода цветов |
| `app/ir/storyboard_test.py` | Каждая из 10 проверок раздела 4.3 отдельным кейсом |
| `app/motion/rhythm_test.py` | Сумма попадает в `durationRange`, дубли разведены, округление по кадрам, невязка |
| `app/motion/compile_test.py` | Детерминизм по `content_hash`, detached-слои переживают перекомпиляцию, ошибки — `ValueError` |
| `app/motion/sample_test.py` | Каждая интерполяция: `hold`, `linear`, `bezier`, `spring`; зажим за краями |
| `app/ir/motion_v2_test.py` | Дополнить: миграция 2.0 → 2.1, `safeAreas`, семантика 2.1 |
| `app/motion_render_test.py` | Дополнить: `validate_render_input_v21`, разметка стадии, лимит кадров |
| `app/motion/judge_test.py` | Синтетические кадры с известными нарушениями по каждой метрике |
| `app/motion/repair_test.py` | Приём при росте балла, откат при падении, лимит итераций |
| `app/motion_director_live_test.py` | Live-тест по образцу `app/fidelity_repair_live_test.py`, требует провайдера |

**Фикстуры** — `app/fixtures/`: один Design IR лендинга, один Source Artifact
к нему, три рукописные раскадровки (промо, реклама 9:16, онбординг).

---

## 18. Сквозная приёмка

1. `Source Import` реального сайта → Source Artifact с ≥ 8 компонентами.
2. `Режиссёр`: бриф «30-секундный промо-ролик, показать создание счёта в один
   клик», пресет `promo-16x9`, провайдер Claude Opus.
3. Раскадровка: 6–8 сцен, каждая цель существует, нет трёх одинаковых приёмов
   подряд, первая — из `opening`, последняя — из `closing`.
4. `Motion`: компиляция → Motion IR 2.1, сумма длительностей 20–40 с.
5. Правка руками: сменить приём в сцене 3, растянуть сцену 5, подвинуть рамку
   камеры в сцене 2 — применяется без перегенерации остального.
6. Судья → 0 находок либо починка их закрывает, `score` вырос.
7. Рендер → mp4 1920×1080, играет, без рывков на переходах.
8. Перезагрузка проекта: граф с нодой `Режиссёр` и раскадровкой восстанавливается.

---

## 19. Что осознанно не делаем

- **Звук и озвучка.** `motion_render.py` собирает поток с `-an`
  (`app/motion_render.py:72`). Ролик выходит немой — музыка и голос кладутся
  снаружи. `renderSettings.audio.enabled` всегда `false`. Синхронизация с
  дикторским текстом по SRT — отдельная задача; Motion IR 2.0 уже содержит
  `captions[]` и `assets[type: "audio"]`, контейнер под неё готов.
- **Съёмка говорящей головы.** Только `safeAreas`, чтобы контент не залезал
  в зарезервированное место.
- **Произвольные видео и картинки со стороны.** Только наши компоненты.
- **3D, частицы, морфинг.** Каталог расширяемый, но не сейчас.
- **Правка Motion IR моделью.** Модель пишет только Storyboard. Всегда.

---

## 20. Известные ограничения — учесть при реализации

1. **`MAX_RENDER_FRAMES = 10_800`** (`app/motion_render.py:15`) = 6 минут при
   30 fps. Пресет `onboarding-16x9` до 180 с укладывается. Все пресеты
   фиксируют `fps: 30`; 60 fps не вводить, пока лимит не поднят.
2. **Чётность размеров.** `validate_render_input` требует чётные `width`/`height`
   (h264). Все разрешения в пресетах чётные — проверить при добавлении новых.
3. **`llm_client` сейчас Sol-only** (`app/llm_client.py:22` — `PROVIDERS` только
   `openai`). Codex и Claude доступны **исключительно** через desktop-путь
   `prepareOnly` + `desktop.providers.chatRequest`. В web-режиме нода работает
   на Sol. Это существующее поведение, менять его не нужно.
4. **`stripHeavy`** (`frontend/src/flow/serialize.ts:47`) выкидывает при сейве
   строки > 200 КБ и `data:`-строки. Раскадровка маленькая и переживёт сейв;
   `layerIrs` и `motion` — нет. Их не персистить: после загрузки проекта нода
   `Motion` перекомпилируется из `storyboard` по кнопке. Показать это статусом
   «Нажмите «Собрать таймлайн», чтобы восстановить ролик».
5. **`engine.js` — собранный артефакт** (`app/static/flow/engine.js`, 184 КБ),
   пересобирается `npm --prefix frontend run build:engine`. Если правишь
   рендерер — правь исходник во `frontend/src/engine/`, потом пересобирай.
