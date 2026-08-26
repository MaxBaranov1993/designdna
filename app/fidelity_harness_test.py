"""Fidelity harness: детерминированный golden-тест на фикстуре chess_arena
и fail-closed гейтинг кэш-записей Source Import.

Запуск: .venv/Scripts/python -m pytest app/fidelity_harness_test.py
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

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


def _stub_provenance(**overrides):
    payload = scraper.build_capture_provenance(
        compiler_sha256="a" * 64,
        browser={"name": "chromium", "version": "test"},
        viewport={"name": "desktop", "width": 1440, "height": 900},
        fonts=[],
        assets=[],
        device_scale_factor=1.0,
    )
    payload.update(overrides)
    if "fingerprint" not in overrides:
        payload["fingerprint"] = scraper.provenance_fingerprint(payload)
    return payload


def _report(**viewport_metrics):
    return {"raster_fallback": False,
            "provenance": _stub_provenance(),
            "viewports": {name: _full_metrics(**kw) for name, kw in viewport_metrics.items()}}


# ---------- gate: чистая логика, без браузера ----------

def test_gate_passes_on_healthy_report():
    gate = fidelity_harness.evaluate_gate(_report(desktop={}, tablet={}, mobile={}))
    assert gate["passed"], gate["reasons"]


def test_gate_fails_without_report():
    assert not fidelity_harness.evaluate_gate(None)["passed"]
    assert not fidelity_harness.evaluate_gate({})["passed"]
    assert not fidelity_harness.evaluate_gate({"viewports": {}})["passed"]


def test_gate_fails_without_capture_provenance():
    report = {"raster_fallback": False, "viewports": {"desktop": _full_metrics()}}
    gate = fidelity_harness.evaluate_gate(report)
    assert not gate["passed"]
    assert any("provenance" in reason for reason in gate["reasons"])


def test_gate_fails_on_provenance_fingerprint_mismatch():
    report = _report(desktop={})
    report["provenance"]["fingerprint"] = "0" * 64
    gate = fidelity_harness.evaluate_gate(report)
    assert not gate["passed"]
    assert any("fingerprint" in reason for reason in gate["reasons"])


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


def test_nested_component_frame_is_absolute_to_block_root():
    ir = {"tree": [{
        "frame": {"x": 0, "y": 0, "width": 1000, "height": 700},
        "children": [{
            "frame": {"x": 104, "y": 80, "width": 792, "height": 500},
            "responsive": {"mobile": {"frame": {"x": 16, "y": 48, "width": 358}}},
            "children": [{
                "sourceKey": "grid/card:1",
                "sourceMeta": {"componentBoundary": True},
                "frame": {"x": 30, "y": 24, "width": 240, "height": 286},
                "responsive": {"mobile": {"frame": {"x": 0, "y": 12, "width": 358, "height": 286}}},
            }],
        }],
    }]}
    boundary = fidelity_harness._component_boundaries(ir)["grid/card:1"]
    assert fidelity_harness._viewport_component_frame(boundary, "desktop") == {
        "x": 134.0, "y": 104.0, "width": 240, "height": 286,
    }
    assert fidelity_harness._viewport_component_frame(boundary, "mobile") == {
        "x": 16.0, "y": 60.0, "width": 358, "height": 286,
    }


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


def test_put_gated_refuses_without_provenance(tmp_cache):
    report = {"raster_fallback": False, "viewports": {"desktop": _full_metrics()}}
    ok = tmp_cache.put_gated("clone_block", "k-noprov", {"ir": {"v": 1}}, report)
    assert not ok
    assert tmp_cache.get("clone_block", "k-noprov") is None


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
    captured = scraper.capture_block_irs(url, ARENA_BLOCK, viewports=VIEWPORTS, timeout_ms=30000)
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
    assert block.get("fidelityReport", {}).get("gate", {}).get("passed") is True
    assert all("artifacts" not in metrics for metrics in block["fidelityReport"]["viewports"].values())
    assert all("region_diffs" not in metrics for metrics in block["fidelityReport"]["viewports"].values())
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


# ---------- WebP card residual: shared lossless intermediate ----------

def _webp_supported() -> bool:
    buf = io.BytesIO()
    try:
        Image.new("RGB", (8, 8), (12, 34, 56)).save(buf, format="WEBP", quality=40)
        return True
    except Exception:
        return False


def _write_webp_card_fixture(root: Path) -> bytes:
    """High-frequency WebP displayed smaller than intrinsic with cover crop.

    Matches the live residual: CSS background-size/object-fit resample of a
    lossy WebP disagrees with a second Chromium decode of the same bytes.
    """
    from PIL import Image as PILImage

    width, height = 320, 180
    img = PILImage.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (x * 13 + y * 7) % 256,
                (y * 17 + x * 5) % 256,
                (x * y * 3) % 256,
            )
    for y in range(40, 140):
        for x in range(80, 240):
            pixels[x, y] = (28, 96, 210)
    raw_path = root / "card.webp"
    img.save(raw_path, format="WEBP", quality=35, method=6)
    payload = raw_path.read_bytes()
    (root / "cards.html").write_text(
        """<!doctype html>
