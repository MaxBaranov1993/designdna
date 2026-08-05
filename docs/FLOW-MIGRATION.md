# FLOW-MIGRATION — спека миграции нодового редактора на React Flow + shadcn/ui

Дата: 2026-08-05 · Статус: черновик для Фазы A/B спринта 5 (PLAN.md)

Источники (только чтение): `app/static/nodes.js` (1317 строк), `app/static/nodes.html`,
`app/server.py`, `app/static/renderer.js`. Все ссылки на строки даны по состоянию на
коммит `b30bada` (ветка `flow-spec`).

Существующий редактор — vanilla-JS IIFE (`nodes.js`), dataflow pull-based, состояние
`nodes[] + edges[] + view` в памяти с автосейвом в localStorage (`nodes.js:16-22`).
Legacy-ядро (`renderer.js`, `geoedit.js`, `inspector.js`, `irhistory.js`, `editor.js`)
НЕ переписывается и встраивается в новый UI как движок превью/Figma-правки (решение
владельца №6 от 2026-08-05, AGENTS.md).

---

## 1. Инвентарь типов нод

Объявления: `NODE_DEFS` — заголовок/иконка/ширина (`nodes.js:24-32`), `PORTS` —
статические порты (`nodes.js:35-48`), `defaultData()` — дефолтные поля `data`
(`nodes.js:266-275`), `bodyHtml()` — разметка тела (`nodes.js:158-249`),
`wireNodeEvents()` — обработчики контролов (`nodes.js:325-469`).

В коде существует **7 типов**: 6 целевых + `reproduce` (`nodes.js:31`,
в контекстном меню `nodes.js:1096-1104`). Reproduce обязан мигрировать вместе со
всеми — он в графах пользователей и в тестах.

Состояние ноды в памяти: `{id, type, x, y, data, el, geo?}` (`nodes.js:16`);
`el`/`geo`/`history`/`refreshEdit` — runtime-поля, в сохранение не попадают
(сериализуется только `{id, type, x, y, data}`, `nodes.js:1178`).

### 1.1 Промпт (`prompt`)

- Определение: `nodes.js:25` (w=260), порты `nodes.js:36`, тело `nodes.js:165-167`.
- Порты: in — нет; out — `out` (kind `text`, label «текст»).
- Поля `data` (`nodes.js:267`):
  - `text: string` — текст задачи; пишется на каждый input textarea (`nodes.js:364-367`),
    вызывает `propagate()` + `save()`.
- Выходное значение: `data.text` (`nodes.js:924`).

### 1.2 Референс (`reference`)

- Определение: `nodes.js:26` (w=270), порты `nodes.js:37-38`, тело `nodes.js:169-177`.
- Порты: in — `ir` (kind `ir`); out — `out` (kind `text`, label «стиль»).
- Поля `data` (`nodes.js:268`):
  - `brief: string` — описание стиля, уходит в текстовый провод (`nodes.js:379`);
  - `image: string|null` — base64 data-URL загруженного изображения
    (file input `nodes.js:371-377`);
  - `fileName: string` — имя файла (`nodes.js:375`);
  - `decomposed: boolean` — флаг «Разбить на компоненты» (checkbox `nodes.js:380-388`).
- Runtime-поле: `data.ir` — IR, полученный по проводу через `propagate()`
  (reference-ветка `nodes.js:957-963`); используется как источник для декомпозиции
  (`nodes.js:584`).
- Выходное значение: `data.brief` или `"Референс: <fileName>"` (`nodes.js:925`).

### 1.3 Генератор (`generator`)

- Определение: `nodes.js:27` (w=300), порты `nodes.js:39-41`, тело `nodes.js:179-191`.
- Порты: in — `prompt` (text), `style` (text); out — `ir` (kind `ir`, label «варианты»).
- Поля `data` (`nodes.js:269`):
  - `provider: string` — `"qwen"|"kimi"|"openrouter"` (select, `nodes.js:394`);
  - `count: number` — число вариантов 1..3 (`nodes.js:395`);
  - `ownPrompt: string` — свой промпт, fallback при отсутствии провода (`nodes.js:396`,
    чтение в `runGenerator` `nodes.js:499`);
  - `variants: IR[]` — результат генерации, пишется целиком из ответа API (`nodes.js:506`);
  - `active: number` — индекс выбранного варианта (клик по миниатюре `nodes.js:487-492`,
    сброс в 0 после генерации `nodes.js:507`).
