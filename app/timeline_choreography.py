"""Хореография видео-таймлайна: роли слоёв, шаблоны монтажа, нормализация планов.

Модель (или разбор ключевых слов) выбирает шаблон и акценты; здесь план
превращается в детерминированные операции с кинематографическими кривыми.
Все шаблоны опираются на пресеты ``ir.timeline.preset_operations`` и слой
камеры, поэтому результат остаётся обратимым change-set'ом.
"""
from __future__ import annotations

import re

from ir.timeline import (
    CAMERA_LAYER_ID,
    CAMERA_PRESETS,
    NAMED_CURVES,
    PRESET_NAMES,
    ensure_camera_operations,
    merge_keyframe_operations,
    preset_operations,
)

TEMPLATE_NAMES = ("product-showcase", "presentation", "feature-tour", "clean-reveal", "cinematic-camera")

# Один шаг плана анимирует не больше этого числа слоёв: каскад по сотням
# слоёв раздувает change-set за границы сложности контракта.
MAX_LAYERS_PER_STEP = 32
# Длинная страница: шаблон даёт до ~25 шагов (секции, дети hero, камера, финал).
MAX_STEPS = 32

# Ритм продуктового ролика (мс): короче — дёргано, длиннее — вяло.
MIN_REVEAL_MS = 450
MAX_REVEAL_MS = 1600
MAX_STAGGER_MS = 220
# Высота секции по умолчанию, когда в IR нет геометрии: оценка для панорамы камеры.
DEFAULT_SECTION_HEIGHT = 720
# Скорость панорамы по измеренной странице (px композиции в секунду): до неё
# пролёт покрывает страницу целиком, дальше камера мелькает.
MAX_PAN_SPEED = 700
# Пресеты появления: слой невидим до своего шага.
ENTRANCE_PRESETS = ("fade-in", "fade-in-up", "slide-in-left", "slide-in-right", "zoom-in", "scale-reveal",
                    "focus-pull", "rotate-in", "wipe-reveal")

# Слова, при которых запрос касается взаимодействия/состояний страницы, а не
# только движения: такой запрос идёт через полный сценарный путь с vision.
INTERACTION_RE = re.compile(
    r"\b(click|tap|press|type|typing|enter|fill in|cursor|hover|menu|dropdown|dialog|modal|overlay|"
    r"translate|translation|language|state|navigate|navigation|scroll to|open|close|select|submit|"
    r"клик|кликн|нажм|нажат|курсор|ввод|введ|напечат|форм|меню|диалог|окно|перев[ео]д|язык|состояни|"
    r"перейти|переход|открой|открыть|закрой|выбер|выбор|скролл к|прокрут)",
    re.IGNORECASE,
)

ROLE_PATTERNS = (
    ("button", re.compile(r"button|btn|cta|submit|subscribe|buy|start|get started|купить|начать|подписаться", re.I)),
    ("image", re.compile(r"image|img|photo|picture|media|hero-media|illustration|video|фото|картин|изображ", re.I)),
    ("heading", re.compile(r"heading|headline|title|h1|h2|h3|заголов", re.I)),
    ("text", re.compile(r"text|paragraph|subheading|subtitle|caption|description|lead|текст|описан", re.I)),
    ("card", re.compile(r"card|tier|feature|item|карточ|плитк", re.I)),
)


# Положительный словарь движения: без него короткий ответ на уточняющий вопрос
# режиссёра («Диван») не должен уходить в моушн-путь.
MOTION_RE = re.compile(
    r"(motion|animat|camera|zoom|reveal|fade|cinemat|smooth|soft|showcase|presentation|parallax|stagger|pulse|"
    r"dynamic|slide|pan|push|drift|bounce|tilt|dramatic|energetic|calm|minimal|elegant|premium|product video|"
    r"promo|launch|intro|outro|transition|easing|анимац|движ|камер|наезд|появ|плавн|кинемат|презентац|"
    r"продукт|эффект|ролик|каскад|пульс|зум|приближ|панорам|пролёт|пролет|мягч|мягк|динамич|интро|заставк|"
    r"промо|запуск|стиль|атмосфер|эпич|минимал)",
    re.IGNORECASE,
)


