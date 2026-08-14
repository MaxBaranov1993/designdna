"""Seedance-only asynchronous generative-video gateway.

The transport is intentionally isolated from the text/vision Codex client.
Configure it later with SEEDANCE_VIDEO_URL and SEEDANCE_API_KEY.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


# Kept as a module variable so a local contract test or an adapter can replace
# the endpoint without changing production configuration.
VIDEO_API_URL = os.environ.get("SEEDANCE_VIDEO_URL", "").strip().rstrip("/")
VIDEO_MODELS = {
    "draft": "bytedance/seedance-2.0-fast",
    "studio": "bytedance/seedance-2.0",
    # Preserve the existing tier while guaranteeing a Seedance-only route.
    "cinematic": "bytedance/seedance-2.0",
}
ASPECT_RATIOS = {"1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"}
RESOLUTIONS = {"480p", "720p", "1080p"}
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")


def model_for_tier(tier: str) -> str:
    if tier not in VIDEO_MODELS:
        raise ValueError(f"unknown video quality tier: {tier}")
    override = os.environ.get(f"SEEDANCE_VIDEO_MODEL_{tier.upper()}", "").strip()
    model = override or VIDEO_MODELS[tier]
    if (
        not re.fullmatch(r"[A-Za-z0-9._~/-]+", model)
        or ".." in model
        or model.startswith("/")
        or "seedance" not in model.lower()
    ):
        raise ValueError(f"invalid Seedance video model slug: {model!r}")
    return model


def public_models() -> dict[str, str]:
    return {tier: model_for_tier(tier) for tier in VIDEO_MODELS}


def public_config() -> dict:
    parsed = urllib.parse.urlsplit(VIDEO_API_URL)
    return {
        "id": "seedance",
        "label": "Seedance",
        "configured": bool(VIDEO_API_URL and os.environ.get("SEEDANCE_API_KEY", "").strip()),
        "baseUrlHost": parsed.netloc or (parsed.path.split("/", 1)[0] if parsed.path else "later"),
    }


def _key() -> str:
    value = os.environ.get("SEEDANCE_API_KEY", "").strip()
    if not value:
        raise RuntimeError("SEEDANCE_API_KEY is not configured")
    return value


def _request(method: str, url: str, payload: dict | None = None) -> dict:
    if not VIDEO_API_URL:
        raise RuntimeError("SEEDANCE_VIDEO_URL is not configured")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            try:
                return json.loads(response.read())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("Seedance video API returned invalid JSON") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Seedance video HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Seedance video network error: {exc.reason}") from exc


def submit(
    prompt: str,
    tier: str = "studio",
    duration: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = False,
    references: list[str] | None = None,
    seed: int | None = None,
) -> dict:
    clean_prompt = prompt.strip()
    if not clean_prompt or len(clean_prompt) > 5000:
        raise ValueError("video prompt must contain 1-5000 characters")
    if not 1 <= int(duration) <= 15:
        raise ValueError("video duration must be between 1 and 15 seconds")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"unsupported video aspect ratio: {aspect_ratio}")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unsupported video resolution: {resolution}")
    payload = {
        "model": model_for_tier(tier),
        "prompt": clean_prompt,
        "duration": int(duration),
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "generate_audio": bool(generate_audio),
    }
    if references:
        payload["input_references"] = [{
            "type": "image_url",
            "image_url": {"url": url},
        } for url in references]
    if seed is not None:
        payload["seed"] = int(seed)
    result = _request("POST", VIDEO_API_URL, payload)
    if not result.get("id") or not result.get("status"):
        raise RuntimeError("Seedance returned an invalid video job")
    return {**result, "tier": tier, "model": payload["model"]}


def status(job_id: str) -> dict:
    if not _JOB_ID.fullmatch(job_id or ""):
        raise ValueError("invalid Seedance video job id")
    return _request("GET", f"{VIDEO_API_URL}/{job_id}")
