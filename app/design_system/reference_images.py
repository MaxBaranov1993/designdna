"""Визуальные референсы генератора из evidence дизайн-системы.

Текстовый профиль ДС описывает токены и анатомию, но не показывает, как
секции исходника выглядят целиком: ритм, воздух, декоративные элементы.
Здесь из `referenceAssets` (скриншоты исходных блоков) и границ мастеров
собираются до трёх картинок: блоки, в которых живут самые релевантные
брифу мастера, и кроп самого мастера. Картинки уходят частями `image_url`
(data:image/jpeg) — их принимают все транспорты: OpenAI Responses,
`claude -p` (файл + Read), Codex app-server (localImage) и `codex exec -i`.

Выбор кандидатов дешёвый и логируется всегда; декодирование PNG и сжатие в
JPEG выполняются только когда промпт действительно уходит модели.
"""
from __future__ import annotations

import base64
import io
from typing import Any

from . import styleguide

MAX_IMAGES = 3
MAX_TOTAL_BYTES = 2_500_000
BLOCK_MAX_WIDTH = 1100
BLOCK_MAX_HEIGHT = 1500
JPEG_QUALITY = 76
PAGE_SURFACES = ("landing", "page", "website", "site")


def _component_lookup(document: dict, key: str) -> dict | None:
    components = document.get("components") if isinstance(document.get("components"), dict) else {}
    direct = components.get(key)
    if isinstance(direct, dict):
        return direct
    return next((c for c in components.values() if isinstance(c, dict) and str(c.get("componentKey") or "") == key), None)


def _evidence_for(document: dict, component: dict) -> tuple[str, dict | None]:
    source_ref = component.get("sourceRef") if isinstance(component.get("sourceRef"), dict) else {}
    key = str(source_ref.get("evidenceKey") or "")
    evidence = (document.get("referenceAssets") or {}).get(key) if key else None
    if not isinstance(evidence, dict):
        return "", None
    previews = evidence.get("referencePreviews") if isinstance(evidence.get("referencePreviews"), dict) else {}
    if not any(previews.get(viewport) for viewport in ("desktop", "tablet", "mobile")):
        return "", None
    return key, evidence


def select_candidates(document: dict, context: dict, *, surface: str = "", limit: int = MAX_IMAGES) -> list[dict]:
    """Кандидаты в порядке важности: для страницы — сначала целые блоки,
    для компонента — сначала кроп самого релевантного мастера."""
    components = [c for c in (context.get("components") or []) if isinstance(c, dict)]
    blocks: list[dict] = []
    crops: list[dict] = []
    seen_blocks: set[str] = set()
    seen_names: set[str] = set()
    for component in components:
        key = str(component.get("componentKey") or "")
        evidence_key, evidence = _evidence_for(document, component)
        if not evidence_key or evidence is None:
            continue
        block_name = str(evidence.get("sourceBlock") or evidence_key)
        # Один и тот же блок бывает захвачен дважды (повторный импорт): вторая
        # копия не добавляет информации, а ревью-мастера одного блока — тем более.
        if evidence_key not in seen_blocks and block_name not in seen_names:
            seen_blocks.add(evidence_key)
            seen_names.add(block_name)
            blocks.append({"kind": "block", "evidenceKey": evidence_key, "componentKey": key,
                           "label": f"блок «{block_name}» исходного сайта целиком (desktop); в нём живёт мастер {key}"})
        if len(crops) < 4:
            crops.append({"kind": "crop", "evidenceKey": evidence_key, "componentKey": key,
                          "label": f"мастер {key} крупным планом (кроп исходного скриншота)"})
    page_like = str(surface or "") in PAGE_SURFACES
    # Страница: разные блоки источника показывают ритм и композицию лучше, чем
    # три кропа одной секции; компонент: сначала сам мастер крупно, затем его блок.
    ordered = (blocks[:3] + crops[:1] + blocks[3:] + crops[1:]) if page_like \
        else (crops[:1] + blocks[:1] + crops[1:2] + blocks[1:] + crops[2:])
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in ordered:
        ident = (item["kind"], item["evidenceKey"] if item["kind"] == "block" else item["componentKey"])
        if ident in seen:
            continue
        seen.add(ident)
        out.append(item)
        if len(out) >= max(0, int(limit)):
            break
    return out