- Run-based: выполняется кнопкой ▶ (`nodes.js:397` → `runGenerator` `nodes.js:498-518`);
  сам не транслирует вход через себя — только по кнопке (комментарий `nodes.js:941-942`).
- Выходное значение: `variants[active]` (`nodes.js:926`).

### 1.4 Редактор (`edit`, «Редактор (DNA)»)

- Определение: `nodes.js:28` (w=780 — самая широкая нода), порты `nodes.js:42-43`,
  тело `nodes.js:193-204`.
- Порты: in — `ir` (kind `ir`); out — `ir` (kind `ir`).
- Поля `data` (`nodes.js:270`):
  - `ir: object|null` — единственный источник правды этой ноды. Заполняется:
    проводом через `propagate()` с клоном (edit-ветка `nodes.js:950-956`), кнопками
    «→ Editor» (`sendToNode` `nodes.js:522-545`), из полноэкранного редактора
    (колбэк `Editor.open`, `nodes.js:690-696`), через `GraphDev.setIR`
    (`nodes.js:1274-1282`), undo/redo-снапшотами (`applyEditSnapshot` `nodes.js:646-651`).
- Runtime: `history` — `IRHistory.createHistory({limit: 50})` (`nodes.js:675`),
  `geo` — инстанс GeoEdit (`GeoEdit.attach`, `nodes.js:735-759`), `editZoom`
  (`nodes.js:718`), `refreshEdit()` — единственная точка lifecycle (`nodes.js:731-764`,
  комментарий `nodes.js:663-666`). Ctrl+Z/Ctrl+Y в выделенной edit-ноде — undo/redo IR
  (`nodes.js:1134-1146`).
- Выходное значение: `data.ir` (`nodes.js:927`).

### 1.5 Микс (`mix`)

- Определение: `nodes.js:29` (w=290), порты `nodes.js:44`, тело `nodes.js:206-210`.
- Порты: in — **динамические**, по именам из `data.inputs`, все kind `ir`
  (`portsOf`, `nodes.js:77-83`); out — `ir` (kind `ir`).
- Поля `data` (`nodes.js:271`):
  - `inputs: string[]` — имена входов, стартово `["a","b"]`, максимум 4
    (добавление `nodes.js:403-412`, имена из `["a","b","c","d"]`, `nodes.js:405`);
  - `weights: Record<string, number>` — веса 0..100 на вход, дефолт `a:70, b:30`,
    новый вход — 50 (`nodes.js:407`); слайдер `nodes.js:794-798`;
  - `ir: object|null` — результат микса (`nodes.js:829`).
- Удаление входа снимает и его провода (`nodes.js:800-808`, фильтр рёбер `nodes.js:803`).
- Run-based: «Смешать по весам» (`nodes.js:413` → `runMix` `nodes.js:815-836`),
  требуется ≥2 подключённых IR-входа (`nodes.js:825`).
- Выходное значение: `data.ir` (`nodes.js:928`).

### 1.6 Клон (`clone`)

- Определение: `nodes.js:30` (w=310, icon пустой), порты `nodes.js:45`,
  тело `nodes.js:212-219`.
- Порты: in — нет; out — `ir` (kind `ir`).
- Поля `data` (`nodes.js:272`):
  - `url: string` — URL сайта (`nodes.js:417`);
  - `component: string` — какой компонент клонировать (`nodes.js:418`);
  - `ir: object|null` — результат (`nodes.js:847`).
- Необъявленное поле: `provider` — отсутствует в `defaultData`, читается как
  `n.data.provider || "qwen"` (`nodes.js:419-420`), появляется после первой смены
  select. При миграции объявить явно.
- Run-based: «⧉ Клонировать» (`nodes.js:421` → `runClone` `nodes.js:838-857`).
- Выходное значение: `data.ir` (`nodes.js:929`).

### 1.7 Reproduce (`reproduce`) — седьмой тип, присутствует в коде

