"""AI-ревью мастеров дизайн-системы: агент вместо пользователя.

Детерминированный fidelity-гейт (pixel similarity ≥ 95 и т. д.) отправляет
мастера, не прошедшие порог, в пул «на ревью». Раньше решение оставалось за
пользователем. Здесь ревью делает vision-агент: он получает кроп оригинала и
рендер мастера, ищет РЕАЛЬНЫЕ дефекты (пропавшие элементы, иной перенос
строк, наложения, чужой шрифт/вес, другие цвета) и выносит вердикт.
Одобренный мастер переезжает в реестр со статусом verified и записью
``fidelity.aiReview``; отклонённый уходит в цикл починки
(`master_repair.repair_master`), где второй агент правит только визуальные
каналы (цвета с альфой, рамки, тени, вес, трекинг, прозрачность) и тот же судья
пересматривает результат. Не починенный мастер остаётся на ревью с конкретными
дефектами. Геометрию, текст и состав узлов не меняет никто: это точная копия
источника.
"""
from __future__ import annotations

import base64
import copy
import json
import math
import re
from typing import Any, Callable

from .document import content_hash, preview_ir_for_master

REVIEW_SYSTEM = (
    "You are a meticulous design-system QA reviewer. You compare a screenshot crop of the ORIGINAL website "
    "component with a RENDER of the reconstructed master. The master must be usable as an exact component: "
    "same elements, same text and line breaks, same font family and weight, same colors, spacing and radii. "
    "Ignore sub-pixel anti-aliasing, 1–2px shifts and JPEG noise. Report only real, visible defects. "
    "Return ONE JSON object: {\"approved\": true|false, \"score\": 0-100, \"summary\": \"…\", "
    "\"defects\": [{\"severity\": \"critical|major|minor\", \"what\": \"…\", \"where\": \"…\"}]}. "
    "Approve when there are no critical/major defects."
)

APPROVE_MIN_SCORE = 85


def review_candidates(document: dict) -> list[tuple[str, dict]]:
    """Компоненты пула «на ревью», у которых есть источник для сравнения."""
    out: list[tuple[str, dict]] = []
    assets = document.get("referenceAssets") if isinstance(document.get("referenceAssets"), dict) else {}
    for key, comp in (document.get("reviewComponents") or {}).items():
        if not isinstance(comp, dict) or not isinstance(comp.get("masterIr"), dict):
            continue
        fidelity = comp.get("fidelity") if isinstance(comp.get("fidelity"), dict) else {}
        if isinstance(fidelity.get("aiReview"), dict) and fidelity["aiReview"].get("verdict") == "approved":
            continue
        source_ref = comp.get("sourceRef") if isinstance(comp.get("sourceRef"), dict) else {}
        if not assets.get(source_ref.get("evidenceKey")):
            continue
        out.append((str(key), comp))
    return out


def _preview_size(preview: dict, viewport: str) -> tuple[int, int]:
    root = (preview.get("tree") or [{}])[0]
    frame = root.get("frame") if isinstance(root.get("frame"), dict) else {}
    override = ((root.get("responsive") or {}).get(viewport) or {}).get("frame") or {}
    width = override.get("width") or frame.get("width") or 320
    height = override.get("height") or frame.get("height") or 120
    return max(16, int(round(float(width)))), max(16, int(round(float(height))))


def proof_aligned_preview(comp: dict, viewport: str) -> tuple[dict, int, int]:
    """Match Source crop pixel edges without resizing evidence or the pinned master."""
    preview = preview_ir_for_master(comp["masterIr"])
    width, height = _preview_size(preview, viewport)
    root = (preview.get("tree") or [{}])[0]
    ref = comp.get("sourceRef") or {}
    bounds = (ref.get("boundsByViewport") or {}).get(viewport) or ref.get("bounds") or {}
    values = [bounds.get(key) for key in ("x", "y", "width", "height")]
    if (root.get("id") != "ds-master-preview" or not root.get("children")
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or min(values[:2]) < 0 or min(values[2:]) <= 0):
        return preview, width, height
    x, y, w, h = values
    child = root["children"][0]
    child_frame = {**(child.get("frame") or {}),
                   **(((child.get("responsive") or {}).get(viewport) or {}).get("frame") or {})}
    # Never use the capture canvas to hide a changed master boundary. A resized
    # candidate keeps its own extent, so the existing size gate still rejects it.
    if any(type(child_frame.get(k)) not in (int, float) or abs(child_frame[k] - expected) > .001
           for k, expected in (("width", w), ("height", h))):
        return preview, width, height
    # proof_crop uses int(left/top/right/bottom), not round(width/height).
    # Preserve the fractional origin inside that pixel-aligned capture canvas.
    width, height = max(1, int(x + w) - int(x)), max(1, int(y + h) - int(y))
    root.setdefault("frame", {}).update(width=width, height=height)
    root.setdefault("responsive", {}).setdefault(viewport, {}).setdefault("frame", {}).update(width=width, height=height)
    preview.setdefault("responsive", {}).setdefault("viewports", {})[viewport] = {"width": width, "height": height}
    child = root["children"][0]
    offset = {"x": x - int(x), "y": y - int(y)}
    child.setdefault("frame", {}).update(offset)
    child.setdefault("responsive", {}).setdefault(viewport, {}).setdefault("frame", {}).update(offset)
    return preview, width, height


