"""Small, strict OpenRouter video client pinned to Seedance 2.5.

Text planners (GPT/Claude) never call this module.  The only paid boundary is
``submit`` and callers must enforce an explicit confirmation before reaching it.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


OPENROUTER_VIDEO_URL = os.environ.get(
    "OPENROUTER_VIDEO_URL", "https://openrouter.ai/api/v1/videos"
).strip().rstrip("/")
MODEL = "bytedance/seedance-2.5"
ASPECT_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}
RESOLUTIONS = {"480p", "720p"}
MIN_DURATION = 4
MAX_DURATION = 30
MAX_PROMPT_CHARS = 5_000
MAX_REFERENCES = 50
MAX_REFERENCE_BYTES = 48 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}

_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
_DATA_URL = re.compile(
    r"^data:(image|video|audio)/[A-Za-z0-9.+-]+;base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)
_REFERENCE_FIELDS = {
    "image_url": "image_url",
    "video_url": "video_url",
    "audio_url": "audio_url",
}


def public_config() -> dict[str, Any]:
    """Return non-secret capability metadata for the renderer UI."""
    return {
        "provider": "openrouter",
        "model": MODEL,
        "configured": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "async": True,
        "pollIntervalMs": 30_000,
        "terminalStatuses": sorted(TERMINAL_STATUSES),
        "resolutions": sorted(RESOLUTIONS),
        "aspectRatios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
        "duration": {"min": MIN_DURATION, "max": MAX_DURATION},
        "supports": {
            "videoReference": True,
            "imageReference": True,
            "audioReference": True,
            "audioGeneration": True,
            "seed": True,
        },
        # OpenRouter currently documents that video generation is not ZDR.
        "privacy": {"zeroDataRetention": False},
    }


def _key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not value:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    return value


def _headers(*, json_body: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_key()}",
        "Accept": "application/json" if json_body else "video/*,application/octet-stream",
        "X-Title": "DesignDNA Motion Design",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    return headers


def _http_error(exc: urllib.error.HTTPError) -> RuntimeError:
    detail = exc.read(2_000).decode("utf-8", errors="replace").strip()
    return RuntimeError(f"OpenRouter video HTTP {exc.code}: {detail or exc.reason}")


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter video network error: {exc.reason}") from exc
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("OpenRouter video API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("OpenRouter video API returned a non-object response")
    return decoded


def _is_public_https_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)


def _validate_reference_url(value: Any) -> str:
    url = str(value or "").strip()
    match = _DATA_URL.fullmatch(url)
    if match:
        encoded = match.group(2).replace("\r", "").replace("\n", "")
        if len(encoded) > ((MAX_REFERENCE_BYTES + 2) // 3) * 4:
            raise ValueError("inline reference exceeds 48 MiB")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("inline reference is not valid base64") from exc
        if len(decoded) > MAX_REFERENCE_BYTES:
            raise ValueError("inline reference exceeds 48 MiB")
        return url
    if not _is_public_https_url(url):
        raise ValueError("reference URL must be public HTTPS or an image/video/audio data URL")
    return url


def validate_references(references: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not references:
        return []
    if len(references) > MAX_REFERENCES:
        raise ValueError(f"at most {MAX_REFERENCES} input references are allowed")
    clean: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("each input reference must be an object")
        ref_type = str(reference.get("type") or "")
        field = _REFERENCE_FIELDS.get(ref_type)
        nested = reference.get(field or "")
        if not field or not isinstance(nested, dict) or set(reference) != {"type", field}:
            raise ValueError("invalid input reference shape")
        if set(nested) != {"url"}:
            raise ValueError("input reference must contain only url")
        clean.append({"type": ref_type, field: {"url": _validate_reference_url(nested.get("url"))}})
    return clean


def submit(
    prompt: str,
    *,
    duration: int = 8,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = False,
    input_references: list[dict[str, Any]] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt or len(clean_prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"video prompt must contain 1-{MAX_PROMPT_CHARS} characters")
    duration = int(duration)
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValueError(f"video duration must be between {MIN_DURATION} and {MAX_DURATION} seconds")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"unsupported video aspect ratio: {aspect_ratio}")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unsupported video resolution: {resolution}")
    if seed is not None and not 0 <= int(seed) <= 4_294_967_295:
        raise ValueError("video seed must be between 0 and 4294967295")

    payload: dict[str, Any] = {
        "model": MODEL,
        "prompt": clean_prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "generate_audio": bool(generate_audio),
    }
    references = validate_references(input_references)
    if references:
        payload["input_references"] = references
    if seed is not None:
        payload["seed"] = int(seed)

    result = _request_json("POST", OPENROUTER_VIDEO_URL, payload)
    if not _JOB_ID.fullmatch(str(result.get("id") or "")) or not result.get("status"):
        raise RuntimeError("OpenRouter returned an invalid video job")
    return {**result, "model": MODEL}


def _job_url(job_id: str, suffix: str = "") -> str:
    if not _JOB_ID.fullmatch(str(job_id or "")):
        raise ValueError("invalid OpenRouter video job id")
    return f"{OPENROUTER_VIDEO_URL}/{job_id}{suffix}"


def status(job_id: str) -> dict[str, Any]:
    return _request_json("GET", _job_url(job_id))


def content(job_id: str) -> tuple[bytes, str]:
    request = urllib.request.Request(_job_url(job_id, "/content"), method="GET", headers=_headers(json_body=False))
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            media_type = response.headers.get_content_type() or "application/octet-stream"
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise RuntimeError("OpenRouter video content exceeds 512 MiB")
                chunks.append(chunk)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter video network error: {exc.reason}") from exc
    return b"".join(chunks), media_type
