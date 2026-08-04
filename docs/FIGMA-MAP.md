# Figma ↔ DesignAI: карта соответствия и план

## Часть 1: Как устроен Figma (исследование)

### Обзорная модель: 4 слоя
1. **Scene graph** — дерево нод (Document → Page → Frame → Group → Shape/Text/Image)
2. **Canvas** — рендеринг scene graph через WebGL + DOM overlay для текста
3. **Tools** — state machine: select, frame, shape, text, pen, hand, comment
4. **Panels** — layers, design inspector, prototype, assets

### Selection model: 8 способов выделения
1. Click — выделить верхний элемент под курсором
2. Shift+click — toggle в множественном выделении
3. Marquee (drag по пустому) — резиновое выделение
4. Cmd/Ctrl+click — **deep select**: пропустить контейнер, выделить вложенный элемент
5. Double-click — **enter container**: войти в группу/фрейм, выделять только его детей
6. Esc — **exit container**: выйти на уровень выше
7. Tab / Shift+Tab — циклическое выделение сиблингов
8. Layers panel click — выделение по дереву

### Editing model
- **Move**: drag выделенного, snap к smart guides, Shift = constrain axis
- **Resize**: 8 хендлов, Shift = preserve aspect, Alt = from center
- **Inline text**: double-click на тексте → contenteditable
- **Nudge**: Arrow keys = 1px, Shift+Arrow = 10px
- **Duplicate**: Alt+drag = копировать, Cmd+D = duplicate in place
- **Rotate**: handle сверху, Shift = snap 15°

### Smart guides
- **Красные линии** alignment (left/center/right/top/middle/bottom) при drag
- **Зелёные distance labels** — расстояние до соседей при hover/drag
- **Equal spacing** — фиолетовые метки когда gap между 3+ элементами одинаковый

### Toolbar: 16 инструментов Figma → 5 нужных нам
1. **Select (V)** — ✅ есть
2. **Frame (F)** — 🟡 через IR frame
3. **Text (T)** — ✅ inline edit
4. **Hand (H/Space)** — ✅ pan в nodes.js
5. **Comment (C)** — ❌ не нужен

Не нужны: Rectangle, Ellipse, Pen, Pencil, Arrow, Line, Image, Slice, Paint bucket, Eyedropper

### Components
- Main component → instance (linked copy)
- Variants (property-based)
- Component properties (boolean, text, instance swap)

### Auto Layout
- direction (row/column), spacing, padding
- Resizing: hug contents / fill container / fixed
- Min/max width/height

### Layers panel + Inspector
- Дерево с visibility/lock toggles
- Inspector: position (X/Y), size (W/H), rotation, opacity, fill, stroke, effects, layout, export

---

## Часть 2: Карта Figma ↔ DesignAI IR

| Figma концепт | DesignAI IR | Статус |
|---|---|---|
| Document | graph JSON (nodes+edges) | ✅ |
| Page | — (одна страница) | 🟡 |
| Frame | section.frame | ✅ |
| Group | section (type grouping) | 🟡 |
| Auto Layout | frame.layout:"auto" + direction/gap/padding | ✅ |
| Absolute positioning | frame.layout:"free" + x/y | ✅ |
| Constraints | — | ❌ |
| Component | — | ❌ |
| Instance | — | ❌ |
| Variant | section.variant | ✅ |
| Text node | element type:"heading"/"text" | ✅ |
| Image node | element type:"image" | ✅ |
| Vector/Shape | — (закрытая библиотека) | ❌ не нужно |
| Fill (solid) | tokens.color.* | ✅ |
| Fill (gradient) | — | ❌ |
| Stroke | tokens.color.border | 🟡 |
| Effect (shadow) | tokens.shadow | ✅ |
| Effect (blur) | — | ❌ |
| Opacity | — | ❌ |
| Corner radius | tokens.radius.* | ✅ |
| Per-corner radius | — | ❌ |
| Font family | tokens.font.*.family | ✅ |
| Font size | TYPE_SCALE + element.size | 🟡 |
| Line height | — | ❌ |
| Letter spacing | — | ❌ |
| Text align | element.align | ✅ |
| Smart guides | — | ❌ P0 |
| Distance labels | — | ❌ P0 |
| Selection overlay | geoedit.js | ✅ |
| Resize handles | geoedit.js (8 handles) | ✅ |
| Rotation handle | — | ❌ |
| Layers panel | editor.js layers | ✅ |
| Inspector | editor.js inspector | ✅ |
| Nudge (arrows) | — | ❌ P0 |
| Deep select (Cmd+click) | — | ❌ P0 |
| Enter container (dbl-click) | — | ❌ P0 |

