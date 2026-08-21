"""Fidelity harness: детерминированный golden-тест на фикстуре chess_arena
и fail-closed гейтинг кэш-записей Source Import.

Запуск: .venv/Scripts/python -m pytest app/fidelity_harness_test.py
"""
from __future__ import annotations

import io
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import cache_store  # noqa: E402
import fidelity_harness  # noqa: E402
import scraper  # noqa: E402

VIEWPORTS = [
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
]
ARENA_BLOCK = [{"name": "arena", "label": "Arena", "kind": "section", "selector": "#arena"}]


def _full_metrics(**overrides):
    metrics = {
        "pixel_similarity": 97.5,
        "bbox_mean": 0.4,
        "bbox_p95": 1.2,
        "bbox_max": 2.0,
        "grid_origin_error": 0.0,
        "paint_coverage": 99.0,
        "visual_losses": [],
        "unexplained_losses": 0,
    }
    metrics.update(overrides)
    return metrics


def _report(**viewport_metrics):
    return {"raster_fallback": False,
            "viewports": {name: _full_metrics(**kw) for name, kw in viewport_metrics.items()}}


# ---------- gate: чистая логика, без браузера ----------

def test_gate_passes_on_healthy_report():
    gate = fidelity_harness.evaluate_gate(_report(desktop={}, tablet={}, mobile={}))
    assert gate["passed"], gate["reasons"]


def test_gate_fails_without_report():
    assert not fidelity_harness.evaluate_gate(None)["passed"]
    assert not fidelity_harness.evaluate_gate({})["passed"]
    assert not fidelity_harness.evaluate_gate({"viewports": {}})["passed"]


def test_gate_fails_when_any_required_metric_missing():
    for key in fidelity_harness.REQUIRED_METRICS:
        metrics = _full_metrics()
        metrics[key] = None
        gate = fidelity_harness.evaluate_gate({"viewports": {"desktop": metrics}})
        assert not gate["passed"], f"missing {key} must fail the gate"
        assert any(key in reason for reason in gate["reasons"])


def test_gate_enforces_thresholds():
    cases = [
        ({"grid_origin_error": 2.1}, "origin"),
        ({"paint_coverage": 94.9}, "paint"),
        ({"pixel_similarity": 84.9}, "similarity"),
        ({"unexplained_losses": 1,
          "visual_losses": [{"kind": "extra", "sourceKey": "k",
                             "reason": "raster-unavailable", "explained": False}]}, "lost"),
    ]
    for overrides, marker in cases:
        gate = fidelity_harness.evaluate_gate(_report(desktop=overrides))
        assert not gate["passed"], f"{marker} violation must fail the gate"
        assert any(marker in reason for reason in gate["reasons"]), gate["reasons"]


def test_gate_boundary_values_pass():
    gate = fidelity_harness.evaluate_gate(_report(desktop={
        "grid_origin_error": 2.0, "paint_coverage": 95.0, "pixel_similarity": 85.0}))
    assert gate["passed"], gate["reasons"]


def test_explained_losses_do_not_fail_gate():
    gate = fidelity_harness.evaluate_gate(_report(desktop={
        "visual_losses": [{"kind": "extra", "sourceKey": "k",
                           "reason": "background-image", "explained": True}],
        "unexplained_losses": 0}))
    assert gate["passed"], gate["reasons"]


def test_explicit_raster_fallback_is_allowed():
    gate = fidelity_harness.evaluate_gate({"raster_fallback": True, "viewports": {}})
    assert gate["passed"], gate["reasons"]


def _locked_raster_layer(source_key: str = "arena:root/canvas:0",
                         src: str = "data:image/png;base64,AAAA") -> dict:
    return {"type": "image", "src": src, "editable": False, "sourceKey": source_key,
            "lockedReason": "raster surface",
            "sourceMeta": {"kind": "canvas", "reason": "raster snapshot"}}


def _fallback_child(source_key: str = "arena:root") -> dict:
    return {"type": "image", "src": "data:image/png;base64,AAAA", "editable": False,
            "sourceKey": source_key, "sourceMeta": {"kind": "dom", "reason": "raster-fallback"}}