def _block_image(evidence: dict, budget_left: int) -> tuple[str | None, int, str | None]:
    previews = evidence.get("referencePreviews") if isinstance(evidence.get("referencePreviews"), dict) else {}
    reference = previews.get("desktop") or previews.get("tablet") or previews.get("mobile")
    raw = styleguide._decode_preview(reference)
    if not raw:
        return None, 0, "скриншот блока не удалось прочитать"
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return None, 0, f"скриншот не декодируется: {exc}"
    if image.height > BLOCK_MAX_HEIGHT:
        image = image.crop((0, 0, image.width, BLOCK_MAX_HEIGHT))
    if image.width > BLOCK_MAX_WIDTH:
        ratio = BLOCK_MAX_WIDTH / image.width
        image = image.resize((BLOCK_MAX_WIDTH, max(1, int(image.height * ratio))))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    payload = buffer.getvalue()
    if len(payload) > budget_left:
        return None, 0, "скриншот пропущен: превышен бюджет изображений"
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii"), len(payload), None


def render(document: dict, candidates: list[dict], *, max_total_bytes: int = MAX_TOTAL_BYTES) -> list[dict]:
    """Декодирует кандидатов → [{"part": {type: image_url,…}, "label", "bytes"}].
    Кандидат, которого не удалось отрисовать, получает `skipped` с причиной."""
    rendered: list[dict] = []
    budget = int(max_total_bytes)
    for candidate in candidates:
        if candidate.get("kind") == "block":
            evidence = (document.get("referenceAssets") or {}).get(str(candidate.get("evidenceKey") or ""))
            url, size, note = _block_image(evidence, budget) if isinstance(evidence, dict) else (None, 0, "нет evidence")
        else:
            component = _component_lookup(document, str(candidate.get("componentKey") or ""))
            url, size, note = (styleguide.proof_crop(document, component, budget_left=budget)
                               if component is not None else (None, 0, "нет компонента"))
        if not url:
            candidate["skipped"] = note or "не отрисован"
            continue
        budget -= size
        rendered.append({"part": {"type": "image_url", "image_url": {"url": url}},
                         "label": str(candidate.get("label") or ""), "bytes": size,
                         "kind": candidate.get("kind"), "componentKey": candidate.get("componentKey")})
    return rendered


def prompt_note(rendered: list[dict]) -> str:
    if not rendered:
        return ""
    lines = ["## Визуальные референсы (изображения приложены к этому сообщению)"]
    for index, item in enumerate(rendered, start=1):
        lines.append(f"{index}. {item['label']}")
    lines.append(
        "Перенимай из них композицию и ритм секций, воздух, толщину и цвет рамок, форму бейджей и "
        "кнопок, моно-лейблы, стрелки, точки статуса и фоновые градиенты. Это образцы характера, "
        "а не макет для копирования: тексты, контент и порядок секций — по брифу и описанию сайта."
    )
    return "\n".join(lines)


def describe(candidates: list[dict], rendered: list[dict] | None = None) -> list[dict[str, Any]]:
    """Компактное описание для generationLog: что выбрано, что приложено, что пропущено."""
    attached = {(item.get("kind"), item.get("componentKey")) for item in rendered or []}
    out = []
    for candidate in candidates:
        entry = {"kind": candidate.get("kind"), "componentKey": candidate.get("componentKey"),
                 "label": candidate.get("label")}
        if rendered is not None:
            entry["attached"] = (candidate.get("kind"), candidate.get("componentKey")) in attached
        if candidate.get("skipped"):
            entry["skipped"] = candidate["skipped"]
        out.append(entry)
    return out