def render_master_png(page, comp: dict, viewport: str) -> bytes:
    """Рендер мастера тем же движком, что и fidelity harness (шрифты источника инлайнятся)."""
    import fidelity_harness
    import scraper

    preview, width, height = proof_aligned_preview(comp, viewport)
    resolved, errors = scraper.resolve_ir_blobs(preview)
    if errors:
        raise RuntimeError("blob resolve failed: " + "; ".join(errors[:3]))
    return fidelity_harness._render_block_png(page, resolved, viewport, width, height)


def build_prompt(comp: dict, viewport: str, *, include_capture_metrics: bool = True) -> str:
    reasons = list(((comp.get("review") or {}).get("reasons")) or [])
    fidelity = comp.get("fidelity") if isinstance(comp.get("fidelity"), dict) else {}
    metrics = (fidelity.get("viewports") or {}).get(viewport) or {}
    if not include_capture_metrics:
        context = (
            "These are fresh, isolated renders of this component. Source capture metrics were measured "
            "earlier inside the full page and are not measurements of these images. "
            "Judge only visible differences in the supplied ORIGINAL and current RENDER for this viewport. "
            "Do not infer a defect or an offset from historical capture diagnostics.\n"
        )
    elif fidelity.get("basis") == "component-source-fidelity-harness":
        context = (
            f"Component gate reasons: {'; '.join(reasons) or 'none'}.\n"
            f"Historical Source capture: pixel similarity {metrics.get('pixelSimilarity')}, bbox p95 {metrics.get('bboxP95')}px, "
            f"origin error {metrics.get('originError')}px, paint coverage {metrics.get('paintCoverage')}.\n"
        )
    else:
        # Block/legacy metrics triggered review but cannot locate a defect in this crop.
        # Passing them as component measurements makes the judge invent identical offsets.
        context = (
            "This candidate was flagged by Source block metrics, not measurements of this component. "
            "Judge the two component images directly; do not infer a positional offset or a visual "
            "defect from a block-level gate. Report only differences visible in this viewport.\n"
        )
    return (
        f"Component: {comp.get('name') or comp.get('componentKey')} ({comp.get('category') or 'component'}), "
        f"viewport {viewport}.\n"
        + context +
        "Image 1 = ORIGINAL crop from the site screenshot. Image 2 = RENDER of the reconstructed master. "
        "Decide whether the master reproduces the original faithfully enough to ship as an exact component."
    )