def test_visual_loss_classification():
    item = {
        "ir": {"tree": [{"children": [
            _locked_raster_layer("a"),
        ]}]},
        "extras_by_viewport": {"desktop": [
            {"sourceKey": "a", "reason": "raster-unavailable", "visual": True},
            {"sourceKey": "b", "reason": "background-image", "visual": True},
            {"sourceKey": "c", "reason": "pseudo", "visual": False},
        ]},
        "dropped_by_viewport": {"desktop": [
            {"sourceKey": "d", "reason": "non-container-child", "visual": True},
            {"sourceKey": "e", "reason": "invisible", "visual": False},
        ]},
    }
    losses = fidelity_harness.visual_losses(item, "desktop")
    by_key = {loss["sourceKey"]: loss["explained"] for loss in losses}
    assert by_key == {"a": True, "b": False, "d": False}
    assert sum(1 for loss in losses if not loss["explained"]) == 2


# ---------- is_raster_fallback: только целиком locked raster ----------

def test_raster_fallback_accepts_exclusive_locked_raster():
    ir = {"tree": [{"children": [_fallback_child()]}]}
    assert fidelity_harness.is_raster_fallback(ir)


def test_raster_fallback_rejects_mixed_ir():
    """Editable слой + raster child — не fallback: метрики не обходятся."""
    ir = {"tree": [{"children": [
        _fallback_child(),
        {"type": "text", "text": "hi", "sourceKey": "arena:root/p:0"},
    ]}]}
    assert not fidelity_harness.is_raster_fallback(ir)


def test_raster_fallback_rejects_unlocked_child():
    child = {**_fallback_child(), "editable": True}
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})


def test_raster_fallback_rejects_empty_or_missing_tree():
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": []}]})
    assert not fidelity_harness.is_raster_fallback({"tree": []})
    assert not fidelity_harness.is_raster_fallback({})
    assert not fidelity_harness.is_raster_fallback(None)


def test_raster_fallback_accepts_multi_section_all_strict():
    ir = {"tree": [{"children": [_fallback_child("a"), _fallback_child("b")]},
                   {"children": [_fallback_child("c")]}]}
    assert fidelity_harness.is_raster_fallback(ir)


def test_raster_fallback_rejects_extra_section():
    """Первая секция чистая, вторая — нет: проверяется каждая секция."""
    ir = {"tree": [{"children": [_fallback_child()]},
                   {"children": [{"type": "text", "text": "x"}]}]}
    assert not fidelity_harness.is_raster_fallback(ir)
    ir = {"tree": [{"children": [_fallback_child()]}, {"children": []}]}
    assert not fidelity_harness.is_raster_fallback(ir)


def test_raster_fallback_rejects_child_with_nested_children():
    child = {**_fallback_child(), "children": [{"type": "text", "text": "x"}]}
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})


def test_raster_fallback_rejects_missing_or_empty_src():
    child = _fallback_child()
    del child["src"]
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})
    child = {**_fallback_child(), "src": ""}
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})


def test_raster_fallback_rejects_wrong_type():
    child = {**_fallback_child(), "type": "div"}
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})
    child = _fallback_child()
    del child["type"]
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})


def test_raster_fallback_rejects_wrong_reason():
    child = {**_fallback_child(),
             "sourceMeta": {"kind": "dom", "reason": "raster snapshot"}}
    assert not fidelity_harness.is_raster_fallback({"tree": [{"children": [child]}]})


# ---------- visual_losses: reason-only whitelist снят, нужна корреляция ----------

def _item_with_loss(ir, reason="background-image", key="arena:root/div:0",
                    kind="extras_by_viewport"):
    return {"ir": ir, "extras_by_viewport": {"desktop": []},
            "dropped_by_viewport": {"desktop": []},
            kind: {"desktop": [{"sourceKey": key, "reason": reason, "visual": True}]}}


def test_visual_loss_explained_only_by_actual_locked_raster_layer():
    key = "arena:root/canvas:0"
    # locked raster слой вложен глубже корня — корреляция по всему дереву
    ir = {"tree": [{"children": [{"type": "section", "sourceKey": "arena:root/div:9",
                                  "children": [_locked_raster_layer(key)]}]}]}
    losses = fidelity_harness.visual_losses(
        _item_with_loss(ir, reason="raster-unavailable", key=key), "desktop")
    assert losses and losses[0]["explained"]


def test_visual_loss_background_image_without_layer_fails():
    """reason-only whitelist background-image снят: без locked raster слоя — потеря."""
    ir = {"tree": [{"children": [{"type": "text", "text": "x", "sourceKey": "k"}]}]}
    losses = fidelity_harness.visual_losses(_item_with_loss(ir), "desktop")
    assert losses and not losses[0]["explained"]


def test_visual_loss_pseudo_without_layer_fails():
    ir = {"tree": [{"children": []}]}
    losses = fidelity_harness.visual_losses(_item_with_loss(ir, reason="pseudo"), "desktop")
    assert losses and not losses[0]["explained"]


