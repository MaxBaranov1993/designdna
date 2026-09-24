"""A save may drop a stored page only when the client deleted it explicitly.

Regression (2026-09-24): a client state that had lost two pages saved a
one-page project over the full one with a valid CAS revision.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import project_store
from server import app


def _project(*pages: tuple[str, str]) -> dict:
    return {"version": "designai-pages-v1", "activePageId": pages[0][0],
            "pages": [{"id": pid, "name": name, "graph": {"nodes": [], "edges": []}} for pid, name in pages]}


def test_save_refuses_silent_page_loss_and_allows_explicit_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "projects.db")
    with TestClient(app) as client:
        empty = client.post("/api/project/load", json={}).json()["revision"]
        full = _project(("p1", "Landing"), ("p2", "Client work"), ("p3", "Test"))
        saved = client.post("/api/project/save", json={"project": full, "expectedRevision": empty}).json()
        assert saved["ok"], saved

        lost = client.post("/api/project/save", json={"project": _project(("p3", "Test")),
                                                     "expectedRevision": saved["revision"]})
        assert lost.status_code == 409
        body = lost.json()
        assert body["error"] == "page_loss" and body["missingPages"] == ["Landing", "Client work"]
        assert body["missingPageIds"] == ["p1", "p2"]
        stored = client.post("/api/project/load", json={}).json()["project"]
        assert [page["name"] for page in stored["pages"]] == ["Landing", "Client work", "Test"], "nothing was overwritten"

        deleted = client.post("/api/project/save", json={"project": _project(("p1", "Landing"), ("p3", "Test")),
                                                        "expectedRevision": saved["revision"], "deletedPages": ["p2"]})
        assert deleted.status_code == 200 and deleted.json()["ok"], "an explicit delete is saved"
