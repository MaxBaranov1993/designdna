"""Улики захвата: без них AI-починка была холостой, а статус не догонял IR.

Две дыры закрываются здесь.

Первая: карта расхождений harness (region_diffs) намеренно не уезжает в ответ
/api/block-parse — сетка 8×8 на каждый компонент когда-то раздувала полезную
нагрузку до предела live-сессии. Но выбирать регион для диагностики можно
только по ней, поэтому prepareOnly всегда возвращал ноль заданий: чинить было
нечего просто потому, что модель не видела, где расхождение. Теперь карта
лежит в кэше улик и берётся оттуда по ключу блока.

Вторая: перезамер. Правка меняет IR, а отчёт остаётся снятым до починки —
компонент навсегда «нужна проверка». Перезамер честный или его нет вовсе: без
измеренных на живой странице листовых кадров bbox мерить нечем, и ослаблять
гейт ради зелёного статуса нельзя.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DESIGNDNA_DATA_DIR", tempfile.mkdtemp(prefix="repair-evidence-"))

from fastapi.testclient import TestClient  # noqa: E402

import blockparse  # noqa: E402
import server  # noqa: E402

# Без `with`: контекст TestClient гоняет lifespan приложения, а его shutdown
# гасит общий EXECUTOR сервера — следующие в прогоне тесты остались бы без
# пула потоков. Эндпоинту починки lifespan не нужен.
client = TestClient(server.app)


def _ir() -> dict:
    return {
        "version": "1.1",
        "tree": [{
            "type": "source-block", "sourceKey": "root",
            "frame": {"x": 0, "y": 0, "width": 800, "height": 400, "layout": "auto"},
            "children": [
                {"type": "heading", "sourceKey": "hero-title", "text": "Outreach autopilot",
                 "frame": {"x": 100, "y": 40, "width": 600, "height": 60},
                 "style": {"color": "#ffffff", "fontWeight": 800}},
            ],
        }],
    }


def _harness_report(passed: bool = False) -> dict:
    """Внутренний отчёт harness — с картой расхождений и артефактами."""
    return {
        "raster_fallback": False,
        "gate": {"passed": passed, "reasons": [] if passed else ["desktop: pixel similarity 88.0 < 97"]},
        "viewports": {
            "desktop": {
                "pixel_similarity": 88.0,
                "paint_coverage": 99.0,
                "bbox_p95": 1.0,
                "grid_origin_error": 0.0,
                "unexplained_losses": 0,
                "size_match": True,
                "reference_size": [800, 400],
                "render_size": [800, 400],
                "region_diffs": [
                    {"region": [0, 1], "mismatch_pct": 42.0},
                    {"region": [2, 3], "mismatch_pct": 11.5},
                ],
                "artifacts": {"reference": "C:/tmp/ref.png"},
                "gate": {"passed": passed, "reasons": []},
            },
        },
        "components": {},
    }


def _capture_item() -> dict:
    return {
        "ir": _ir(),
        "leaf_boxes_by_viewport": {"desktop": [
            {"sourceKey": "hero-title", "x": 100, "y": 40, "width": 600, "height": 60},
        ]},
        "paint_coverage": {"desktop": 99.0},
        "dropped_by_viewport": {},
        "extras_by_viewport": {},
        "provenance": {"captureVersion": "dom-v41"},
    }


def _stash(url: str = "https://example.com", selector: str = "#hero") -> str:
    return blockparse._stash_repair_evidence(url, selector, _capture_item(), _harness_report())


def _block(evidence_key: str, *, passed: bool = False) -> dict:
    """Публичный блок — ровно то, что редактор шлёт назад в /repair."""
    return {
        "name": "hero", "selector": "#hero", "ir": _ir(),
        "evidenceKey": evidence_key,
        "fidelityReport": blockparse._public_fidelity_report(_harness_report(passed)),
        "previews": {"desktop": "data:image/png;base64,AAAA"},
        "sizes": {"desktop": {"width": 800, "height": 400}},
    }


def test_public_report_still_hides_region_diffs_and_artifacts():
    public = blockparse._public_fidelity_report(_harness_report())
    metrics = public["viewports"]["desktop"]
    assert "region_diffs" not in metrics, "карта расхождений не должна уезжать в редактор"
    assert "artifacts" not in metrics
    assert metrics["pixel_similarity"] == 88.0


def test_evidence_carries_region_map_and_measured_leaf_boxes():
    import cache_store

    key = _stash()
    assert key
    evidence = cache_store.get("repair_evidence", key)
    assert evidence["regionDiffsByViewport"]["desktop"][0]["mismatch_pct"] == 42.0
    assert evidence["leafBoxesByViewport"]["desktop"][0]["sourceKey"] == "hero-title"
    assert evidence["paintCoverage"]["desktop"] == 99.0


def test_prepare_builds_tasks_from_cached_region_map():
    key = _stash()
    resp = client.post("/api/block-parse/repair",
                       json={"blocks": [_block(key)], "viewport": "desktop", "prepareOnly": True})
    assert resp.status_code == 200, resp.text
    tasks = resp.json()["tasks"]
    assert tasks, "без карты расхождений из кэша починка была холостой"
    assert tasks[0]["block"] == "hero"
    assert tasks[0]["messages"], "задание диагностики без промпта бессмысленно"


def test_prepare_skips_blocks_that_already_passed_the_gate():
    key = _stash()
    resp = client.post("/api/block-parse/repair",
                       json={"blocks": [_block(key, passed=True)], "viewport": "desktop",
                             "prepareOnly": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["tasks"] == []


def test_gate_reading_matches_the_harness_verdict():
    assert server._block_gate_passed(_block("", passed=True)) is True
    assert server._block_gate_passed(_block("", passed=False)) is False
    assert server._block_gate_passed({"name": "no-report"}) is False


def test_remeasure_is_skipped_without_measured_leaf_boxes():
    """Fail-closed: нет улик — нет перезамера, а не перезамер по слабым данным."""
    block = _block("missing-key")
    before = block["fidelityReport"]
    assert server._refresh_block_fidelity(block, page=None) is False
    assert block["fidelityReport"] is before, "отчёт не должен подменяться без улик"