- Определение: `nodes.js:31` (w=340), порты `nodes.js:46-48`, тело `nodes.js:221-246`.
- Порты: in — нет; out — `ir` (ir), `html` (text), `diff` (text).
- Поля `data` (`nodes.js:273`):
  - `image: string|null` — base64 data-URL скриншота (file input `nodes.js:426-440`);
  - `fileName: string`;
  - `url: string` — альтернатива изображению (`nodes.js:443-444`);
  - `provider: string` — `"qwen"|"gemini"|"groq"|"xai"|"glm"|"openrouter"`
    (select `nodes.js:226-233`);
  - `result: object|null` — полный ответ `/api/reproduce` целиком (`nodes.js:873`),
    включает `ir`, `html`, `diff`, `colors`, `repro_png` (data-URL), `icons_count` и др.
- Run-based: `runReproduce` (`nodes.js:861-886`); кнопки просмотра HTML/Diff/→ Editor
  (`nodes.js:446-459`), восстановление изображения из сейва (`nodes.js:461-466`).
- Выходное значение: `result.ir` (`nodes.js:930`).

---

## 2. Формат сохранения графа

### 2.1 localStorage

Ключ: **`designai-graph-v1`** (`nodes.js:22`). Запись — `save()` (`nodes.js:1174-1196`)
с дебаунсом **300 мс** (`nodes.js:1175-1176`). Точный payload (`nodes.js:1177-1180`):

```jsonc
{
  "nodes": [
    { "id": 1, "type": "generator", "x": 420, "y": 120, "data": { /* см. раздел 1 */ } }
  ],
  "edges": [
    { "from": { "node": 1, "port": "ir" }, "to": { "node": 2, "port": "ir" } }
  ],
  "view": { "x": 80, "y": 40, "zoom": 1 },
  "nextId": 3
}
```

Имена полей и типы:

| Поле | Тип | Комментарий |
|---|---|---|
| `nodes[].id` | number | инкрементный, выдаёт `nextId` (`nodes.js:257`) |
| `nodes[].type` | string | один из 7 ключей `NODE_DEFS` |
| `nodes[].x`, `nodes[].y` | number | мировые px, левый-верхний угол ноды, `Math.round` (`nodes.js:336-337`) |
| `nodes[].data` | object | только поля data; runtime-поля не сериализуются |
| `edges[].from.node` / `.to.node` | number | id нод |
| `edges[].from.port` / `.to.port` | string | имя порта (`"ir"`, `"out"`, `"prompt"`, `"style"`, у mix — `"a".."d"`) |
| `view.x`, `view.y`, `view.zoom` | number | translate/zoom холста; дефолт `{x:80, y:40, zoom:1}` (`nodes.js:18`) |
| `nextId` | number | только в localStorage; при загрузке пересчитывается как `max(nextId, max(id)+1)` (`nodes.js:1214`) |

Чтение: `loadFromStorage()` (`nodes.js:1221-1227`) → `load()` (`nodes.js:1202-1219`);
битый JSON молча игнорируется (пустой граф).

### 2.2 Экспорт / импорт JSON

- Экспорт (`nodes.js:1238-1249`): payload **`{nodes, edges, view}`** — тот же формат,
  но **без `nextId`** (`nodes.js:1239-1242`); скачивается файл `designai-graph.json`
  (`nodes.js:1246`).
- Импорт (`nodes.js:1250-1266`): FileReader → `JSON.parse` → `load()` → `save()`;
  ошибки парсинга — toast.

### 2.3 Совместимость при миграции (обязательное требование Фазы B)

Новый UI обязан:

1. Читать и писать тот же ключ `designai-graph-v1` с теми же именами полей.
2. Экспортировать/импортировать формат `{nodes, edges, view}` побайтово совместимо
   (те же имена, number-id, вложенные `from/to`).
3. Конвертация в типы React Flow — только в рантайме:
   - RF-нода: `{id: String(n.id), type: n.type, position: {x: n.x, y: n.y}, data: n.data}`
     (RF требует строковый id; семантика позиции совпадает — px, левый-верх);
   - RF-рёбра: `{id: "e<from.node>:<from.port>-<to.node>:<to.port>", source: String(from.node), sourceHandle: from.port, target: String(to.node), targetHandle: to.port}`;
   - `view` ↔ viewport RF совпадают по смыслу (`{x, y, zoom}`, translate в px) —
     сохранять как есть.

---

## 3. Правила проводов

### 3.1 Типы портов