def is_motion_request(prompt: str, conversation: list[dict] | None = None) -> bool:
    """Запрос только про движение/атмосферу ролика (без кликов, меню, переводов).

    Ответ на уточняющий вопрос режиссёра (последняя реплика ассистента —
    вопрос) всегда идёт сценарным путём, каким бы коротким он ни был.
    """
    text = str(prompt or "")
    if conversation:
        last = conversation[-1] if isinstance(conversation[-1], dict) else {}
        if last.get("role") == "assistant" and str(last.get("content") or "").rstrip().endswith("?"):
            return False
    return bool(MOTION_RE.search(text)) and not INTERACTION_RE.search(text)


def _sections(timeline: dict) -> list[dict]:
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    out = []
    for layer in layers:
        if not isinstance(layer, dict) or layer.get("type") != "component":
            continue
        parent = layer.get("parent")
        if parent and str(layer.get("id", "")).endswith(str(parent)[4:]):
            out.append(layer)
    return out or [layer for layer in layers if isinstance(layer, dict) and layer.get("type") == "component"]


def layer_roles(timeline: dict) -> list[dict]:
    """Роли слоёв для режиссёра: секция или элемент (heading/text/image/button/card)."""
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    section_ids = {str(layer["id"]) for layer in _sections(timeline)}
    section_order: dict[str, int] = {}
    roles: list[dict] = []
    for layer in layers:
        if not isinstance(layer, dict) or layer.get("type") != "component":
            continue
        layer_id = str(layer.get("id"))
        parent = str(layer.get("parent") or "")
        if parent not in section_order:
            section_order[parent] = len(section_order)
        haystack = " ".join(str(layer.get(key) or "") for key in ("name", "ref", "id"))
        if layer_id in section_ids:
            role = "section"
        else:
            role = next((name for name, pattern in ROLE_PATTERNS if pattern.search(haystack)), "element")
        roles.append({"id": layer_id, "name": str(layer.get("name") or layer_id)[:80], "role": role,
                      "section": section_order[parent], "pageId": layer.get("pageId")})
    return roles


def _children_of(roles: list[dict], section_index: int) -> list[dict]:
    return [item for item in roles if item["section"] == section_index and item["role"] != "section"]


def _page_geometry(timeline: dict, section_count: int, page_heights: dict[str, float] | None = None) -> tuple[float, float, bool]:
    """(ширина макета, высота страницы, измерено ли) в px дизайна: высота,
    измеренная плеером редактора (``page_heights``), затем frame.height секций
    IR первой страницы сценария, иначе оценка по числу секций."""
    story = timeline.get("story") if isinstance(timeline.get("story"), dict) else {}
    pages = story.get("pages") if isinstance(story.get("pages"), list) else []
    ir = pages[0].get("ir") if pages and isinstance(pages[0], dict) else None
    design_width = 1440.0
    if isinstance(ir, dict):
        frame = ir.get("frame") if isinstance(ir.get("frame"), dict) else {}
        try:
            design_width = float(frame.get("width") or design_width) or 1440.0
        except (TypeError, ValueError):
            design_width = 1440.0
    if page_heights:
        first_id = str(story.get("initialPageId") or (pages[0].get("id") if pages and isinstance(pages[0], dict) else ""))
        measured = page_heights.get(first_id) or next(iter(page_heights.values()), None)
        if measured and float(measured) > 0:
            return design_width, float(measured), True
    if isinstance(ir, dict):
        frame = ir.get("frame") if isinstance(ir.get("frame"), dict) else {}
        try:
            design_width = float(frame.get("width") or design_width) or 1440.0
        except (TypeError, ValueError):
            design_width = 1440.0
        heights = []
        for section in ir.get("tree") or []:
            section_frame = section.get("frame") if isinstance(section, dict) and isinstance(section.get("frame"), dict) else {}
            try:
                value = float(section_frame.get("height") or 0)
            except (TypeError, ValueError):
                value = 0.0
            heights.append(value if value > 0 else DEFAULT_SECTION_HEIGHT)
        if heights and any(value != DEFAULT_SECTION_HEIGHT for value in heights):
            return design_width, sum(heights), True
    return design_width, section_count * DEFAULT_SECTION_HEIGHT, False


