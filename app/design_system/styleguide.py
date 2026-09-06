"""Живой UI kit одним самодостаточным HTML-файлом.

Страница не пишется руками по впечатлению от сайта — она СОБИРАЕТСЯ из
измеренной дизайн-системы. Читатель у неё двойной: дизайнер/разработчик,
который встраивает новые компоненты в существующий сайт, и AI-генератор,
которому она служит справочником. Поэтому страница отвечает на вопрос «как
сделать в этом стиле», а не «насколько точно мы скопировали»:

1. Стиль сайта — описание и дизайн-язык;
2. Токены — измеренные основы;
3. Компоненты — все мастера как готовые к использованию блоки;
4. Правила — do/don't;
5. Код — CSS-переменные, Tailwind, Figma-токены.

Доказательство точности (кроп источника рядом с рендером, таблицы fidelity,
бейджи «нужна проверка», пулы ревью) — инструмент верификации, а не документ
для встраивания: по умолчанию его на странице нет. `include_fidelity=True`
возвращает компактную сноску с процентами, `proof_crop` остаётся публичным для
панели ревью мастеров.

Файл открывается двойным кликом: шрифты, картинки и движок рендера встроены,
наружу страница не ходит ни одним запросом.

Честность важнее полноты: состояния компонентов в документе — заглушки без
визуальных данных, поэтому страница их перечисляет с пометкой «не наблюдалось»,
а не рисует выдуманный hover.
"""
from __future__ import annotations

import base64
import copy
import html
import json
import os
import re
from pathlib import Path
from typing import Any

from . import document as dsdoc

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parents[2])
ENGINE_JS = ROOT / "app" / "static" / "flow" / "engine.js"

# Прозрачный 1×1 PNG — заменяет ассет, который не удалось встроить. Пропажа
# должна быть видимой (карточка получает пометку), а не молчаливой.
BLANK_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

# Бюджеты в байтах: страница обязана оставаться открываемой.
FONT_BUDGET = 12_000_000
PROOF_BUDGET = 16_000_000
DEFAULT_MAX_BYTES = 48_000_000

# Те же правила, что у рендерера (renderer.ts:935-947) и harness
# (fidelity_harness.py:262-268). Три копии — осознанный компромисс: они живут
# в TS и двух Python-модулях, менять нужно все три сразу.
_FAMILY_RE = re.compile(r"[A-Za-z0-9 ._-]{1,80}")
_WEIGHT_RE = re.compile(r"(?:[1-9]00(?: [1-9]00)?|normal|bold)")
_UNICODE_RE = re.compile(r"[Uu+0-9A-Fa-f? ,\-]{1,2048}")
_FONT_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _fonts_dir() -> Path:
    """Путь читается в момент вызова: модульные константы scraper/harness
    снимают DESIGNDNA_DATA_DIR на импорте и в тестах с tmpdir дают чужой путь."""
    return Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data") / "fonts"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# ---------- сбор данных ----------

def all_masters(document: dict) -> list[tuple[str, dict, dict | None]]:
    """(componentKey, component, variant|None) для каждого мастера документа.

    Вариант с собственным masterIr — отдельный мастер; вариант с
    masterRef == "self" рендерится мастером компонента.
    """
    out: list[tuple[str, dict, dict | None]] = []
    for pool in ("components", "reviewComponents"):
        for key, component in (document.get(pool) or {}).items():
            if not isinstance(component, dict):
                continue
            out.append((str(key), component, None))
            for variant in (component.get("variants") or {}).values():
                if isinstance(variant, dict) and isinstance(variant.get("masterIr"), dict):
                    out.append((str(key), component, variant))
    return out


def collect_font_faces(document: dict) -> list[dict]:
    """Все @font-face со всех мастеров, дедуплицированные.

    Рендерер берёт шрифты только из ir.meta.fontFaces и перезаписывает
    общий на документ <style> при каждом вызове — поэтому собираем их
    заранее и один раз.
    """
    seen: set[tuple] = set()
    faces: list[dict] = []
    for _key, component, variant in all_masters(document):
        source = variant if variant is not None else component
        master = source.get("masterIr") if isinstance(source.get("masterIr"), dict) else {}
        meta = master.get("meta") if isinstance(master.get("meta"), dict) else {}
        for face in meta.get("fontFaces") or []:
            if not isinstance(face, dict):
                continue
            signature = (str(face.get("family") or ""), str(face.get("weight") or ""),
                         str(face.get("style") or ""), str(face.get("unicodeRange") or ""),
                         str(face.get("url") or ""))
            if signature in seen:
                continue
            seen.add(signature)
            faces.append(dict(face))
    return faces


def inline_font_css(faces: list[dict], *, budget: int = FONT_BUDGET) -> tuple[str, list[dict], list[str]]:
    """@font-face со встроенными data:-URL + спецификации для предзагрузки."""
    fonts_dir = _fonts_dir()
    rules: list[str] = []
    specs: list[dict] = []
    warnings: list[str] = []
    used = 0
    for face in faces:
        family = str(face.get("family") or "")
        weight = str(face.get("weight") or "")
        style = str(face.get("style") or "")
        url = str(face.get("url") or "")
        unicode_range = str(face.get("unicodeRange") or "")
        if not _FAMILY_RE.fullmatch(family) or not _WEIGHT_RE.fullmatch(weight):
            continue
        if style not in ("normal", "italic", "oblique") or not url.startswith("/fonts/"):
            continue
        if unicode_range and not _UNICODE_RE.fullmatch(unicode_range):
            continue
        filename = url.rsplit("/", 1)[-1]
        if not _FONT_FILE_RE.fullmatch(filename):
            continue
        path = fonts_dir / filename
        if not path.is_file():
            warnings.append(f"шрифт {family} {weight}: файл {filename} не найден")
            continue
        payload = path.read_bytes()
        if used + len(payload) > budget:
            warnings.append(f"шрифт {family} {weight} пропущен: превышен бюджет шрифтов")
            continue
        used += len(payload)
        suffix = path.suffix.lower()
        mime = "font/woff2" if suffix == ".woff2" else "font/woff" if suffix == ".woff" else "font/ttf"
        fmt = "woff2" if suffix == ".woff2" else "woff" if suffix == ".woff" else "truetype"
        encoded = base64.b64encode(payload).decode("ascii")
        unicode_rule = f"unicode-range:{unicode_range};" if unicode_range else ""
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
            f"{unicode_rule}src:url('data:{mime};base64,{encoded}') format('{fmt}');"
            "font-display:block;}")
        specs.append({"family": family, "weight": weight.split()[0]})
    return "\n".join(rules), specs, warnings


def _strip_font_faces(ir: dict) -> dict:
    """Убрать meta.fontFaces из встраиваемого IR.

    Рендерер перезаписывает общий #ir-fontfaces при каждом вызове — с пустым
    списком это становится no-op по построению, и наши встроенные шрифты
    переживают рендер любого числа компонентов. Предзагрузку берёт на себя
    bootstrap страницы.
    """
    meta = ir.get("meta")
    if isinstance(meta, dict):
        meta.pop("fontFaces", None)
    return ir


def _inline_ir_assets(ir: dict) -> tuple[dict, list[str]]:
    """Развернуть ddna://blobs и обезвредить всё, что осталось не data:."""
    import scraper

    warnings: list[str] = []
    try:
        resolved, errors = scraper.resolve_ir_blobs(ir)
        warnings.extend(str(item) for item in errors or [])
    except Exception as exc:  # blob-хранилище недоступно — страница всё равно нужна
        resolved, _ = copy.deepcopy(ir), None
        warnings.append(f"blob-ссылки не развёрнуты: {exc}")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("src", "preview", "sourcePreview"):
                value = node.get(key)
                if isinstance(value, str) and value and not value.startswith("data:"):
                    node[key] = BLANK_PNG
                    warnings.append(f"ассет не встроен: {value[:60]}")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(resolved)
    return resolved, warnings


