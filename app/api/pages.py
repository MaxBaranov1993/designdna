"""HTML-поверхность и захваченные шрифты: /, /nodes, /flow, /fonts/{name}."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from api.common import APP_ROOT, DATA_ROOT

router = APIRouter()

# ---------- база захваченных шрифтов сайтов (Source Import) ----------
FONTS_DIR = DATA_ROOT / "fonts"
_FONT_NAME = re.compile(r"^[0-9a-f]{16}\.(woff2|woff|ttf|otf)$")


@router.get("/nodes")
def nodes_page():
    # Legacy-граф снят: старый адрес ведёт в единственную актуальную SPA.
    return RedirectResponse(url="/flow", status_code=307)


@router.get("/")
def root_page():
    # Корень не является отдельной поверхностью продукта: канонический UI только /flow.
    return RedirectResponse(url="/flow", status_code=307)


@router.get("/flow")
@router.get("/flow/{rest:path}")
def flow_page():
    # Единственная актуальная SPA: новый нодовый редактор (React Flow, сборка из
    # frontend/). Любой подпуть /flow отдаёт index.html, ассеты приходят через
    # /static/flow/.
    index_path = APP_ROOT / "static" / "flow" / "index.html"
    html = index_path.read_text(encoding="utf-8")
    # The static build must stay relative for Electron file://. For the HTTP
    # surface, inject a literal base before SvelteKit's preload links so the
    # browser preload scanner resolves them through the existing /static mount.
    html = html.replace("<head>", '<head><base href="/static/flow/">', 1)
    return HTMLResponse(html)


@router.get("/fonts/{name}")
def serve_font(name: str):
    safe = Path(name).name
    if not _FONT_NAME.match(safe):
        return JSONResponse({"detail": "not found"}, status_code=404)
    p = FONTS_DIR / safe
    if not p.exists():
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(p, media_type=mimetypes.guess_type(safe)[0] or "font/woff2")
