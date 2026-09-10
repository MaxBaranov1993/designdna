"""Deterministic migration between Design IR schema versions."""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

from colorutils import contrast_ratio, mix_hex_colors
from typography import font_stack

from .hash import content_hash
from .schema import CURRENT_SCHEMA_VERSION
from .source_key import deduplicate_source_keys
from .responsive import ensure_fluid_layout


# Project loads must be a pure function of the stored JSON.  A wall-clock
# timestamp here made two reads of the same persisted revision produce
# different bytes, which correctly tripped the desktop live-session CAS guard
# after a renderer reload.  Standalone generation still uses the real clock;
# only project-payload migration supplies this stable "unknown legacy time".
_PROJECT_MIGRATION_TIME = "1970-01-01T00:00:00+00:00"

_GENERATED_META_KEYS = {
    "name", "description", "qaWarnings", "fontFaces", "activeViewport", "styleTags", "mixOf",
    "designSystemErrors", "designSystemWarnings", "designSystemRef", "compiledContextHash",
    "archetypeId", "identityScore", "identityReport", "strictRecovery", "requestedComponentKey",
    "sourceTokenLock", "sourceTokenNodeId", "exactServiceCardEmbedded", "direction",
    "strictRecoveryReason", "contentRewrite",
}
_GENERATED_DENSITY_ALIASES = {
    "balanced": "normal", "dense": "tight", "compact": "tight",
    "spacious": "airy", "loose": "airy", "relaxed": "airy",
}
_GENERATED_SIZE_ALIASES = {
    "h1": "display", "h2": "xl", "h3": "lg", "h4": "md",
    "body": "md", "caption": "sm", "small": "sm", "large": "lg",
    # роли типографики tokens v2, которые модель тянет в size элементов
    "lead": "lg", "eyebrow": "xs", "hero": "display",
}
# tone кнопок/бейджей: модель отвечает именами цветовых ролей
_GENERATED_TONE_ALIASES = {
    "secondary": "muted", "ghost": "muted", "neutral": "default", "brand": "primary",
    "warning": "accent", "danger": "accent", "info": "muted", "outline": "default",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- tokens v2 --
#
# v1 tokens carry eight flat colors, two font faces and three scalars.  v2 adds
# the roles the renderer and the generator actually need (background family,
# ink family, accents; a typographic scale by role; space/radius/shadow ladders
# and one reveal animation).  The derivation below is a pure function of the v1
# block so a stored project migrates to identical bytes on every load — the
# live-session CAS guard compares those bytes.
#
# The mapping is chosen so a migrated document keeps its appearance: v2 `accent`
# is v1 `primary` (the color the renderer paints buttons with), `bg`/`ink`/`line`
# are the v1 background/text/border, and only genuinely new roles (bg2,
# surface2, ink2) are interpolated.

_V1_COLOR_FALLBACK = {
    "primary": "#5b5bd6", "background": "#ffffff", "surface": "#f5f5f7",
    "text": "#1a1a1a", "textMuted": "#666666", "border": "#e0e0e0",
}
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

_TYPE_BASE = {"compact": 15.0, "default": 16.0, "spacious": 17.0}
_TYPE_RATIO = {"compact": 1.35, "default": 1.45, "spacious": 1.5}
# Steps of the modular scale; sizes are base * ratio ** step.
_ROLE_STEPS = {"display": 4.0, "h1": 3.0, "h2": 2.0, "h3": 1.0, "lead": 0.5,
               "body": 0.0, "small": -1.0, "eyebrow": -1.5}
_ROLE_LINE_HEIGHT = {"display": 1.02, "h1": 1.08, "h2": 1.14, "h3": 1.25,
                     "lead": 1.5, "body": 1.6, "small": 1.5, "eyebrow": 1.2}
_ROLE_TRACKING = {"display": -0.03, "h1": -0.025, "h2": -0.02, "h3": -0.01,
                  "lead": -0.005, "body": 0.0, "small": 0.0, "eyebrow": 0.12}
_DISPLAY_ROLES = ("display", "h1", "h2", "h3")

_SPACE_SCALE = [4, 8, 12, 16, 24, 32, 40, 48, 64, 80, 96, 128, 160]
_RADIUS_BASE = {"none": 0.0, "sm": 4.0, "md": 8.0, "lg": 14.0, "xl": 22.0, "full": 28.0}
_SHADOW_LADDER = {"sm": "0 1px 3px rgba(0,0,0,0.12)",
                  "md": "0 6px 20px rgba(0,0,0,0.16)",
                  "lg": "0 18px 50px rgba(0,0,0,0.24)"}
_SHADOW_NONE = {"sm": "none", "md": "none", "lg": "none"}
_MOTION = {"name": "fade-up", "durationMs": 420, "easing": "cubic-bezier(0.22, 1, 0.36, 1)"}


def _hex(value: object, fallback: str) -> str:
    """Normalize an untrusted v1 color to lowercase #rrggbb."""
    if isinstance(value, str):
        candidate = value.strip()
        if _HEX_RE.match(candidate):
            body = candidate[1:].lower()
            if len(body) == 3:
                body = "".join(char * 2 for char in body)
            return "#" + body
    return fallback


def _mix(first: str, second: str, weight: float) -> str:
    """`weight` of `first` mixed with the rest of `second`, in OKLCH."""
    return mix_hex_colors([(first, weight), (second, 1.0 - weight)])


def _weight(face: object, fallback: int) -> int:
    raw = face.get("weight") if isinstance(face, dict) else None
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return fallback
    return max(100, min(900, value))


def _family(face: object, fallback: str) -> str:
    if isinstance(face, dict):
        name = face.get("family")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return fallback


def derive_tokens_v2(tokens: dict) -> dict | None:
    """Deterministically derive `tokens.v2` from a v1 token block.

    Returns ``None`` when the input has no v1 color/font block to derive from
    (empty legacy fixtures), so migration stays a no-op instead of inventing a
    palette the document never had.
    """
    if not isinstance(tokens, dict):
        return None
    color = tokens.get("color")
    font = tokens.get("font")
    if not isinstance(color, dict) or not isinstance(font, dict):
        return None

    def v1(key: str) -> str:
        return _hex(color.get(key), _V1_COLOR_FALLBACK[key])

    bg = v1("background")
    line = v1("border")
    surface = _hex(color.get("surface"), _V1_COLOR_FALLBACK["surface"])
    # `surface == background` is a common extraction defect: the page then has
    # no elevation at all.  Nudge the surface toward the border instead of
    # emitting two identical roles.
    if surface == bg:
        surface = _mix(bg, line, 0.93)
    ink = v1("text")
    ink_muted = v1("textMuted")
    accent = v1("primary")
    secondary = color.get("secondary")
    accent2 = _hex(secondary, accent) if isinstance(secondary, str) else accent
    accent_ink = ("#ffffff" if contrast_ratio("#ffffff", accent) >= contrast_ratio("#111111", accent)
                  else "#111111")

    scale = font.get("scale") if isinstance(font.get("scale"), str) else "default"
    base = _TYPE_BASE.get(scale, _TYPE_BASE["default"])
    ratio = _TYPE_RATIO.get(scale, _TYPE_RATIO["default"])
    display_family = _family(font.get("display"), "Inter")
    body_family = _family(font.get("body"), "Inter")
    display_weight = _weight(font.get("display"), 700)
    body_weight = _weight(font.get("body"), 400)

    roles = {}
    for role, step in _ROLE_STEPS.items():
        size = max(11.0, min(160.0, round(base * (ratio ** step))))
        if role in _DISPLAY_ROLES:
            weight = display_weight
        elif role == "eyebrow":
            weight = max(600, body_weight)
        else:
            weight = body_weight
        roles[role] = {"size": size, "lineHeight": _ROLE_LINE_HEIGHT[role],
                       "tracking": _ROLE_TRACKING[role], "weight": weight}

    radius_base = _RADIUS_BASE.get(
        tokens.get("radius", {}).get("card") if isinstance(tokens.get("radius"), dict) else None,
        _RADIUS_BASE["md"],
    )
    shadow = _SHADOW_NONE if tokens.get("shadow") == "none" else dict(_SHADOW_LADDER)

    return {
        "color": {
            "bg": bg,
            "bg2": _mix(bg, surface, 0.5),
            "surface": surface,
            "surface2": _mix(surface, line, 0.7),
            "ink": ink,
            "ink2": _mix(ink, ink_muted, 0.6),
            "inkMuted": ink_muted,
            "line": line,
            "accent": accent,
            "accentInk": accent_ink,
            "accent2": accent2,
        },
        "type": {
            "families": {
                "display": {"family": display_family, "stack": font_stack(display_family),
                            "weight": display_weight},
                "body": {"family": body_family, "stack": font_stack(body_family),
                         "weight": body_weight},
            },
            "base": base,
            "ratio": ratio,
            "roles": roles,
        },
        "space": list(_SPACE_SCALE),
        "radius": {
            "sm": round(radius_base * 0.5),
            "md": radius_base,
            "lg": round(radius_base * 1.75),
            "pill": 999,
        },
        "shadow": shadow,
        "motion": dict(_MOTION),
    }


def ensure_tokens_v2(ir: dict) -> None:
    """Attach `tokens.v2` in place when the document only carries v1 tokens."""
    tokens = ir.get("tokens")
    if not isinstance(tokens, dict) or isinstance(tokens.get("v2"), dict):
        return
    derived = derive_tokens_v2(tokens)
    if derived is not None:
        tokens["v2"] = derived


GENERATED_ARTBOARD_WIDTH = 1440


def _unwrap_generated_document(ir: dict) -> dict:
    """Модель иногда заворачивает документ: {"designIR": {...}} / {"ir": {...}}.
    Если корень без ``tree``, а ровно одно значение — словарь с ``tree``, берём его."""
    if "tree" in ir:
        return ir
    candidates = [value for value in ir.values() if isinstance(value, dict) and "tree" in value]
    if len(candidates) == 1:
        return candidates[0]
    return ir


def sanitize_generated_ir(ir: dict) -> dict:
    """Repair common provider-only aliases without weakening Design IR validation.

    Provider responses frequently add descriptive metadata that is not part of
    the interchange contract, or use HTML typography names for the closed
    ``size`` enum.  Normalize only those known cases; every other schema error
    remains visible to the caller.
    """
    if not isinstance(ir, dict):
        raise ValueError("IR must be a dict")
    out = copy.deepcopy(_unwrap_generated_document(ir))
    meta = out.get("meta")
    if isinstance(meta, dict):
        out["meta"] = {key: value for key, value in meta.items() if key in _GENERATED_META_KEYS}

    def strip_invented_src(media: object) -> None:
        """Модель не умеет давать реальные картинки: выдуманный http/относительный
        src ломается битой ссылкой в превью. Оставляем заглушку (imagePrompt),
        которую пользователь заменяет своим файлом в редакторе. Встроенные
        data:-URL и внутренние ddna:// сохраняем."""
        if not isinstance(media, dict):
            return
        src = media.get("src")
        if not isinstance(src, str):
            return
        if src.startswith(("data:", "ddna://")):
            return
        media.pop("src", None)
        if not media.get("imagePrompt"):
            media["imagePrompt"] = str(media.get("alt") or "изображение")

    def normalize_node(node: object) -> None:
        if not isinstance(node, dict):
            return
        raw_size = node.get("size")
        if isinstance(raw_size, str) and raw_size in _GENERATED_SIZE_ALIASES:
            node["size"] = _GENERATED_SIZE_ALIASES[raw_size]
        raw_tone = node.get("tone")
        if isinstance(raw_tone, str) and raw_tone in _GENERATED_TONE_ALIASES:
            node["tone"] = _GENERATED_TONE_ALIASES[raw_tone]
        if node.get("type") == "image":
            strip_invented_src(node)
        props = node.get("props")
        if isinstance(props, dict):
            strip_invented_src(props.get("media"))
            # Арт-направление описывает ритм словами airy/balanced/dense (design-brief),
            # а плотность секции в IR — tight/normal/airy: модель переносит слова
            # брифа в props.density, и схема отклоняла весь вариант.
            density = props.get("density")
            if isinstance(density, str) and density in _GENERATED_DENSITY_ALIASES:
                props["density"] = _GENERATED_DENSITY_ALIASES[density]
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                normalize_node(child)

    tree = out.get("tree")
    if isinstance(tree, list):
        for section in tree:
            normalize_node(section)
            _normalize_composition_frame(section)
            _drop_duplicate_section_heading(section)
            _normalize_generated_layout(section)

    # Артборд. Промпты (DESIGN.md) просят компоновать под 1440px, а рендер без
    # корневого frame берёт холст 960px и масштабирует его 1.5×: контейнер
    # «wide» превращается в 896px, ряды hero (650px колонка + кнопка) не
    # помещаются и складываются в столбик. Судья снимал за это на каждой странице.
    frame = out.get("frame")
    if not isinstance(frame, dict):
        frame = {}
    if not _is_number(frame.get("width")):
        frame = dict(frame, width=GENERATED_ARTBOARD_WIDTH)
    out["frame"] = frame
    return out


_COMPOSITION_RAIL_KEYS = ("contentMaxWidth", "contentGutter")
_COMPOSITION_LAYOUT_KEYS = ("direction", "gap", "justify", "align", "wrap")


def _normalize_composition_frame(section: object) -> None:
    """Frame секции-композиции — только рельс контента или свободный холст.

    Модель иногда пишет auto-layout прямо на секции (direction/gap/align/
    padding/width). Рендерер применяет frame секции к обёртке ВОКРУГ <section>:
    между секциями появляются поля цвета страницы, а дети остаются без колонки
    и зазора и наезжают друг на друга. Раскладка переезжает в дочерний frame,
    как того требует BLOCKS.md; padding секции задаёт props.density.
    """
    if not isinstance(section, dict) or section.get("type") != "composition":
        return
    frame = section.get("frame")
    if not isinstance(frame, dict) or frame.get("layout") == "free":
        return
    stray = {key: value for key, value in frame.items() if key not in _COMPOSITION_RAIL_KEYS}
    if not stray:
        return
    rail = {key: frame[key] for key in _COMPOSITION_RAIL_KEYS if key in frame}
    if rail:
        section["frame"] = rail
    else:
        section.pop("frame", None)
    children = section.get("children")
    layout = {key: stray[key] for key in _COMPOSITION_LAYOUT_KEYS if key in stray}
    if not isinstance(children, list) or not children or not (layout or stray.get("layout") == "auto"):
        return
    wrapper_frame = {"layout": "auto", "direction": str(stray.get("direction") or "column"), **layout, "width": "fill"}
    section["children"] = [{"type": "frame", "frame": wrapper_frame, "children": children}]


GENERATED_FLUID_WIDTH = 360     # шире — не помещается в мобильный вьюпорт 390px
GENERATED_SHORT_LABEL = 16      # короткий текст в ряду не должен сжиматься до нуля


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _is_master_instance(node: dict) -> bool:
    source_meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
    return isinstance(source_meta.get("componentRef"), dict)


def _drop_duplicate_section_heading(section: object) -> None:
    """props.heading/subheading композиции, повторённые дочерним заголовком/текстом,
    рендерились дважды (слева белым и ещё раз в дереве). Дерево модели важнее."""
    if not isinstance(section, dict) or section.get("type") != "composition":
        return
    props = section.get("props")
    if not isinstance(props, dict):
        return
    texts: set[str] = set()

    def collect(node: object, depth: int = 0) -> None:
        if depth > 6 or not isinstance(node, dict):
            return
        if node.get("type") in ("heading", "text"):
            normalized = _normalized_text(node.get("text"))
            if normalized:
                texts.add(normalized)
        for child in node.get("children") or []:
            collect(child, depth + 1)

    for child in section.get("children") or []:
        collect(child)
    for key in ("heading", "subheading"):
        value = props.get(key)
        if isinstance(value, str) and _normalized_text(value) and _normalized_text(value) in texts:
            props.pop(key, None)


def _normalize_generated_layout(section: object) -> None:
    """Раскладочные привычки модели, ломавшие адаптив и ряды (по вердиктам судьи):

    - фиксированная ширина > 360px у контейнера/поля/кнопки в колонке вылезает
      за мобильный экран — становится width:"fill" с maxWidth (в ряду фиксированная
      ширина делит место между соседями, её не трогаем);
    - в ряду с полем ввода (inline-форма) короткий текст без ширины рендерер
      сжимал до нуля («https://» → «h»), а кнопка с width:"fill" переносила
      текст на две строки — такие лейблы и кнопки получают hug.
    Точные копии мастеров (sourceMeta.componentRef), free-раскладки и эталоны
    из app/exemplars не меняются.
    """

    def visit(node: object, parent_frame: dict | None, parent_children: list, depth: int = 0) -> None:
        if depth > 14 or not isinstance(node, dict) or _is_master_instance(node):
            return
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else None
        kind = str(node.get("type") or "")
        parent_layout = str((parent_frame or {}).get("layout") or "auto")
        parent_free = parent_layout == "free"
        parent_row = parent_layout == "auto" and (parent_frame or {}).get("direction") == "row"
        # Ряд с полем ввода — inline-форма: её лейблы и кнопка не должны сжиматься.
        inline_form_row = parent_row and any(
            isinstance(sibling, dict) and sibling.get("type") == "input" for sibling in parent_children)
        # Фиксированная ширина в колонке (а не в ряду, где она делит ширину между
        # соседями) — это «форма 640px», которая вылезает за экран 390px.
        if not parent_free and not parent_row and frame is not None:
            width = frame.get("width")
            if (kind in ("frame", "card", "input", "button", "image") and _is_number(width)
                    and width > GENERATED_FLUID_WIDTH and not (frame.get("absolute") or _is_number(frame.get("x")))):
                frame["width"] = "fill"
                frame.setdefault("maxWidth", width)
        if inline_form_row and kind in ("text", "heading"):
            text = _normalized_text(node.get("text"))
            if text and len(text) <= GENERATED_SHORT_LABEL and (frame is None or frame.get("width") in (None, "fill")):
                node["frame"] = {**(frame or {}), "width": "hug"}
        if inline_form_row and kind == "button" and (frame is None or frame.get("width") in (None, "fill")):
            node["frame"] = {**(frame or {}), "width": "hug"}
        child_frame = node.get("frame") if isinstance(node.get("frame"), dict) else None
        children = [child for child in (node.get("children") or []) if isinstance(child, dict)]
        # Ряд inline-формы должен переноситься на узком экране: иначе кнопка
        # и префикс сжимаются до нечитаемости на 390px.
        if (child_frame is not None and child_frame.get("layout") == "auto" and child_frame.get("direction") == "row"
                and any(child.get("type") == "input" for child in children) and "wrap" not in child_frame):
            child_frame["wrap"] = True
        for child in children:
            visit(child, child_frame, children, depth + 1)

    if isinstance(section, dict) and section.get("type") == "composition":
        section_frame = section.get("frame") if isinstance(section.get("frame"), dict) else None
        children = [child for child in (section.get("children") or []) if isinstance(child, dict)]
        for child in children:
            visit(child, section_frame, children)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def migrate_ir(ir: dict, source: str | None = None, *, recorded_at: str | None = None) -> dict:
    """Return a migrated copy of `ir` to the current schema version.

    - If the document already reports the current version, it is still
      canonicalized (contentHash, sourceKey deduplication and conservative
      responsive fallbacks for generated card rows).
    - If the document is missing `version` or reports `1.0`, it is upgraded
      to 1.1 and provenance is recorded.
    - The original dict is never mutated.
    - Optional responsive text/src values are preserved verbatim. Older
      captures without them retain shared content; lost line text cannot be
      inferred during migration and requires a fresh capture.
    - Measured fontSmoothing is optional and preserved in styles; migration
      never assumes a smoothing mode for old captures.
    """
    if not isinstance(ir, dict):
        raise ValueError("IR must be a dict")

    out = copy.deepcopy(ir)
    migration_time = recorded_at or _now()
    original_version = str(out.get("version", "1.0"))
    is_legacy = original_version != CURRENT_SCHEMA_VERSION

    # Ensure version is set to current.
    out["version"] = CURRENT_SCHEMA_VERSION

    # Initialize provenance if missing.
    provenance = out.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        out["provenance"] = provenance
    if is_legacy:
        provenance["migratedFrom"] = original_version
        provenance["migratedAt"] = migration_time
    if source:
        provenance["importedFrom"] = source
    if not provenance.get("createdAt"):
        provenance["createdAt"] = migration_time

    # Ensure a stable element identity graph.
    out = deduplicate_source_keys(out)
    out = ensure_fluid_layout(out)
    ensure_tokens_v2(out)

    # Recompute content hash excluding preview/runtime fields.
    out["contentHash"] = content_hash(out)

    return out


def ensure_current(ir: dict | None, source: str | None = None) -> dict | None:
    """Convenience helper: migrate only if the input is a non-empty dict."""
    if not isinstance(ir, dict) or not ir:
        return ir
    return migrate_ir(ir, source=source)


def migrate_project_payload(payload: dict) -> dict:
    """Migrate editable project IR without traversing Source/DS snapshots.

    Pinned masters and captured Source IR are owned by their ingress pipelines.
    Adding project-load provenance or tokens there invalidates master hashes
    and Source fingerprints even when the user has made no changes.
    """
    payload = copy.deepcopy(payload)

    def _migrate_value(value, slot=""):
        if isinstance(value, dict):
            # Treat entire node/snapshot boundaries as opaque, including all
            # variants, rollback history and nested sourceArtifact evidence.
            if (value.get("type") in ("sourceimport", "designsystem")
                    or str(value.get("schemaVersion") or "").startswith(("design-system/", "source-pack/"))
                    or slot in ("masterIr", "templateIr", "sourceArtifact", "sourcePack", "polish", "blocks")):
                return value
            if value.get("version") in ("1.0", "1.1") and "tree" in value and "tokens" in value:
                if slot not in ("ir", "variants", "channels"):
                    return value
                # A current captured IR may also be exposed as a channel or
                # derived page input outside its Source node. Preserve it too.
                roots = value.get("tree")
                if (value.get("version") == CURRENT_SCHEMA_VERSION and isinstance(roots, list)
                        and any(isinstance(root, dict) and root.get("type") == "source-block" for root in roots)):
                    return value
                provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
                # Prefer the document's own stable creation time.  Legacy IR
                # without one receives a deterministic sentinel instead of
                # the wall clock, keeping repeated loads byte-identical.
                recorded_at = provenance.get("createdAt") or _PROJECT_MIGRATION_TIME
                return migrate_ir(value, source="project-load", recorded_at=str(recorded_at))
            return {k: _migrate_value(v, k if slot != "channels" else "channels") for k, v in value.items()}
        if isinstance(value, list):
            return [_migrate_value(v, slot) for v in value]
        return value

    return _migrate_value(payload)
