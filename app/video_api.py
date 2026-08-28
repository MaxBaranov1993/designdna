"""FastAPI boundary for paid Seedance 2.5 jobs through OpenRouter."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import video_client


router = APIRouter()


class SeedanceSubmitRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=video_client.MAX_PROMPT_CHARS)
    duration: int = Field(default=8, ge=video_client.MIN_DURATION, le=video_client.MAX_DURATION)
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    generate_audio: bool = False
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    input_references: list[dict[str, Any]] = Field(default_factory=list, max_length=video_client.MAX_REFERENCES)
    confirmed_paid: bool = False


def _raise_video_error(error: Exception) -> None:
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    message = str(error)
    status_code = 503 if "not configured" in message.lower() else 502
    raise HTTPException(status_code=status_code, detail=message) from error


@router.get("/api/video/seedance/config")
def seedance_config() -> dict[str, Any]:
    return video_client.public_config()


@router.post("/api/video/seedance/submit")
def seedance_submit(request: SeedanceSubmitRequest) -> dict[str, Any]:
    # This branch must remain before every transport/credential lookup: tests
    # and the UI rely on the guarantee that an unconfirmed click cannot spend.
    if not request.confirmed_paid:
        raise HTTPException(status_code=409, detail="Confirm the paid Seedance generation before submitting.")
    try:
        return video_client.submit(
            request.prompt,
            duration=request.duration,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            generate_audio=request.generate_audio,
            input_references=request.input_references,
            seed=request.seed,
        )
    except (ValueError, RuntimeError) as error:
        _raise_video_error(error)
    raise AssertionError("unreachable")


@router.get("/api/video/seedance/{job_id}")
def seedance_status(job_id: str) -> dict[str, Any]:
    try:
        return video_client.status(job_id)
    except (ValueError, RuntimeError) as error:
        _raise_video_error(error)
    raise AssertionError("unreachable")


@router.get("/api/video/seedance/{job_id}/content")
def seedance_content(job_id: str) -> Response:
    try:
        body, media_type = video_client.content(job_id)
    except (ValueError, RuntimeError) as error:
        _raise_video_error(error)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="seedance-{job_id[:12]}.mp4"'},
    )