def render_ir_for(component: dict, variant: dict | None) -> tuple[dict | None, list[str]]:
    """Готовый ко вставке IR одного мастера: нормализованный, самодостаточный."""
    source = variant if variant is not None else component
    master = source.get("masterIr") if isinstance(source.get("masterIr"), dict) else None
    if not isinstance(master, dict) or not master.get("tree"):
        return None, []
    preview = dsdoc.preview_ir_for_master(master)
    resolved, warnings = _inline_ir_assets(preview)
    return _strip_font_faces(resolved), warnings


# ---------- доказательство точности ----------

def _decode_preview(reference: str) -> bytes | None:
    """data:-URL или ddna://blobs/<sha>.png → байты PNG."""
    if not isinstance(reference, str) or not reference:
        return None
    if reference.startswith("data:"):
        _, _, payload = reference.partition(",")
        try:
            return base64.b64decode(payload)
        except Exception:
            return None
    try:
        import scraper
        digest = scraper.parse_blob_ref(reference)
        return scraper.read_png_blob(digest) if digest else None
    except Exception:
        return None


def proof_crop(document: dict, component: dict, viewport: str = "desktop",
               *, budget_left: int = PROOF_BUDGET) -> tuple[str | None, int, str | None]:
    """Кроп исходного скриншота по границам компонента → (dataURL, байты, note).

    Режем на сервере, а не канвасом в браузере: скриншот целого блока
    (1440×4000) в base64 — главный риск веса страницы, а кроп до кнопки
    превращает мегабайты в килобайты. Математика та же, что в панели
    (DesignSystemPanel.svelte:277-306).
    """
    source_ref = component.get("sourceRef") if isinstance(component.get("sourceRef"), dict) else {}
    evidence = (document.get("referenceAssets") or {}).get(source_ref.get("evidenceKey"))
    if not isinstance(evidence, dict):
        return None, 0, "нет source-скриншота для этого компонента"
    previews = evidence.get("referencePreviews") if isinstance(evidence.get("referencePreviews"), dict) else {}
    reference = previews.get(viewport) or previews.get("desktop")
    raw = _decode_preview(reference)
    if not raw:
        return None, 0, "source-скриншот не удалось прочитать"

    bounds_by_viewport = source_ref.get("boundsByViewport") if isinstance(source_ref.get("boundsByViewport"), dict) else {}
    bounds = bounds_by_viewport.get(viewport) or source_ref.get("bounds") or {}
    block_sizes = evidence.get("blockSizes") if isinstance(evidence.get("blockSizes"), dict) else {}
    block = block_sizes.get(viewport) or block_sizes.get("desktop") or {}

    try:
        import io
        from PIL import Image
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        return None, 0, f"скриншот не декодируется: {exc}"

    note: str | None = None
    values = [_num(bounds.get(key)) for key in ("x", "y", "width", "height")]
    block_w, block_h = _num(block.get("width")), _num(block.get("height"))
    can_crop = (all(value is not None for value in values)
                and values[2] and values[3] and block_w and block_h)
    if can_crop:
        scale_x = image.width / block_w
        scale_y = image.height / block_h
        sx = max(0, values[0] * scale_x)
        sy = max(0, values[1] * scale_y)
        sw = min(image.width - sx, values[2] * scale_x)
        sh = min(image.height - sy, values[3] * scale_y)
        if sw > 0 and sh > 0:
            image = image.crop((int(sx), int(sy), int(sx + sw), int(sy + sh)))
        else:
            note = "границы компонента вне скриншота — показан весь блок"
    else:
        note = "нет измеренных границ — показан весь блок"

    if image.width > 1200:
        ratio = 1200 / image.width
        image = image.resize((1200, max(1, int(image.height * ratio))))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82, optimize=True)
    payload = buffer.getvalue()
    if len(payload) > budget_left:
        return None, 0, "скриншот пропущен: превышен бюджет изображений"
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii"), len(payload), note


# ---------- живой код ----------

def tokens_css(document: dict) -> str:
    """CSS-переменные кита. У каждой строки — комментарий, откуда значение."""
    tokens = ((document.get("styleGuide") or {}).get("tokens") or {})
    foundations = document.get("foundations") or {}
    lines = [":root {"]
    for name, value in tokens.items():
        lines.append(f"  --ddna-{name}: {value};  /* styleGuide.tokens.{name} */")
    for name, value in (foundations.get("spacing") or {}).items():
        lines.append(f"  --ddna-space-{name}: {value}px;  /* foundations.spacing.{name} · измерено */")
    for index, value in enumerate(foundations.get("radii") or [], start=1):
        lines.append(f"  --ddna-radius-{index}: {value}px;  /* foundations.radii · измерено */")
    for index, value in enumerate(foundations.get("shadows") or [], start=1):
        lines.append(f"  --ddna-shadow-{index}: {value};  /* foundations.shadows · измерено */")
    for name, value in ((foundations.get("typography") or {}).get("scale") or {}).items():
        lines.append(f"  --ddna-font-size-{name}: {value}px;  /* foundations.typography.scale.{name} */")
    lines.append("}")
    return "\n".join(lines)


def tailwind_theme(document: dict) -> dict:
    """theme.extend для tailwind.config.

    Форма зеркалит app/ir/tailwind_projection.py::_theme, но источник другой:
    та функция читает ir.tokens.semantic, которого у документа дизайн-системы
    нет. При правках держать обе в согласии.
    """
    tokens = ((document.get("styleGuide") or {}).get("tokens") or {})
    foundations = document.get("foundations") or {}
    colors = {name: f"var(--ddna-{name})" for name, value in tokens.items()
              if isinstance(value, str) and value.startswith("#")}
    typography = foundations.get("typography") or {}
    return {
        "extend": {
            "colors": colors,
            "fontFamily": {
                "display": [str((typography.get("display") or {}).get("family") or "")],
                "body": [str((typography.get("body") or {}).get("family") or "")],
            },
            "borderRadius": {f"ddna-{index}": f"var(--ddna-radius-{index})"
                             for index, _ in enumerate(foundations.get("radii") or [], start=1)},
            "spacing": {name: f"var(--ddna-space-{name})"
                        for name in (foundations.get("spacing") or {})},
            "boxShadow": {f"ddna-{index}": f"var(--ddna-shadow-{index})"
                          for index, _ in enumerate(foundations.get("shadows") or [], start=1)},
            "fontSize": {name: f"var(--ddna-font-size-{name})"
                         for name in (typography.get("scale") or {})},
            "screens": {name: f"{int(value)}px"
                        for name, value in (foundations.get("breakpoints") or {}).items()
                        if _num(value)},
        },
    }