def test_visual_loss_editable_layer_does_not_explain():
    """Синтетический editable слой (background-image/pseudo) — не locked raster."""
    key = "arena:root/div:0"
    editable_layer = {"type": "image", "src": "data:image/png;base64,AAAA",
                      "sourceKey": key, "sourceMeta": {"kind": "background-image"}}
    ir = {"tree": [{"children": [editable_layer]}]}
    losses = fidelity_harness.visual_losses(_item_with_loss(ir, key=key), "desktop")
    assert losses and not losses[0]["explained"]


def test_visual_loss_source_key_must_match_exactly():
    ir = {"tree": [{"children": [_locked_raster_layer("arena:root/other:1")]}]}
    losses = fidelity_harness.visual_losses(_item_with_loss(ir), "desktop")
    assert losses and not losses[0]["explained"]


def test_visual_loss_empty_src_is_not_actual_raster():
    key = "arena:root/canvas:0"
    ir = {"tree": [{"children": [_locked_raster_layer(key, src="")]}]}
    losses = fidelity_harness.visual_losses(
        _item_with_loss(ir, reason="raster-unavailable", key=key), "desktop")
    assert losses and not losses[0]["explained"]


def test_visual_loss_dropped_correlates_like_extra():
    key = "arena:root/iframe:0"
    ir = {"tree": [{"children": [_locked_raster_layer(key)]}]}
    item = _item_with_loss(ir, reason="cross-origin-iframe", key=key,
                           kind="dropped_by_viewport")
    losses = fidelity_harness.visual_losses(item, "desktop")
    assert losses and losses[0]["kind"] == "dropped" and losses[0]["explained"]


def test_gate_fails_on_visual_extra_without_correlated_layer():
    gate = fidelity_harness.evaluate_gate(_report(desktop={
        "visual_losses": [{"kind": "extra", "sourceKey": "k",
                           "reason": "background-image", "explained": False}],
        "unexplained_losses": 1}))
    assert not gate["passed"]
    assert any("lost" in reason for reason in gate["reasons"])


# ---------- evaluate_gate: пустые агрегаты fail-closed ----------

def test_gate_fails_on_empty_blocks_aggregate():
    gate = fidelity_harness.evaluate_gate({"blocks": []})
    assert not gate["passed"]
    assert any("no blocks" in reason for reason in gate["reasons"])


# ---------- bbox: matched/unmatched считаются честно ----------

class _FakePage:
    def __init__(self, measured):
        self._measured = measured

    def evaluate(self, _script):
        return self._measured


def test_bbox_matched_counts_only_matched():
    page = _FakePage({"origin": {"x": 0, "y": 0},
                      "boxes": {"a": {"x": 0, "y": 0, "width": 10, "height": 10}}})
    leaf_boxes = [{"sourceKey": "a", "x": 0, "y": 0, "width": 10, "height": 10},
                  {"sourceKey": "missing", "x": 0, "y": 0, "width": 5, "height": 5}]
    metrics = fidelity_harness._bbox_metrics(page, leaf_boxes)
    assert metrics["bbox_matched"] == 1
    assert metrics["bbox_unmatched"] == 1
    assert metrics["bbox_total"] == 2
    assert metrics["bbox_max"] == fidelity_harness.UNMATCHED_BOX_PENALTY


def test_bbox_empty_leaf_boxes():
    page = _FakePage({"origin": {"x": 1, "y": 0}, "boxes": {}})
    metrics = fidelity_harness._bbox_metrics(page, [])
    assert metrics["bbox_matched"] == 0
    assert metrics["bbox_unmatched"] == 0
    assert metrics["bbox_total"] == 0
    assert metrics["bbox_mean"] is None


# ---------- region diffs: разбиение покрывает каждый пиксель ----------

def _png_bytes(array) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
    return buf.getvalue()


def test_region_diffs_cover_remainder_rows_and_columns():
    """Размер 10×10 не делится на сетку 8×8: расхождение в последней строке и
    колонке обязано попасть в region_diffs, а не выпасть из разбиения."""
    import numpy as np

    height, width = 10, 10
    ref = np.zeros((height, width, 3), dtype=np.uint8)
    got = ref.copy()
    got[height - 1, width - 1] = [255, 255, 255]
    metrics = fidelity_harness._image_metrics(_png_bytes(ref), _png_bytes(got))
    assert metrics["size_match"]
    assert metrics["pixel_similarity"] is not None
    assert {"region": [7, 7], "mismatch_pct": 25.0} in metrics["region_diffs"]


