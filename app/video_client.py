"""OpenRouter asynchronous generative-video gateway."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


VIDEO_API_URL = os.environ.get("OPENROUTER_VIDEO_URL", "https://openrouter.ai/api/v1/videos").rstrip("/")
VIDEO_MODELS = {
    "draft": "bytedance/seedance-2.0-fast",
    "studio": "bytedance/seedance-2.0",
    "cinematic": "google/veo-3.1",
}
ASPECT_RATIOS = {"1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"}
RESOLUTIONS = {"480p", "720p", "1080p"}
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")


def model_for_tier(tier: str) -> str:
    if tier not in VIDEO_MODELS:
        raise ValueError(f"unknown video quality tier: {tier}")
    override = os.environ.get(f"OPENROUTER_VIDEO_MODEL_{tier.upper()}", "").strip()
    model = override or VIDEO_MODELS[tier]
    if not re.fullmatch(r"[A-Za-z0-9._~/-]+", model) or ".." in model or model.startswith("/"):
        raise ValueError(f"invalid OpenRouter video model slug: {model!r}")
    return model


def public_models() -> dict[str, str]:
    return {tier: model_for_tier(tier) for tier in VIDEO_MODELS}


def _key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not value:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    return value


def _request(method: str, url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://designai.local",
        "X-Title": "DesignAI Web",
    })
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            try:
                return json.loads(response.read())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError("OpenRouter video API returned invalid JSON") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter video HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter video network error: {exc.reason}") from exc


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
        raise RuntimeError("OpenRouter returned an invalid video job")
    return {**result, "tier": tier, "model": payload["model"]}


def status(job_id: str) -> dict:
    if not _JOB_ID.fullmatch(job_id or ""):
        raise ValueError("invalid OpenRouter video job id")
    return _request("GET", f"{VIDEO_API_URL}/{job_id}")