def _page_travel(timeline: dict, sections: list[dict], page_heights: dict[str, float] | None = None,
                 pan_ms: int = 0) -> int:
    """Пролёт камеры (px композиции), чтобы показать страницу целиком.

    С измеренной геометрией пролёт покрывает страницу: до 2.5 высот кадра или
    до ``MAX_PAN_SPEED`` за время панорамы ``pan_ms``, если оно длиннее.
    Раньше жёсткие 2.5 кадра оставляли низ длинной страницы (форму, CTA) за
    кадром. Без геометрии оценка консервативна (до 1.2 высоты кадра), чтобы
    камера не уезжала за край короткой страницы.
    """
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    height = int(composition.get("height") or 1080)
    width = int(composition.get("width") or 1920)
    design_width, page_height, measured = _page_geometry(timeline, len(sections), page_heights)
    scale = width / max(1.0, design_width)
    cap = max(height * 2.5, MAX_PAN_SPEED * pan_ms / 1000) if measured else height * 1.2
    return int(max(0, min(page_height * scale - height, cap)))


def template_steps(timeline: dict, template: str, *, prompt: str = "", page_heights: dict[str, float] | None = None) -> list[dict]:
    """Шаги шаблона в долях длительности (совместимы с планом режиссёра)."""
    if template not in TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template!r}")
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    duration = max(250, int(composition.get("duration") or 6000))
    roles = layer_roles(timeline)
    sections = [item for item in roles if item["role"] == "section"]
    section_ids = [item["id"] for item in sections]
    if not section_ids:
        return []
    steps: list[dict] = []

    def add(preset: str, layers: list[str], start_ms: int, duration_ms: int, stagger: int = 0, **extra) -> None:
        if not layers:
            return
        step = {"preset": preset, "layers": layers, "start": start_ms / duration,
                "duration": duration_ms / duration, "staggerMs": stagger}
        step.update(extra)
        steps.append(step)

    def reveal_children(section_index: int, at: int, preset_map: dict[str, str] | None = None) -> None:
        children = _children_of(roles, section_index)
        preset_map = preset_map or {}
        # Порядок появления следует документу: заголовок → текст → медиа → кнопка.
        order = {"heading": 0, "text": 1, "image": 2, "card": 3, "element": 4, "button": 5}
        ordered = sorted(children, key=lambda item: (order.get(item["role"], 4)))
        for offset, item in enumerate(ordered[:12]):
            preset = preset_map.get(item["role"], "fade-in-up")
            add(preset, [item["id"]], at + 90 * offset, 720, travel=64)

    hero = section_ids[0]
    rest = section_ids[1:]
    buttons = [item["id"] for item in roles if item["role"] == "button"][:2]
    pan_windows = {"presentation": 0.75, "feature-tour": 0.8, "cinematic-camera": 0.58}
    pan = _page_travel(timeline, sections, page_heights, int(duration * pan_windows.get(template, 0.75)))

    if template == "product-showcase":
        add("camera-push", [CAMERA_LAYER_ID], 0, duration)
        add("scale-reveal", [hero], 0, 900, travel=120)
        reveal_children(0, 260, {"image": "scale-reveal", "button": "cta-bounce"})
        add("fade-in-up", rest, int(duration * 0.32), 820, stagger=140, travel=140)
        add("zoom-spotlight", [section_ids[-1]], int(duration * 0.62), int(duration * 0.36))
        add("cta-pulse", buttons or [hero], int(duration * 0.8), 700)
    elif template == "presentation":
        add("fade-in-up", [hero], 0, 900, travel=100)
        reveal_children(0, 200)
        if rest:
            slot = int(duration * 0.7 / max(1, len(rest)))
            for index, layer_id in enumerate(rest):
                add("fade-in-up", [layer_id], int(duration * 0.25) + slot * index, 820, travel=120)
            if pan:
                add("camera-pan", [CAMERA_LAYER_ID], int(duration * 0.2), int(duration * 0.75), travel=pan)
        add("hero-focus", [section_ids[-1]], int(duration * 0.82), int(duration * 0.18))
    elif template == "feature-tour":
        add("fade-in", [hero], 0, 600)
        reveal_children(0, 120)
        if rest:
            slot = int(duration * 0.72 / len(rest))
            for index, layer_id in enumerate(rest):
                at = int(duration * 0.18) + slot * index
                add("slide-in-left" if index % 2 == 0 else "slide-in-right", [layer_id], at, 820, travel=160)
                add("hero-focus", [layer_id], at + 700, max(600, slot - 700))
            if pan:
                add("camera-pan", [CAMERA_LAYER_ID], int(duration * 0.15), int(duration * 0.8), travel=pan)
        add("cta-pulse", buttons or [section_ids[-1]], int(duration * 0.86), 600)
    elif template == "clean-reveal":
        add("fade-in-up", section_ids, 0, 800, stagger=160, travel=110)
        reveal_children(0, 220)
        add("hero-focus", [hero], int(duration * 0.55), int(duration * 0.45))
    elif template == "cinematic-camera":
        add("camera-push", [CAMERA_LAYER_ID], 0, int(duration * 0.55))
        if pan:
            add("camera-pan", [CAMERA_LAYER_ID], int(duration * 0.4), int(duration * 0.58), travel=pan)
        add("fade-in", section_ids, 0, 900, stagger=120)
        reveal_children(0, 300, {"image": "focus-pull", "heading": "rotate-in"})
        add("drift-up", [item["id"] for item in roles if item["role"] == "image"][:6], 0, duration, travel=180)
    return normalize_steps(timeline, steps)