Два kind: **`text`** и **`ir`** — объявлены в `PORTS` (`nodes.js:35-48`); у mix
входные порты строятся динамически с kind `ir` (`nodes.js:77-83`). Kind провода
наследуется от выходного порта источника (`edgeKind`, `nodes.js:988-993`) и влияет
только на цвет (`w-text` серый / `w-ir` акцентный, CSS `#wires path` в nodes.html).

### 3.2 Валидация в `connect()` — `nodes.js:1049-1070`

Правила по строкам:

1. Источник и приёмник существуют и это разные ноды — `nodes.js:1050-1051`
   (самосоединение молча отклоняется).
2. Оба порта существуют в декларациях (`portsOf`) — `nodes.js:1052-1054`.
3. **Совпадение kind**: `outP.kind !== inP.kind` → toast «Несовместимые порты» и
   отказ — `nodes.js:1055-1058`.
4. **Проверка циклов**: `reachable(to.node, from.node)` — DFS по существующим рёбрам
   (`nodes.js:1032-1047`); если путь уже есть → toast «Нельзя: соединение создаёт
   цикл» и отказ — `nodes.js:1059-1062`.
5. **Один провод на вход**: существующее ребро в тот же `(to.node, to.port)`
   **заменяется**, а не отклоняется: `edges = edges.filter(...)` — `nodes.js:1063`
   (комментарий «один провод на вход»).
6. После добавления: `refreshPortStates()` + `drawWires()` + `propagate(from.node)` +
   `save()` — `nodes.js:1064-1068`.

Соединение стартует только с выходного порта (listener на `.port-row.out .port`,
`nodes.js:354-362`), drop — на `.port-row.in` через `document.elementFromPoint`
(`startWireDrag`, `nodes.js:1072-1092`; id ноды при drop приводится к Number,
`nodes.js:1087`).

### 3.3 Перенос в React Flow

Правила 1–4 переносятся в `isValidConnection` (проп `<ReactFlow>` или отдельных
`<Handle>`); правило 5 (замена ребра) — в `onConnect`, т.к. `isValidConnection`
может только разрешить/запретить. Эскиз (иллюстративный, не код для коммита):

```ts
// Таблица портов — зеркало PORTS из nodes.js:35-48 (+ mix: kind "ir" на все data.inputs)
const PORT_KIND: Record<string, Record<string, "text" | "ir">> = { /* ... */ };

function portKind(nodeType: string, data: NodeData, handleId: string, dir: "in" | "out") {
  if (nodeType === "mix" && dir === "in") return "ir"; // динамические входы
  return PORT_KIND[nodeType]?.[handleId];
}

const isValidConnection = (c: Connection) => {
  if (!c.source || !c.target || c.source === c.target) return false;        // правило 1
  const src = getNode(c.source), dst = getNode(c.target);
  if (!src || !dst) return false;                                           // правило 2
  if (portKind(src.type, src.data, c.sourceHandle!, "out") !==
      portKind(dst.type, dst.data, c.targetHandle!, "in")) return false;    // правило 3
  return !createsCycle(getEdges(), c);                                      // правило 4: DFS
};

const onConnect = (c: Connection) => {
  // правило 5: одно ребро на вход — заменить, как nodes.js:1063
  setEdges(eds => eds
    .filter(e => !(e.target === c.target && e.targetHandle === c.targetHandle))
    .concat(makeEdge(c)));
  propagate(c.source); // зеркало nodes.js:1067
};
```

Проверку циклов реализовать DFS/стеком по `getEdges()` (аналог `reachable`,
`nodes.js:1032-1047`); готовой встроенной проверки в React Flow нет, но помогают
`getIncomers`/`getOutcomers` из `@xyflow/system`. Тосты об отказе — sonner/shadcn
(аналог `toast()`, `nodes.js:53-59`).

---

## 4. Fetch-вызовы из nodes.js в `/api/*`

Все POST-вызовы идут через общий хелпер `api()` (`nodes.js:61-71`): JSON-тело,
ответ парсится как JSON, при `!resp.ok` бросается `Error(data.detail || "HTTP …")`.

