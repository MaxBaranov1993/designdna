"""_with_reproduce_parser_contract: кэш с пустым деревом не должен ронять /api/reproduce."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


def test_empty_tree_payload_passes_through_without_contract():
    payload = {"ir": {"tree": []}, "structure": {"cached": 1}, "provider_used": "cache"}
    out = server._with_reproduce_parser_contract(payload, "screenshot://x", "image")
    assert out == payload
    assert "parserContract" not in out


def test_missing_ir_passes_through():
    payload = {"provider_used": "cache"}
    assert server._with_reproduce_parser_contract(payload, "screenshot://x", "image") == payload


def test_existing_contract_is_not_rebuilt():
    payload = {"ir": {"tree": [{"type": "hero"}]}, "parserContract": {"version": "x"}}
    out = server._with_reproduce_parser_contract(payload, "u", "url")
    assert out["parserContract"] == {"version": "x"}
