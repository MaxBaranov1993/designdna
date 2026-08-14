from __future__ import annotations

import json
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


def test_generate_receives_taste_memory(tmp_path: Path) -> None:
    old_db = project_store.DB_PATH
    old_chat = server.llm.chat
    old_acceptance = server._run_generation_acceptance
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

        def fake_chat(provider, messages, temperature, role=None, **kwargs):
            seen.append(messages[-1]["content"])
            return '{"version":"1.0","tokens":{},"tree":[]}'

        server.llm.chat = fake_chat
        server._run_generation_acceptance = lambda candidate, brief, index, deadline: (
            candidate, {"index": index, "score": 100, "verdict": "pass", "issues": [], "fixed": 0}
        )
        response = server.generate(server.GenerateReq(brief="сделай hero", count=1))
        check("generate returns variant", bool(response["variants"]))
        check("generate prompt includes taste memory", "Project Taste Memory" in seen[0] and "editorial" in seen[0], seen[0])
    finally:
        server.llm.chat = old_chat
        server._run_generation_acceptance = old_acceptance
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