def test_region_diffs_partition_covers_every_pixel():
    """Сумма площадей ячеек разбиения равна площади образа при любом размере."""
    grid = fidelity_harness.REGION_GRID
    for height, width in ((10, 10), (17, 9), (8, 8), (3, 5), (1440, 900)):
        rows = [(height * r // grid, height * (r + 1) // grid) for r in range(grid)]
        cols = [(width * c // grid, width * (c + 1) // grid) for c in range(grid)]
        covered = sum((y1 - y0) * (x1 - x0) for (y0, y1) in rows for (x0, x1) in cols)
        assert covered == height * width


# ---------- cache_store.put_gated: fail-closed ----------

@pytest.fixture()
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "cache.db")
    return cache_store


def test_put_gated_refuses_without_report(tmp_cache):
    ok = tmp_cache.put_gated("clone_block", "k-no-report", {"ir": {"v": 1}}, None)
    assert not ok
    assert tmp_cache.get("clone_block", "k-no-report") is None


def test_put_gated_refuses_on_failed_gate(tmp_cache):
    report = _report(desktop={"pixel_similarity": 10.0})
    ok = tmp_cache.put_gated("clone_block", "k-bad", {"ir": {"v": 1}}, report)
    assert not ok
    assert tmp_cache.get("clone_block", "k-bad") is None


def test_put_gated_refuses_on_partial_metrics(tmp_cache):
    report = {"viewports": {"desktop": {"pixel_similarity": 99.0}}}
    ok = tmp_cache.put_gated("clone_block", "k-partial", {"ir": {"v": 1}}, report)
    assert not ok
    assert tmp_cache.get("clone_block", "k-partial") is None


def test_put_gated_accepts_passing_report(tmp_cache):
    report = _report(desktop={}, tablet={}, mobile={})
    ok = tmp_cache.put_gated("clone_block", "k-good", {"ir": {"v": 2}}, report)
    assert ok
    assert tmp_cache.get("clone_block", "k-good") == {"ir": {"v": 2}}


def _locked_raster_payload() -> dict:
    return {"ir": {"tree": [{"children": [_fallback_child()]}]}}


def test_put_gated_accepts_exclusive_locked_raster_ir(tmp_cache):
    """Без метрик проходит только блок, целиком представленный явными locked
    raster fallback слоями в фактическом IR payload."""
    payload = _locked_raster_payload()
    ok = tmp_cache.put_gated("clone_block", "k-raster", payload, None)
    assert ok
    assert tmp_cache.get("clone_block", "k-raster") == payload


def test_put_gated_caller_boolean_never_bypasses(tmp_cache):
    """payload["rasterFallback"] = True без подтверждающего IR — отказ."""
    payload = {"ir": {"v": 1}, "rasterFallback": True}
    ok = tmp_cache.put_gated("clone_block", "k-bool", payload, None)
    assert not ok
    assert tmp_cache.get("clone_block", "k-bool") is None


def test_put_gated_mixed_ir_with_boolean_refused(tmp_cache):
    """Смешанный IR (editable слой + raster child) + флаг — не обход гейтинга."""
    payload = _locked_raster_payload()
    payload["ir"]["tree"][0]["children"].append(
        {"type": "text", "text": "x", "sourceKey": "arena:root/p:0"})
    payload["rasterFallback"] = True
    ok = tmp_cache.put_gated("clone_block", "k-mixed", payload, None)
    assert not ok
    assert tmp_cache.get("clone_block", "k-mixed") is None


def test_put_gated_unlocked_raster_child_refused(tmp_cache):
    payload = _locked_raster_payload()
    payload["ir"]["tree"][0]["children"][0]["editable"] = True
    payload["rasterFallback"] = True
    ok = tmp_cache.put_gated("clone_block", "k-unlocked", payload, None)
    assert not ok
    assert tmp_cache.get("clone_block", "k-unlocked") is None


def test_put_gated_spoofed_report_flag_refused(tmp_cache):
    """fidelity_report["raster_fallback"] = True без подтверждающего IR — отказ,
    несмотря на то что evaluate_gate такой отчёт пропускает."""
    payload = {"ir": {"v": 1}}
    report = {"raster_fallback": True, "viewports": {}}
    ok = tmp_cache.put_gated("clone_block", "k-spoof", payload, report)
    assert not ok
    assert tmp_cache.get("clone_block", "k-spoof") is None


def test_put_gated_mixed_ir_with_spoofed_report_flag_refused(tmp_cache):
    """Смешанный IR (editable слой + raster child) + spoofed report flag."""
    payload = _locked_raster_payload()
    payload["ir"]["tree"][0]["children"].append(
        {"type": "text", "text": "x", "sourceKey": "arena:root/p:0"})
    report = {"raster_fallback": True, "viewports": {}}
    ok = tmp_cache.put_gated("clone_block", "k-mixed-spoof", payload, report)
    assert not ok
    assert tmp_cache.get("clone_block", "k-mixed-spoof") is None


def test_put_gated_extra_section_with_spoofed_report_flag_refused(tmp_cache):
    """Лишняя не-raster секция + spoofed report flag — отказ."""
    payload = _locked_raster_payload()
    payload["ir"]["tree"].append({"children": [{"type": "text", "text": "x"}]})
    ok = tmp_cache.put_gated("clone_block", "k-extra-sec", payload,
                             {"raster_fallback": True, "viewports": {}})
    assert not ok
    assert tmp_cache.get("clone_block", "k-extra-sec") is None


def test_put_gated_strict_raster_ir_with_report_flag_accepted(tmp_cache):
    """Флаг отчёта не вредит, когда фактический IR сам проходит strict check."""
    payload = _locked_raster_payload()
    ok = tmp_cache.put_gated("clone_block", "k-raster-flag", payload,
                             {"raster_fallback": True, "viewports": {}})
    assert ok
    assert tmp_cache.get("clone_block", "k-raster-flag") == payload


# ---------- golden: фикстура chess_arena на трёх viewport ----------

@pytest.fixture()
def fixture_server():
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_chess_arena_golden(tmp_path, fixture_server, monkeypatch):
    """Golden: каждый viewport рендерится в точном размере, образы равны по
    размеру, все обязательные метрики есть, артефакты сохранены, gate пройден."""
    url = f"{fixture_server}/chess_arena.html"
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    captured = scraper.capture_block_irs(url, ARENA_BLOCK, viewports=VIEWPORTS, timeout_ms=5000)
    item = captured["#arena"]
    assert not item.get("error"), item.get("error")

    reports = fidelity_harness.evaluate_captures(captured, artifacts_dir=tmp_path)
    report = reports["#arena"]

    assert set(report["viewports"]) == {"desktop", "tablet", "mobile"}
    for name, metrics in report["viewports"].items():
        for key in fidelity_harness.REQUIRED_METRICS:
            assert metrics.get(key) is not None, f"[{name}] missing {key}"
        assert metrics["size_match"], (
            f"[{name}] reference {metrics['reference_size']} != render {metrics['render_size']}")
        for artifact in ("reference", "render", "diff"):
            path = Path(metrics["artifacts"][artifact])
            assert path.exists() and path.stat().st_size > 100, f"[{name}] {artifact}"
        # артефакты теста живут только в OS temp, не в репозитории
        assert str(tmp_path) in str(path)

    gate = fidelity_harness.evaluate_gate(report)
    assert gate["passed"], gate["reasons"]


# ---------- import path: IR возвращается всегда, кэш — только при пройденном gate ----------

def test_parse_blocks_warms_cache_only_when_gate_passes(tmp_path, fixture_server, monkeypatch):
    import blockparse

    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "cache.db")
    url = f"{fixture_server}/chess_arena.html"
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)

    parsed = blockparse.parse_blocks(url, blocks=ARENA_BLOCK)
    block = parsed["blocks"][0]
    assert block.get("ir"), block.get("error")  # импорт отдаёт IR
    key = blockparse._block_cache_key(url, "arena", "#arena")
    assert cache_store.get("clone_block", key) is not None  # golden фикстура греет кэш


def test_parse_blocks_fail_closed_when_harness_has_no_metrics(tmp_path, fixture_server, monkeypatch):
    import blockparse
    import fidelity_harness as harness

    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "cache.db")
    url = f"{fixture_server}/chess_arena.html"
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    # harness не смог измерить (например, нет Chromium): метрик нет → fail-closed
    monkeypatch.setattr(harness, "evaluate_captures", lambda items, artifacts_dir=None: {})

    parsed = blockparse.parse_blocks(url, blocks=ARENA_BLOCK)
    block = parsed["blocks"][0]
    assert block.get("ir"), block.get("error")  # IR всё равно возвращается
    key = blockparse._block_cache_key(url, "arena", "#arena")
    assert cache_store.get("clone_block", key) is None  # но кэш не прогрет