---

## Часть 3: Что уже есть

### geoedit.js (~870→1020 строк)
1. ✅ Click select / Shift+click toggle
2. ✅ Marquee selection
3. ✅ Drag move с snap 8px
4. ✅ 8 resize handles
5. ✅ Live preview при drag/resize
6. ✅ Selection boxes + chips (type · W×H)
7. ✅ Hover highlight
8. ✅ Alignment (6 направлений)
9. ✅ Distribution (H/V)
10. ✅ setFrame / resetFrame
11. ✅ Inline text edit (dblclick)
12. ✅ Геометрический hit-testing (tldraw-модель)

### editor.js (~760 строк)
1. ✅ Полноэкранный режим
2. ✅ Layers panel
3. ✅ Inspector (X/Y/W/H + токены)
4. ✅ Undo/redo (command pattern)
5. ✅ Toolbar
6. ✅ Zoom controls

### IR Schema
- 19 типов секций
- 13 типов элементов
- Frame model (Figma-like geometry)
- Tokens (color/font/radius/spacing/shadow)

---

## Часть 4: Приоритизированный план

### P0 — «фигмовское ощущение» (1.5 недели)
- [ ] Smart guides: красные линии alignment при drag
- [ ] Distance labels: зелёные метки расстояния до соседей
- [ ] Equal spacing: фиолетовые метки равных gap
- [ ] Keyboard nudging: Arrow = 1px, Shift+Arrow = 10px
- [ ] Deep select: Cmd/Ctrl+click пропускает контейнер
- [ ] Enter container: dbl-click входит в группу, Esc выходит

### P1 — продуктивность (2 недели)
- [ ] Lock/Hide в layers panel
- [ ] Search по layers
- [ ] Numeric math в инспекторе (W: 100*2)
- [ ] Drag scrub на числовых полях
- [ ] Shift constrain (drag только по одной оси)
- [ ] Alt+drag duplicate
- [ ] Multi-edit (изменение свойства у нескольких выделенных)

### P2 — layout (3 недели)
- [ ] Constraints (left/right/center/scale)
- [ ] Per-corner radius
- [ ] Reorder в layers (drag & drop)
- [ ] Group / Ungroup
- [ ] Z-order (bring forward / send back)

### P3 — компоненты (4-6 недель)
- [ ] Main component / instance
- [ ] Instance swap
- [ ] Component properties

### P4 — инструменты (2 недели)
- [ ] Text tool (создание текста кликом)
- [ ] Image tool (upload + crop)
- [ ] Slice tool (export region)

---

## Часть 5: Уникальные фичи DesignAI (нет в Figma)

1. **AI-driven editing** — LLM Refine: «сделай кнопки круглее» → IR mutation
2. **Token propagation visualization** — подсветка всех элементов, использующих токен
3. **Mix preview** — split-screen сравнение двух IR
4. **Style DNA lock** — залочить стиль, менять только структуру
5. **Critic-нода** — рендер → скриншот → VLM оценка → автофикс

---

## Часть 6: Антипаттерны — что НЕ переносить

- ❌ Vector tools (Pen/Pencil/Rectangle) — закрытая библиотека блоков
- ❌ Prototype mode — не наша аудитория
- ❌ Dev Mode — export layer закроет
- ❌ Plugins system на старте
- ❌ Multiple pages per file
- ❌ Branching & merge
- ❌ Sticky notes / FigJam
- ❌ Boolean operations

---

## Ключевые выводы

**Главный инсайт:** solid foundation (geoedit + editor) уже есть, но не хватает «фигмовского ощущения» — smart guides и привычных keyboard interactions. P0 закроет 80% ощущения «настоящего редактора».

**Критичные 2 недели:**
1. Smart guides (красные линии alignment)
2. Distance labels + equal spacing
3. Keyboard nudging (стрелки 1px, Shift+стрелки 10px)
4. Cmd+click deep select
5. Double-click enter container + Esc exit

**Не делать:** vector tools, prototype mode, plugins — распылит ресурсы без ценности.