def figma_tokens(document: dict) -> dict:
    """Токены в формате W3C Design Tokens (его импортирует Tokens Studio)."""
    tokens = ((document.get("styleGuide") or {}).get("tokens") or {})
    foundations = document.get("foundations") or {}
    out: dict[str, dict] = {"color": {}, "dimension": {}, "fontFamily": {}, "shadow": {}}
    for name, value in tokens.items():
        if isinstance(value, str) and value.startswith("#"):
            out["color"][name] = {"$type": "color", "$value": value,
                                  "$description": f"styleGuide.tokens.{name}"}
    for name, value in (foundations.get("spacing") or {}).items():
        if _num(value) is not None:
            out["dimension"][f"space-{name}"] = {"$type": "dimension", "$value": f"{value}px",
                                                 "$description": "измеренный отступ источника"}
    for index, value in enumerate(foundations.get("radii") or [], start=1):
        out["dimension"][f"radius-{index}"] = {"$type": "dimension", "$value": f"{value}px",
                                               "$description": "измеренный радиус источника"}
    typography = foundations.get("typography") or {}
    for role in ("display", "body"):
        family = (typography.get(role) or {}).get("family")
        if family:
            out["fontFamily"][role] = {"$type": "fontFamily", "$value": str(family),
                                       "$description": f"foundations.typography.{role}"}
    for index, value in enumerate(foundations.get("shadows") or [], start=1):
        out["shadow"][f"shadow-{index}"] = {"$type": "shadow", "$value": str(value),
                                            "$description": "измеренная тень источника"}
    return {group: items for group, items in out.items() if items}


# ---------- сборка карточек ----------

def _atomic_groups(document: dict) -> list[dict]:
    catalog = document.get("catalog") if isinstance(document.get("catalog"), dict) else {}
    levels = catalog.get("levels")
    if isinstance(levels, list) and levels:
        return levels
    # Черновик без организатора: считаем ось на лету, чтобы экспорт не пустел.
    from .organizer import deterministic_catalog
    return deterministic_catalog(document).get("levels") or []


def _section_label(catalog: dict, key: str) -> str:
    for section in catalog.get("sections") or []:
        if key in (section.get("componentKeys") or []):
            return str(section.get("label") or section.get("key") or "")
    return ""


def _component_ref(document: dict, component: dict) -> dict:
    """Ссылка на мастера в том же виде, что получает генератор.

    Та же форма, что `compiler.component_handle`: страница обязана давать
    ref, который примет strict-режим, иначе скопированный со страницы сниппет
    отвалится на валидации.
    """
    from .compiler import component_master_hash

    return {
        "systemId": str(document.get("id") or ""),
        "revision": int(document.get("revision") or 0),
        "componentKey": str(component.get("componentKey") or component.get("key") or ""),
        "masterHash": component_master_hash(component),
    }


def _accuracy(fidelity_viewports: dict) -> str:
    """Компактная строка точности: `desktop=93.38;mobile=97.10`.

    Живёт в data-атрибуте карточки: отладка не требует, чтобы страница
    показывала таблицы, но и терять измерение незачем.
    """
    parts = []
    for name, metrics in (fidelity_viewports or {}).items():
        similarity = _num((metrics or {}).get("pixelSimilarity")) if isinstance(metrics, dict) else None
        if similarity is not None:
            parts.append(f"{name}={similarity:.2f}")
    return ";".join(parts)


def _usage_note(document: dict, key: str, component: dict) -> str:
    """Одна строка «зачем этот компонент». Описание → сводка ревью → заметка."""
    review = component.get("review") if isinstance(component.get("review"), dict) else {}
    note = str(((document.get("styleGuide") or {}).get("review") or {})
               .get("componentNotes", {}).get(key, ""))
    for candidate in (component.get("description"), review.get("summary"), note):
        text = " ".join(str(candidate or "").split())
        if text:
            return text
    return ""


def component_cards(document: dict, *, include_proof: bool = False,
                    include_review: bool = True, viewport: str = "desktop",
                    proof_budget: int = PROOF_BUDGET) -> tuple[list[dict], list[str], int]:
    """Карточки всех мастеров документа: components + reviewComponents.

    include_review оставлен ради обратной совместимости и по умолчанию
    включён: мастер «на ревью» — такой же точный захват с сайта, прятать его
    из кита незачем. include_proof по умолчанию выключен — кроп источника
    нужен панели ревью, а не документу для встраивания.
    """
    catalog = document.get("catalog") if isinstance(document.get("catalog"), dict) else {}
    meta = catalog.get("componentMeta") if isinstance(catalog.get("componentMeta"), dict) else {}
    pools = {**(document.get("components") or {})}
    if include_review:
        pools.update(document.get("reviewComponents") or {})
        # Черновики до появления reviewComponents держали наблюдённых мастеров
        # в suggestions — иначе часть кита просто не доедет до страницы.
        for key, candidate in (document.get("suggestions") or {}).items():
            if isinstance(candidate, dict) and candidate.get("origin") == "observed":
                pools.setdefault(str(key), candidate)
    warnings: list[str] = []
    proof_used = 0
    cards: list[dict] = []

    for level in _atomic_groups(document):
        for key in level.get("componentKeys") or []:
            component = pools.get(key)
            if not isinstance(component, dict):
                continue
            renders: list[dict] = []
            base_ir, base_warnings = render_ir_for(component, None)
            warnings.extend(base_warnings)
            variants = component.get("variants") if isinstance(component.get("variants"), dict) else {}
            for variant_key, variant in variants.items():
                if not isinstance(variant, dict):
                    continue
                own = isinstance(variant.get("masterIr"), dict)
                ir, variant_warnings = render_ir_for(component, variant if own else None)
                warnings.extend(variant_warnings)
                if ir is None:
                    continue
                renders.append({
                    "variantKey": str(variant_key),
                    "label": str(variant.get("label") or variant_key),
                    "observedCount": int(variant.get("observedCount") or 1),
                    "observedStyle": variant.get("observedStyle") or {},
                    "ir": ir,
                })
            if not renders and base_ir is not None:
                renders.append({"variantKey": "default", "label": "Default",
                                "observedCount": 1, "observedStyle": {}, "ir": base_ir})

            proof = None
            if include_proof:
                data_url, size, note = proof_crop(document, component, viewport,
                                                  budget_left=proof_budget - proof_used)
                proof_used += size
                proof = {"image": data_url, "note": note}
                if note:
                    warnings.append(f"{key}: {note}")

            states = component.get("states") if isinstance(component.get("states"), dict) else {}
            fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
            review = component.get("review") if isinstance(component.get("review"), dict) else {}
            provenance = component.get("provenance") if isinstance(component.get("provenance"), dict) else {}
            source_ref = component.get("sourceRef") if isinstance(component.get("sourceRef"), dict) else {}
            category = str(component.get("category") or "")
            cards.append({
                "key": key,
                "componentRef": _component_ref(document, {**component, "componentKey":
                                                          component.get("componentKey") or key}),
                "usage": _usage_note(document, key, component),
                "accuracy": _accuracy(fidelity.get("viewports") or {}),
                "categoryLabel": _section_label(catalog, key) or category.title() or "Компоненты",
                "level": str(level.get("key") or ""),
                "levelLabel": str(level.get("label") or ""),
                "section": _section_label(catalog, key),
                "name": str(component.get("name") or key),
                "role": str(component.get("canonicalRole") or ""),
                "category": str(component.get("category") or ""),
                "description": str(component.get("description") or ""),
                "status": str(component.get("status") or "verified"),
                "occurrences": int(provenance.get("occurrenceCount") or 1),
                "sourceBlock": str(source_ref.get("sourceBlock") or ""),
                "selector": str(source_ref.get("selector") or ""),
                "renders": renders,
                "states": [{"key": str(name), "label": str((value or {}).get("label") or name),
                            "description": str((value or {}).get("description") or "")}
                           for name, value in states.items()],
                "fidelity": fidelity.get("viewports") or {},
                "fidelityStatus": str(fidelity.get("status") or ""),
                "reviewReasons": list(review.get("reasons") or []) or list(fidelity.get("reasons") or []),
                "props": list((component.get("propsSchema") or {}).keys()),
                "accessibility": component.get("accessibility") or {},
                "note": str(((document.get("styleGuide") or {}).get("review") or {})
                            .get("componentNotes", {}).get(key, "")),
                "proof": proof,
                "variantCount": int((meta.get(key) or {}).get("variantCount") or len(variants) or 1),
            })
    return cards, warnings, proof_used


