"""Сборка system-промпта generate-first: DesignBrief, few-shot эталоны, плейсхолдеры."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
import llm_client  # noqa: E402


ROOT = APP.parent
PROMPT_FILES = (
    "app/prompts/SYSTEM.md", "schema/design-ir.schema.json",
    "app/prompts/BLOCKS.md", "app/prompts/DESIGN.md",
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    llm_client.invalidate_prompt_cache()
    yield
    llm_client.invalidate_prompt_cache()


def test_placeholders_are_all_substituted():
    prompt = llm_client.build_system_prompt("generate")
    for placeholder in ("{{SCHEMA}}", "{{BLOCKS}}", "{{DESIGN}}", "{{DESIGN_BRIEF}}",
                        "{{EXEMPLARS}}", "{{BRIEF}}", "{{STYLE_HINT}}", "{{MODE}}"):
        assert placeholder not in prompt, placeholder


def test_generate_is_the_primary_mode():
    """Регрессия на корневую причину из §2.3 аудита: edit больше не «главная роль»."""
    prompt = llm_client.build_system_prompt("generate")
    assert "You are an EDITING tool first" not in prompt
    assert "Current operation: generate" in prompt
    assert "In generate mode, solve the brief" in prompt
    assert "In edit mode, reproduce" in prompt
    assert "preserve all other content and structure" in prompt
    assert '"composition"' in prompt


def test_default_call_stays_cached_and_backward_compatible():
    first = llm_client.build_system_prompt("generate")
    assert llm_client.build_system_prompt("generate") is first
    assert llm_client.build_system_prompt("generate", design_brief="", exemplars="") is first


def test_context_is_injected_and_not_cached_over():
    plain = llm_client.build_system_prompt("generate")
    brief = {"schemaVersion": "design-brief/1.0", "tone": "industrial"}
    with_brief = llm_client.build_system_prompt("generate", design_brief=brief)
    assert '"tone": "industrial"' in with_brief
    assert with_brief != plain
    # непустой контекст не отравляет кэш пустого вызова
    assert llm_client.build_system_prompt("generate") == plain

    with_exemplars = llm_client.build_system_prompt("generate", exemplars="### exemplar: x")
    assert "### exemplar: x" in with_exemplars
    assert llm_client.build_system_prompt("generate") == plain


def test_prompt_files_are_read_once_per_build(monkeypatch, tmp_path):
    """Кэш файлов из llm_prompt_cache_test не должен ломаться новыми плейсхолдерами."""
    for name in PROMPT_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(llm_client, "ROOT", tmp_path)
    llm_client.invalidate_prompt_cache()

    reads = {"n": 0}
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (reads.__setitem__("n", reads["n"] + 1),
                                                                 original(self, *a, **k))[1])
    llm_client.build_system_prompt("generate", design_brief="{}", exemplars="x")
    assert reads["n"] == len(PROMPT_FILES)


@pytest.mark.parametrize("product_type,expected", [
    ("SaaS-платформа для складов", "saas-landing"),
    ("маркетплейс промышленного оборудования", "marketplace"),
    ("винный бар с кухней, меню и бронью", "restaurant"),
])
def test_exemplar_selection_follows_product_type(product_type, expected):
    names = llm_client.exemplar_names(product_type)
    assert names[0] == expected, names
    assert 2 <= len(names) <= 3


def test_unknown_product_type_falls_back_to_two_exemplars():
    names = llm_client.exemplar_names("нечто без единого ключевого слова")
    assert names[:2] == list(llm_client._EXEMPLAR_FALLBACK)
    assert len(names) == 3


@pytest.mark.parametrize("product_type", [
    "ecommerce", "education", "fintech", "healthcare", "portfolio", "real-estate", "travel",
])
def test_product_id_selects_its_own_exemplar_first(product_type):
    assert llm_client.exemplar_names(product_type)[0] == product_type


def test_load_exemplars_emits_valid_json_within_budget():
    """Обрезка идёт секциями, а не символами: модель не должна видеть битый JSON."""
    block = llm_client.load_exemplars("маркетплейс станков")
    assert block.startswith("### exemplar: marketplace")
    assert "направление" in block
    bodies = [chunk.split("\n```")[0] for chunk in block.split("```json\n")[1:]]
    assert bodies, block[:200]
    for body in bodies:
        assert len(body) <= llm_client.EXEMPLAR_BUDGET
        document = json.loads(body)
        assert document["tree"], "у ужатого эталона должна остаться хотя бы одна секция"


def test_fit_exemplar_drops_tail_sections_only():
    document = {"version": "1.1", "tokens": {}, "tree": [{"id": f"s{i}", "text": "x" * 400}
                                                         for i in range(10)]}
    body, dropped = llm_client.fit_exemplar(document, budget=1500)
    assert dropped > 0
    kept = json.loads(body)["tree"]
    assert len(body) <= 1500 and kept == document["tree"][:len(kept)]
    assert llm_client.fit_exemplar(document, budget=10**6) == (json.dumps(
        document, ensure_ascii=False, separators=(",", ":")), 0)


def test_load_exemplars_tolerates_missing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client, "ROOT", tmp_path)
    llm_client.invalidate_prompt_cache()
    assert llm_client.load_exemplars("маркетплейс") == ""


def test_full_generate_prompt_carries_brief_and_exemplars():
    prompt = llm_client.build_system_prompt(
        "generate",
        design_brief={"tone": "editorial", "typePair": "lora-literata"},
        exemplars=llm_client.load_exemplars("винный бар"),
    )
    assert "editorial" in prompt
    assert "### exemplar: restaurant" in prompt
    # Assigned art direction and examples remain subordinate to pinned masters.
    assert "tradeoff" in prompt
    assert "Assigned direction (subordinate to locked DS and user scope)" in prompt
    assert "Relevant examples (not facts or replacement masters)" in prompt
    assert prompt.index("Applicable policy and pinned constraints") < prompt.index("### exemplar: restaurant")
