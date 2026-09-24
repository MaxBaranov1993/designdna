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


def test_asset_undo_snapshots_migrate_with_current_results_and_preserve_source_boundaries() -> None:
    before = _legacy_ir()
    after = copy.deepcopy(before)
    after["tree"]["children"] = [{"type": "image", "src": "ddna://blobs/" + "a" * 64 + ".png"}]
    data = {"ir": after, "variants": [after], "mixVariants": [after],
            "assetVersions": [{"runId": "r", "before": [before], "after": [after]}]}
    payload = {"pages": [{"graph": {"nodes": [
        {"type": kind, "data": copy.deepcopy(data)} for kind in ("derive", "mix", "reskin", "sourceimport", "designsystem")
    ]}}]}
    original = copy.deepcopy(payload)
    migrated = migrate_project_payload(payload)
    assert payload == original
    assert migrate_project_payload(migrated) == migrated
    nodes = migrated["pages"][0]["graph"]["nodes"]
    for node in nodes[:3]:
        current = node["data"]
        snapshot = current["assetVersions"][0]
        assert snapshot["after"] == current["variants"] == current["mixVariants"] == [current["ir"]]
        assert snapshot["before"][0]["version"] == "1.1"
        assert snapshot["before"][0]["tree"]["children"] == []
    assert nodes[3:] == original["pages"][0]["graph"]["nodes"][3:]