def parse_verdict(raw: str) -> dict:
    match = re.search(r"\{.*\}", str(raw or ""), re.S)
    if not match:
        raise ValueError("review response contains no JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("review response is not an object")
    defects = []
    for item in parsed.get("defects") or []:
        if isinstance(item, dict) and item.get("what"):
            defects.append({
                "severity": str(item.get("severity") or "minor")[:12],
                "what": " ".join(str(item["what"]).split())[:240],
                "where": " ".join(str(item.get("where") or "").split())[:120],
            })
        elif isinstance(item, str) and item.strip():
            defects.append({"severity": "minor", "what": item.strip()[:240], "where": ""})
    try:
        score = max(0, min(100, int(round(float(parsed.get("score") or 0)))))
    except (TypeError, ValueError):
        score = 0
    blocking = any(d["severity"] in ("critical", "major") for d in defects)
    approved = bool(parsed.get("approved")) and not blocking and score >= APPROVE_MIN_SCORE
    return {
        "approved": approved,
        "score": score,
        "summary": " ".join(str(parsed.get("summary") or "").split())[:400],
        "defects": defects[:12],
    }


def apply_verdict(document: dict, key: str, verdict: dict, *, provider: str, viewport: str) -> dict:
    """Одобрено → в реестр как verified; отклонено → остаётся на ревью с дефектами."""
    review_pool = document.setdefault("reviewComponents", {})
    comp = review_pool.get(key)
    if not isinstance(comp, dict):
        return document
    fidelity = comp.setdefault("fidelity", {})
    fidelity["aiReview"] = {
        "verdict": "approved" if verdict["approved"] else "rejected",
        "score": verdict["score"],
        "summary": verdict["summary"],
        "defects": verdict["defects"],
        "provider": str(provider)[:40],
        "viewport": viewport,
        "deterministicReasons": list(((comp.get("review") or {}).get("reasons")) or []),
    }
    if verdict["approved"]:
        fidelity["status"] = "verified"
        comp["status"] = "verified"
        comp["confirmed"] = True
        comp["review"] = {"kind": "ai-fidelity", "reasons": [], "verdict": "approved",
                          "summary": verdict["summary"]}
        review_pool.pop(key, None)
        components = document.setdefault("components", {})
        target = key
        family = str(comp.get("componentKey") or key)
        if family not in components and family != key:
            target = family
            comp["componentKey"] = family
        components[target] = comp
    else:
        comp["status"] = "needs-review"
        comp["review"] = {
            "kind": "ai-fidelity", "verdict": "rejected", "summary": verdict["summary"],
            "reasons": [f"{d['severity']}: {d['what']}" + (f" ({d['where']})" if d["where"] else "")
                        for d in verdict["defects"]] or [verdict["summary"] or "AI review rejected the master"],
        }
    return document


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def run(document: dict, *, provider: str = "auto", viewport: str = "desktop", max_components: int = 8,
        chat_vision: Callable[..., str] | None = None,
        render: Callable[[Any, dict, str], bytes] | None = None,
        repair: bool = True, chat_repair: Callable[..., str] | None = None,
        repair_rounds: int = 3) -> tuple[dict, list[dict]]:
    """Прогнать AI-ревью по кандидатам. Возвращает (обновлённый документ, вердикты).

    Отклонённый мастер не остаётся ждать человека: при ``repair`` включается
    цикл `master_repair.repair_master` — второй агент чинит визуальные каналы, а
    тот же судья пересматривает результат.
    """
    from . import master_repair, styleguide

    updated = copy.deepcopy(document)
    candidates = review_candidates(updated)[:max(1, int(max_components))]
    results: list[dict] = []
    if not candidates:
        return updated, results
    if chat_vision is None:
        import llm_client
        chat_vision = lambda images, prompt: llm_client.chat_vision(  # noqa: E731
            provider if provider != "auto" else "auto", images, prompt, REVIEW_SYSTEM, 0.1, role="quality_judge")
    if chat_repair is None:
        import llm_client
        chat_repair = lambda images, prompt: llm_client.chat_vision(  # noqa: E731
            provider if provider != "auto" else "auto", images, prompt,
            master_repair.REPAIR_SYSTEM, 0.1, role="quality_judge")
    render_fn = render or render_master_png

    def _review_all(page) -> None:
        for key, comp in candidates:
            entry: dict[str, Any] = {"key": key, "name": comp.get("name")}
            try:
                original, _bytes, note = styleguide.proof_crop(updated, comp, viewport, budget_left=4_000_000)
                if not original:
                    raise RuntimeError(note or "no original crop")
                master_png = render_fn(page, comp, viewport)
                raw = chat_vision([original, _data_url(master_png)], build_prompt(comp, viewport))
                verdict = parse_verdict(raw)
                repair_result = None
                if repair and not verdict["approved"]:
                    repair_result = master_repair.repair_master(
                        updated, key, comp, verdict, chat_repair=chat_repair, chat_vision=chat_vision,
                        render=render_fn, viewport=viewport, max_rounds=repair_rounds,
                        page=page, original=original)
                    verdict = repair_result["verdict"]
                apply_verdict(updated, key, verdict, provider=provider, viewport=viewport)
                if repair_result is not None:
                    # apply_verdict переписывает aiReview целиком — след починки
                    # дописываем поверх итоговой записи.
                    master_repair.annotate_review(comp, repair_result)
                entry.update(verdict)
                entry["repaired"] = bool(repair_result and repair_result["repaired"])
                entry["rounds"] = int(repair_result["rounds"]) if repair_result else 0
            except Exception as exc:  # noqa: BLE001 — один сбой не должен ронять ревью остальных
                entry.update({"approved": False, "repaired": False, "rounds": 0,
                              "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            results.append(entry)

    if render is not None:
        _review_all(None)
    else:
        import scraper
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = scraper.launch_chromium(playwright)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
                _review_all(page)
            finally:
                browser.close()
    updated["status"] = "draft"
    updated["contentHash"] = content_hash(updated)
    return updated, results
