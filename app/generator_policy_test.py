"""Runtime design-policy contracts. No model/network or user's project writes."""
import copy
import io
import json

import pytest
from PIL import Image

import generator_policy as policy
import server
from design_system import store
from design_system_strict_fallback_test import _document, _fixture
from generation_provider_test import art_directions
from quality_pass_test import HIGH_JUDGE, LOW_JUDGE
from test_qualitygate import BASE_IR


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    cache = {}
    monkeypatch.setattr(server.cache_store, "get", lambda kind, key: copy.deepcopy(cache.get((kind, key))))
    monkeypatch.setattr(server.cache_store, "put", lambda kind, key, value: cache.__setitem__((kind, key), copy.deepcopy(value)))
    monkeypatch.setattr(server.project_rules, "prompt_block", lambda *_: "")
    monkeypatch.setattr(server.project_store, "build_prompt_memory_hint", lambda: "")
    monkeypatch.setattr(server.llm, "chat", lambda *_a, **_k: pytest.fail("unexpected model call"))


@pytest.mark.parametrize("brief,expected", [
    ("Лендинг поиска квартир", "landing"), ("Каталог квартир", "catalog"),
    ("Карточка товара", "detail"), ("Оформление заказа", "checkout"),
    ("Форма настроек", "form"), ("Dashboard analytics", "dashboard"),
    ("Canvas editor", "editor"), ("AI assistant", "ai-workspace"),
    ("Editorial article", "article"), ("Лента публикаций", "feed"),
    ("Button component", "component"),
])
def test_surface_classification(brief, expected):
    assert policy.surface_for(brief) == expected


def test_explicit_surface_and_style_retrieval():
    assert policy.surface_for("Лендинг", "form") == "form"
    data = policy.knowledge()
    assert set(data["styles"]) == set(policy.STYLE_IDS) - {"auto"}
    assert set(data["patterns"]) == set(policy.SURFACES) - {"auto"}
    free = policy.prompt(policy.context("Form", style="luxury"))
    locked = policy.prompt(policy.context("Form", style="luxury", locked=True))
    assert "Selected style" in free and "Selected style" not in locked
    assert "surface" in policy.judge_rules("landing", BASE_IR, "form").lower()
    assert "Surface: form" in policy.judge_rules("landing", BASE_IR, "form")


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_utility_prompt_and_receipt(provider):
    request = dict(brief="Форма настроек", surface="form", provider=provider, count=1)
    prepared = server.generate(server.GenerateReq(**request, prepareOnly=True))
    system = prepared["prompts"][0]["messages"][0]["content"]
    assert "generator-design/1.0" in system
    assert '"schemaVersion": "generator-plan/1.0"' in system
    assert '"surface": "form"' in system
    assert prepared["designPolicy"]["requestedMode"] == "freeform"
    applied = server.generate(server.GenerateReq(**request, preparedContextId=prepared["preparedContextId"],
        rawOutputs=[json.dumps(_fixture())]))
    assert applied["variants"] and applied["directions"] == prepared["directions"]
    changed = server.generate(server.GenerateReq(**{**request, "surface": "landing"},
        preparedContextId=prepared["preparedContextId"], rawOutputs=[json.dumps(_fixture())]))
    assert changed.status_code == 409


def test_prepare_snapshot_reuses_exact_art_records(monkeypatch):
    import art_direction
    calls = []
    def direction(*_args, **_kwargs):
        calls.append(1)
        return art_directions()
    monkeypatch.setattr(art_direction, "create_design_brief", direction)
    request = dict(brief="Landing", surface="landing", count=1, selectedDirection="industrial")
    first = server.generate(server.GenerateReq(**request, prepareOnly=True))
    second = server.generate(server.GenerateReq(**request, preparedContextId=first["preparedContextId"],
        rawOutputs=[json.dumps(_fixture())]))
    assert calls == [1]
    assert second["variantDirections"] == first["variantDirections"] == ["Industrial Grid"]
    monkeypatch.setattr(server.project_rules, "prompt_block", lambda *_: "changed policy")
    stale = server.generate(server.GenerateReq(**request, preparedContextId=first["preparedContextId"],
        rawOutputs=[json.dumps(_fixture())]))
    assert stale.status_code == 409


def test_ds_resolved_once_and_changed_revision_rejected(monkeypatch):
    doc = _document(_fixture())
    calls = []
    def resolve(_ref):
        calls.append(1)
        return copy.deepcopy(doc), None
    monkeypatch.setattr(store, "resolve_ref", resolve)
    request = dict(brief="Form", surface="form", count=1,
        designSystem={"systemId": doc["id"], "usageMode": "style-only"})
    first = server.generate(server.GenerateReq(**request, prepareOnly=True))
    assert len(calls) == 1
    doc["revision"] += 1
    second = server.generate(server.GenerateReq(**request, preparedContextId=first["preparedContextId"],
        rawOutputs=[json.dumps(_fixture())]))
    assert second.status_code == 409


