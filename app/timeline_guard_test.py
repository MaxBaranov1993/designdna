"""Границы сложности, ассет-гард рендера, очередь/отмена рендера и ИИ-превью.

Фокус-тесты ремонтных блоков:
* границы сложности контракта (промпт/группы/кейфреймы/операции);
* ассеты рендера: приватные и изменяемые URL отклоняются, контент-адресные
  и мелкие data: проходят, ошибки человекочитаемые;
* очередь рендера ограничена, отменяется и вытесняется по TTL;
* ИИ-режиссёр отдаёт превью с явным планом/фолбэком и не мутирует вход.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import timeline_api
import timeline_assets
import timeline_director
import timeline_render
from server import app
from ir.timeline import (
    MAX_CHANGE_SET_OPERATIONS,
    MAX_GROUPS,
    MAX_KEYFRAMES_PER_TRACK,
    build,
    build_change_set,
    validate,
)

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 1440},
    "tree": [
        {
            "id": "hero-1",
            "sourceKey": "src-hero-1",
            "type": "hero",
            "variant": "center",
            "props": {"heading": "Продукт"},
            "children": [
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
            ],
        },
        {"id": "footer-1", "type": "footer", "variant": "simple", "props": {}},
    ],
}

HASH_HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _timeline(duration: int = 6000) -> dict:
    return build(DESIGN_IR, {"duration": duration})


@pytest.fixture(autouse=True)
def clean_jobs():
    with timeline_render.JOBS_LOCK:
        timeline_render.JOBS.clear()
    yield
    with timeline_render.JOBS_LOCK:
        timeline_render.JOBS.clear()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def silent_submit(monkeypatch):
    """Не запускать настоящий рендер: очередь тестируется без браузера."""
    monkeypatch.setattr(timeline_api, "submit_render", lambda *args, **kwargs: None)


# --------------------------------------------------------------------------
# Границы сложности


def test_assist_rejects_overlong_prompt(client) -> None:
    timeline = _timeline()
    resp = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "интро " * 700})
    assert resp.status_code == 422
    assert "2000" in resp.json()["error"], "ошибка объясняет лимит промпта"


def test_validate_rejects_too_many_groups() -> None:
    timeline = _timeline()
    timeline["groups"] = [
        {"id": f"grp-{i}", "name": f"g{i}", "parent": None} for i in range(MAX_GROUPS + 1)
    ]
    for index, layer in enumerate(timeline["layers"]):
        layer["parent"] = f"grp-{index % (MAX_GROUPS + 1)}"
    errors = validate(timeline)
    assert any("groups" in error for error in errors)


def test_validate_rejects_too_many_keyframes_per_track() -> None:
    timeline = _timeline()
    layer = timeline["layers"][0]
    layer["transform"]["properties"]["x"] = {
        "keyframes": [{"t": i, "value": 0} for i in range(MAX_KEYFRAMES_PER_TRACK + 1)]
    }
    errors = validate(timeline)
    assert any("keyframes per track" in error for error in errors)


def test_commit_rejects_overlarge_operation_batch(client) -> None:
    timeline = _timeline()
    operations = [{
        "kind": "set-keyframes",
        "target": "layer-hero-1",
        "path": "/transform/properties/x",
        "value": {"keyframes": [{"t": 0, "value": float(i)}]},
    } for i in range(MAX_CHANGE_SET_OPERATIONS + 1)]
    resp = client.post("/api/timeline/commit", json={
        "timeline": timeline, "intent": "перегруз", "operations": operations})
    assert resp.status_code == 422
    assert "операций" in resp.json()["error"]


def test_director_bounds_layers_per_step_on_huge_timeline() -> None:
    """Шаг плана по сотням слоёв обрезается: без обрезки 250 слоёв × 2 операции
    дали бы 500+ операций и вышли за лимит change-set."""
    timeline = _timeline()
    extra = [
        {"id": f"layer-bulk-{i}", "name": "секция", "type": "component", "ref": f"src-bulk-{i}",
         "parent": "grp-hero-1", "in": 0, "out": 6000,
         "transform": {"anchor": {"x": 0.5, "y": 0.5}, "properties": {}}}
        for i in range(250)
    ]
    timeline["layers"].extend(extra)
    assert validate(timeline) == []
    step = {"preset": "fade-in-up", "layers": "секция", "start": 0.0, "duration": 0.2}
    operations = timeline_director._step_operations(timeline, step)
    assert len(operations) <= timeline_director.MAX_LAYERS_PER_STEP * 2
    change_set = build_change_set(timeline, "каскад", operations)
    assert len(change_set["operations"]) <= MAX_CHANGE_SET_OPERATIONS


# --------------------------------------------------------------------------
# Ассет-гард рендера


def test_asset_guard_rejects_private_and_changing_urls() -> None:
    # приватный контент-адресный адрес — всё равно отказ (SSRF)
    with pytest.raises(ValueError, match="внутреннюю сеть"):
        timeline_assets.validate_asset_url(f"https://10.0.0.1/assets/{HASH_HEX}.png")
    # изменяемые параметры — отказ
    with pytest.raises(ValueError, match="query/fragment"):
        timeline_assets.validate_asset_url(f"https://cdn.example.com/assets/{HASH_HEX}.png?sig=abc")
    # нет хэша в пути — недетерминированный
    with pytest.raises(ValueError, match="контент-адрес"):
        timeline_assets.validate_asset_url("https://cdn.example.com/img/logo.png")
    # file:/javascript: и прочие схемы
    with pytest.raises(ValueError, match="схема"):
        timeline_assets.validate_asset_url("file:///etc/passwd")
    # большой data: URL
    huge = "data:image/png;base64," + "A" * (timeline_assets.MAX_DATA_URL_CHARS + 10)
    with pytest.raises(ValueError, match="лимит"):
        timeline_assets.validate_asset_url(huge)


def test_asset_guard_accepts_content_addressed_and_small_data() -> None:
    assert timeline_assets.validate_asset_url(f"https://1.1.1.1/assets/{HASH_HEX}.png")
    assert timeline_assets.validate_asset_url("data:image/png;base64,QUJD")
    assert timeline_assets.validate_asset_url("/fonts/inter.woff2")  # локальный инертный путь


def test_asset_guard_checks_hostname_dns(monkeypatch) -> None:
    def fake_resolve(host: str, port: int) -> tuple[str, ...]:
        if host == "evil.internal":
            raise ValueError("Хост 'evil.internal' ведёт во внутреннюю сеть (10.1.2.3)")
        return ("93.184.216.34",)

    monkeypatch.setattr(timeline_assets, "resolve_public_ips", fake_resolve)
    with pytest.raises(ValueError, match="недоступен для рендера"):
        timeline_assets.validate_asset_url(f"https://evil.internal/assets/{HASH_HEX}.png")
    assert timeline_assets.validate_asset_url(f"https://cdn.example.com/a/{HASH_HEX}.png")


def test_validate_render_assets_reports_paths_and_blocks_render(client, silent_submit) -> None:
    bad_ir = copy.deepcopy(DESIGN_IR)
    # контент-адресный путь, но приватный хост — отказ именно по SSRF-правилу
    bad_ir["tree"][0]["children"][0]["src"] = f"https://127.0.0.1:8420/assets/{HASH_HEX}.png"
    errors = timeline_assets.validate_render_assets(bad_ir)
    assert errors and "/tree/0/children/0/src" in errors[0]
    assert "внутреннюю сеть" in errors[0]

    # таймлайн собирается поверх того же IR, чтобы хэш-связка сошлась
    timeline = build(bad_ir, {"duration": 500})
    resp = client.post("/api/timeline/render", json={"timeline": timeline, "ir": bad_ir})
    assert resp.status_code == 422
    assert "ассеты" in resp.json()["error"].lower()


def test_render_accepts_content_addressed_asset(client, silent_submit) -> None:
    timeline = _timeline(duration=500)
    # пересобираем таймлайн поверх IR с ассетом, чтобы хэши сошлись
    ir = copy.deepcopy(DESIGN_IR)
    ir["tree"][0]["children"][0]["src"] = f"https://1.1.1.1/assets/{HASH_HEX}.png"
    timeline = build(ir, {"duration": 500})
    resp = client.post("/api/timeline/render", json={"timeline": timeline, "ir": ir})
    assert resp.status_code == 200, resp.text
    assert resp.json()["renderId"]


# --------------------------------------------------------------------------
# Очередь рендера: лимит, отмена, TTL


def _register_fake_jobs(count: int, status: str = "queued") -> list[str]:
    ids = []
    for i in range(count):
        render_id = f"fake{i:04d}"
        job = timeline_render.register_job(render_id, 10, "mp4", Path(f"/tmp/fake{i}.mp4"))
        assert job is not None
        with timeline_render.JOBS_LOCK:
            timeline_render.JOBS[render_id]["status"] = status
        ids.append(render_id)
    return ids


def test_render_queue_is_bounded(client, silent_submit) -> None:
    _register_fake_jobs(timeline_render.MAX_ACTIVE_RENDERS)
    timeline = _timeline(duration=500)
    resp = client.post("/api/timeline/render", json={"timeline": timeline, "ir": DESIGN_IR})
    assert resp.status_code == 429
    assert "Очередь" in resp.json()["error"]


def test_cancel_queued_and_running_jobs(client) -> None:
    queued_id, running_id = _register_fake_jobs(2)
    with timeline_render.JOBS_LOCK:
        timeline_render.JOBS[running_id]["status"] = "running"

    resp = client.post(f"/api/timeline/render/{queued_id}/cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    status = client.get(f"/api/timeline/render/{queued_id}").json()
    assert status["status"] == "cancelled"

    resp = client.post(f"/api/timeline/render/{running_id}/cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancelling"
    with timeline_render.JOBS_LOCK:
        assert timeline_render.JOBS[running_id]["cancelRequested"] is True

    assert client.post("/api/timeline/render/nope/cancel").status_code == 404
    with timeline_render.JOBS_LOCK:
        timeline_render.JOBS[queued_id]["status"] = "complete"
    assert client.post(f"/api/timeline/render/{queued_id}/cancel").status_code == 409


def test_ttl_eviction_drops_old_jobs_and_files(client, monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "evict.mp4"
    output.write_bytes(b"video")
    job = timeline_render.register_job("evictme", 10, "mp4", output)
    assert job is not None
    with timeline_render.JOBS_LOCK:
        timeline_render.JOBS["evictme"]["status"] = "complete"

    # через час с лишним завершённая задача вытесняется вместе с файлом;
    # задача, созданная уже «после» скачка часов, остаётся
    base = time.monotonic()
    monkeypatch.setattr(timeline_render, "_clock", lambda: base + timeline_render.JOB_TTL_SECONDS + 60)
    fresh = timeline_render.register_job("fresh", 10, "mp4", tmp_path / "fresh.mp4")
    assert fresh is not None

    assert client.get("/api/timeline/render/evictme").status_code == 404
    assert not output.exists(), "артефакт вытесненной задачи удаляется с диска"
    assert client.get("/api/timeline/render/fresh").status_code == 200


# --------------------------------------------------------------------------
# ИИ-режиссёр: превью без мутации канона + видимый фолбэк провайдера


def test_assist_returns_preview_without_mutation(client) -> None:
    timeline = _timeline()
    canonical = copy.deepcopy(timeline)
    resp = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "интро снизу"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preview"] is True
    assert body["planSource"] in ("llm", "deterministic")
    assert body["changeSet"]["atomic"] is True
    assert body["timeline"] != canonical, "превью отличается от исходного таймлайна"
    assert timeline == canonical, "входной канонический таймлайн не мутирован"


def test_assist_reports_llm_fallback(client, monkeypatch) -> None:
    monkeypatch.setenv("DESIGNAI_FLAG_AIDIRECTOR", "1")

    def broken_chat(*args, **kwargs):
        raise RuntimeError("нет подключённых аккаунтов")

    monkeypatch.setattr(timeline_director.llm, "chat", broken_chat)
    timeline = _timeline()
    resp = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "интро снизу"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["planSource"] == "deterministic"
    assert body["warning"] and "LLM-провайдер недоступен" in body["warning"]


def test_direct_uses_llm_plan_when_available(monkeypatch) -> None:
    timeline = _timeline()
    # LLM отвечает — план строится моделью, фолбэк-предупреждения нет
    monkeypatch.setattr(
        timeline_director, "plan_from_llm",
        lambda tl, prompt: [{"preset": "fade-in", "layers": "*", "start": 0.0, "duration": 0.3}])
    applied, change_set, meta = timeline_director.direct(timeline, "интро", allow_llm=True)
    assert meta["planSource"] == "llm" and meta["warning"] is None
    assert validate(applied) == []


def test_render_rejects_overlong_frame_budget(client, silent_submit) -> None:
    # 10 минут на 30 fps = 18000 кадров > лимита 10800
    timeline = build(DESIGN_IR, {"duration": 600000, "fps": 30})
    resp = client.post("/api/timeline/render", json={"timeline": timeline, "ir": DESIGN_IR})
    assert resp.status_code == 422
    assert "frame" in resp.json()["error"].lower()
