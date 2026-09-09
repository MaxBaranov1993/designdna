"""Стадии длинных запусков (generate, quality-pass): опрос, SSE и отмена."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import run_registry
from api.common import err

router = APIRouter()


@router.get("/api/runs/{run_id}")
def run_status(run_id: str):
    """Стадия длинного запуска (generate/quality-pass) — клиент поллит параллельно POST."""
    run = run_registry.get(run_id)
    if not run:
        return err(404, "Запуск не найден")
    return run


@router.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    """Push run stage changes to browser clients; polling remains a client fallback."""
    async def events():
        revision = 0
        empty_waits = 0
        while True:
            run = await asyncio.to_thread(run_registry.wait_for_update, run_id, revision, 15.0)
            if run is None:
                empty_waits += 1
                yield ": keep-alive\n\n"
                if revision == 0 and empty_waits >= 2:
                    break
                continue
            empty_waits = 0
            revision = int(run.get("revision") or revision)
            payload = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {revision}\ndata: {payload}\n\n"
            if run.get("status") in {"complete", "error", "cancelled"}:
                break

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/runs/{run_id}/cancel")
def run_cancel(run_id: str):
    """Кооперативная отмена: хендлер прервётся на следующей проверке между стадиями."""
    return {"cancelled": run_registry.cancel(run_id), "runId": run_id}