def test_default_strict_never_silently_extends(monkeypatch):
    master = _fixture()
    monkeypatch.setattr(store, "resolve_ref", lambda _: (_document(master), None))
    result = server.generate(server.GenerateReq(brief="unrelated canvas", count=1,
        designSystem={"systemId": "ds-pricing", "revision": 1, "usageMode": "strict"},
        rawOutputs=[json.dumps(master)]))
    assert result.status_code == 422


def test_invalid_system_is_an_explicit_error():
    result = server.generate(server.GenerateReq(brief="Form", designSystem={}))
    assert result.status_code == 422


def test_repair_preserves_foundations_and_exact_master():
    before = copy.deepcopy(BASE_IR)
    after = copy.deepcopy(before)
    after["tokens"]["color"]["primary"] = "#ff0000"
    assert "foundations" in policy.repair_guard(before, after, "landing")
    before["tree"][0]["sourceMeta"] = {"componentRef": {"componentKey": "hero", "masterHash": "hash"}}
    after = copy.deepcopy(before)
    after["tree"][0].setdefault("style", {})["background"] = "#ff0000"
    assert "exact master" in policy.repair_guard(before, after, "landing")


def test_lint_exempts_components_from_page_rules_only():
    value = copy.deepcopy(BASE_IR)
    value["tree"] = [{"type": "source-block", "children": []}]
    assert "single-h1" not in {x["rule"] for x in policy.lint(value, "component")}
    assert "single-h1" in {x["rule"] for x in policy.lint(value, "landing")}


@pytest.mark.parametrize("mutation", ["tokens", "new-defect", "no-rejudge", "new-issue", "score-drop"])
def test_bad_repair_rolls_back_exactly(mutation):
    before = copy.deepcopy(BASE_IR)
    after = copy.deepcopy(before)
    initial = json.loads(LOW_JUDGE)
    final = json.loads(HIGH_JUDGE)
    if mutation == "tokens":
        after["tokens"]["color"]["primary"] = "#ff0000"
    elif mutation == "new-defect":
        after["tree"] = []
    elif mutation == "new-issue":
        final["issues"] = [{"category": "color", "path": "tree.0", "problem": "new", "severity": "minor"}]
    elif mutation == "score-drop":
        final["score"] = 59
    request = server.QualityPassReq(ir=before, rejudge=mutation != "no-rejudge")
    result = server._quality_finish(request, after, initial, final,
        {"attempted": True, "applied": True, "error": None}, visual=True)
    assert result["ir"] == before
    assert result["passed"] is False and result["repair"]["applied"] is False
    assert result["repair"]["error"]


def test_major_issue_blocks_pass_and_text_only_remains_unverified():
    initial = json.loads(HIGH_JUDGE)
    request = server.QualityPassReq(ir=copy.deepcopy(BASE_IR), repair=False)
    repair = {"attempted": False, "applied": False, "error": None}
    result = server._quality_finish(request, request.ir, initial, initial, repair)
    assert result["acceptance"]["status"] == "unverified"
    assert result["acceptance"]["checks"]["keyboard"] == "unknown"
    initial["issues"] = [{"severity": "major", "problem": "unusable"}]
    result = server._quality_finish(request, request.ir, initial, initial, repair, visual=True)
    assert result["passed"] is False


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_desktop_vision_uses_real_viewport_mode_and_caches_images(monkeypatch, provider):
    calls = []
    monkeypatch.setattr(server, "_quality_visual_key", lambda ir, brief: policy.digest([ir, brief]))
    def render(_ir, width, **kwargs):
        calls.append((width, kwargs.get("viewport")))
        output = io.BytesIO()
        Image.new("RGB", (width, 100), "white").save(output, "PNG")
        return output.getvalue()
    monkeypatch.setattr(server, "render_png", render)
    request = dict(ir=copy.deepcopy(BASE_IR), provider=provider, visualReview=True, repair=False)
    first = server.quality_pass_codex_step(server.QualityPassCodexReq(**request))
    content = first["pending"]["messages"][1]["content"]
    assert calls == [(1440, "desktop"), (390, "mobile")]
    assert [part["type"] for part in content] == ["text", "image_url", "image_url"]
    server.quality_pass_codex_step(server.QualityPassCodexReq(**request))
    assert len(calls) == 2
    final = server.quality_pass_codex_step(server.QualityPassCodexReq(**request, outputs={"judge": HIGH_JUDGE}))
    assert final["acceptance"]["status"] == "preview-ready"
    assert final["acceptance"]["checks"]["screenReader"] == "unknown"