# ---------- HTML ----------

PAGE_CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:#0b0d12;color:#e6eaf2;font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:#8b7cf6}
.wrap{display:grid;grid-template-columns:236px minmax(0,1fr);gap:32px;max-width:1440px;margin:0 auto;padding:28px 24px 80px}
nav.toc{position:sticky;top:24px;align-self:start;display:grid;gap:4px}
nav.toc a{display:block;padding:7px 10px;border-radius:8px;color:#98a1b3;font-size:12.5px;text-decoration:none}
nav.toc a:hover{background:#151a23;color:#e6eaf2}
h1{margin:0 0 6px;font-size:26px;letter-spacing:-.02em}
h2{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}
h3{margin:22px 0 10px;font-size:13px;color:#9aa3b5;text-transform:uppercase;letter-spacing:.07em}
p.lead{margin:0;color:#98a1b3;font-size:12.5px;line-height:1.55}
section{margin-bottom:44px;scroll-margin-top:20px}
section>header{margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #222834}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:16px}
.stat{border:1px solid #232935;border-radius:12px;background:#11151d;padding:12px 14px}
.stat b{display:block;font-size:24px;line-height:1.1}
.stat span{color:#828b9d;font-size:10.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.swatch{display:flex;gap:10px;align-items:center;border:1px solid #232935;border-radius:10px;background:#11151d;padding:9px}
.swatch i{flex:none;width:36px;height:36px;border:1px solid #333b49;border-radius:8px}
.swatch b{display:block;font-size:11.5px}
.swatch span{color:#7f8899;font-family:ui-monospace,Consolas,monospace;font-size:10px}
.pair{display:grid;place-items:center;height:36px;width:36px;border-radius:8px;border:1px solid #333b49;font-size:11px;font-weight:700}
.bar{height:10px;border-radius:5px;background:linear-gradient(90deg,#8b7cf6,#58d1bc)}
.rowline{display:grid;grid-template-columns:110px minmax(0,1fr) auto;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid #1c212b}
.rowline code{color:#7f8899;font-size:10.5px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid #2c3340;border-radius:999px;background:#151a23;padding:4px 10px;font-size:11px}
.chip small{color:#7f8899;margin-right:5px}
.comp{border:1px solid #232935;border-radius:14px;background:#0f131a;margin-bottom:14px;overflow:hidden}
.comp>header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;padding:13px 15px;border-bottom:1px solid #1c212b;margin:0}
.comp h4{margin:0 0 3px;font-size:14px}
.comp .meta{color:#7f8899;font-size:10.5px}
.comp .use{margin:0;padding:11px 15px 0;color:#98a1b3;font-size:12.5px;line-height:1.5}
.panes{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;padding:14px 15px}
.pane{min-width:0}
.pane>span{display:block;margin-bottom:6px;color:#7f8899;font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.stage{border:1px solid #232935;border-radius:10px;background:#0b0d12;padding:10px;overflow:auto;max-height:340px}
.stage img{display:block;max-width:100%}
.vpbar{display:inline-flex;gap:2px;border:1px solid #2c3340;border-radius:999px;background:#151a23;padding:3px}
.vpbar button{border:0;border-radius:999px;background:transparent;padding:5px 13px;color:#98a1b3;font:inherit;font-size:11.5px;cursor:pointer}
.vpbar button[aria-pressed="true"]{background:#2a3242;color:#e6eaf2}
.snippet{padding:0 15px 14px}
.snippet pre{max-height:200px;font-size:10.5px}
.voice{display:grid;gap:8px;margin-top:8px}
.voice .row{display:grid;grid-template-columns:150px minmax(0,1fr);gap:10px;align-items:baseline}
.voice .row>b{color:#9aa3b5;font-size:11px;font-weight:600}
.quote{border:1px solid #2c3340;border-radius:8px;background:#151a23;padding:4px 9px;color:#d8dded;font-size:11.5px}
.prose{margin:0 0 10px;color:#c3cad8;font-size:13.5px;line-height:1.6;max-width:78ch}
.oneline{margin:0 0 14px;color:#e6eaf2;font-size:16px;line-height:1.45;max-width:70ch}
.variants{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;padding:0 15px 14px}
.variant{border:1px solid #1e2430;border-radius:10px;overflow:hidden}
.variant>b{display:block;padding:7px 9px;border-bottom:1px solid #1e2430;font-size:11px}
.variant>b small{color:#7f8899;font-weight:400;margin-left:6px}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{padding:5px 8px;text-align:left;border-bottom:1px solid #1c212b}
th{color:#7f8899;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
.foot{padding:11px 15px;border-top:1px solid #1c212b;color:#7f8899;font-size:10.5px}
.states{margin:0;padding-left:16px;color:#8d95a6;font-size:11.5px}
.states li{margin-bottom:3px}
.rules{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.rules ul{margin:6px 0 0;padding-left:16px}
.rules li{margin-bottom:5px;font-size:12px;line-height:1.45}
.do li{color:#7fd7b6}
.dont li{color:#e2988a}
pre{margin:0;overflow:auto;max-height:420px;border:1px solid #232935;border-radius:10px;background:#0d1117;padding:12px;color:#cdd4e0;font:11.5px/1.6 ui-monospace,Consolas,monospace}
.codehead{display:flex;justify-content:space-between;align-items:center;margin:18px 0 7px}
button.copy{border:1px solid #394252;border-radius:8px;background:#1b222d;padding:5px 10px;color:#dfe4ee;font-size:11px;cursor:pointer}
button.copy:hover{border-color:#5e6a7f}
@media (max-width:900px){.wrap{grid-template-columns:1fr}nav.toc{position:static}.rules{grid-template-columns:1fr}}
@media print{nav.toc{display:none}.wrap{grid-template-columns:1fr}.stage{max-height:none}}
"""

BOOTSTRAP_JS = r"""
(function(){
  var node = document.getElementById('ddna-payload');
  var DDNA = JSON.parse(node.textContent);
  window.DDNA = DDNA;
  var containers = [];

  function renderOne(el){
    if(el.dataset.rendered) return;
    el.dataset.rendered = '1';
    var ir = DDNA.irs[el.dataset.ir];
    if(!ir){ return; }
    try{
      window.IRRenderer.renderIR(el, ir, {viewport: DDNA.viewport, fit: false});
      var width = Number(el.dataset.width) || 0;
      if(width > 0 && el.parentElement){
        var avail = el.parentElement.clientWidth || width;
        el.style.zoom = String(Math.min(1, avail / width));
      }
    }catch(err){
      console.error('DDNA render failed for ' + el.dataset.ir, err);
    }
  }

  function renderAll(){ containers.forEach(renderOne); }
  DDNA.renderAll = renderAll;

  // Переключатель вьюпорта: тот же IR, другой набор responsive-оверрайдов.
  // Перерисовываем всё разом — переключение это явный клик, не скролл.
  function setViewport(name){
    DDNA.viewport = name;
    containers.forEach(function(el){
      delete el.dataset.rendered;
      el.innerHTML = '';
      el.style.zoom = '';
    });
    Array.prototype.forEach.call(document.querySelectorAll('.vpbar button'), function(button){
      button.setAttribute('aria-pressed', button.dataset.vp === name ? 'true' : 'false');
    });
    renderAll();
  }
  DDNA.setViewport = setViewport;

  function boot(){
    containers = Array.prototype.slice.call(document.querySelectorAll('[data-ddna-render]'));
    // Ленивый рендер: десятки мастеров разом подвесили бы страницу.
    // #all и печать требуют полной отрисовки — для них renderAll.
    if(window.IntersectionObserver && location.hash !== '#all'){
      var io = new IntersectionObserver(function(entries){
        entries.forEach(function(entry){
          if(entry.isIntersecting){ renderOne(entry.target); io.unobserve(entry.target); }
        });
      }, {rootMargin: '600px'});
      containers.forEach(function(el){ io.observe(el); });
    } else {
      renderAll();
    }
    window.addEventListener('beforeprint', renderAll);
    document.documentElement.dataset.ddnaReady = '1';
  }

  // Шрифты предзагружаем сами: meta.fontFaces из встроенных IR снят намеренно,
  // иначе рендерер затирал бы общий на документ <style> при каждом вызове и
  // до последнего компонента доехали бы чужие шрифты.
  var loads = (DDNA.fontSpecs || []).map(function(spec){
    try { return document.fonts.load(spec.weight + ' 16px "' + spec.family + '"'); }
    catch(err){ return Promise.resolve(); }
  });
  Promise.all(loads.map(function(p){ return Promise.resolve(p).catch(function(){}); }))
    .then(function(){ return document.fonts.ready; })
    .catch(function(){})
    .then(boot, boot);

  document.addEventListener('click', function(event){
    // Electron may block fragment navigation on blob:file documents.
    // Scroll without navigating away from this live UI Kit document.
    var link = event.target.closest ? event.target.closest('nav.toc a[href^="#"]') : null;
    if(link && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey){
      var section = document.getElementById(link.getAttribute('href').slice(1));
      if(section){ event.preventDefault(); section.scrollIntoView({block: 'start'}); return; }
    }
    var vp = event.target.closest ? event.target.closest('.vpbar button') : null;
    if(vp && vp.dataset.vp){ setViewport(vp.dataset.vp); return; }
    var button = event.target.closest ? event.target.closest('button.copy') : null;
    if(!button) return;
    var target = document.getElementById(button.dataset.target);
    if(!target) return;
    var text = target.textContent;
    var done = function(){
      var label = button.textContent;
      button.textContent = 'Скопировано';
      setTimeout(function(){ button.textContent = label; }, 1200);
    };
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(done, function(){});
    } else {
      var area = document.createElement('textarea');
      area.value = text; document.body.appendChild(area); area.select();
      try { document.execCommand('copy'); done(); } finally { area.remove(); }
    }
  });
})();
"""


def _swatch(name: str, value: str) -> str:
    return (f'<div class="swatch"><i style="background:{_esc(value)}"></i>'
            f'<div><b>{_esc(name)}</b><span>{_esc(value)}</span></div></div>')


# ---------- стиль сайта ----------

# Профиль хранит машинные значения (dark/pill/airy). Страницу читает человек,
# поэтому подписи переводятся — но только известные: незнакомое значение
# показываем как есть, а не прячем.
_PROFILE_LABELS = (
    ("mode", "Тема"),
    ("cornerCharacter", "Углы"),
    ("density", "Плотность"),
    ("shadowUsage", "Тени"),
    ("paletteCharacter", "Палитра"),
    ("accent", "Акцент"),
    ("typographyCharacter", "Типографика"),
    ("labelStyle", "Лейблы и надзаголовки"),
    ("monoFamily", "Служебный шрифт"),
    ("imageDirection", "Изображения"),
    ("iconStyle", "Иконки"),
)
_PROFILE_VALUES = {
    "mode": {"dark": "тёмная", "light": "светлая"},
    "cornerCharacter": {"sharp": "острые", "subtle": "слегка скруглённые",
                        "rounded": "скруглённые", "pill": "капсульные"},
    "density": {"compact": "плотная", "comfortable": "комфортная", "airy": "просторная"},
    "shadowUsage": {"none": "не используются", "subtle": "едва заметные", "layered": "многослойные"},
}
_REVIEW_LABELS = (
    ("tone", "Тон"),
    ("density", "Плотность"),
    ("cornerCharacter", "Формы"),
    ("colorUsage", "Цвет"),
    ("typographyCharacter", "Типографика"),
    ("imageryStyle", "Изображения"),
)
_VOICE_LABELS = (
    ("heading", "Заголовки"),
    ("eyebrow", "Надзаголовки"),
    ("cta", "Кнопки и CTA"),
    ("badge", "Бейджи и цифры"),
    ("text", "Текст"),
)
_CONTENT_LABELS = (
    ("brand", "Бренд"),
    ("nav", "Навигация"),
    ("cta", "Призывы к действию"),
    ("heading", "Заголовки"),
    ("title", "Названия"),
    ("category", "Категории"),
    ("badge", "Бейджи"),
    ("price", "Цены"),
    ("question", "Вопросы"),
)


def _as_list(value: Any) -> list[str]:
    """Строка, список строк или список словарей → плоский список строк."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            head = str(item.get("label") or item.get("title") or item.get("name")
                       or item.get("key") or "").strip()
            tail = str(item.get("summary") or item.get("description") or item.get("value") or "").strip()
            joined = " — ".join(part for part in (head, tail) if part)
            if joined:
                out.append(joined)
    return out


def _kv_rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="rowline"><code>{_esc(label)}</code>'
                   f'<div>{_esc(value)}</div><span></span></div>'
                   for label, value in pairs if value)


def _quote_chips(values: list[str], limit: int = 5) -> str:
    return "".join(f'<span class="quote">«{_esc(value)}»</span>' for value in values[:limit])


def _style_html(document: dict, *, url: str = "", generated_at: str = "",
                stats: list[tuple[str, str]] | None = None) -> str:
    """«Стиль сайта»: чем сайт является и на каком языке он говорит.

    Всё опционально: siteBrief может отсутствовать, AI-ревью — не выполняться,
    профиль — быть только детерминированным. Секция показывает то, что есть,
    и не выдумывает недостающее.
    """
    brief = document.get("siteBrief") if isinstance(document.get("siteBrief"), dict) else {}
    guide = document.get("styleGuide") if isinstance(document.get("styleGuide"), dict) else {}
    profile = guide.get("profile") if isinstance(guide.get("profile"), dict) else {}
    review = guide.get("review") if isinstance(guide.get("review"), dict) else {}
    identity = document.get("identity") if isinstance(document.get("identity"), dict) else {}
    one_line = str((((identity.get("soul") or {}).get("oneLine") or {}).get("value")) or "").strip()
    reference = (document.get("referenceContent")
                 if isinstance(document.get("referenceContent"), dict) else {})

    parts = ['<section id="style"><header>',
             f'<h1>{_esc(document.get("name") or "UI Kit")}</h1>',
             '<p class="lead">Как выглядит и звучит этот сайт. Новый компонент должен встраиваться '
             'в этот язык, а не выделяться на его фоне.</p>',
             '</header>']

    meta_bits = [f'Источник: {_esc(url)}' if url else "",
                 f'ревизия {_esc(document.get("revision"))}',
                 _esc((document.get("contentHash") or "")[:19]),
                 _esc(generated_at) if generated_at else ""]
    parts.append('<p class="lead">' + " · ".join(bit for bit in meta_bits if bit) + "</p>")

    if stats:
        parts.append('<div class="stats">')
        parts.extend(f'<div class="stat"><b>{_esc(value)}</b><span>{_esc(label)}</span></div>'
                     for value, label in stats)
        parts.append("</div>")

    if one_line:
        parts.append(f'<p class="oneline" style="margin-top:18px">{_esc(one_line)}</p>')
    for field in ("summary", "description", "about"):
        text = " ".join(str(brief.get(field) or "").split())
        if text:
            parts.append(f'<p class="prose">{_esc(text)}</p>')

    brief_rows = [("Аудитория", " ".join(str(brief.get("audience") or "").split())),
                  ("Тон", " ".join(str(brief.get("tone") or "").split()))]
    voice_text = brief.get("voice")
    if isinstance(voice_text, str) and voice_text.strip():
        brief_rows.append(("Голос", " ".join(voice_text.split())))
    rows = _kv_rows(brief_rows)
    if rows:
        parts.append("<h3>О сайте</h3>" + rows)

    sections = _as_list(brief.get("sections"))
    if sections:
        parts.append("<h3>Разделы сайта</h3><div class=\"chips\">")
        parts.extend(f'<span class="chip">{_esc(item)}</span>' for item in sections[:24])
        parts.append("</div>")

    language: list[tuple[str, str]] = []
    for field, label in _PROFILE_LABELS:
        raw = profile.get(field)
        if raw in (None, "", [], {}):
            continue
        value = str(raw)
        language.append((label, _PROFILE_VALUES.get(field, {}).get(value, value)))
    for field, label in _REVIEW_LABELS:
        text = " ".join(str(review.get(field) or "").split())
        if text:
            language.append((f"{label} (ревью)", text))
    if language:
        parts.append('<h3>Дизайн-язык</h3>' + _kv_rows(language))

    voice = profile.get("copyVoice") if isinstance(profile.get("copyVoice"), dict) else {}
    voice_rows = [(label, _quote_chips(_as_list(voice.get(field)))) for field, label in _VOICE_LABELS]
    voice_rows = [(label, chips) for label, chips in voice_rows if chips]
    if voice_rows:
        parts.append('<h3>Голос копирайта</h3><p class="lead">Образцы взяты со страницы источника — '
                     'новый текст пишется в том же регистре и той же длины.</p><div class="voice">')
        parts.extend(f'<div class="row"><b>{_esc(label)}</b><div class="chips">{chips}</div></div>'
                     for label, chips in voice_rows)
        parts.append("</div>")

    content_rows = [(label, _quote_chips(_as_list(reference.get(field)), limit=6))
                    for field, label in _CONTENT_LABELS]
    content_rows = [(label, chips) for label, chips in content_rows if chips]
    if content_rows:
        parts.append('<h3>Слова сайта</h3><div class="voice">')
        parts.extend(f'<div class="row"><b>{_esc(label)}</b><div class="chips">{chips}</div></div>'
                     for label, chips in content_rows)
        parts.append("</div>")

    parts.append("</section>")
    return "".join(parts)


def _foundations_html(document: dict) -> str:
    foundations = document.get("foundations") or {}
    guide = document.get("styleGuide") or {}
    tokens = guide.get("tokens") or {}
    measured = guide.get("measured") or {}
    colors = foundations.get("colors") or {}
    semantic = colors.get("semantic") or {}
    primitives = colors.get("primitives") or {}
    typography = foundations.get("typography") or {}
    scale = typography.get("scale") or {}
    spacing = foundations.get("spacing") or {}
    measurement = foundations.get("measurement") or {}

    parts = ['<section id="tokens"><header><h2>Токены</h2>'
             '<p class="lead">Значения измерены на странице источника, а не подобраны на глаз. '
             'Семантические роли следуют соглашению shadcn/ui — их и должен использовать генератор новых компонентов.</p></header>']

    parts.append("<h3>Семантические токены</h3><div class=\"grid\">")
    for name, value in tokens.items():
        if isinstance(value, str) and value.startswith("#"):
            fg = tokens.get(f"{name}-foreground")
            if isinstance(fg, str) and fg.startswith("#"):
                parts.append(f'<div class="swatch"><span class="pair" style="background:{_esc(value)};color:{_esc(fg)}">Aa</span>'
                             f'<div><b>{_esc(name)}</b><span>{_esc(value)} / {_esc(fg)}</span></div></div>')
            else:
                parts.append(_swatch(name, value))
    parts.append("</div>")

    if semantic:
        parts.append("<h3>Палитра источника</h3><div class=\"grid\">")
        parts.extend(_swatch(name, value) for name, value in semantic.items() if isinstance(value, str))
        parts.append("</div>")
    if primitives:
        brand = {k: v for k, v in primitives.items() if k.startswith("brand")}
        pixels = {k: v for k, v in primitives.items() if not k.startswith("brand")}
        if brand:
            parts.append("<h3>Брендовые цвета (из токенов источника)</h3><div class=\"grid\">")
            parts.extend(_swatch(name, value) for name, value in brand.items())
            parts.append("</div>")
        if pixels:
            parts.append("<h3>Измеренные цвета (частота в пикселях)</h3><div class=\"grid\">")
            parts.extend(_swatch(name, value) for name, value in pixels.items())
            parts.append("</div>")

    if scale:
        display_family = (typography.get("display") or {}).get("family") or ""
        body_family = (typography.get("body") or {}).get("family") or ""
        parts.append("<h3>Типографика</h3>")
        for name, size in scale.items():
            family = display_family if name in ("display", "h2", "h3") else body_family
            parts.append(
                f'<div class="rowline"><code>{_esc(name)}</code>'
                f'<div style="font-family:\'{_esc(family)}\',sans-serif;font-size:{_esc(size)}px;line-height:1.15;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                f'Дизайн-система собрана из измерений</div>'
                f'<code>{_esc(family)} · {_esc(size)}px</code></div>')
        weights = ", ".join(str(w) for w in typography.get("weights") or [])
        if weights:
            parts.append(f'<p class="lead">Начертания: {_esc(weights)}. Дисплейный шрифт — {_esc(display_family)}, текстовый — {_esc(body_family)}.</p>')

    if spacing:
        parts.append("<h3>Отступы</h3>")
        values = [v for v in spacing.values() if _num(v)]
        peak = max(values) if values else 1
        for name, value in spacing.items():
            width = max(2.0, 100.0 * (_num(value) or 0) / peak)
            parts.append(f'<div class="rowline"><code>{_esc(name)}</code>'
                         f'<div class="bar" style="width:{width:.1f}%"></div>'
                         f'<code>{_esc(value)}px</code></div>')

    radii = foundations.get("radii") or []
    radius_map = foundations.get("radius") or {}
    if radii or radius_map:
        parts.append("<h3>Радиусы</h3><div class=\"chips\">")
        parts.extend(f'<span class="chip"><small>измерено</small>{_esc(value)}px</span>' for value in radii)
        parts.extend(f'<span class="chip"><small>{_esc(name)}</small>{_esc(value)}px</span>'
                     for name, value in radius_map.items())
        parts.append("</div>")

    shadows = foundations.get("shadows") or []
    if shadows:
        parts.append("<h3>Тени</h3><div class=\"grid\">")
        for index, shadow in enumerate(shadows[:8], start=1):
            parts.append(f'<div class="swatch"><i style="box-shadow:{_esc(shadow)};background:#151a23"></i>'
                         f'<div><b>shadow-{index}</b><span>измерено</span></div></div>')
        parts.append("</div>")

    breakpoints = foundations.get("breakpoints") or {}
    containers = foundations.get("containers") or {}
    if breakpoints or containers or measured:
        parts.append("<h3>Сетка и характер</h3><div class=\"chips\">")
        parts.extend(f'<span class="chip"><small>{_esc(name)}</small>{_esc(int(value))}px</span>'
                     for name, value in breakpoints.items() if _num(value))
        parts.extend(f'<span class="chip"><small>контейнер</small>{_esc(int(value))}px</span>'
                     for value in containers.values() if _num(value))
        parts.extend(f'<span class="chip"><small>{_esc(name)}</small>{_esc(value)}</span>'
                     for name, value in measured.items())
        parts.append("</div>")

    if measurement:
        parts.append(f'<p class="lead" style="margin-top:14px">Основа измерений: {_esc(measurement.get("basis"))} · '
                     f'размеров шрифта {_esc(measurement.get("fontSizeCount"))} · '
                     f'отступов {_esc(measurement.get("spacingCount"))} · '
                     f'радиусов {_esc(measurement.get("radiusCount"))}.</p>')

    ir_tokens = guide.get("irTokens")
    if isinstance(ir_tokens, dict) and ir_tokens:
        parts.append('<h3>Design IR tokens</h3><p class="lead">Полная форма токенов, которую лочит '
                     'генератор: те же значения, но в схеме Design IR.</p>')
        parts.append(_code_block("code-ir-tokens", "styleGuide.irTokens",
                                 json.dumps(ir_tokens, ensure_ascii=False, indent=2)))
    parts.append("</section>")
    return "".join(parts)


def _accuracy_note(card: dict) -> str:
    """Компактная сноска точности — только проценты, без порогов и вердиктов.

    Появляется лишь при include_fidelity=True: страница для встраивания не
    обсуждает, насколько хорошо мы скопировали — она даёт то, что копируют.
    """
    pairs = []
    for name, metrics in (card.get("fidelity") or {}).items():
        similarity = _num((metrics or {}).get("pixelSimilarity")) if isinstance(metrics, dict) else None
        if similarity is not None:
            pairs.append(f"{name} {similarity:.1f}%")
    if not pairs:
        return ""
    return f'<div class="foot">Точность: {_esc(" · ".join(pairs))}</div>'


def _snippet(card: dict) -> str:
    """Копируемая ссылка на мастера — то, что вставляют в задание генератору."""
    anchor = "snip-" + re.sub(r"[^A-Za-z0-9_-]+", "-", card["key"])
    payload = {
        "componentKey": card["key"],
        "componentRef": card["componentRef"],
        "variants": [render["variantKey"] for render in card["renders"]],
    }
    if card["props"]:
        payload["props"] = card["props"]
    return ('<div class="snippet">'
            + _code_block(anchor, "Ссылка на мастер",
                          json.dumps(payload, ensure_ascii=False, indent=2))
            + "</div>")


def _stage(render: dict, ir_index: dict, *, max_height: int = 340) -> str:
    ir_id = ir_index[id(render["ir"])]
    width = int(_num((render["ir"].get("tree") or [{}])[0].get("frame", {}).get("width")) or 0)
    return (f'<div class="stage" style="max-height:{max_height}px">'
            f'<div data-ddna-render data-ir="{_esc(ir_id)}" data-width="{width}"></div></div>')


def _component_html(card: dict, ir_index: dict, *, include_fidelity: bool = False) -> str:
    """Карточка готового к использованию компонента.

    Ни бейджа статуса, ни кропа источника, ни таблицы точности: у читателя
    задача «встроить», а не «проверить». Всё, что нужно для встраивания —
    как выглядит, где встречается, какие варианты и как на него сослаться.
    """
    meta = [card["categoryLabel"], card["key"],
            f'{card["occurrences"]}× на сайте']
    if card["variantCount"] > 1:
        meta.append(f'вариантов: {card["variantCount"]}')
    parts = [f'<article class="comp" id="c-{_esc(card["key"])}"'
             f' data-accuracy="{_esc(card["accuracy"])}"'
             f' data-component-key="{_esc(card["key"])}">',
             '<header><div>'
             f'<h4>{_esc(card["name"])}</h4>'
             f'<div class="meta">{_esc(" · ".join(part for part in meta if part))}</div>'
             '</div></header>']

    if card["usage"]:
        parts.append(f'<p class="use">{_esc(card["usage"])}</p>')

    renders = card["renders"]
    if len(renders) == 1:
        parts.append('<div class="panes"><div class="pane">'
                     + _stage(renders[0], ir_index) + "</div></div>")
    elif renders:
        parts.append('<h3 style="margin:14px 15px 8px">Варианты</h3><div class="variants">')
        for render in renders:
            style_rows = "".join(
                f"<tr><td>{_esc(name)}</td><td>{_esc(value)}</td></tr>"
                for name, value in (render.get("observedStyle") or {}).items())
            parts.append(
                f'<div class="variant"><b>{_esc(render["label"])}'
                f'<small>×{_esc(render["observedCount"])}</small></b>'
                + _stage(render, ir_index, max_height=220)
                + (f"<table>{style_rows}</table>" if style_rows else "")
                + "</div>")
        parts.append("</div>")

    if card["states"]:
        items = "".join(f'<li>{_esc(state["label"])} — {_esc(state["description"])}</li>'
                        for state in card["states"])
        parts.append('<div style="padding:0 15px"><h3>Состояния</h3>'
                     f'<ul class="states">{items}</ul>'
                     '<p class="lead">Состояния не наблюдались в источнике: статичный захват страницы их не содержит. '
                     'DesignDNA не рисует то, чего не измерил — подтвердите их вручную в редакторе системы.</p></div>')

    parts.append(_snippet(card))

    accessibility = card.get("accessibility") or {}
    parts.append(
        '<div class="foot">'
        f'Блок источника: {_esc(card["sourceBlock"]) or "—"} · селектор <code>{_esc(card["selector"]) or "—"}</code>'
        f'{" · роль " + _esc(accessibility.get("role")) if accessibility.get("role") else ""}'
        f'{" · свойства: " + _esc(", ".join(card["props"])) if card["props"] else ""}'
        "</div>")
    if include_fidelity:
        parts.append(_accuracy_note(card))
    parts.append("</article>")
    return "".join(parts)


def _rules_html(document: dict) -> str:
    """Правила встраивания: AI-ревью + siteBrief, без дублей.

    Правила не выдумываются: если ни ревью, ни брифа нет, показан только
    измеренный характер — и об этом сказано прямо.
    """
    guide = document.get("styleGuide") or {}
    review = guide.get("review") or {}
    measured = guide.get("measured") or {}
    brief = document.get("siteBrief") if isinstance(document.get("siteBrief"), dict) else {}
    do_list = list(dict.fromkeys(_as_list(review.get("doRules")) + _as_list(brief.get("doRules"))))
    dont_list = list(dict.fromkeys(_as_list(review.get("dontRules")) + _as_list(brief.get("dontRules"))))

    parts = ['<section id="rules"><header><h2>Правила</h2>'
             '<p class="lead">По ним новый компонент вписывается в существующий продукт, '
             'а не выглядит вставкой из другого сайта.</p></header>']

    labels = [("tone", "Тон"), ("density", "Плотность"), ("cornerCharacter", "Формы"),
              ("colorUsage", "Цвет"), ("typographyCharacter", "Типографика"), ("imageryStyle", "Изображения")]
    rows = _kv_rows([(label, " ".join(str(review.get(field) or "").split())) for field, label in labels])
    if rows:
        parts.append(rows)

    if do_list or dont_list:
        do_rules = "".join(f"<li>{_esc(rule)}</li>" for rule in do_list)
        dont_rules = "".join(f"<li>{_esc(rule)}</li>" for rule in dont_list)
        parts.append('<div class="rules" style="margin-top:18px">'
                     f'<div class="do"><h3>Делать</h3><ul>{do_rules}</ul></div>'
                     f'<div class="dont"><h3>Не делать</h3><ul>{dont_rules}</ul></div></div>')
    elif not rows:
        chips = "".join(f'<span class="chip"><small>{_esc(name)}</small>{_esc(value)}</span>'
                        for name, value in measured.items())
        parts.append(f'<div class="chips">{chips}</div>'
                     '<p class="lead" style="margin-top:12px">Правил в документе пока нет — показан только '
                     'измеренный характер. Правила не выдумываются: пока сайт не описан, их здесь не будет.</p>')
    parts.append("</section>")
    return "".join(parts)


def _code_block(anchor: str, title: str, body: str, language: str = "") -> str:
    return (f'<div class="codehead"><h3 style="margin:0">{_esc(title)}</h3>'
            f'<button class="copy" data-target="{_esc(anchor)}">Копировать</button></div>'
            f'<pre id="{_esc(anchor)}">{_esc(body)}</pre>')


def _code_html(document: dict) -> str:
    tailwind = json.dumps(tailwind_theme(document), ensure_ascii=False, indent=2)
    figma = json.dumps(figma_tokens(document), ensure_ascii=False, indent=2)
    return ('<section id="code"><header><h2>Код</h2>'
            '<p class="lead">Значения те же, что на странице — они не переписаны руками, а собраны из документа системы.</p></header>'
            + _code_block("code-tokens", "tokens.css", tokens_css(document))
            + _code_block("code-tailwind", "tailwind.config — theme", tailwind)
            + _code_block("code-figma", "design-tokens.json (W3C / Tokens Studio)", figma)
            + "</section>")


VIEWPORTS = (("desktop", "Desktop"), ("tablet", "Tablet"), ("mobile", "Mobile"))


def _viewport_bar(active: str) -> str:
    buttons = "".join(
        f'<button type="button" data-vp="{_esc(key)}" '
        f'aria-pressed="{"true" if key == active else "false"}">{_esc(label)}</button>'
        for key, label in VIEWPORTS)
    return f'<div class="vpbar" role="group" aria-label="Вьюпорт">{buttons}</div>'


def _components_html(cards: list[dict], ir_index: dict, *, viewport: str = "desktop",
                     include_fidelity: bool = False) -> str:
    """«Компоненты»: каждый мастер как готовый к вставке блок, по категориям."""
    groups: dict[str, list[dict]] = {}
    for card in cards:
        groups.setdefault(card["categoryLabel"] or "Компоненты", []).append(card)

    parts = ['<section id="components"><header>'
             '<div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap">'
             '<div><h2>Компоненты</h2>'
             '<p class="lead">Готовые блоки сайта: возьмите нужный, сошлитесь на его мастер и наполните '
             'своим содержимым. Каждый отрисован движком редактора из точного захвата страницы.</p></div>'
             + _viewport_bar(viewport) + '</div></header>']
    if not cards:
        parts.append('<p class="lead">В документе нет мастеров — соберите UI Kit из Source.</p></section>')
        return "".join(parts)
    for label, items in groups.items():
        parts.append(f"<h3>{_esc(label)}</h3>")
        parts.extend(_component_html(card, ir_index, include_fidelity=include_fidelity)
                     for card in items)
    parts.append("</section>")
    return "".join(parts)


def render_styleguide(document: dict, *, include_proof: bool = True,
                      include_review_components: bool = True,
                      viewport: str = "desktop",
                      generated_at: str = "",
                      max_bytes: int = DEFAULT_MAX_BYTES,
                      include_fidelity: bool = False) -> tuple[str, dict]:
    """Документ дизайн-системы → (самодостаточный HTML, отчёт сборки).

    Страница — документ для встраивания: стиль сайта, токены, все компоненты,
    правила, код. Верификационной обвязки (кроп источника, таблицы точности,
    бейджи «нужна проверка», пулы ревью) на ней нет.

    `include_review_components` сохранён ради совместимости и трактуется как
    всегда включённый: мастер «на ревью» — такой же точный захват сайта.
    `include_proof` игнорируется: кроп источника не рендерится ни при каких
    значениях. `include_fidelity=True` добавляет к карточке компактную сноску
    с процентами — и только её.

    Документ не мутируется. Страница не делает ни одного внешнего запроса:
    шрифты, картинки и движок рендера встроены.
    """
    source = copy.deepcopy(document)
    faces = collect_font_faces(source)
    font_css, font_specs, font_warnings = inline_font_css(faces)
    cards, card_warnings, proof_bytes = component_cards(
        source, include_proof=False, include_review=True, viewport=viewport)

    # IR складываем в один индекс: одинаковые мастера не дублируются в payload.
    irs: dict[str, dict] = {}
    ir_index: dict[int, str] = {}
    for card in cards:
        for render in card["renders"]:
            key = f"ir{len(irs)}"
            irs[key] = render["ir"]
            ir_index[id(render["ir"])] = key

    warnings = font_warnings + card_warnings
    report = {
        "componentCount": len(cards),
        "fontFaceCount": len(font_specs),
        "proofBytes": proof_bytes,
        "warnings": warnings,
    }

    summary = dsdoc.summary(source)
    url = ""
    for ref in source.get("sourceRefs") or []:
        if isinstance(ref, dict) and ref.get("url"):
            url = str(ref["url"])
            break

    stats = [(str(summary["catalogComponents"]), "компонентов"),
             (str(summary["catalogVariants"]), "вариантов"),
             (str(len(((source.get("styleGuide") or {}).get("tokens") or {}))), "токенов"),
             (str(len(font_specs)), "шрифтов встроено")]

    body = [
        _style_html(source, url=url, generated_at=generated_at, stats=stats),
        _foundations_html(source),
        _components_html(cards, ir_index, viewport=viewport, include_fidelity=include_fidelity),
        _rules_html(source),
        _code_html(source),
    ]

    payload = json.dumps({"irs": irs, "fontSpecs": font_specs, "viewport": viewport},
                         ensure_ascii=False).replace("</", "<\\/")
    engine_js = ENGINE_JS.read_text(encoding="utf-8") if ENGINE_JS.is_file() else ""
    if not engine_js:
        warnings.append("движок рендера не найден — компоненты не отрисуются")

    toc = "".join(
        f'<a href="#{anchor}">{_esc(label)}</a>' for anchor, label in (
            ("style", "Стиль сайта"), ("tokens", "Токены"), ("components", "Компоненты"),
            ("rules", "Правила"), ("code", "Код")))

    html_text = (
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{_esc(source.get('name') or 'UI Kit')}</title>"
        # Оба синглтона рендерера создаём заранее и в этом порядке: он найдёт
        # их по id, не создаст <link> на Google Fonts, и наши встроенные
        # шрифты объявлены ПОСЛЕ — значит выигрывают по порядку документа.
        "<style id=\"ir-fonts\"></style>"
        "<style id=\"ir-fontfaces\"></style>"
        f"<style id=\"ddna-fonts\">{font_css}</style>"
        f"<style>{PAGE_CSS}</style></head><body>"
        f'<div class="wrap"><nav class="toc">{toc}</nav><main>{"".join(body)}</main></div>'
        f'<script type="application/json" id="ddna-payload">{payload}</script>'
        f"<script>{engine_js}</script>"
        f"<script>{BOOTSTRAP_JS}</script>"
        "</body></html>")

    report["bytes"] = len(html_text.encode("utf-8"))
    if report["bytes"] > max_bytes:
        raise ValueError(f"страница получилась {report['bytes'] // 1_000_000} МБ — "
                         f"больше лимита {max_bytes // 1_000_000} МБ")
    return html_text, report
