from __future__ import annotations

import json
import tempfile
from pathlib import Path

import project_store
import server


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        raise AssertionError(name)


def test_project_save_load_and_taste(tmp_path: Path) -> None:
    old_db = project_store.DB_PATH
    project_store.DB_PATH = tmp_path / "projects.db"
    try:
        heavy = "data:image/jpeg;base64," + ("A" * 500_000)
        editable = "data:image/svg+xml;base64,PHN2Zy8+"
        payload = {
            "version": "designai-pages-v1",
            "activePageId": "page-1",
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "graph": {
                        "nodes": [
                            {
                                "id": 1,
                                "type": "prompt",
                                "x": 80,
                                "y": 40,
                                "data": {"text": "делай компактный премиальный SaaS, много воздуха, неоновые акценты"},
                            },
                            {
                                "id": 2,
                                "type": "edit",
                                "x": 420,
                                "y": 40,
                                "data": {
                                    "ir": {
                                        "version": "1.0",
                                        "sourcePreview": heavy,
                                        "tokens": {
                                            "color": {"primary": "#7c3aed", "accent": "#14b8a6"},
                                            "font": {"body": "Inter"},
                                        },
                                        "tree": [
                                            {
                                                "type": "button",
                                                "preview": heavy,
                                                "style": {"background": "#7c3aed", "fontFamily": "Inter"},
                                                "children": [{"type": "image", "src": editable}],
                                            }
                                        ],
                                    }
                                },
                            },
                        ],
                        "edges": [],
                        "view": {"x": 0, "y": 0, "zoom": 1},
                        "nextId": 3,
                    },
                }
            ],
            "channels": {},
        }

        result = project_store.save_project(payload)
        loaded = project_store.load_project()
        text = json.dumps(loaded["payload"], ensure_ascii=False)
        profile = project_store.load_taste_profile()
        hint = project_store.build_prompt_memory_hint()

        check("project saved", result["ok"] is True)
        check("project loads from sqlite", loaded is not None and loaded["payload"]["activePageId"] == "page-1")
        check("screenshot previews stay in sqlite", "data:image/jpeg;base64," in text)
        check("editable image sources stay", editable in text)
        check("taste profile learns prompts", profile["prompt_count"] >= 1, json.dumps(profile, ensure_ascii=False))
        check("taste profile learns colors", "#7c3aed" in json.dumps(profile), json.dumps(profile, ensure_ascii=False))
        check("prompt memory hint is generated", "Project Taste Memory" in hint and "SaaS" in hint, hint)
    finally:
        project_store.DB_PATH = old_db


def test_http_save_supports_cas_and_load_returns_revision(tmp_path: Path) -> None:
    old_db = project_store.DB_PATH
    project_store.DB_PATH = tmp_path / "projects.db"
    payload = {
        "version": "designai-pages-v1",
        "activePageId": "page-1",
        "pages": [
            {"id": "page-1", "name": "Home", "graph": {"nodes": [], "edges": [], "view": {"x": 0, "y": 0, "zoom": 1}, "nextId": 1}}
        ],
        "channels": {},
    }
    try:
        # load пустого проекта отдаёт ревизию-заглушку
        empty = server.project_load(server.ProjectLoadReq())
        check("empty load has revision", empty["revision"] is project_store.EMPTY_REVISION, str(empty))
        # сохранение без expectedRevision — прежнее поведение
        plain = server.project_save(server.ProjectSaveReq(project=payload))
        check("plain save ok", plain["ok"] is True and plain.get("revision"), json.dumps(plain))

        loaded = server.project_load(server.ProjectLoadReq())
        revision = loaded["revision"]
        check("load returns stored revision", isinstance(revision, str) and revision != project_store.EMPTY_REVISION)

        # CAS по актуальной ревизии проходит
        payload["pages"][0]["name"] = "Landing"
        cas = server.project_save(server.ProjectSaveReq(project=payload, expectedRevision=revision))
        check("cas save ok", cas["ok"] is True and cas.get("stale") is False, json.dumps(cas))

        # CAS по устаревшей ревизии — 409 stale с текущей ревизией в теле
        stale = server.project_save(server.ProjectSaveReq(project=payload, expectedRevision=revision))
        check("stale save returns 409", getattr(stale, "status_code", None) == 409, str(stale))
        stale_body = json.loads(stale.body)
        check("stale body carries current revision", stale_body.get("stale") is True and stale_body.get("revision"))
    finally:
        project_store.DB_PATH = old_db


