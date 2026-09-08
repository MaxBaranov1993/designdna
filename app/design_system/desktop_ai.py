"""Server-owned, staged DS prompts for subscription desktop chat; no LLM calls.

Include ``router`` in the application once. POST prepare accepts document,
operation (organize/style-review/master-review), selected desktop provider,
reasoningEffort and repair. Send every ready task's messages to desktop chat.
POST apply accepts prepareId, documentHash, the current document and responses
[{taskId, output: raw JSON string}]. It saves a draft and returns document,
summary, results, complete and nextPreparation. Continue with the returned
document and nextPreparation until complete. Unsupported tasks have no response.

Preparations are single-use, process-local, bounded and expire after 30 minutes.
Restart/expiry requires prepare again. Repairs get one bounded attempt followed
by fresh review of every visible viewport. All three viewports are accounted
for; proven Source-hidden viewports are listed in optional skippedViewports
instead of tasks and retain deterministic evidence (never an AI approval).
Unapproved candidate IR is never saved.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
import threading
import time
import uuid
from contextlib import contextmanager, ExitStack, nullcontext
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from . import document as dsdoc, master_repair, master_review, organizer, store, style_review, styleguide

router = APIRouter(prefix="/api/design-system/desktop-ai", tags=["design-system"])
VIEWPORTS = ("desktop", "tablet", "mobile")
TTL_SECONDS = 1800
MAX_PREPARATIONS = 64
_LOCK = threading.RLock()
_PREPARATIONS: dict[str, dict] = {}


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict
    operation: Literal["organize", "style-review", "master-review"]
    provider: Literal["codex", "claude", "openai", "astra"]
    reasoningEffort: Literal["medium", "high", "max"] = "high"
    repair: bool = True


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: StrictStr
    output: StrictStr = Field(max_length=2_000_000)


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prepareId: StrictStr
    documentHash: StrictStr
    document: dict
    responses: list[TaskResponse]


class InvalidAIOutput(ValueError):
    """An individual response can be corrected without consuming its preparation."""

    def __init__(self, error: Exception, task: dict, index: int, stage: str):
        message = str(error)[:500]
        super().__init__(message)
        self.detail = {"code": "invalid-ai-output", "message": message,
                       "taskId": task["id"], "stage": stage, "component": task["componentKey"],
                       "path": f"responses[{index}].output", "retryable": True}


def document_hash(document: dict) -> str:
    """Hash actual submitted content, including revision/status and evidence.

    Do not trust document.contentHash: the publishing hash omits some fields
    that must invalidate an in-flight desktop review.
    """
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _registry_hash(document: dict) -> str | None:
    if not store._db_path().exists():
        return None
    current = store.get_revision(document["id"], 0)
    return document_hash(current) if current is not None else None


def _check_document(document: dict) -> None:
    if not isinstance(document.get("id"), str) or not document["id"].strip():
        raise ValueError("document.id is required")
    if not isinstance(document.get("name"), str) or not document["name"].strip():
        raise ValueError("document.name is required")
    for field in ("components", "reviewComponents", "suggestions", "referenceAssets"):
        if field in document and not isinstance(document[field], dict):
            raise ValueError(f"document.{field} must be an object")
    document_hash(document)
    errors = []

    def check_master(value: Any, path: str, *, inherited_observed: bool = False) -> None:
        if not isinstance(value, dict):
            return
        observed = value.get("origin", "observed" if inherited_observed else "") == "observed"
        master = value.get("masterIr")
        ref = value.get("sourceRef")
        # Unpinned suggestions/missing masters remain explicit review cases.
        # A supplied immutable pin, however, cannot be downgraded to missing
        # visual evidence and then persisted over a valid registry snapshot.
        if (observed and isinstance(master, dict) and isinstance(ref, dict)
                and "masterHash" in ref and ref["masterHash"] != dsdoc.content_hash(master)):
            errors.append({"code": "master-hash-mismatch", "path": f"{path}.sourceRef.masterHash",
                           "masterPath": f"{path}.masterIr",
                           "message": "Observed master differs from its supplied Source hash; restore or rebuild from Source"})
        for pool in ("variants", "states"):
            nested_pool = value.get(pool) or {}
            if not isinstance(nested_pool, dict):
                raise ValueError(f"{path}.{pool} must be an object")
            for key, nested in nested_pool.items():
                check_master(nested, f"{path}.{pool}[{json.dumps(str(key), ensure_ascii=False)}]",
                             inherited_observed=observed)

    for pool in ("components", "reviewComponents", "suggestions"):
        for key, comp in (document.get(pool) or {}).items():
            check_master(comp, f"document.{pool}[{json.dumps(str(key), ensure_ascii=False)}]")
    if errors:
        raise HTTPException(422, {"code": "invalid-master-pins", "message": "Invalid immutable Source master pins",
                                  "errors": errors})


def _json_output(raw: str) -> dict:
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    parsed = json.loads(text, object_pairs_hook=pairs)
    if not isinstance(parsed, dict):
        raise ValueError("Response must be one JSON object")
    # Also rejects NaN, Infinity and overflowing exponents in nested values.
    document_hash(parsed)
    return parsed


def _verdict(parsed: dict) -> dict:
    if set(parsed) != {"approved", "score", "summary", "defects"}:
        raise ValueError("Verdict requires exactly approved, score, summary, defects")
    score = parsed["score"]
    if (type(parsed["approved"]) is not bool or type(score) not in (int, float)
            or not math.isfinite(score) or not 0 <= score <= 100):
        raise ValueError("Verdict requires a boolean approved and finite score in 0..100")
    if not isinstance(parsed["summary"], str) or not parsed["summary"].strip():
        raise ValueError("Verdict summary is required")
    defects = parsed["defects"]
    if not isinstance(defects, list) or len(defects) > 12:
        raise ValueError("defects must be an array of at most 12 entries")
    for defect in defects:
        if (not isinstance(defect, dict) or set(defect) != {"severity", "what", "where"}
                or defect["severity"] not in ("minor", "major", "critical")
                or not isinstance(defect["what"], str) or not defect["what"].strip()
                or not isinstance(defect["where"], str)):
            raise ValueError("Malformed defect; severity must be minor, major or critical")
    return master_review.parse_verdict(json.dumps(parsed))


def _organize_messages(document: dict) -> list[dict]:
    baseline = organizer.deterministic_catalog(document)
    data = {
        "task": "Organize exact Source-derived components; metadata only",
        "allowedSectionKeys": sorted(organizer.SECTION_KEYS),
        "rules": ["Return every input key exactly once, including review masters.",
                  "Keep variants with their family. Never change IR, identity, status, fidelity or pools."],
        "components": [organizer._descriptor(key, comp, baseline)
                       for key, comp in organizer._catalog_components(document).items()],
        "output": {"components": [{"key": "input key", "sectionKey": "allowed section",
                    "family": "family", "role": "role", "label": "label", "order": 0,
                    "confidence": 1.0, "rationale": "reason"}]},
    }
    return [{"role": "system", "content": "You organize a design-system catalog. Return JSON only."},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]


def _catalog(parsed: dict, document: dict, provider: str, effort: str) -> dict:
    expected = set(organizer._catalog_components(document))
    items = parsed.get("components")
    if set(parsed) != {"components"} or not isinstance(items, list):
        raise ValueError("Organizer response requires a components array")
    seen = set()
    for item in items:
        fields = {"key", "sectionKey", "family", "role", "label", "order", "confidence", "rationale"}
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Malformed organizer entry")
        for field in fields - {"order", "confidence"}:
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"Organizer {field} must be nonempty text")
        if item["key"] not in expected or item["key"] in seen:
            raise ValueError("Unknown or duplicate organizer key")
        if item["sectionKey"] not in organizer.SECTION_KEYS:
            raise ValueError("Unknown sectionKey; deterministic fallback is disabled")
        if (type(item["order"]) is not int or type(item["confidence"]) not in (int, float)
                or not 0 <= item["confidence"] <= 1):
            raise ValueError("Malformed organizer order/confidence")
        seen.add(item["key"])
    if seen != expected:
        raise ValueError("Organizer must return every input key exactly once")
    catalog = organizer._validate_ai_plan(parsed, document, organizer.deterministic_catalog(document), effort)
    catalog["organizer"] = {"kind": "ai", "provider": provider, "model": None,
                            "transport": "desktop-chat", "reasoningEffort": effort}
    return catalog


def _task(kind: str, key: str | None = None, viewport: str | None = None) -> dict:
    return {"id": uuid.uuid4().hex, "kind": kind, "componentKey": key, "viewport": viewport,
            "status": "unsupported", "messages": [], "reason": "Not prepared"}


def _vision_messages(system: str, prompt: str, original: str, png: bytes) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": original}},
        {"type": "image_url", "image_url": {"url": master_review._data_url(png)}},
    ]}]


@contextmanager
def _renderer(render=None):
    if render is not None:
        yield None, render
        return
    import scraper
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            yield page, master_review.render_master_png
        finally:
            browser.close()


def _hidden_evidence(document: dict, comp: dict, viewport: str) -> dict | None:
    """Prove Source-root absence, never infer it from a blank image or missing crop.

    Source merge records explicit false visibility, and DS extraction omits
    bounds for that viewport. Ancestor-only absence is not provable after
    extraction and intentionally remains unsupported.
    """
    if not isinstance(comp, dict) or comp.get("origin") != "observed":
        return None
    master = comp.get("masterIr")
    if not isinstance(master, dict):
        return None
    roots = master.get("tree")
    if not isinstance(roots, list) or len(roots) != 1 or not isinstance(roots[0], dict):
        return None
    root = roots[0]
    override = (root.get("responsive") or {}).get(viewport)
    if not isinstance(override, dict) or override.get("visible") is not False:
        return None
    ref = comp.get("sourceRef") or {}
    revisions = {r.get("revisionHash") for r in document.get("sourceRefs") or [] if isinstance(r, dict)}
    if (not ref.get("sourceRevisionHash") or ref["sourceRevisionHash"] not in revisions
            or not ref.get("sourceKey") or ref["sourceKey"] != root.get("sourceKey")
            or ref.get("masterHash") != dsdoc.content_hash(master)):
        return None
    bounds = ref.get("boundsByViewport")
    if not isinstance(bounds, dict) or viewport in bounds:
        return None  # Explicit absence must not contradict a captured box, including a zero-size box.
    captured = ((master.get("responsive") or {}).get("viewports") or {}).get(viewport)
    evidence = (document.get("referenceAssets") or {}).get(ref.get("evidenceKey")) or {}
    block = (evidence.get("blockSizes") or {}).get(viewport)
    for dimensions in (captured, block):
        if not isinstance(dimensions, dict) or any(
            type(dimensions.get(k)) not in (int, float) or not math.isfinite(dimensions[k]) or dimensions[k] <= 0
            for k in ("width", "height")
        ):
            return None
    reference = (evidence.get("referencePreviews") or {}).get(viewport)
    raw = styleguide._decode_preview(reference)
    if not raw:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
    except Exception:
        return None
    return {"basis": "source-responsive-visibility", "sourceKey": ref["sourceKey"],
            "sourceRevisionHash": ref["sourceRevisionHash"], "masterHash": ref["masterHash"],
            "evidenceKey": ref["evidenceKey"], "viewport": viewport, "visible": False,
            "boundsAbsent": True, "referenceHash": "sha256:" + hashlib.sha256(raw).hexdigest()}


def _proof(document: dict, comp: dict, viewport: str) -> str:
    if not isinstance(comp, dict) or not isinstance(comp.get("masterIr"), dict) or not comp["masterIr"].get("tree"):
        raise ValueError("Missing master IR")
    if comp.get("origin") != "observed":
        raise ValueError("Only observed Source masters are supported")
    ref = comp.get("sourceRef") or {}
    if ref.get("masterHash") != dsdoc.content_hash(comp["masterIr"]):
        raise ValueError("Master is not pinned to its Source hash")
    # Do not ask vision to approve a blank mask when visibility evidence is
    # contradictory or incomplete. Proven hidden roots are handled before this.
    for root in comp["masterIr"]["tree"]:
        if isinstance(root, dict) and (root.get("visible") is False or
                ((root.get("responsive") or {}).get(viewport) or {}).get("visible") is False):
            raise ValueError(f"Hidden {viewport} root lacks consistent Source visibility evidence")
    # A base-master verdict must not implicitly approve independent variants/states.
    for pool in ("variants", "states"):
        for value in (comp.get(pool) or {}).values():
            if isinstance(value, dict) and (value.get("masterIr") or value.get("templateIr")) and value.get("masterRef") != "self":
                raise ValueError(f"Independent {pool} require separate Source review; base approval is unsupported")
    evidence = (document.get("referenceAssets") or {}).get(ref.get("evidenceKey")) or {}
    if not (evidence.get("referencePreviews") or {}).get(viewport):
        raise ValueError(f"Missing {viewport} screenshot; viewport fallback is disabled")
    bounds = (ref.get("boundsByViewport") or {}).get(viewport)
    block = (evidence.get("blockSizes") or {}).get(viewport)
    if not isinstance(bounds, dict) or not isinstance(block, dict):
        raise ValueError(f"Missing measured {viewport} bounds/block size")
    numbers = [bounds.get(k) for k in ("x", "y", "width", "height")] + [block.get(k) for k in ("width", "height")]
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in numbers):
        raise ValueError("Invalid Source bounds")
    x, y, w, h, bw, bh = numbers
    if min(x, y) < 0 or min(w, h, bw, bh) <= 0 or x + w > bw + .5 or y + h > bh + .5:
        raise ValueError("Source crop escapes measured block bounds")
    original, _, note = styleguide.proof_crop(copy.deepcopy(document), copy.deepcopy(comp), viewport,
                                             budget_left=4_000_000)
    if not original or note:
        raise ValueError(note or "Source crop unavailable")
    return original


def _visual_tasks(document: dict, stage: str, components: dict, *, render=None, verdicts=None, renderer_context=None) -> list[dict]:
    tasks = []
    for key, comp in components.items():
        component_tasks = []
        for viewport in VIEWPORTS:
            task = _task(stage, key, viewport)
            hidden = _hidden_evidence(document, comp, viewport)
            if hidden:
                task.update(status="skipped", reason="source-hidden", evidence=hidden)
            component_tasks.append(task)
        if stage == "master-repair":
            # A mobile-only component must be repairable without a desktop crop.
            component_tasks = [next((t for t in component_tasks if t["status"] != "skipped"), component_tasks[0])]
        tasks.extend(component_tasks)
    if not tasks:
        return tasks
    if all(t["status"] == "skipped" for t in tasks):
        return tasks
    try:
        with (nullcontext(renderer_context) if renderer_context is not None else _renderer(render)) as (page, render_fn):
            for task in tasks:
                if task["status"] == "skipped":
                    continue
                key, viewport = task["componentKey"], task["viewport"]
                comp = components[key]
                try:
                    original = _proof(document, comp, viewport)
                    # Blob expansion belongs ONLY to the helper's disposable render copy.
                    png = render_fn(page, copy.deepcopy(comp), viewport)
                    if not isinstance(png, bytes) or not png:
                        raise ValueError("Empty master render")
                    if stage == "master-repair":
                        prompt = master_repair.build_repair_prompt(comp, verdicts[key], viewport,
                                                                  master_repair.describe_nodes(comp["masterIr"]))
                        prompt += "\nAll viewport verdicts: " + json.dumps(verdicts[key].get("viewports", {}))
                        prompt += (
                            "\nStrict response contract: return ONE JSON object with ONLY the key operations. "
                            f"operations must contain at most {master_repair.MAX_OPERATIONS} operations TOTAL "
                            "across all viewports, not per viewport. Prioritize the listed defects within this "
                            "budget; if no safe bounded repair is possible, return {\"operations\": []}. "
                            "Each operation must have exactly these four keys: op, sourceKey, property, value. "
                            "Allowed op values are restore-style and restore-layout only. "
                            "For restore-style, property must be one of "
                            + json.dumps(sorted(master_repair.repairable_props()))
                            + "; for restore-layout, property must be one of "
                            + json.dumps(sorted(master_repair.LAYOUT_PROPS))
                            + ". sourceKey must identify a supplied existing node. Never repeat a "
                            "(sourceKey, property) pair. Do not emit layoutOperation, explanations, or other keys. "
                            "All original safety and value bounds still apply; over-budget or unsupported "
                            "operations reject the entire response and are never truncated."
                        )
                        # Supply all three pairs so a desktop fix cannot ignore a mobile defect.
                        messages = _vision_messages(master_repair.REPAIR_SYSTEM, prompt, original, png)
                        for other in VIEWPORTS:
                            if other == viewport or _hidden_evidence(document, comp, other):
                                continue
                            other_original = _proof(document, comp, other)
                            other_png = render_fn(page, copy.deepcopy(comp), other)
                            messages[1]["content"].extend([
                                {"type": "text", "text": f"{other}: ORIGINAL then current RENDER"},
                                {"type": "image_url", "image_url": {"url": other_original}},
                                {"type": "image_url", "image_url": {"url": master_review._data_url(other_png)}},
                            ])
                    else:
                        messages = _vision_messages(master_review.REVIEW_SYSTEM,
                            master_review.build_prompt(comp, viewport, include_capture_metrics=False), original, png)
                    task.update(status="ready", messages=messages, reason=None)
                except Exception as exc:
                    task["reason"] = f"{type(exc).__name__}: {str(exc)[:240]}"
                    task["error"] = {"code": "source-proof-unavailable", "stage": stage,
                                     "component": key, "path": f"referenceAssets.{(comp.get('sourceRef') or {}).get('evidenceKey', '')}",
                                     "viewport": viewport, "retryable": False,
                                     **getattr(exc, "detail", {})}
    except Exception as exc:
        for task in tasks:
            if task["status"] != "skipped":
                task.update(status="unsupported", messages=[], reason=f"Renderer unavailable: {str(exc)[:240]}")
    return tasks


def _prune() -> None:
    for key, state in list(_PREPARATIONS.items()):
        if state["deadline"] <= time.time():
            del _PREPARATIONS[key]


def _remember(document: dict, settings: dict, stage: str, tasks: list[dict], *, render=None,
              candidates=None, operations=None) -> dict:
    _prune()
    if len(_PREPARATIONS) >= MAX_PREPARATIONS:
        raise HTTPException(503, "Too many pending preparations; finish a pending operation or retry after expiry")
    deadline = time.time() + TTL_SECONDS
    envelope = {"prepareId": uuid.uuid4().hex, "documentHash": document_hash(document),
                "operation": settings["operation"], "provider": settings["provider"],
                "reasoningEffort": settings["reasoningEffort"], "stage": stage,
                "tasks": [t for t in tasks if t["status"] != "skipped"],
                "expiresAt": datetime.fromtimestamp(deadline, timezone.utc).isoformat()}
    skipped = [{k: t[k] for k in ("componentKey", "viewport", "reason", "evidence")}
               for t in tasks if t["status"] == "skipped"]
    if skipped:
        envelope["skippedViewports"] = skipped
    _PREPARATIONS[envelope["prepareId"]] = {
        "envelope": copy.deepcopy(envelope), "deadline": deadline, "document": copy.deepcopy(document),
        "registryHash": _registry_hash(document), "settings": settings, "render": render,
        "candidates": copy.deepcopy(candidates or {}), "operations": copy.deepcopy(operations or {}),
    }
    return envelope


def prepare(req: PrepareRequest, *, render=None) -> dict:
    _check_document(req.document)
    document = copy.deepcopy(req.document)
    settings = {"operation": req.operation, "provider": req.provider,
                "reasoningEffort": req.reasoningEffort, "repair": req.repair}
    # Match apply's lock order, including the draft snapshot used for stale-write detection.
    with _LOCK, store._LOCK:
        if req.operation == "master-review":
            # Unlike review_candidates(), enumerate unsupported entries too: nothing silently disappears.
            eligible = dict(master_review.review_candidates(document))
            components = {key: eligible.get(key, comp) for key, comp in (document.get("reviewComponents") or {}).items()}
            tasks = _visual_tasks(document, "master-review", components, render=render)
        else:
            task = _task(req.operation)
            messages = (_organize_messages(document) if req.operation == "organize"
                        else style_review.build_style_review_prompt(document))
            task.update(status="ready", messages=messages, reason=None)
            tasks = [task]
        return _remember(document, settings, req.operation, tasks, render=render)


def _unsupported(reason: str) -> dict:
    return {"approved": False, "score": 0, "summary": reason,
            "defects": [{"severity": "major", "what": reason, "where": "Source evidence"}]}


def _aggregate(verdicts: dict) -> dict:
    active = [v for v in verdicts.values() if v.get("status") != "skipped"]
    return {"approved": bool(active) and all(v["approved"] for v in active) and set(verdicts) == set(VIEWPORTS),
            "score": min((v["score"] for v in active), default=0),
            "summary": "; ".join(f"{vp}: {v['summary']}" for vp, v in verdicts.items())[:400],
            "defects": [dict(d, where=f"{vp}: {d['where']}") for vp, v in verdicts.items() for d in v["defects"]],
            "viewports": verdicts}


def _apply_verdict(document: dict, key: str, verdict: dict, provider: str) -> None:
    comp = (document.get("reviewComponents") or {}).get(key)
    if not isinstance(comp, dict):
        return
    if verdict["approved"] and key in (document.get("components") or {}):
        raise ValueError(f"Promotion would overwrite existing component {key}")
    previous = (comp.get("fidelity") or {}).get("aiReview") or {}
    rejected = previous.get("rejected") or previous.get("previousRepairRejections") or []
    master_review.apply_verdict(document, key, verdict, provider=provider, viewport="all")
    comp["fidelity"]["aiReview"].update(viewports=copy.deepcopy(verdict["viewports"]), transport="desktop-chat")
    if rejected and not verdict["approved"]:
        comp["fidelity"]["aiReview"]["previousRepairRejections"] = [str(reason)[:400] for reason in rejected[:8]]


def _safe_candidate(document: dict, comp: dict, operations: list[dict], render=None, *, renderer_context=None) -> dict:
    candidate = copy.deepcopy(comp)
    master_repair.pin_master(candidate, master_repair.apply_operations(comp["masterIr"], operations))
    if candidate["masterIr"] == comp["masterIr"]:
        raise ValueError("no-safe-fix: operations do not change the master")
    with (nullcontext(renderer_context) if renderer_context is not None else _renderer(render)) as (page, render_fn):
        for viewport in VIEWPORTS:
            if _hidden_evidence(document, comp, viewport):
                if not _hidden_evidence(document, candidate, viewport):
                    raise ValueError(f"{viewport}: repair changed Source-hidden visibility evidence")
                continue
            original = _proof(document, comp, viewport)
            before_png = render_fn(page, copy.deepcopy(comp), viewport)
            candidate_png = render_fn(page, copy.deepcopy(candidate), viewport)
            safe, reasons = master_repair._layout_acceptance(
                comp["masterIr"], candidate["masterIr"], page=page, viewport=viewport,
                original=original, before_png=before_png, candidate_png=candidate_png)
            if not safe:
                raise ValueError(f"{viewport}: " + ", ".join(reasons))
    return candidate


def _task_output(state: dict, task: dict, raw: str):
    value = _json_output(raw)
    kind = task["kind"]
    if kind in ("master-review", "master-verify"):
        return _verdict(value)
    if kind == "organize":
        return _catalog(value, state["document"], state["settings"]["provider"], state["settings"]["reasoningEffort"])
    if kind == "style-review":
        style_review.validate_review(value, state["document"])
        style_review.validate_site_brief(value, state["document"])
    if kind == "master-repair":
        if set(value) != {"operations"} or not isinstance(value["operations"], list):
            raise ValueError("Repair requires an operations array")
        raw_ops = value["operations"]
        if len(raw_ops) > master_repair.MAX_OPERATIONS or any(
            not isinstance(op, dict) or set(op) != {"op", "sourceKey", "property", "value"} for op in raw_ops
        ):
            raise ValueError("Malformed or excessive repair operations")
        comp = state["document"]["reviewComponents"][task["componentKey"]]
        clean = master_repair.validate_operations(value, comp["masterIr"])
        if len(clean) != len(raw_ops):
            seen = set()
            for index, op in enumerate(raw_ops):
                signature = (op["sourceKey"], op["property"])
                valid = master_repair.validate_operations({"operations": [op]}, comp["masterIr"])
                if signature in seen or not valid:
                    node = next((n for n in master_repair._walk(comp["masterIr"].get("tree", []))
                                 if n.get("sourceKey") == op["sourceKey"]), {})
                    frame = node.get("frame") or {}
                    measured = {k: frame[k] for k in ("x", "y", "width", "height", "gap", "padding") if k in frame}
                    reason = "duplicate" if signature in seen else "unsupported or out-of-bounds"
                    raise ValueError(
                        f"operations[{index}] is {reason}: sourceKey={str(op['sourceKey'])[:70]}, "
                        f"property={op['property']}, value={json.dumps(op['value'])[:60]}. "
                        f"Current frame: {json.dumps(measured)}. "
                        "Correct this operation within the supplied bounds, or omit it; return the complete operations array.")
                seen.add(signature)
            raise ValueError("Repair contains unsupported, duplicate or out-of-bounds operations")
        return clean
    return value


def _validated_responses(state: dict, responses: list[TaskResponse]) -> dict:
    tasks = {t["id"]: t for t in state["envelope"]["tasks"] if t["status"] == "ready"}
    if len(responses) != len(tasks) or {r.taskId for r in responses} != set(tasks):
        raise ValueError("Supply exactly one response per ready task; unknown, duplicate or missing taskId")
    parsed = {}
    for index, response in enumerate(responses):
        task = tasks[response.taskId]
        try:
            parsed[response.taskId] = _task_output(state, task, response.output)
        except (ValueError, TypeError, KeyError) as exc:
            raise InvalidAIOutput(exc, task, index, state["envelope"]["stage"]) from exc
    return parsed


def apply(req: ApplyRequest) -> dict:
    with _LOCK, store._LOCK:
        _check_document(req.document)
        _prune()
        state = _PREPARATIONS.get(req.prepareId)
        if state is None:
            raise HTTPException(410, "Preparation expired, consumed or lost on restart; prepare again")
        _check_document(state["document"])
        envelope = state["envelope"]
        if req.documentHash != envelope["documentHash"] or document_hash(req.document) != envelope["documentHash"]:
            raise HTTPException(409, "Document changed since prepare; prepare again with current content")
        if _registry_hash(req.document) != state["registryHash"]:
            raise HTTPException(409, "Saved draft changed since prepare; reload and prepare again")
        parsed = _validated_responses(state, req.responses)
        updated = copy.deepcopy(state["document"])
        settings, stage = state["settings"], envelope["stage"]
        provider, render = settings["provider"], state["render"]
        results, next_tasks, candidates, operations = [], [], {}, {}
        next_stage = None
        if stage == "organize":
            catalog = next(iter(parsed.values()))
            updated = organizer.apply_catalog(updated, catalog)
            results.append({"kind": stage, "applied": True})
        elif stage == "style-review":
            updated = style_review.apply_style_review(updated, json.dumps(next(iter(parsed.values()))), provider=provider)
            results.append({"kind": stage, "applied": True})
        elif stage == "master-repair":
            # Browser startup/shutdown is expensive on Windows. A repair batch
            # owns one renderer (including fresh verification inputs), not one
            # Chromium/driver process pair per component. Layout is still reset
            # and all three viewport gates run for every candidate.
            with ExitStack() as render_stack:
                renderer_context = None
                for task in envelope["tasks"]:
                    key = task["componentKey"]
                    ops = parsed.get(task["id"], [])
                    result = {"key": key, "kind": stage, "repaired": False, "rounds": 1}
                    try:
                        if task["status"] != "ready" or not ops:
                            raise ValueError(task["reason"] or "no-safe-fix: no operations")
                        if renderer_context is None:
                            renderer_context = render_stack.enter_context(_renderer(render))
                        candidates[key] = _safe_candidate(updated, updated["reviewComponents"][key], ops,
                                                          renderer_context=renderer_context)
                        operations[key] = ops
                        result["pendingVerification"] = True
                    except Exception as exc:
                        result["rejected"] = [str(exc)[:400]]
                        master_repair.annotate_review(updated["reviewComponents"][key], result)
                    results.append(result)
                if candidates:
                    next_stage = "master-verify"
                    next_tasks = _visual_tasks(updated, next_stage, candidates, renderer_context=renderer_context)
        else:
            by_key: dict[str, dict] = {}
            supported: dict[str, bool] = {}
            for skipped in envelope.get("skippedViewports", []):
                key, vp = skipped["componentKey"], skipped["viewport"]
                by_key.setdefault(key, {})[vp] = {
                    "status": "skipped", "approved": None, "score": None, "defects": [],
                    "summary": "Intentionally hidden in the captured Source viewport",
                    "evidence": copy.deepcopy(skipped["evidence"]),
                }
                supported[key] = True
            for task in envelope["tasks"]:
                key, vp = task["componentKey"], task["viewport"]
                by_key.setdefault(key, {})[vp] = parsed.get(task["id"], _unsupported(task["reason"] or "Unsupported"))
                supported[key] = supported.get(key, True) and task["status"] == "ready"
            rejected = {}
            for key, viewports in by_key.items():
                verdict = _aggregate(viewports)
                if all(v.get("status") == "skipped" for v in viewports.values()):
                    # An entirely invisible component has no reviewed visual
                    # evidence and cannot be promoted or sent for repair.
                    supported[key] = False
                    verdict["summary"] = "No visible viewport to review; all three are Source-hidden"
                if stage == "master-verify" and verdict["approved"]:
                    updated["reviewComponents"][key] = copy.deepcopy(state["candidates"][key])
                comp = updated["reviewComponents"][key]
                _apply_verdict(updated, key, verdict, provider)
                result = {"key": key, "kind": stage, **verdict, "supported": supported[key],
                          "repaired": stage == "master-verify" and verdict["approved"]}
                if stage == "master-verify":
                    result.update(rounds=1, operations=state["operations"].get(key, []))
                    if not verdict["approved"]:
                        result["rejected"] = ["fidelity: candidate did not pass all three viewports"]
                    master_repair.annotate_review(comp, result)
                elif not verdict["approved"] and supported[key] and settings["repair"]:
                    rejected[key] = verdict
                results.append(result)
            if rejected:
                next_stage = "master-repair"
                next_tasks = _visual_tasks(updated, next_stage,
                    {key: updated["reviewComponents"][key] for key in rejected}, render=render, verdicts=rejected)
        # Existing draft defects are permitted, but this operation may not introduce new ones.
        _check_document(updated)
        before_errors = {dsdoc.canonical_json(e) for e in dsdoc.validate_document(state["document"])}
        new_errors = [e for e in dsdoc.validate_document(updated) if dsdoc.canonical_json(e) not in before_errors]
        if new_errors:
            raise ValueError("Apply would introduce document validation errors: " + json.dumps(new_errors, ensure_ascii=False))
        updated["status"] = "draft"
        saved = store.save_draft(updated)["document"]
        # Consume only after successful validation and persistence; invalid output can be retried.
        del _PREPARATIONS[req.prepareId]
        next_preparation = (_remember(saved, settings, next_stage, next_tasks, render=render,
                                      candidates=candidates, operations=operations) if next_stage else None)
        return {"document": saved, "summary": dsdoc.summary(saved), "results": results,
                "complete": next_preparation is None, "nextPreparation": next_preparation}


@router.post("/prepare")
def prepare_desktop_ai(req: PrepareRequest):
    try:
        return prepare(req)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/apply")
def apply_desktop_ai(req: ApplyRequest):
    try:
        return apply(req)
    except InvalidAIOutput as exc:
        raise HTTPException(422, exc.detail) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