<html><head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; background: #101018; }
  #cards { width: 390px; padding: 8px; box-sizing: border-box; }
  .row { display: flex; gap: 8px; }
  .card { width: 180px; height: 100px; border-radius: 12px; overflow: hidden; }
  .card img { width: 100%; height: 100%; object-fit: cover; object-position: 20% 80%; display: block; }
  .bg { background: url("card.webp") 20% 80% / cover no-repeat; }
</style>
</head>
<body>
<section id="cards">
  <div class="row">
    <div class="card"><img src="card.webp" alt="cover"></div>
    <div class="card bg"></div>
  </div>
</section>
</body></html>
""",
        encoding="utf-8",
    )
    return payload


def _serve_dir(directory: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 partial(SimpleHTTPRequestHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture()
def blob_home(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(root))
    return root


def test_lossless_png_from_bytes_is_deterministic(tmp_path):
    if not _webp_supported():
        pytest.skip("Pillow WebP support is required")
    raw = _write_webp_card_fixture(tmp_path)
    first = scraper.lossless_png_from_bytes(raw, 180, 100, "cover", "20% 80%")
    second = scraper.lossless_png_from_bytes(raw, 180, 100, "cover", "20% 80%")
    assert first == second
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    assert scraper.image_dimensions(scraper.png_data_url(first)) == (180, 100)
    assert hashlib.sha256(raw).hexdigest() != hashlib.sha256(first).hexdigest()


def test_png_blob_object_bytes_hash_to_filename(blob_home):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (12, 34, 56)).save(buf, format="PNG")
    png = buf.getvalue()
    digest = scraper.put_png_blob(png)
    path = scraper.blobs_dir() / f"{digest}.png"
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert path.read_bytes() == png
    assert scraper.put_png_blob(png) == digest
    assert list(scraper.blobs_dir().glob("*.png")) == [path]


def test_png_blob_refuses_corrupt_overwrite_and_read(blob_home):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
    png = buf.getvalue()
    digest = scraper.put_png_blob(png)
    path = scraper.blobs_dir() / f"{digest}.png"
    garbage = b"not-a-png-object-at-this-path"
    path.write_bytes(garbage)
    with pytest.raises(ValueError, match="different bytes"):
        scraper.put_png_blob(png)
    assert path.read_bytes() == garbage
    with pytest.raises(ValueError, match="corrupt"):
        scraper.read_png_blob(digest)
    missing = "0" * 64
    with pytest.raises(FileNotFoundError):
        scraper.read_png_blob(missing)


def test_png_blob_concurrent_writers_reuse_one_object(blob_home):
    from concurrent.futures import ThreadPoolExecutor

    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (9, 10, 11)).save(buf, format="PNG")
    png = buf.getvalue()

    def write_once(_index: int) -> str:
        return scraper.put_png_blob(png)

    with ThreadPoolExecutor(max_workers=16) as pool:
        digests = list(pool.map(write_once, range(32)))
    assert len(set(digests)) == 1
    digest = digests[0]
    files = sorted(scraper.blobs_dir().glob("*.png"))
    assert [path.name for path in files] == [f"{digest}.png"]
    assert files[0].read_bytes() == png
    assert hashlib.sha256(files[0].read_bytes()).hexdigest() == digest
    assert list(scraper.blobs_dir().glob("*.tmp")) == []


def test_webp_cards_without_shared_lossless_intermediate_remain_nonportable(tmp_path, monkeypatch, blob_home):
    """Without materialization the IR keeps a WebP/network reference.

    Pixel similarity is intentionally not asserted below the gate: decoding and
    resampling the same WebP can be above or below 85 across Chromium/GPU builds.
    The deterministic positive test below proves the required ddna PNG replay.
    """
    if not _webp_supported():
        pytest.skip("Pillow WebP support is required")
    raw = _write_webp_card_fixture(tmp_path)
    server = _serve_dir(tmp_path)
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    monkeypatch.setattr(scraper, "_materialize_capture_assets", lambda *args, **kwargs: [])
    url = f"http://127.0.0.1:{server.server_port}/cards.html"
    try:
        captured = scraper.capture_block_irs(
            url,
            [{"name": "cards", "label": "Cards", "kind": "section", "selector": "#cards"}],
            viewports=[{"name": "mobile", "width": 390, "height": 844}],
            timeout_ms=30000,
        )
        item = captured["#cards"]
        assert not item.get("error"), item.get("error")
        srcs = [str(node.get("src") or "") for node, _p in scraper._walk_source_nodes(
            (item.get("ir") or {}).get("tree") or [])]
        assert any(src.endswith(".webp") or "card.webp" in src or src.startswith("data:image/webp")
                   for src in srcs), srcs
        reports = fidelity_harness.evaluate_captures(captured, artifacts_dir=tmp_path / "before")
        metrics = reports["#cards"]["viewports"]["mobile"]
        similarity = metrics.get("pixel_similarity")
        assert similarity is not None, metrics
        assert 0.0 <= similarity <= 100.0
        assert any(not src.startswith("ddna://blobs/") and ("card.webp" in src or src.startswith("data:image/webp"))
                   for src in srcs), srcs
    finally:
        server.shutdown()
        server.server_close()
    assert raw[:4] == b"RIFF"


def test_webp_cards_capture_replay_is_deterministic(tmp_path, monkeypatch, blob_home):
    """Shared lossless PNG objects: gate passes and a second capture reuses refs."""
    if not _webp_supported():
        pytest.skip("Pillow WebP support is required")
    raw = _write_webp_card_fixture(tmp_path)
    server = _serve_dir(tmp_path)
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    url = f"http://127.0.0.1:{server.server_port}/cards.html"
    block = [{"name": "cards", "label": "Cards", "kind": "section", "selector": "#cards"}]
    viewports = [{"name": "mobile", "width": 390, "height": 844}]
    try:
        first = scraper.capture_block_irs(url, block, viewports=viewports, timeout_ms=30000)
        second = scraper.capture_block_irs(url, block, viewports=viewports, timeout_ms=30000)
    finally:
        server.shutdown()
        server.server_close()

    item = first["#cards"]
    assert not item.get("error"), item.get("error")
    ir = item.get("ir") or {}
    assert scraper.ir_raster_data_urls(ir) == [], scraper.ir_raster_data_urls(ir)
    provenance = item.get("provenance") or {}
    assert provenance.get("captureVersion") == scraper.SOURCE_CAPTURE_VERSION
    assert len(str(provenance.get("compilerSha256") or "")) == 64
    assert (provenance.get("browser") or {}).get("name") == "chromium"
    assert (provenance.get("browser") or {}).get("version")
    assert provenance.get("deviceScaleFactor") == 1.0
    assert provenance.get("fingerprint") == scraper.provenance_fingerprint(provenance)
    assert provenance.get("assets"), "content-addressed source bytes must be recorded"
    source_hash = hashlib.sha256(raw).hexdigest()
    assert {rec.get("sourceSha256") for rec in provenance["assets"]} == {source_hash}
    for rec in provenance["assets"]:
        object_hash = rec.get("objectSha256")
        assert object_hash and object_hash != rec.get("sourceSha256")
        assert rec.get("ref") == scraper.blob_ref(object_hash)
        stored = scraper.read_png_blob(object_hash)
        assert hashlib.sha256(stored).hexdigest() == object_hash
        assert rec.get("width") == 180 and rec.get("height") == 100
        assert rec.get("objectFit") == "cover"
        assert rec.get("captureVersion") == scraper.SOURCE_CAPTURE_VERSION

    hashed_nodes = []
    for node, _parent in scraper._walk_source_nodes((ir.get("tree") or [])):
        meta = node.get("sourceMeta") or {}
        if node.get("type") == "image" and meta.get("objectSha256"):
            hashed_nodes.append(node)
            assert scraper.parse_blob_ref(str(node.get("src") or "")) == meta["objectSha256"]
            assert not str(node.get("src") or "").startswith("data:")
            assert (node.get("style") or {}).get("objectFit") == "fill"
            assert meta.get("url")
            assert meta.get("sourceSha256") == source_hash
            assert meta.get("sourceSha256") != meta.get("objectSha256")
    assert len(hashed_nodes) >= 2, "img + background-image cards must become hashed PNG layers"

    first_hashed = [(n.get("sourceKey"), n.get("src"), n.get("sourceMeta", {}).get("objectSha256"))
                    for n in hashed_nodes]
    second_hashed = [(node.get("sourceKey"), node.get("src"),
                      (node.get("sourceMeta") or {}).get("objectSha256"))
                     for node, _p in scraper._walk_source_nodes(
                         (second["#cards"].get("ir") or {}).get("tree") or [])
                     if (node.get("sourceMeta") or {}).get("objectSha256")]
    assert first_hashed == second_hashed
    assert (first["#cards"]["provenance"]["fingerprint"]
            == second["#cards"]["provenance"]["fingerprint"])

    reports = fidelity_harness.evaluate_captures(first, artifacts_dir=tmp_path / "after-1")
    report = reports["#cards"]
    metrics = report["viewports"]["mobile"]
    assert metrics["pixel_similarity"] is not None
    assert metrics["pixel_similarity"] >= fidelity_harness.GATE_THRESHOLDS["min_pixel_similarity"]
    assert metrics["size_match"]
    gate = fidelity_harness.evaluate_gate(report)
    assert gate["passed"], gate["reasons"]
    assert scraper.ir_raster_data_urls(first["#cards"]["ir"]) == []

    reports2 = fidelity_harness.evaluate_captures(second, artifacts_dir=tmp_path / "after-2")
    render1 = Path(metrics["artifacts"]["render"]).read_bytes()
    render2 = Path(reports2["#cards"]["viewports"]["mobile"]["artifacts"]["render"]).read_bytes()
    assert render1 == render2
    assert reports2["#cards"]["viewports"]["mobile"]["pixel_similarity"] == metrics["pixel_similarity"]


def test_missing_or_corrupt_blob_fails_closed(tmp_path, monkeypatch, blob_home):
    if not _webp_supported():
        pytest.skip("Pillow WebP support is required")
    _write_webp_card_fixture(tmp_path)
    server = _serve_dir(tmp_path)
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    url = f"http://127.0.0.1:{server.server_port}/cards.html"
    try:
        captured = scraper.capture_block_irs(
            url,
            [{"name": "cards", "label": "Cards", "kind": "section", "selector": "#cards"}],
            viewports=[{"name": "mobile", "width": 390, "height": 844}],
            timeout_ms=30000,
        )
    finally:
        server.shutdown()
        server.server_close()
    item = captured["#cards"]
    assert not item.get("error"), item.get("error")
    objects = sorted({rec.get("objectSha256") for rec in (item.get("provenance") or {}).get("assets") or []
                      if rec.get("objectSha256")})
    assert objects
    original = json.dumps(item["ir"], sort_keys=True)
    blob_files = list(scraper.blobs_dir().glob("*.png"))
    assert blob_files
    for path in blob_files:
        path.unlink()
    reports = fidelity_harness.evaluate_captures(captured, artifacts_dir=tmp_path / "missing")
    metrics = reports["#cards"]["viewports"]["mobile"]
    assert metrics.get("pixel_similarity") is None
    assert not reports["#cards"]["gate"]["passed"]
    assert json.dumps(item["ir"], sort_keys=True) == original

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (9, 9, 9)).save(buf, format="PNG")
    (scraper.blobs_dir() / f"{objects[0]}.png").write_bytes(buf.getvalue())
    reports_corrupt = fidelity_harness.evaluate_captures(captured, artifacts_dir=tmp_path / "corrupt")
    assert reports_corrupt["#cards"]["viewports"]["mobile"].get("pixel_similarity") is None
    assert not reports_corrupt["#cards"]["gate"]["passed"]
    assert json.dumps(item["ir"], sort_keys=True) == original