| № | Эндпоинт | Вызов в nodes.js | Payload (точные поля) | Куда ложится результат |
|---|---|---|---|---|
| 1 | `POST /api/generate` | `runGenerator` — `nodes.js:505` | `{brief, count, provider, styleHint}` (`styleHint` = значение входа `style` или undefined, `nodes.js:501`) | `n.data.variants = res.variants; n.data.active = 0` — `nodes.js:506-507`; счётчик ошибок из `res.errors` в статус (`nodes.js:509-510`) |
| 2 | `POST /api/generate` (fallback декомпозиции) | `runDecompose` — `nodes.js:615` | `{brief, count: 1, provider: "qwen"}` | `ir = res.variants[0]` — `nodes.js:616`, далее `decomposeIR()` и новая edit-нода (`nodes.js:630-635`) |
| 3 | `POST /api/vision-decompose` | `runDecompose` — `nodes.js:598-602` | `{image (base64 data-URL), brief, provider: "qwen"}` | `ir = res.ir` — `nodes.js:603` |
| 4 | `POST /api/mix` | `runMix` — `nodes.js:828` | `{irs: IR[], weights: number[]}` (веса нормированы 0..1, `nodes.js:821`) | `n.data.ir = res.ir` — `nodes.js:829` |
| 5 | `POST /api/clone` | `runClone` — `nodes.js:846` | `{url, component, provider}` | `n.data.ir = res.ir` — `nodes.js:847`; `res.cached` — в статус (`nodes.js:848`) |
| 6 | `POST /api/reproduce` | `runReproduce` — `nodes.js:868-872` | `{image (или ""), url, provider}` | `n.data.result = res` целиком — `nodes.js:873` |
| 7 | `GET /api/cache/stats` | `refreshCacheStat` — `nodes.js:1308` | — (GET без тела) | текст в топбар `#cache-stat` (nodes.html); вызывается на старте (`nodes.js:1315`) и после clone/reproduce (`nodes.js:851`, `nodes.js:880`) |

После каждого успешного run-вызова: `propagate(n.id)` + `save()`
(generate `nodes.js:511-512`, mix `nodes.js:831-832`, clone `nodes.js:849-850`,
reproduce `nodes.js:878-879`).

Соответствие на бэкенде (`app/server.py`): модели запросов `GenerateReq` (:91),
`MixReq` (:104), `CloneReq` (:119), `VisionDecomposeReq` (:125), `ReproduceReq` (:136);
хендлеры `/api/generate` (:145, ответ `{variants, errors}`), `/api/mix` (:230, `{ir}`),
`/api/clone` (:315, `{ir, cached}`, SSRF-гард + кэш `clone_url`),
`/api/vision-decompose` (:414, `{ir, provider_used}`, перебор vision-провайдеров),
`/api/reproduce` (:498, payload `{structure, colors, measurements, icons_count,
contents_count, html, diff, ir, repro_png, provider_used, cached}`, кэш по URL и по
хэшу изображения), `/api/cache/stats` (:569). Маршруты страниц: `GET /` и `GET /nodes`
→ `nodes.html` (:575-578), статика на `/static` (:581). Новый маршрут `/flow`
добавляется рядом, бэкенд не меняется.

---

## 5. Маппинг на React Flow

Пакет: `@xyflow/react` (React Flow 12), UI-обвязка — shadcn/ui (тёмная тема;
CSS-переменные перенести из `:root` nodes.html: `--bg #0e0e13`, `--panel #16161d`,
`--accent #5B5BD6` и т.д.).

### 5.1 Кастомные типы нод

`nodeTypes` — по одному React-компоненту на тип, мемоизированный объект вне
компонента: `{prompt, reference, generator, edit, mix, clone, reproduce}`
(ключи = legacy `type`, конвертация данных не нужна). Ширины из `NODE_DEFS`
(`nodes.js:24-32`) — в `style={{width}}` или CSS-классы. Внутренности компонентов —
перенос `bodyHtml()` (`nodes.js:158-249`) на shadcn-примитивы: Textarea, Select,
Button, Slider (веса mix), Checkbox (decompose), Label-drop для file input.

### 5.2 Handles

- Статические порты — по таблице `PORTS` (`nodes.js:35-48`): `<Handle type="source|target" position={Position.Left|Right} id="<port>" />`;
  входные слева, выходные справа (легаси-верстка: in-строки слева, out справа,
  классы `.port-row` в nodes.html).
- У mix входные handles **рендерятся динамически** из `data.inputs`
  (зеркало `renderMixInputs`, `nodes.js:781-813`); при «+ вход»/«✕» обновляется
  `data.inputs`, handles перерисовываются автоматически, а висящие рёбра на
  удалённый порт снимаются (аналог `nodes.js:803`).
