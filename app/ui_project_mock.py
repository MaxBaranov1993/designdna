"""Stateful in-memory stand-in for /api/project/load and /api/project/save in UI tests.

The project lives only in the DB (2026-09-24), so a test that reloads the page
needs a store that keeps what autosave wrote and honours the CAS revision,
instead of the shared SQLite of the test server.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable


class ProjectStoreMock:
    def __init__(self, project: dict | None = None) -> None:
        self.project: dict | None = project
        self.revision = self._revision(project)
        self.saves = 0

    @staticmethod
    def _revision(project: dict | None) -> str:
        raw = json.dumps(project, sort_keys=True, ensure_ascii=False)
        return "mock-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def install(self, page) -> "ProjectStoreMock":
        page.route("**/api/project/load", self._load)
        page.route("**/api/project/save", self._save)
        return self

    def _reply(self, route, body: dict, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def _load(self, route) -> None:
        self._reply(route, {"project": self.project, "updated_at": None, "revision": self.revision})

    def _save(self, route) -> None:
        try:
            body = json.loads(route.request.post_data or "{}")
        except ValueError:
            self._reply(route, {"ok": False, "error": "bad_json"}, 422)
            return
        if body.get("expectedRevision") != self.revision:
            self._reply(route, {"ok": False, "error": "stale_revision", "revision": self.revision}, 409)
            return
        self.project = body.get("project")
        self.revision = self._revision(self.project)
        self.saves += 1
        self._reply(route, {"ok": True, "revision": self.revision, "updated_at": None})

    def active_nodes(self) -> list[dict]:
        project = self.project or {}
        pages = project.get("pages") or []
        page = next((p for p in pages if p.get("id") == project.get("activePageId")), pages[0] if pages else None)
        return list(((page or {}).get("graph") or {}).get("nodes") or [])

    def wait_until(self, page, predicate: Callable[["ProjectStoreMock"], Any], timeout_ms: int = 6000) -> bool:
        """Poll while Playwright pumps route handlers (autosave is debounced and idle-scheduled)."""
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if predicate(self):
                return True
            page.wait_for_timeout(100)
        return bool(predicate(self))