def normalize_steps(timeline: dict, steps: list[dict]) -> list[dict]:
    """Привести план к ритму ролика: известные пресеты и слои, границы времени.

    Реве́йлы короче MIN_REVEAL_MS выглядят рывком, длиннее MAX_REVEAL_MS — вялым;
    stagger больше MAX_STAGGER_MS растягивает каскад за пределы такта. Камера
    и медленные пролёты сохраняют свою длительность.
    """
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    duration = max(250, int(composition.get("duration") or 6000))
    known = {str(layer.get("id")) for layer in (timeline.get("layers") or []) if isinstance(layer, dict)}
    known.add(CAMERA_LAYER_ID)
    slow = set(CAMERA_PRESETS) | {"zoom-spotlight", "hero-focus", "drift-up", "pan-down", "dim", "defocus", "fade-out"}
    out: list[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        preset = str(step.get("preset") or "")
        if preset not in PRESET_NAMES:
            continue
        layers = step.get("layers")
        if isinstance(layers, list):
            layers = [str(item) for item in layers if str(item) in known][:MAX_LAYERS_PER_STEP]
            if preset in CAMERA_PRESETS:
                layers = [CAMERA_LAYER_ID]
            if not layers:
                continue
        start = max(0.0, min(0.98, float(step.get("start") or 0)))
        share = float(step.get("duration") or 0.2)
        length = share * duration
        if preset not in slow:
            length = max(MIN_REVEAL_MS, min(MAX_REVEAL_MS, length))
        length = max(150, min(length, duration - start * duration))
        normalized = dict(step)
        normalized.update({
            "preset": preset, "layers": layers, "start": start, "duration": length / duration,
            "staggerMs": max(0, min(MAX_STAGGER_MS if preset not in slow else 600, int(step.get("staggerMs") or 0))),
        })
        out.append(normalized)
    # Одна панорама: шаблон (по геометрии страницы) идёт первым, лишние
    # camera-pan модели сливались с ним в ключевые кадры с возвратом камеры.
    pans = [step for step in out if step["preset"] == "camera-pan"]
    out = [step for step in out if step["preset"] != "camera-pan" or step is pans[0]]
    _sync_reveals_with_camera(timeline, out, duration)
    # При усечении камера и медленные акценты важнее лишних ревейлов: без
    # camera-pan длинная страница остаётся на первом экране.
    priority = [step for step in out if step["preset"] in CAMERA_PRESETS or step["preset"] in slow]
    rest = [step for step in out if step not in priority]
    return (priority + rest)[:MAX_STEPS]


# Longest presentation the director may stretch a clip to for a long page.
MAX_PRESENTATION_MS = 20_000


def extend_for_long_page(timeline: dict, steps: list[dict],
                         page_heights: dict[str, float] | None = None) -> tuple[dict, list[dict]]:
    """Lengthen the clip so a camera pan can show a long page to its end.

    An 8 s presentation of a 6000 px page capped the pan by speed and never
    reached the bottom (the contact form the prompt asked to finish on). When
    the plan pans over a measured page that needs more time at
    ``MAX_PAN_SPEED``, the composition (and every full-length layer) grows up to
    ``MAX_PRESENTATION_MS``; steps are fractions, so the plan scales with it.
    Returns the timeline to plan on and the operations that lengthen it (they
    precede the plan in the same reversible change-set). Mutates ``steps``.
    """
    import copy
    import math

    pan = next((step for step in steps if step.get("preset") == "camera-pan"), None)
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    duration = max(250, int(composition.get("duration") or 6000))
    if pan is None:
        return timeline, []
    sections = [item for item in layer_roles(timeline) if item["role"] == "section"]
    design_width, page_height, measured = _page_geometry(timeline, len(sections), page_heights)
    if not measured:
        return timeline, []
    frame_h = int(composition.get("height") or 1080)
    full = int(page_height * int(composition.get("width") or 1920) / max(1.0, design_width) - frame_h)
    if full <= int(pan.get("travel") or 0) + 1:
        return timeline, []
    share = max(0.1, float(pan.get("duration") or 0.75))
    needed = math.ceil(full / MAX_PAN_SPEED * 1000 / share / 500) * 500
    new_duration = min(MAX_PRESENTATION_MS, needed)
    if new_duration <= duration:
        return timeline, []
    working = copy.deepcopy(timeline)
    working["composition"]["duration"] = new_duration
    operations: list[dict] = [{"kind": "set-composition", "target": "composition", "path": "/duration", "value": new_duration}]
    for layer in working.get("layers") or []:
        if isinstance(layer, dict) and int(layer.get("out") or 0) >= duration:
            layer["out"] = new_duration
            operations.append({"kind": "set-layer-property", "target": str(layer.get("id")), "path": "/out",
                               "value": new_duration})
    pan["travel"] = int(min(full, MAX_PAN_SPEED * share * new_duration / 1000))
    _sync_reveals_with_camera(working, steps, new_duration)
    return working, operations


def _bezier_progress(points: tuple, progress: float) -> float:
    """y(x) кривой cubic-bezier(x1, y1, x2, y2) для x = progress (бисекция)."""
    x1, y1, x2, y2 = points
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        x = 3 * (1 - mid) ** 2 * mid * x1 + 3 * (1 - mid) * mid ** 2 * x2 + mid ** 3
        lo, hi = (mid, hi) if x < progress else (lo, mid)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3


def _sync_reveals_with_camera(timeline: dict, steps: list[dict], duration: int) -> None:
    """Секция раскрывается до того, как камера приводит её в кадр.

    Появления секций шли равномерно по ролику, а панорама — по кинематографической
    кривой с быстрым стартом: камера обгоняла ревейлы и снимала ещё прозрачные
    секции (белые кадры в середине видео). Здесь старт появления каждой секции
    сдвигается не позже момента, когда её верх (оценка по порядку секций)
    входит в кадр; секции первого экрана раскрываются сразу, каскадом.
    Мутирует ``steps``.
    """
    pan = next((step for step in steps if step["preset"] == "camera-pan"), None)
    if pan is None:
        return
    sections = [item["id"] for item in layer_roles(timeline) if item["role"] == "section"]
    if len(sections) < 2:
        return
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    frame_h = float(composition.get("height") or 1080)
    travel = float(pan.get("travel") or 240)
    pan_start = float(pan["start"]) * duration
    pan_len = max(1.0, float(pan["duration"]) * duration)
    curve = pan.get("curve") if pan.get("curve") in NAMED_CURVES else "cinematic"
    points = NAMED_CURVES[curve]
    page_h = travel + frame_h
    index_of = {layer_id: index for index, layer_id in enumerate(sections)}

    def enters_at(top: float) -> float:
        """Момент (мс), когда y=top показывается на 15% высоты кадра снизу."""
        needed = top + frame_h * 0.15 - frame_h
        if needed <= 0:
            return 0.0
        if needed >= travel:
            return pan_start + pan_len
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _bezier_progress(points, mid) * travel < needed else (lo, mid)
        return pan_start + hi * pan_len

    for step in steps:
        if step["preset"] not in ENTRANCE_PRESETS or not isinstance(step.get("layers"), list):
            continue
        indexes = [index_of[layer_id] for layer_id in step["layers"] if layer_id in index_of]
        if not indexes:
            continue
        first = min(indexes)
        top = first / len(sections) * page_h
        reveal = float(step["duration"]) * duration
        if top <= frame_h * 0.6:
            latest = 120.0 * first
        else:
            latest = max(0.0, enters_at(top) - reveal * 0.6)
        if float(step["start"]) * duration > latest:
            step["start"] = max(0.0, latest / duration)


def step_operations(timeline: dict, step: dict, resolve_layers) -> list[dict]:
    """Операции одного шага плана; ``resolve_layers`` разбирает строковые маркеры."""
    preset = str(step.get("preset") or "")
    if preset not in PRESET_NAMES:
        raise ValueError(f"unknown preset in plan: {preset!r}")
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    duration = max(250, int(composition.get("duration") or 6000))
    raw_layers = step.get("layers")
    if preset in CAMERA_PRESETS:
        layer_ids = [CAMERA_LAYER_ID]
    elif isinstance(raw_layers, list):
        known = {str(layer.get("id")) for layer in (timeline.get("layers") or []) if isinstance(layer, dict)}
        layer_ids = [str(item) for item in raw_layers if str(item) in known]
    else:
        layer_ids = resolve_layers(timeline, str(raw_layers or "*"))
    if not layer_ids:
        raise ValueError("plan references no layers")
    layer_ids = layer_ids[:MAX_LAYERS_PER_STEP]
    start = max(0.0, min(1.0, float(step.get("start") or 0)))
    share = max(0.02, min(1.0, float(step.get("duration") or 0.2)))
    params = {
        "start": int(start * duration),
        "duration": max(150, int(share * duration)),
        "staggerMs": max(0, min(2000, int(step.get("staggerMs") or 0))),
    }
    if step.get("travel") is not None:
        # камера проходит длинную страницу целиком; остальные сдвиги — локальные
        params["travel"] = max(8, min(12000 if preset in CAMERA_PRESETS else 4000, int(step["travel"])))
    if step.get("curve"):
        params["curve"] = str(step["curve"])
    return preset_operations(preset, layer_ids, params)


def plan_operations(timeline: dict, steps: list[dict], resolve_layers) -> list[dict]:
    """План → слитые операции (+ слой камеры, если план её использует)."""
    operations: list[dict] = []
    for step in steps:
        operations.extend(step_operations(timeline, step, resolve_layers))
    if any(op.get("target") == CAMERA_LAYER_ID for op in operations):
        operations = ensure_camera_operations(timeline) + operations
    return merge_keyframe_operations(timeline, operations)


def describe_vocabulary() -> str:
    """Словарь для системного промпта режиссёра."""
    return (
        "Presets (what they do): fade-in (opacity), fade-in-up (rise + opacity, expo-out), slide-in-left/right, "
        "zoom-in (0.92→1), scale-reveal (0.88→1 with soft overshoot), focus-pull (blur 14px→sharp + opacity, for hero media), "
        "rotate-in (subtle tilt settle), defocus (blur 0→6px on secondary blocks), wipe-reveal (mask opens from the bottom), wipe-out, "
        "zoom-spotlight (slow 1→1.12 push on one block), hero-focus (gentle 1→1.04), dim (opacity→0.35 for non-focus blocks), "
        "fade-out, pan-down (block drifts up), drift-up (slow parallax float for images), cta-pulse, cta-bounce; "
        "camera-push (whole frame 1→1.08), camera-pull, camera-pan (frame travels down the page; travel px), camera-drift. "
        "Templates: " + ", ".join(TEMPLATE_NAMES) + "."
    )
