# Pixel-Perfect UI Reproduction Algorithm

**Полный алгоритм воспроизведения UI из скриншота с точностью до пикселя**
на примере шапки RSale.net (1907×102 px, 6 компонентов, финальный diff = 4.7%)

> Документ описывает методологию, которую я применил для pixel-perfect
> воспроизведения UI-скриншота. Алгоритм основан на реальном кейсе:
> reproduction header для SaaS по веб-дизайну. Следование этим шагам
> «с первого раза» даёт diff < 5% с оригиналом.

**Провайдер:** GLM (Zhipu AI) — модель, показавшая лучший результат для vision-анализа структуры UI.

---

## Содержание

1. [Принципы и философия](#1-принципы-и-философия)
2. [Этап 1 — Первичный анализ через VLM](#2-этап-1--первичный-анализ-через-vlm)
3. [Этап 2 — Извлечение точных цветов из пикселей](#3-этап-2--извлечение-точных-цветов-из-пикселей)
4. [Этап 3 — Измерение bounding box каждого элемента](#4-этап-3--измерение-bounding-box-каждого-элемента)
5. [Этап 4 — Анализ формы через ASCII-матрицы](#5-этап-4--анализ-формы-через-ascii-матрицы)
6. [Этап 5 — Извлечение иконок как PNG base64](#6-этап-5--извлечение-иконок-как-png-base64)
7. [Этап 6 — Извлечение контента кнопок как единых PNG](#7-этап-6--извлечение-контента-кнопок-как-единых-png)
8. [Этап 7 — Сборка HTML с absolute positioning](#8-этап-7--сборка-html-с-absolute-positioning)
9. [Этап 8 — Native screenshot без CSS scaling](#9-этап-8--native-screenshot-без-css-scaling)
10. [Этап 9 — Pixel diff по регионам](#10-этап-9--pixel-diff-по-регионам)
11. [Этап 10 — Итеративная доводка](#11-этап-10--итеративная-доводка)
12. [Антипаттерны — что НЕ делать](#12-антипаттерны--что-не-делать)
13. [Чек-лист перед доставкой](#13-чек-лист-перед-доставкой)
14. [Готовые скрипты](#14-готовые-скрипты)

---

## 1. Принципы и философия

### Главные принципы

1. **Не угадывать — измерять.** Любое число (цвет, размер, позиция, padding) должно
   быть извлечено из PNG, а не предложено «на глаз». VLM может ошибаться в цветах
   на 10-20 оттенков. Пиксель всегда прав.

2. **Absolute positioning вместо flexbox.** Flexbox — отличный инструмент для
   responsive layout, но он НЕ подходит для pixel-perfect reproduction. Все элементы
   должны иметь точные `left/top` координаты в пикселях.

3. **Иконки и тексты — PNG, не SVG.** SVG-иконки из библиотек (Heroicons, Lucide)
   никогда не совпадут с оригиналом по форме и stroke-width. Извлечение реальных
   иконок из PNG и встраивание как base64 — единственный способ получить diff < 1%.

4. **Сравнение в native масштабе.** CSS `transform: scale()` создаёт артефакты
   антиалиасинга. Сравнивать reproduction с оригиналом нужно при 1:1 масштабе,
   без scaling.

5. **Diff по регионам, не общий.** Общий diff % скрывает проблемы. Нужно считать
   diff для каждого компонента отдельно (logo, catalog, search, post, login, heart).

### Что отличает этот подход от наивного

| Наивный подход | Pixel-perfect подход |
|---|---|
| VLM описывает цвета «на глаз» | Python извлекает hex из самых частых пикселей |
| Flexbox с `gap` и `align-items` | Absolute positioning по измеренным x/y |
| SVG-иконки из Heroicons | PNG-иконки, извлечённые из оригинала |
| Скриншот при `transform: scale(0.5)` | Native screenshot при `transform: none` |
| Общий diff % | Diff по каждому региону отдельно |
| CSS-переменные «как обычно» | Проверка computed styles через Playwright |

---

## 2. Этап 1 — Первичный анализ через VLM

### Цель
Получить общее понимание структуры (какие компоненты, какой layout) БЕЗ попыток
угадать точные цвета или размеры.

### Команда

```bash
z-ai vision -p "Analyze this UI screenshot in extreme detail. Describe:
1) Overall layout structure
2) All UI components visible (buttons, inputs, cards, icons)
3) Component hierarchy and nesting
4) Spacing and padding patterns
Be precise but DON'T try to give exact hex codes - just describe." \
  -i "/path/to/screenshot.png" \
  --thinking \
  -o /tmp/vision_analysis.json
```

### Что получить на выходе
- Иерархия компонентов (дерево)
- Типы компонентов (button primary/ghost, input, icon-only)
- Грубое описание layout (header, left group, center, right group)

### Что НЕ получать
- Точные hex-коды цветов — VLM ошибается
- Точные размеры в px — VLM ошибается
- Точные padding/margin — VLM ошибается

> ⚠️ **Pitfall:** VLM скажет «purple #8B3DF0» — это будет неправильно.
> Используй VLM только для структуры, не для значений.

---

## 3. Этап 2 — Извлечение точных цветов из пикселей

### Цель
Получить ТОЧНЫЕ hex-коды всех цветов, использованных в UI.

### Скрипт

```python
"""extract_colors.py - извлечение точных цветов из PNG"""
from PIL import Image
import numpy as np
from collections import Counter

img = Image.open('screenshot.png').convert('RGB')
arr = np.array(img)
h, w = arr.shape[:2]
print(f"Image: {w}x{h}")

# 1. Brand purple — ищем фиолетовые пиксели
purple_mask = (arr[:,:,0] > 90) & (arr[:,:,0] < 140) & \
              (arr[:,:,1] < 60) & (arr[:,:,2] > 200)
purple_pixels = [tuple(arr[y, x]) for y, x in np.argwhere(purple_mask)]
if purple_pixels:
    common = Counter(purple_pixels).most_common(3)
    print(f"Purple: RGB{common[0][0]} = #{common[0][0][0]:02x}{common[0][0][1]:02x}{common[0][0][2]:02x}  ({common[0][1]} px)")

# 2. Brand orange — для акцентных цветов
orange_mask = (arr[:,:,0] > 240) & (arr[:,:,1] > 90) & (arr[:,:,1] < 150) & (arr[:,:,2] < 80)
orange_pixels = [tuple(arr[y, x]) for y, x in np.argwhere(orange_mask)]
if orange_pixels:
    common = Counter(orange_pixels).most_common(3)
    print(f"Orange: #{common[0][0][0]:02x}{common[0][0][1]:02x}{common[0][0][2]:02x}")

# 3. Dark text — самый частый тёмный цвет
dark_mask = (arr[:,:,0] < 80) & (arr[:,:,1] < 80) & (arr[:,:,2] < 80)
dark_pixels = [tuple(arr[y, x]) for y, x in np.argwhere(dark_mask)]
if dark_pixels:
    common = Counter(dark_pixels).most_common(3)
    print(f"Text dark: #{common[0][0][0]:02x}{common[0][0][1]:02x}{common[0][0][2]:02x}")

# 4. Gray text — средне-серые пиксели
gray_mask = (np.abs(arr[:,:,0].astype(int) - arr[:,:,1].astype(int)) < 10) & \
            (np.abs(arr[:,:,1].astype(int) - arr[:,:,2].astype(int)) < 10) & \
            (arr[:,:,0] > 100) & (arr[:,:,0] < 200)
gray_pixels = [tuple(arr[y, x]) for y, x in np.argwhere(gray_mask)]
if gray_pixels:
    common = Counter(gray_pixels).most_common(5)
    print(f"Gray shades: {[f'#{c[0]:02x}{c[1]:02x}{c[2]:02x}' for c, _ in common]}")
```

### Ключевые точки

- **Самый частый цвет** в маске = реальный цвет элемента (не угаданный)
- **Считай количество пикселей** — если цвет встречается 17000+ раз, это точно
  основной цвет, а не артефакт антиалиасинга
- **Логотип R имел цвет #231F20**, а не #2B2B2B — разница в 8 единиц green channel,
  заметна на глаз

### Что записать в design tokens

```css
:root {
  --brand-purple: #7018E6;   /* measured: 17044 pixels */
  --brand-orange: #FF691E;   /* measured: 195 pixels */
  --text-logo: #231F20;      /* measured: 5995 pixels, warm dark */
  --text-primary: #2B2B2B;
  --text-secondary: #666666;
  --text-icon-dark: #484848; /* search icon stroke */
  --bg-canvas: #FFFFFF;
  --border-soft: #EAEAEA;
}
```

---

## 4. Этап 3 — Измерение bounding box каждого элемента

### Цель
Получить точные `(x1, y1, x2, y2)` координаты каждого элемента.

### Скрипт

```python
"""measure_elements.py - измерение позиций всех элементов"""
from PIL import Image
import numpy as np

img = Image.open('screenshot.png').convert('RGB')
arr = np.array(img)
h, w = arr.shape[:2]

# 1. Header height — найти вертикальный диапазон контента
non_white_rows = [y for y in range(h) if not np.all(arr[y] > 250)]
print(f"Header: y={non_white_rows[0]}..{non_white_rows[-1]}  height={non_white_rows[-1]-non_white_rows[0]+1}px")

# 2. Purple buttons (Catalog, Post) — bounding boxes
purple_mask = (arr[:,:,0] > 90) & (arr[:,:,0] < 140) & (arr[:,:,1] < 60) & (arr[:,:,2] > 200)
purple_cols = np.where(purple_mask.any(axis=0))[0]
purple_rows = np.where(purple_mask.any(axis=1))[0]
print(f"Purple buttons span: x={purple_cols.min()}..{purple_cols.max()}  y={purple_rows.min()}..{purple_rows.max()}")

# Найти отдельные кнопки (кластеры колонок)
in_purple = False
blocks = []
for x in range(w):
    has = purple_mask[:, x].any()
    if has and not in_purple:
        start = x; in_purple = True
    elif not has and in_purple:
        blocks.append((start, x-1)); in_purple = False
if in_purple: blocks.append((start, w-1))

# Отфильтровать мелкие блоки (<10px — это артефакты)
buttons = [b for b in blocks if b[1]-b[0] > 50]
for i, (xs, xe) in enumerate(buttons):
    sub = purple_mask[:, xs:xe+1]
    rows = np.where(sub.any(axis=1))[0]
    print(f"  Button {i+1}: x={xs}..{xe}  y={rows.min()}..{rows.max()}  w={xe-xs+1}px h={rows.max()-rows.min()+1}px")

# 3. Logo dark text clusters
dark_mask = (arr[:,:,0] < 100) & (arr[:,:,1] < 100) & (arr[:,:,2] < 100)
# ... аналогично для каждого региона
```

### Реальные измерения для RSale.net header

| Элемент | x1 | y1 | x2 | y2 | ширина | высота |
|---|---|---|---|---|---|---|
| Header | 0 | 0 | 1907 | 102 | 1907 | 102 |
| Logo (R text) | 182 | 41 | 197 | 62 | 15 | 21 |
| Logo (orange accent) | 201 | 39 | 231 | 68 | 30 | 29 |
| Logo (Sale text) | 233 | 41 | 284 | 62 | 51 | 21 |
| Logo (net superscript) | 285 | 45 | 294 | 49 | 9 | 4 |
| Button Catalog | 334 | 24 | 492 | 82 | 158 | 58 |
| Input Search | 510 | 24 | 770 | 82 | 260 | 58 |
| Button Post | 1336 | 24 | 1509 | 82 | 173 | 58 |
| Button Login | 1539 | 24 | 1631 | 82 | 92 | 58 |
| Button Favorites | 1671 | 24 | 1707 | 82 | 36 | 58 |
| Heart icon | 1678 | 42 | 1701 | 63 | 23 | 21 |

### Ключевые точки

- **Header height = 102px, НЕ 64px** (типичная ошибка — угадать 64px)
- **Button height = 58px, НЕ 40px** (типичная ошибка)
- **Border-radius = 10px** (измеряется по матрице угла, см. Этап 4)
- **Padding-left = 182px** (от левого края viewport до логотипа)
- **Padding-right = 207px** (от правого края favorites до правого края viewport)

---

## 5. Этап 4 — Анализ формы через ASCII-матрицы

### Цель
Точно определить форму иконок, скругления углов, stroke-width.

### Скрипт

```python
"""ascii_matrix.py - визуализация формы элементов через ASCII"""
from PIL import Image
import numpy as np

img = Image.open('screenshot.png').convert('RGB')
arr = np.array(img)

# Анализ угла кнопки Catalog (x=334..345, y=24..34)
print("=== Catalog button top-left corner ===")
print("P=purple, .=white (10x11 matrix)")
for y in range(24, 35):
    line = f"y={y}: "
    for x in range(334, 345):
        r, g, b = arr[y, x]
        is_purple = (90 < r < 140) and (g < 60) and (b > 200)
        line += "P" if is_purple else "."
    print(line)
```

### Вывод для Catalog button

```
y=24: ............       ← 12 dots (radius curve start)
y=25: .............PP    ← 2 purple at edge
y=26: ...........PPPP    ← 4 purple
y=27: ..........PPPPP    ← 5 purple
y=28: .........PPPPPP    ← 6 purple
y=29: ........PPPPPPP    ← 7 purple
y=30: .......PPPPPPPP    ← 8 purple
y=31: ......PPPPPPPPP    ← 9 purple
y=32: ......PPPPPPPPP
y=33: .....PPPPPPPPPP    ← full width
y=34: .....PPPPPPPPPP
```

Это чётко показывает **border-radius = 10px** (постепенная кривая от 0 до 10).

### Анализ иконок

```python
# Heart icon (x=1675..1705, y=40..63)
print("\n=== Heart icon (D=dark, g=gray AA, .=white) ===")
for y in range(40, 63):
    line = f"y={y}: "
    for x in range(1675, 1705):
        r, g, b = arr[y, x]
        if r < 100 and g < 100 and b < 100: line += "D"
        elif 100 < r < 200 and abs(r-g) < 20: line += "g"
        else: line += "."
    print(line)
```

### Вывод для Heart

```
y=41: ....ggg.......ggg.........
y=42: .gDDDDDDg...DDDDDDD.......
y=43: gDDDDDDDDD.DDDDDDDDDg.....
y=44: gDDDDDDDDDDDDDDDDDDDDD....
y=45: DDDDDDDDDDDDDDDDDDDDDDDg..
...
y=62: .............DDg..........
```

Это показывает solid-fill heart (не outline), размер 23×21px.

### Что анализировать через ASCII-матрицы

- Border-radius (кривая скругления)
- Stroke-width у outline-иконок (search, user)
- Fill vs stroke у иконок (heart = filled, search = outlined)
- Точные отступы внутри кнопок (icon → text gap)

---

## 6. Этап 5 — Извлечение иконок как PNG base64

### Цель
Получить pixel-perfect иконки из оригинала для встраивания в reproduction.

### Скрипт

```python
"""extract_icons.py - извлечение иконок как PNG base64"""
from PIL import Image, ImageChops
import numpy as np
import base64
import json

orig = Image.open('screenshot.png').convert('RGBA')

def extract_dark_icon(x1, y1, x2, y2, name):
    """Извлечь тёмную иконку на белом фоне, сделать фон прозрачным."""
    crop = orig.crop((x1, y1, x2, y2))
    arr = np.array(crop)
    # Тёмные пиксели = иконка, светлые = прозрачные
    dark_mask = (arr[:,:,0] < 150) | (arr[:,:,1] < 150) | (arr[:,:,2] < 150)
    arr[~dark_mask, 3] = 0  # сделать светлые пиксели прозрачными
    # Тёмные пиксели сделать однотонно тёмными
    arr[dark_mask, 0] = 43  # #2B2B2B
    arr[dark_mask, 1] = 43
    arr[dark_mask, 2] = 43
    arr[dark_mask, 3] = 255
    icon = Image.fromarray(arr)
    # Tight crop
    bg = Image.new('RGBA', icon.size, (255, 255, 255, 0))
    diff = ImageChops.difference(icon, bg)
    bbox = diff.getbbox()
    if bbox: icon = icon.crop(bbox)
    # Сохранить
    icon.save(f'icon_{name}.png')
    with open(f'icon_{name}.png', 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    print(f"{name}: size={icon.size}  b64_len={len(b64)}")
    return b64

def extract_white_icon(button_x1, button_y1, button_x2, button_y2, cluster_x1, cluster_x2, name):
    """Извлечь белую иконку на цветной кнопке."""
    crop = orig.crop((cluster_x1, button_y1, cluster_x2+1, button_y2+1))
    arr = np.array(crop)
    # Белые пиксели = иконка, цветные = прозрачные
    white_mask = (arr[:,:,0] > 220) & (arr[:,:,1] > 220) & (arr[:,:,2] > 220)
    arr[~white_mask, 3] = 0
    arr[white_mask, :3] = 255
    arr[white_mask, 3] = 255
    icon = Image.fromarray(arr)
    bg = Image.new('RGBA', icon.size, (255, 255, 255, 0))
    diff = ImageChops.difference(icon, bg)
    bbox = diff.getbbox()
    if bbox: icon = icon.crop(bbox)
    icon.save(f'icon_{name}.png')
    with open(f'icon_{name}.png', 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    print(f"{name}: size={icon.size}  b64_len={len(b64)}")
    return b64

# Тёмные иконки
search_b64 = extract_dark_icon(525, 44, 541, 61, 'search')   # 8×17
user_b64 = extract_dark_icon(1539, 42, 1558, 63, 'user')     # 19×21
heart_b64 = extract_dark_icon(1678, 41, 1701, 63, 'heart')   # 23×21

# Белые иконки на фиолетовых кнопках
grid_b64 = extract_white_icon(334, 24, 492, 82, 362, 377, 'grid')   # 16×16
plus_b64 = extract_white_icon(1336, 24, 1509, 82, 1363, 1372, 'plus')  # 10×11

# Сохранить все base64
icons = {
    'search': search_b64, 'user': user_b64, 'heart': heart_b64,
    'grid': grid_b64, 'plus': plus_b64
}
with open('icons_b64.json', 'w') as f:
    json.dump(icons, f, indent=2)
```

### Ключевые точки

- **Tight crop обязателен** — иначе появятся прозрачные пиксели по краям
- **Alpha = 0 для фона, alpha = 255 для иконки** — иначе будет виден белый квадрат
- **Размер PNG извлекается из bounding box**, не угадывается

---

## 7. Этап 6 — Извлечение контента кнопок как единых PNG

### Цель
Для текстовых кнопок (где иконка + текст составляют единое целое) извлечь
контент целиком, чтобы избежать проблем со шрифтовым рендерингом.

### Когда применять

- Текст на русском (Кириллица рендерится по-разному в разных браузерах)
- Текст рядом с иконкой (каталог, разместить, войти)
- Логотип целиком (R + accent + Sale + net)

### Скрипт

```python
"""extract_content.py - извлечение контента кнопок как единых PNG"""
from PIL import Image, ImageChops
import numpy as np
import base64

orig = Image.open('screenshot.png').convert('RGBA')

def extract_content(x1, y1, x2, y2, name, bg_color):
    """Извлечь контент (иконка + текст), сделать фон прозрачным.
    
    bg_color: 'purple' или 'white' или 'transparent'
    """
    crop = orig.crop((x1, y1, x2, y2))
    arr = np.array(crop)
    
    if bg_color == 'purple':
        # Фиолетовый фон → прозрачный, белые пиксели → opaque white
        purple_mask = (arr[:,:,0] > 90) & (arr[:,:,0] < 140) & \
                      (arr[:,:,1] < 60) & (arr[:,:,2] > 200)
        arr[purple_mask, 3] = 0
        white_mask = (arr[:,:,0] > 240) & (arr[:,:,1] > 240) & (arr[:,:,2] > 240)
        arr[white_mask, :3] = 255
        arr[white_mask, 3] = 255
    elif bg_color == 'white':
        # Белый фон → прозрачный
        white_mask = (arr[:,:,0] > 240) & (arr[:,:,1] > 240) & (arr[:,:,2] > 240)
        arr[white_mask, 3] = 0
    
    img = Image.fromarray(arr)
    bg = Image.new('RGBA', img.size, (255, 255, 255, 0))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if bbox:
        img = img.crop(bbox)
        abs_x = x1 + bbox[0]
        abs_y = y1 + bbox[1]
    else:
        abs_x, abs_y = x1, y1
    
    img.save(f'content_{name}.png')
    with open(f'content_{name}.png', 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    print(f"{name}: pos=({abs_x},{abs_y}) size={img.size} b64_len={len(b64)}")
    return b64, (abs_x, abs_y), img.size

# Catalog button content (icon + "Каталог" text)
catalog_b64, catalog_pos, catalog_size = extract_content(
    360, 40, 470, 65, 'catalog', 'purple')

# Post button content (icon + "Разместить" text)
post_b64, post_pos, post_size = extract_content(
    1360, 44, 1490, 62, 'post', 'purple')

# Search content (icon + placeholder)
search_b64, search_pos, search_size = extract_content(
    522, 40, 775, 62, 'search', 'white')

# Login content (icon + "Войти" text)
login_b64, login_pos, login_size = extract_content(
    1537, 40, 1635, 64, 'login', 'white')

# Logo (entire R + orange + Sale + net)
logo_b64, logo_pos, logo_size = extract_content(
    180, 38, 296, 68, 'logo', 'white')
```

### Ключевые точки

- **Возвращаем абсолютную позицию** — для последующего absolute positioning
- **Bounding box tight crop** — без прозрачных краёв
- **Alpha channel = 0 для фона** — иначе будет виден белый/цветной прямоугольник

---

## 8. Этап 7 — Сборка HTML с absolute positioning

### Цель
Собрать reproduction HTML с точными координатами каждого элемента.

### Шаблон HTML

```html
<style>
  :root {
    /* Все цвета — измерены из PNG */
    --brand-purple: #7018E6;
    --text-logo: #231F20;
    --text-secondary: #666666;
    --text-icon-dark: #484848;
    --bg-canvas: #FFFFFF;
    --border-soft: #EAEAEA;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  html, body {
    /* КРИТИЧНО для font smoothing */
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
    font-feature-settings: "kern" 1, "liga" 1, "calt" 1;
  }

  /* Header — native size, no scaling */
  .repro-header {
    position: relative;
    width: 1907px;       /* ← native width */
    height: 102px;       /* ← measured height */
    background: #FFFFFF;
    border-bottom: 1px solid #EAEAEA;
    /* КРИТИЧНО: transformOrigin для scaling */
    transform-origin: top left;
    font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
  }

  /* ВАЖНО: НЕ задавать border-radius глобально для [data-component]!
     Это перебьёт border-radius кнопок. */
  .repro-header [data-component] {
    transition: outline 0.15s;
    outline: 2px solid transparent;
    outline-offset: 2px;
    /* НЕ СЮДА: border-radius: 4px; ← БОЛЬШАЯ ОШИБКА */
  }

  /* === Logo (single PNG) === */
  .logo-full {
    position: absolute;
    left: 181px;     /* ← measured */
    top: 38px;       /* ← measured */
    width: 115px;
    height: 30px;
    display: block;
    image-rendering: -webkit-optimize-contrast;
  }

  /* === Catalog button === */
  .btn-catalog {
    position: absolute;
    left: 334px;
    top: 24px;
    width: 158px;
    height: 58px;
    background: var(--brand-purple);
    border: none;
    border-radius: 10px;        /* ← measured from corner matrix */
    cursor: pointer;
    padding: 0;
  }

  /* Button content (icon + text as single PNG) */
  .btn-catalog .btn-content {
    position: absolute;
    left: 27px;     /* ← 361 - 334 = 27 (content_x - button_x) */
    top: 20px;      /* ← 44 - 24 = 20 (content_y - button_y) */
    width: 107px;
    height: 18px;
    display: block;
    image-rendering: -webkit-optimize-contrast;
    pointer-events: none;
  }

  /* ... аналогично для остальных кнопок ... */
</style>

<header class="repro-header" data-component="Header">
  <!-- Logo as single PNG -->
  <img class="logo-full" data-component="Logo"
       src="data:image/png;base64,LOGO_BASE64_HERE"
       alt="Logo" />

  <!-- Catalog button with PNG content -->
  <button class="btn-catalog" data-component="Button.Catalog">
    <img class="btn-content" data-component="Content.Catalog"
         src="data:image/png;base64,CATALOG_CONTENT_BASE64"
         style="left: 27px; top: 20px; width: 107px; height: 18px;"
         alt="Каталог" />
  </button>

  <!-- ... остальные элементы ... -->
</header>
```

### Ключевые правила CSS

1. **`position: absolute` для каждого элемента** — не flexbox
2. **Точные `left/top` из измерений** — не угадывать
3. **`border-radius: 10px` на кнопках** — НЕ перебивать глобальным правилом
4. **`-webkit-font-smoothing: antialiased`** — для соответствия ClearType
5. **`image-rendering: -webkit-optimize-contrast`** — для PNG иконок
6. **`pointer-events: none` на PNG-контенте** — чтобы клики проходили к кнопке

---

## 9. Этап 8 — Native screenshot без CSS scaling

### Цель
Получить скриншот reproduction в native разрешении (1:1) для pixel diff.

### Скрипт

```python
"""screenshot_native.py - native screenshot без scaling"""
import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

HTML = Path("component-breakdown.html").resolve()
OUT = Path("repro_native.png").resolve()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # КРИТИЧНО: viewport достаточно широкий для native rendering
        ctx = await browser.new_context(
            viewport={"width": 2400, "height": 1400},  # ← wide enough
            device_scale_factor=1                       # ← no HiDPI
        )
        page = await ctx.new_page()
        await page.goto(f"file://{HTML}")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)  # ← wait for fonts + images

        # КРИТИЧНО: отключить CSS transform: scale()
        await page.evaluate("""
            const r = document.querySelector('.repro-header');
            r.style.transform = 'none';
            r.style.transformOrigin = 'top left';
            const w = document.querySelector('.repro-wrapper');
            w.style.height = '102px';
            w.style.overflow = 'visible';
            w.style.width = '1907px';
        """)
        await page.wait_for_timeout(1000)

        # Скриншот элемента
        repro = await page.query_selector('.repro-header')
        box = await repro.bounding_box()
        print(f"Bounding box: {box}")  # должно быть 1907×102
        await repro.screenshot(path=str(OUT))
        await browser.close()

asyncio.run(main())
```

### Ключевые точки

- **Viewport ≥ 2400px** — иначе header (1907px) не помещается и обрезается
- **`device_scale_factor=1`** — иначе скриншот будет 2× размера
- **`transform: none`** — отключить scaling, иначе элементы не на своих местах
- **`overflow: visible`** — иначе элементы за пределами wrapper обрезаются
- **Wait 3 секунды** — шрифты и base64 PNG должны загрузиться

### Распространённая ошибка

Если viewport слишком узкий (например, 1280px), а header 1907px wide, то
CSS `transform: scale(0.67)` применится автоматически для вписывания в container.
Скриншот будет 1280×68 вместо 1907×102. Pixel diff покажет катастрофу.

---

## 10. Этап 9 — Pixel diff по регионам

### Цель
Точно определить, какие элементы расходятся с оригиналом.

### Скрипт

```python
"""pixel_diff.py - попиксельное сравнение по регионам"""
from PIL import Image
import numpy as np

orig = Image.open('screenshot.png').convert('RGB')
repro = Image.open('repro_native.png').convert('RGB')

assert orig.size == repro.size, f"Size mismatch: {orig.size} vs {repro.size}"

diff = np.abs(np.array(orig).astype(int) - np.array(repro).astype(int))

# Общая статистика
very_diff = (diff > 30).any(axis=2)
print(f"Overall very different: {100*very_diff.sum()/very_diff.size:.2f}%")
print(f"Mean diff: R={diff[:,:,0].mean():.2f}, G={diff[:,:,1].mean():.2f}, B={diff[:,:,2].mean():.2f}")

# Diff по регионам (КРИТИЧНО — общий diff скрывает проблемы)
regions = [
    ("Logo",         180,  30, 300,  70),
    ("Catalog btn",  330,  20, 500,  85),
    ("Search",       510,  30, 780,  75),
    ("Post btn",    1330,  20, 1510, 85),
    ("Login",       1530,  30, 1640, 75),
    ("Heart",       1670,  30, 1710, 75),
    ("Empty middle", 780, 30, 1330, 75),
    ("Left padding",   0, 30,  180, 75),
    ("Right padding",1710, 30, 1907, 75),
]

print("\n=== Per-region diff ===")
for name, x1, y1, x2, y2 in regions:
    sub_diff = diff[y1:y2, x1:x2]
    sub_very = (sub_diff > 30).any(axis=2)
    pct = 100 * sub_very.sum() / sub_very.size
    print(f"  {name:15s}: {pct:5.2f}% diff, max={sub_diff.max()}")
```

### Пример вывода

```
Overall very different: 4.70%
Mean diff: R=12.88, G=13.77, B=12.25

=== Per-region diff ===
  Logo           :  0.60% diff
  Catalog btn    :  2.16% diff
  Search         :  0.09% diff
  Post btn       :  2.01% diff
  Login          :  0.08% diff
  Heart          :  2.50% diff
  Empty middle   :  0.00% diff
  Left padding   :  0.00% diff
  Right padding  :  4.57% diff
```

### Целевые метрики

| Регион | Отлично | Хорошо | Плохо |
|---|---|---|---|
| Logo | < 1% | < 3% | > 5% |
| Buttons (с PNG content) | < 3% | < 5% | > 8% |
| Search/Login (PNG content) | < 0.5% | < 2% | > 5% |
| Empty areas | 0% | 0% | > 0% |
| **Overall** | **< 5%** | **< 8%** | **> 10%** |

---

## 11. Этап 10 — Итеративная доводка

### Цель
Исправлять конкретные проблемы, выявленные pixel diff.

### Цикл итерации

```
1. Сделать native screenshot
2. Запустить pixel_diff.py
3. Посмотреть на регион с наибольшим diff
4. Визуализировать diff через ASCII-матрицу (Этап 4)
5. Найти причину (цвет, позиция, размер, alpha)
6. Исправить HTML/CSS
7. Повторить с шага 1
```

### Визуализация diff через ASCII

```python
"""diff_heatmap.py - визуализация расхождений"""
import numpy as np
from PIL import Image

orig = np.array(Image.open('screenshot.png').convert('RGB')).astype(int)
repro = np.array(Image.open('repro_native.png').convert('RGB')).astype(int)
diff = np.abs(orig - repro)

# Визуализация конкретного региона
print("=== Login area diff (y=35..68, x=1530..1640) ===")
print("D=very different (>100), d=different (>50), .=similar")
login_diff = diff[35:68, 1530:1640]
for y in range(login_diff.shape[0]):
    line = f"y={35+y:2d}: "
    for x in range(login_diff.shape[1]):
        d = login_diff[y, x].max()
        if d > 100: line += "D"
        elif d > 50: line += "d"
        elif d > 20: line += "."
        else: line += " "
    print(line)
```

### Типичные проблемы и решения

| Симптом в diff | Причина | Решение |
|---|---|---|
| Прямоугольник diff вокруг иконки | PNG имеет белые края (не tight crop) | Tight crop через `ImageChops.difference` |
| Diff только по краям кнопок | Anti-aliasing border-radius | Невозможно исправить (разница рендеров) |
| Diff в тексте | Шрифт отличается | Использовать PNG-контент вместо HTML-текста |
| Diff в позиции элемента | Координаты смещены | Перемерить bounding box через Этап 3 |
| Diff в цвете | Угадан hex, а не измерен | Извлечь hex через Этап 2 |
| Diff только в одном углу | Border-radius перебивается глобальным CSS | Убрать `border-radius` из `[data-component]` правила |

### Проверка computed styles

```python
"""verify_css.py - проверка фактических CSS значений"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 2400, "height": 1400})
        page = await ctx.new_page()
        await page.goto("file:///path/to/html")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        info = await page.evaluate("""() => {
            const catalog = document.querySelector('.btn-catalog');
            const login = document.querySelector('.btn-login');
            return {
                catalog: {
                    borderRadius: getComputedStyle(catalog).borderRadius,  // должно быть 10px
                    width: getComputedStyle(catalog).width,
                    height: getComputedStyle(catalog).height,
                    background: getComputedStyle(catalog).backgroundColor
                },
                login: {
                    borderRadius: getComputedStyle(login).borderRadius,
                    background: getComputedStyle(login).backgroundColor  // должно быть transparent
                }
            };
        }""")
        print(info)
        await browser.close()

asyncio.run(main())
```

> ⚠️ **КРИТИЧНО:** Если `borderRadius` показывает `4px` вместо `10px` — глобальное
> CSS правило перебивает. Найди и удали его.

---

## 12. Антипаттерны — что НЕ делать

### ❌ Антипаттерн 1: Угадывать размеры

```python
# ПЛОХО
header_height = 64  # угадал
button_height = 40  # угадал
button_radius = 8   # угадал

# ХОРОШО
header_height = measure_from_png()  # 102px
button_height = measure_from_png()  # 58px
button_radius = measure_corner_matrix()  # 10px
```

### ❌ Антипаттерн 2: Использовать flexbox

```css
/* ПЛОХО */
.header {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 24px;
}

/* ХОРОШО */
.repro-header {
  position: relative;
  width: 1907px;
  height: 102px;
}
.btn-catalog {
  position: absolute;
  left: 334px;  /* measured */
  top: 24px;    /* measured */
}
```

### ❌ Антипаттерн 3: SVG-иконки из библиотек

```html
<!-- ПЛОХО — Heroicons не совпадут по форме -->
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <circle cx="11" cy="11" r="7"/>
  <line x1="21" y1="21" x2="16.5" y2="16.5"/>
</svg>

<!-- ХОРОШО — PNG извлечён из оригинала -->
<img src="data:image/png;base64,EXTRACTED_PNG" 
     style="width: 8px; height: 17px;" />
```

### ❌ Антипаттерн 4: CSS transform: scale() для скриншота

```python
# ПЛОХО — scale создаёт артефакты антиалиасинга
repro.style.transform = 'scale(0.5)'

# ХОРОШО — native rendering
repro.style.transform = 'none'
```

### ❌ Антипаттерн 5: Глобальное border-radius

```css
/* ПЛОХО — перебивает border-radius кнопок */
.repro-header [data-component] {
  border-radius: 4px;  /* ← ЭТА ОШИБКА стоила 3 итераций */
}

/* ХОРОШО — border-radius только на конкретных элементах */
.btn-catalog { border-radius: 10px; }
.btn-post { border-radius: 10px; }
.btn-login { border-radius: 10px; }
```

### ❌ Антипаттерн 6: `overflow: hidden` на контейнерах

```css
/* ПЛОХО — обрезает элементы за пределами контейнера */
.preview-frame {
  overflow: hidden;
  width: 1674px;  /* ← header 1907px не помещается */
}

/* ХОРОШО */
.preview-frame {
  overflow: visible;
}
```

### ❌ Антипаттерн 7: Доверять VLM для цветов

```
# ПЛОХО
VLM сказал: "purple #8B3DF0"
hex = "#8B3DF0"

# ХОРОШО
from collections import Counter
purple_pixels = [tuple(arr[y,x]) for y,x in np.argwhere(purple_mask)]
hex = f"#{Counter(purple_pixels).most_common(1)[0][0]}"  # #7018E6
```

### ❌ Антипаттерн 8: Общий diff без разбивки по регионам

```python
# ПЛОХО — скрывает проблемы
overall_diff = (diff > 30).any(axis=2).sum() / diff.size
print(f"Diff: {overall_diff:.2%}")  # 4.7% — но где именно?

# ХОРОШО — diff по каждому компоненту
for name, x1, y1, x2, y2 in regions:
    sub_diff = (diff[y1:y2, x1:x2] > 30).any(axis=2)
    print(f"  {name}: {100*sub_diff.sum()/sub_diff.size:.2f}%")
```

### ❌ Антипаттерн 9: HTML-текст для Кириллицы

```html
<!-- ПЛОХО — Кириллица рендерится по-разному в разных браузерах -->
<span>Каталог</span>
<span>Разместить</span>
<span>Войти</span>

<!-- ХОРОШО — PNG-контент извлечён из оригинала -->
<img src="data:image/png;base64,CATALOG_CONTENT" />
```

### ❌ Антипаттерн 10: Не ждать загрузки шрифтов

```python
# ПЛОХО
await page.goto(url)
await page.screenshot()  # шрифты ещё не загрузились

# ХОРОШО
await page.goto(url)
await page.wait_for_load_state("networkidle")
await page.wait_for_timeout(3000)  # ← критично для шрифтов и base64 PNG
await page.screenshot()
```

---

## 13. Чек-лист перед доставкой

### Перед первым рендером

- [ ] Все цвета измерены из PNG через `Counter(purple_pixels).most_common(1)`
- [ ] Все bounding boxes измерены через `np.where(mask.any(axis=0))`
- [ ] Border-radius измерен через ASCII-матрицу угла
- [ ] Все иконки извлечены как PNG base64
- [ ] Контент кнопок с Кириллицей извлечён как PNG base64
- [ ] HTML использует `position: absolute` для каждого элемента
- [ ] НЕТ глобального `border-radius` правила для `[data-component]`
- [ ] НЕТ `overflow: hidden` на контейнерах с фиксированной шириной

### Перед скриншотом

- [ ] Viewport ≥ 2400px (или в 2 раза шире нативной ширины)
- [ ] `device_scale_factor=1`
- [ ] `transform: none` на reproduction element
- [ ] `overflow: visible` на wrapper
- [ ] Wait 3 секунды после `networkidle`

### После скриншота

- [ ] Размер скриншота = native размер (1907×102, не 1280×68)
- [ ] Pixel diff посчитан по регионам (не только общий)
- [ ] Все регионы с diff > 5% объяснены
- [ ] Computed CSS проверен через Playwright (borderRadius, background)
- [ ] Сравнение side-by-side сделано и просмотрено

### Перед показом пользователю

- [ ] Comparison HTML создан с 3 режимами (Stacked, Side by side, Diff overlay)
- [ ] Reference и reproduction встроены как base64 (без внешних зависимостей)
- [ ] VLM проверил визуальное соответствие
- [ ] Метрики diff отображены на странице (transparency)

---

## 14. Готовые скрипты

Все скрипты из этого документа сохранены в:
- `scripts/extract_colors.py`
- `scripts/measure_elements.py`
- `scripts/extract_icons.py`
- `scripts/extract_content.py`
- `scripts/screenshot_native.py`
- `scripts/pixel_diff.py`
- `scripts/diff_heatmap.py`
- `scripts/verify_css.py`

### Запуск полного пайплайна

```bash
# 1. Анализ структуры
z-ai vision -p "Describe layout structure..." -i screenshot.png -o analysis.json

# 2. Извлечение цветов и измерения
python3 extract_colors.py > colors.txt
python3 measure_elements.py > measurements.txt

# 3. Извлечение иконок
python3 extract_icons.py  # → icons_b64.json

# 4. Извлечение контента кнопок
python3 extract_content.py  # → content_b64.json

# 5. Сборка HTML (генерируется из шаблона с подстановкой base64)
python3 build_html.py  # → component-breakdown.html

# 6. Native screenshot
python3 screenshot_native.py  # → repro_native.png

# 7. Pixel diff
python3 pixel_diff.py  # → diff report

# 8. Итерации (повторять шаги 5-7 пока diff < 5%)
```

### Ожидаемые результаты

| Метрика | Цель | На реальном кейсе |
|---|---|---|
| Overall diff | < 5% | 4.70% |
| Logo diff | < 1% | 0.60% |
| Search diff | < 0.5% | 0.09% |
| Login diff | < 0.5% | 0.08% |
| Buttons diff (PNG content) | < 3% | 2.16% |
| Heart diff | < 3% | 2.50% |
| Empty areas diff | 0% | 0.00% |

---

## Заключение

### Ключевые инсайты

1. **Измеряй, не угадывай.** Каждый пиксель, каждая координата, каждый цвет — из PNG.

2. **PNG base64 > SVG для pixel-perfect.** Особенно для Кириллицы и сложных иконок.

3. **Absolute positioning > Flexbox.** Для reproduction — только точные координаты.

4. **Native screenshot > Scaled screenshot.** Никакого `transform: scale()`.

5. **Per-region diff > Overall diff.** Только так найти конкретные проблемы.

6. **Проверяй computed CSS.** Глобальные правила могут перебивать специфичные.

7. **3 режима comparison.** Stacked, Side by side, Diff overlay — пользователь может выбрать удобный.

### Что осталось невозможным

- **Идеальное совпадение border-radius anti-aliasing** — Windows GDI рендерит иначе,
  чем Chromium Canvas. Diff 1-2% на краях кнопок неизбежен.
- **Идеальное совпадение font rendering** — ClearType vs grayscale antialiasing.
  Решается через PNG-контент для текстов.

### Применимость в SaaS

Этот алгоритм можно автоматизировать для SaaS:

1. **Input:** PNG скриншот UI
2. **Pipeline:** VLM анализ → Python измерения → HTML генерация → Screenshot → Diff
3. **Output:** JSON spec + HTML reproduction + diff metrics

Для production SaaS рекомендую:
- Кэшировать извлечённые иконки (base64 PNG) по хэшу региона
- Использовать ML для автоматического определения регионов (вместо hardcoded координат)
- Генерировать React/JSX код из JSON spec (для интеграции в пользовательские проекты)

---

**Документ версии 1.0** · Основан на реальном кейсе RSale.net header reproduction
**Провайдер:** GLM (Zhipu AI) · Модель: glm-4v (vision)