def test_prompt_events_keep_hashes_and_deduplicate(tmp_path: Path) -> None:
    old_db = project_store.DB_PATH
    project_store.DB_PATH = tmp_path / "projects.db"
    payload = {
        "version": "designai-pages-v1",
        "activePageId": "page-1",
        "pages": [
            {
                "id": "page-1",
                "name": "Home",
                "graph": {
                    "nodes": [
                        {"id": 1, "type": "prompt", "data": {"text": "same prompt", "brief": "brief one"}},
                        {"id": 2, "type": "prompt", "data": {"text": "same prompt"}},
                        {"id": 3, "type": "edit", "data": {"prompt": "second prompt"}},
                    ],
                    "edges": [],
                    "view": {"x": 0, "y": 0, "zoom": 1},
                    "nextId": 4,
                },
            }
        ],
        "channels": {},
    }
    expected_bodies = [
        {"nodeType": "prompt", "field": "text", "text": "same prompt"},
        {"nodeType": "prompt", "field": "brief", "text": "brief one"},
        {"nodeType": "edit", "field": "prompt", "text": "second prompt"},
    ]
    expected = {
        project_store.revision_of_raw(json.dumps(body, ensure_ascii=False, sort_keys=True)): body
        for body in expected_bodies
    }
    try:
        first = project_store.save_project(payload)
        with project_store._db() as con:
            first_rows = con.execute(
                "SELECT event_hash, payload, created_at FROM taste_events "
                "WHERE user_id=? AND project_id=? ORDER BY event_hash",
                (project_store.DEFAULT_USER_ID, project_store.DEFAULT_PROJECT_ID),
            ).fetchall()

        check("prompt events save unique hashes", first["ok"] is True and len(first_rows) == len(expected))
        check(
            "prompt event bodies preserve hash contract",
            all(json.loads(body) == expected[event_hash] for event_hash, body, _ in first_rows),
        )

        payload["pages"][0]["name"] = "Renamed"
        second = project_store.save_project(payload)
        with project_store._db() as con:
            second_rows = con.execute(
                "SELECT event_hash, payload, created_at FROM taste_events "
                "WHERE user_id=? AND project_id=? ORDER BY event_hash",
                (project_store.DEFAULT_USER_ID, project_store.DEFAULT_PROJECT_ID),
            ).fetchall()
        check("repeated prompt events stay deduplicated", second["ok"] is True and second_rows == first_rows)
    finally:
        project_store.DB_PATH = old_db


def test_generate_receives_taste_memory(tmp_path: Path) -> None:
    old_db = project_store.DB_PATH
    old_chat = server.llm.chat
    project_store.DB_PATH = tmp_path / "projects.db"
    seen: list[str] = []
    try:
        project_store.save_project(
            {
                "version": "designai-pages-v1",
                "activePageId": "page-1",
                "pages": [
                    {
                        "id": "page-1",
                        "name": "Home",
                        "graph": {
                            "nodes": [
                                {
                                    "id": 1,
                                    "type": "prompt",
                                    "x": 0,
                                    "y": 0,
                                    "data": {"text": "люблю editorial минимализм и строгую сетку"},
                                }
                            ],
                            "edges": [],
                            "view": {"x": 0, "y": 0, "zoom": 1},
                            "nextId": 2,
                        },
                    }
                ],
                "channels": {},
            }
        )

        # Сигнатура llm.chat расширялась (role, model, reasoning_effort);
        # заглушка принимает всё лишнее, чтобы тест не ломался от неё.
        def fake_chat(provider, messages, temperature, role=None, **kwargs):
            seen.append(messages[-1]["content"])
            # Минимальный IR, проходящий схему: пустые tokens/tree сервер
            # отвергает валидацией, и тест падал на этом, а не на памяти вкуса.
            return json.dumps({"version": "1.0", "tokens": {"mode": "light", "color": {"primary": "#111827", "secondary": "#374151", "accent": "#7c6cf0", "background": "#ffffff", "surface": "#f8fafc", "text": "#111827", "textMuted": "#6b7280", "border": "#e5e7eb"}, "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"}, "radius": {"card": "lg", "button": "md", "input": "md"}, "spacing": {"section": "lg", "container": "wide"}, "shadow": "sm"}, "tree": [{"id": "s1", "type": "hero", "variant": "centered", "props": {"heading": "Hero", "subheading": "sub", "ctaPrimary": {"text": "Go", "href": "#"}}}]})

        server.llm.chat = fake_chat
        response = server.generate(server.GenerateReq(brief="сделай hero", count=1))
        check("generate returns variant", bool(response["variants"]))
        generator_prompt = next((item for item in seen if "Project Taste Memory" in item), "")
        check("generate prompt includes taste memory", "editorial" in generator_prompt, generator_prompt)
    finally:
        server.llm.chat = old_chat
        project_store.DB_PATH = old_db


if __name__ == "__main__":
    import tempfile
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        test_project_save_load_and_taste(Path(td) / "a")
    with tempfile.TemporaryDirectory() as td:
        test_generate_receives_taste_memory(Path(td) / "b")
    print("ALL PROJECT STORE CHECKS PASSED")