- Kind → класс/стиль handle (ir — акцентный, text — серый; зеркало
  `.port-row[data-kind="ir"]` в nodes.html) + используется в `isValidConnection`.
- Состояние «connected» (`refreshPortStates`, `nodes.js:1020-1030`) в RF не нужно —
  соединение визуально видно; при желании читать из `useEdges`.

### 5.3 Управление состоянием графа — рекомендация: **zustand**

Рекомендуется собственный zustand-стор поверх `@xyflow/react`
(`useStoreApi`/`applyNodeChanges`), а не локальный `useNodesState`:

1. **Глубокие мутабельные данные**: run-операции перезаписывают вложенные поля
   (`data.variants`, `data.result`, `data.ir` — раздел 4). В `useNodesState` каждое
   такое обновление — `setNodes(ns => ns.map(...))` со spread-копированием; с
   zustand-селекторами обновляется одна нода, остальные не перерисовываются.
2. **Кросс-нодовый dataflow**: `propagate()` (`nodes.js:943-968`) и `connect()` с
   заменой ребра — это действия над всем графом; в zustand они живут как action-ы
   стора (`connect`, `propagate`, `runGenerator`, …) с прямым доступом к состоянию.
3. **Автосейв**: одна `store.subscribe` с дебаунсом 300 мс (зеркало `nodes.js:1175-1176`).
4. **Частые изменения вне графа**: слайдеры весов mix, скраб в инспекторе edit-ноды,
   drag — не должны гонять весь массив нод через setState компонента-владельца.
5. Официальные паттерны React Flow для сложных приложений — внешний стор;
   `useNodesState` позиционируется для прототипов.

Допустимая оговорка: для Фазы A (скаффолд + статический граф) `useNodesState`
приемлем как быстрый старт, но Фаза B (run-операции, propagate, автосейв) всё равно
потребует стора — дешевле начать с zustand сразу.

### 5.4 Dataflow в сторе

- `outValue(n)` (`nodes.js:923-932`) и `pullInput(n, port)` (`nodes.js:934-939`) —
  чистые функции-селекторы стора; pull-модель сохраняется.
- `propagate` (`nodes.js:943-968`): edit/reference-потребители получают **клон** IR
  (`clone()`, `nodes.js:74`), mix помечается stale-статусом (`nodes.js:964-965`);
  через generator/mix поток не идёт (run-based, комментарий `nodes.js:941-942`).
  Перенести 1:1, включая защиту от повторов через `visited` (`nodes.js:944-946`).
- Undo/redo IR выделенной edit-ноды (Ctrl+Z/Y, `nodes.js:1134-1146`) — оставить за
  `IRHistory` внутри ноды; на уровне графа глобальный undo не нужен.

### 5.5 Прочее

- Пан/зум — встроенные RF (заменяют `applyView`/wheel/pan, `nodes.js:88-133`);
  `fitAll` (`nodes.js:135-153`) → `useReactFlow().fitView()` (кнопка shadcn в топбаре).
- Контекстное меню создания ноды (`nodes.js:1096-1122`) → `onPaneContextMenu` +
  shadcn ContextMenu/DropdownMenu, состав `CTX_ITEMS` сохранить.
- Выделение/удаление: `deleteKeyCode` RF заменяет обработчик Delete
  (`nodes.js:1147-1151`); снятие рёбер при удалении ноды RF делает сам (аналог
  `nodes.js:305`).
- Топбар (nodes.html `header.topbar`) — shadcn-панель: Fit, Экспорт JSON, Импорт,
  Очистить (с confirm-диалогом, аналог `nodes.js:1232-1237`), `#cache-stat`, zoom-label
  через `useViewport()`.
- **Совместимость с тестами**: `window.GraphDev` (`nodes.js:1270-1304`: `add`,
  `connect`, `setIR`, `setText`, `run`, `state`, `node`, `fit`) используется
  ~10 Playwright-тестами (`app/ui_*_test.py`). Новый UI обязан держать шим с той же
  сигнатурой (id в `state()`/`node()` принимаются тестами как Number — учесть в шиме).

---

## 6. Превью IR внутри нод через renderer.js

### 6.1 Как устроен renderer.js (факты)

