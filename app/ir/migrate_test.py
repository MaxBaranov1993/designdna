from __future__ import annotations

import copy

from .migrate import migrate_project_payload


def _legacy_ir(*, created_at: str | None = None) -> dict:
    provenance = {"createdAt": created_at} if created_at else {}
    return {
        "version": "1.0",
        "tokens": {},
        "tree": {"id": "root", "type": "frame", "children": []},
        "provenance": provenance,
    }


def test_project_migration_is_repeatable_for_the_same_persisted_bytes() -> None:
    payload = {"pages": [{"graph": {"nodes": [{"data": {"ir": _legacy_ir()}}]}}]}

    first = migrate_project_payload(payload)
    second = migrate_project_payload(payload)

    assert first == second
    migrated = first["pages"][0]["graph"]["nodes"][0]["data"]["ir"]
    assert migrated["provenance"]["createdAt"] == "1970-01-01T00:00:00+00:00"
    assert migrated["provenance"]["migratedAt"] == "1970-01-01T00:00:00+00:00"


def test_project_migration_reuses_existing_creation_time_without_mutating_input() -> None:
    created_at = "2026-08-25T12:00:00+00:00"
    payload = {"ir": _legacy_ir(created_at=created_at)}
    original = copy.deepcopy(payload)

    migrated = migrate_project_payload(payload)

    assert payload == original
    assert migrated["ir"]["provenance"]["createdAt"] == created_at
    assert migrated["ir"]["provenance"]["migratedAt"] == created_at