- Глобал: IIFE выставляет `window.IRRenderer = {renderIR, fitPreview, DESIGN_WIDTH}`
  (`renderer.js:620`), `DESIGN_WIDTH = 960` (`renderer.js:5`).
- `renderIR(container, ir)` (`renderer.js:540-577`):
  - **мутирует входной объект**: `ir.tokens = mergeDefaults(ir.tokens)` (`renderer.js:542`);
  - **инжектит Google Fonts**: singleton-`<link id="ir-fonts">` в `document.head`
    (`renderer.js:545-552`), href строится из `tokens.font` (`fontsUrl`,
    `renderer.js:66-76`) — один link на весь документ, последний рендер «побеждает»;
  - **инжектит `<style>` внутрь container** со скоупом `.ir-<uid>`
    (`renderer.js:566-573`); uid монотонно растёт на каждый рендер (`renderer.js:537`),
    поэтому соседние превью не конфликтуют по CSS;
  - ставит `data-design-width` и в rAF вызывает `fitPreview` — масштабирование
    CSS-transform под ширину контейнера (`renderer.js:576`, функция
    `renderer.js:595-603`).
- Точки использования в nodes.js: миниатюры генератора (`nodes.js:494`), превью
  edit-ноды (`nodes.js:776`), измерительный контейнер `decomposeIR` (`nodes.js:559`).
- К редактору в edit-ноде привязаны глобальные legacy-модули: `GeoEdit.attach`
  (`nodes.js:735-759`, экспорт `geoedit.js:1990`), `Inspector.render`
  (`nodes.js:723-729`, `inspector.js:410`), `Editor.open` (`nodes.js:688-697`,
  `editor.js:814`), `IRHistory` (`irhistory.js:66`). Все они работают с живым DOM
  превью напрямую.

### 6.2 Варианты

**A. Прямое монтирование (как сейчас).** React-компонент превью: стабильный
`<div ref>`, в `useEffect` вызывается `IRRenderer.renderIR(ref.current, ir)`.
React не трогает children этого div (компонент мемоизирован, div обновляется только
эффектом).

- Плюсы: ноль изменений renderer.js; GeoEdit/Inspector/Editor продолжают работать
  без переписывания (ключевое для edit-ноды); одна кодовая база превью; нет
  overhead на процесс/документ на превью.
- Минусы и контрмеры:
  - мутация `ir.tokens` — в эффект передавать глубокую копию (`structuredClone`),
    либо смириться, что сохранённый IR нормализован дефолтами (легаси фактически
    так и живёт);
  - общий `<link id="ir-fonts">`: у превью с разными шрифтами активен последний
    загруженный — принять как известное ограничение (в легаси так же);
  - `fitPreview` использует rAF — при изменении ширины ноды (RF-resize) повторный
    вызов через ResizeObserver.

**B. iframe srcdoc.** Каждое превью — iframe с документом, в который сериализован
рендер (renderer.js подключается внутрь iframe).

- Плюсы: полная изоляция шрифтов/стилей между превью и от хоста.
- Минусы: GeoEdit/Inspector/Editor **не работают** через границу iframe без
  полноценного postMessage-моста и переписывания координатной модели (legacy-движок
  читает `getBoundingClientRect` и вешает overlay в том же документе); свой
  `document.head` — нужно заново заводить link шрифтов в каждом iframe; каждый
  iframe — отдельный layout-документ (тяжело при нескольких edit/превью на холсте);
  синхронизация размеров — только через ResizeObserver + postMessage.

### 6.3 Рекомендация: **прямое монтирование (вариант A)** для всех превью

Обоснование:

1. Edit-нода — центральный элемент спринта (Figma-уровень), а её инструменты
   (GeoEdit overlay внутри `.edit-inner`, `nodes.js:663-666, 735-759`) требуют
   общего DOM и общей системы координат с превью. iframe это ломает, а мост
   сопоставим с переписыванием движка, что запрещено решением владельца №6.
2. renderer.js — глобальный и инжектит `<style>`/Google Fonts в документ: изоляция
   через iframe решает только проблему общего font-link, которая уже существует в
   легаси и не является блокирующей; скоуп CSS по `.ir-<uid>` и так предотвращает
   взаимное влияние превью.
3. Производительность: прямое монтирование дешевле N iframe-документов при
   нескольких генераторах/reproduce на холсте.
4. Перенос затрат минимален: компонент-обёртка `IrPreview({ir})` (~30 строк)
   используется и в миниатюрах генератора, и в edit-ноде, и в reproduce-превью
   (`nodes.js:913-918`), и в «→ Editor/→ Reference» сценариях.

iframe оставить как запасной вариант только для чисто статических миниатюр, если
конфликт шрифтов станет продуктовой проблемой (в этом спринте — не станет).

---

## 7. Риски

1. **localStorage quota (~5–10 МБ на origin).** Тяжёлые поля: `reference.image`,
   `reproduce.image` и `reproduce.result.repro_png/html` (base64 data-URL). Легаси
   уже сталкивается: fallback `stripHeavy()` (`nodes.js:1161-1172`) при
   `QuotaExceededError` **молча выкидывает все строки `data:*` и >200 КБ** — после
   перезагрузки изображения теряются, остаётся только toast (`nodes.js:1185-1188`);
   при повторном провале — `lastSaveOk=false` и флаш `beforeunload`
   (`nodes.js:1189-1192, 1198-1200`). Миграция обязана как минимум сохранить это
   поведение; правильно — вынести бинари из состояния графа: blob-хранилище
   IndexedDB с ключами-хэшами в `data` (серверного эндпоинта загрузки файлов пока
   нет — отдельная бэкенд-задача вне этой спеки).
2. **base64 в состоянии графа.** `reproduce.result` хранится в `data` целиком
   (`nodes.js:873`), включая `html` и `repro_png` — раздувает и сейв, и экспортный
   JSON (`designai-graph.json`), и zustand-снимки. Рекомендация: в новом UI держать
   `result` в сторе, но из сохраняемого `data` вычленять тяжёлые поля (аналог
   `stripHeavy` на записи, детерминированно, а не по ошибке квоты).
3. **Автосейв.** Дебаунс 300 мс (`nodes.js:1175-1176`) сохраняется. В RF
   `onNodesChange` генерируется на каждый кадр драга — не писать в localStorage по
   событиям изменения позиций; точки сохранения: `onNodeDragStop`, изменения `data`,
   connect/disconnect, import. Флаш `beforeunload` при неудачной записи
   (`nodes.js:1198-1200`) перенести.
4. **Мутация `ir.tokens` в renderIR** (`renderer.js:542`) конфликтует с immutable-
   состоянием React/zustand — рендерить только копии (раздел 6.2A), иначе каждый
   рендер «портит» сохранённый объект и провоцирует лишние пересохранения.
5. **Типы id.** Легаси-id — number (`nextId`, `nodes.js:19,257`; Number при drop,
   `nodes.js:1087`), RF требует string. Единый конвертер в обе стороны; в
   экспорт/сейв — обратно number (совместимость, раздел 2.3).
6. **GraphDev и Playwright-тесты.** `window.GraphDev` (`nodes.js:1270-1304`)
   используется тестами `ui_demo_shots.py`, `ui_css_injection_test.py`,
   `ui_p1_*.py`, `ui_storage_test.py` и др. Без шима ломается приёмка Фаз B/C.
7. **Общий ключ localStorage.** Legacy `/nodes` и новый `/flow` пишут в один
   `designai-graph-v1`; две открытые вкладки перезапишут друг друга. На время
   паритета — принять как есть (легаси между собой ведёт себя так же); в Фазе C
   ключ не менять ради обратной совместимости сейвов пользователей.
8. **Перерисовки.** Кастомные ноды мемоизировать; тяжёлые превью (edit 780px,
   reproduce) не должны перерисовываться на каждый pan/зум RF — превью обновляется
   только по изменению `data.ir`.

---

## Сводка рекомендаций

- Раздел 5: кастомные nodeTypes по 7 типам, handles по таблице `PORTS` (+динамические
  у mix), состояние графа — **zustand-стор** (не `useNodesState`), dataflow pull-based
  переносится 1:1 (`outValue`/`pullInput`/`propagate`), формат сейва/экспорта не менять.
- Раздел 6: превью IR — **прямое монтирование `IRRenderer.renderIR` в ref-managed div**,
  iframe srcdoc отклонён из-за несовместимости с GeoEdit/Inspector/Editor и избыточной
  цены изоляции.
