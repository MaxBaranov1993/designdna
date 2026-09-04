"""Импорт ДС файлом, секция мастера для редактора, вариант из редактора.

Загруженная ДС должна давать ту же форму документа, что ДС из Source:
foundations + styleGuide.irTokens, которые генератор лочит; вариант из
редактора добавляется в компонент, а не плодит новые компоненты.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="ddna-import-")
os.environ["DESIGNDNA_DATA_DIR"] = TMP

from fastapi.testclient import TestClient  # noqa: E402

from design_system import document as dsdoc, importer, store  # noqa: E402
from ir.validate import validate_ir  # noqa: E402
from server import app  # noqa: E402

client = TestClient(app)

W3C = {
    "color": {
        "brand": {"primary": {"$type": "color", "$value": "#2f4bd9"},
                  "accent": {"$type": "color", "$value": "#0e6e6a"}},
        "background": {"$type": "color", "$value": "#f5f6f3"},
        "surface": {"$type": "color", "$value": "#ffffff"},
        "text": {"$type": "color", "$value": "#1a1d1b"},
        "text-muted": {"$type": "color", "$value": "{color.text}"},
        "border": {"$type": "color", "$value": "#d9ddd8"},
    },
    "fontFamily": {"heading": {"$type": "fontFamily", "$value": ["Piazzolla", "serif"]},
                   "body": {"$type": "fontFamily", "$value": "Golos Text"}},
    "dimension": {"radius-sm": {"$type": "dimension", "$value": "6px"},
                  "radius-lg": {"$type": "dimension", "$value": "16px"},
                  "space-2": {"$type": "dimension", "$value": "1rem"}},
    "shadow": {"card": {"$type": "shadow", "$value": {"x": 0, "y": 4, "blur": 12, "spread": 0, "color": "#0000001f"}}},
}

TOKENS_STUDIO = {"global": {"colors": {"primary": {"value": "#ff5a1f", "type": "color"},
                                       "bg": {"value": "#111111", "type": "color"},
                                       "fg": {"value": "#f5f5f5", "type": "color"}},
                            "font": {"family": {"sans": {"value": "Inter", "type": "fontFamilies"}}}}}

SHADCN = {"background": "#0b0b0d", "foreground": "#f4f4f5", "card": "#141418", "muted-foreground": "#9a9aa3",
          "primary": "#ff691d", "border": "#26262d"}


def test_detects_formats():
    assert importer.detect_format(W3C) == "design-tokens"
    assert importer.detect_format(TOKENS_STUDIO) == "design-tokens"
    assert importer.detect_format(SHADCN) == "token-map"
    assert importer.detect_format({"schemaVersion": "x", "foundations": {}, "id": "ds-1"}) == "designdna-document"
    assert importer.detect_format({"hello": "world"}) is None
    assert importer.detect_format([]) is None


def test_w3c_tokens_become_a_draft_with_locked_ir_tokens():
    doc = importer.import_design_system(W3C, file_name="brand-tokens.json")
    assert doc["name"] == "brand-tokens"
    assert doc["status"] == "draft" and doc["revision"] == 0
    semantic = doc["foundations"]["colors"]["semantic"]
    assert semantic["primary"] == "#2f4bd9"
    assert semantic["accent"] == "#0e6e6a"
    assert semantic["background"] == "#f5f6f3"
    assert semantic["text"] == "#1a1d1b"
    assert semantic["textMuted"] == "#1a1d1b"  # алиас {color.text} разрешён
    assert semantic["border"] == "#d9ddd8"
    typo = doc["foundations"]["typography"]
    assert typo["display"]["family"] == "Piazzolla"
    assert typo["body"]["family"] == "Golos Text"
    assert doc["foundations"]["radii"] == [6.0, 16.0]
    assert doc["foundations"]["spacing"] == {"space2": 16.0}
    assert doc["foundations"]["shadows"] and "12px" in doc["foundations"]["shadows"][0]
    assert len(doc["foundations"]["colors"]["primitives"]) >= 6
    ir_tokens = doc["styleGuide"]["irTokens"]
    assert ir_tokens["color"]["primary"] == "#2f4bd9"
    assert ir_tokens["font"]["display"]["family"] == "Piazzolla"
    probe = {"version": "1.1", "tokens": ir_tokens, "tree": [{"id": "s", "type": "composition", "children": []}]}
    assert not [e for e in validate_ir(probe) if "tokens" in str(e.path)]
    assert [e for e in dsdoc.validate_document(doc) if e.get("code") != "no-components"] == []
    assert doc["provenance"]["imported"]["format"] == "design-tokens"


def test_tokens_studio_and_shadcn_maps_are_accepted():
    studio = importer.import_design_system(TOKENS_STUDIO, name="Studio")
    assert studio["foundations"]["colors"]["semantic"]["primary"] == "#ff5a1f"
    assert studio["foundations"]["colors"]["semantic"]["background"] == "#111111"
    assert studio["foundations"]["mode"] == "dark"
    assert studio["foundations"]["typography"]["body"]["family"] == "Inter"
    shad = importer.import_design_system(SHADCN, name="Shad")
    assert shad["foundations"]["colors"]["semantic"]["background"] == "#0b0b0d"
    assert shad["foundations"]["colors"]["semantic"]["surface"] == "#141418"
    assert shad["styleGuide"]["irTokens"]["color"]["primary"] == "#ff691d"


def test_unknown_payload_is_rejected():
    try:
        importer.import_design_system({"foo": {"bar": 1}})
    except ValueError as exc:
        assert "формат" in str(exc)
    else:
        raise AssertionError("ожидалась ошибка формата")


def test_import_endpoint_saves_a_draft_and_roundtrips_a_document():
    res = client.post("/api/design-system/import", json={"payload": W3C, "fileName": "kit.json"})
    assert res.status_code == 200, res.text
    body = res.json()
    doc = body["document"]
    assert body["format"] == "design-tokens"
    assert doc["id"].startswith("ds-") and doc["status"] == "draft"
    assert store.get_revision(doc["id"], 0) is not None
    # документ DesignDNA как кит: переносится целиком, остаётся черновиком
    again = client.post("/api/design-system/import", json={"payload": doc, "name": "Kit copy"})
    assert again.status_code == 200, again.text
    copied = again.json()["document"]
    assert copied["id"] == doc["id"] and copied["name"] == "Kit copy" and copied["status"] == "draft"
    assert copied["provenance"]["imported"]["format"] == "designdna-document"
    bad = client.post("/api/design-system/import", json={"payload": {"x": 1}})
    assert bad.status_code == 422


def _user_component(ir_root: dict) -> dict:
    master = {"version": "1.1", "tokens": {}, "tree": [ir_root]}
    return {
        "componentKey": "promo-card", "name": "Promo card", "category": "content",
        "origin": "user", "status": "verified", "confirmed": True,
        "masterIr": master, "propsSchema": {}, "slots": [],
        "variants": {"default": {"label": "Default", "origin": "user", "confirmed": True, "masterRef": "self", "diff": {}}},
        "states": {}, "dependencies": [], "tokenBindings": {}, "mockBindings": [],
    }


def test_variant_save_adds_a_user_variant_and_component_section_pins_a_ref():
    res = client.post("/api/design-system/import", json={"payload": SHADCN, "name": "Variants"})
    doc = res.json()["document"]
    root = {"type": "card", "frame": {"x": 0, "y": 0, "width": 320, "height": 160},
            "children": [{"type": "heading", "level": 3, "text": "Promo"}]}
    doc["components"] = {"promo-card": _user_component(root)}
    saved = client.post("/api/design-system/save-draft", json={"document": doc})
    assert saved.status_code == 200, saved.text

    edited = {"version": "1.1", "tokens": {}, "tree": [{
        "id": "ds-master-preview", "type": "source-block", "variant": "component-master", "props": {},
        "children": [{"type": "card", "frame": {"x": 0, "y": 0, "width": 320, "height": 200},
                      "children": [{"type": "heading", "level": 3, "text": "Promo · dark"}]}]}]}
    res = client.post("/api/design-system/variant/save", json={
        "systemId": doc["id"], "componentKey": "promo-card", "label": "Тёмный", "ir": edited})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["variantKey"] == "user-1"
    comp = body["document"]["components"]["promo-card"]
    assert set(comp["variants"]) == {"default", "user-1"}
    variant = comp["variants"]["user-1"]
    assert variant["origin"] == "user" and variant["label"] == "Тёмный"
    assert variant["masterIr"]["tree"][0]["children"][0]["text"] == "Promo · dark"
    assert len(body["document"]["components"]) == 1  # вариант, а не новый компонент
    assert dsdoc.validate_document(body["document"]) == []

    sec = client.post("/api/design-system/component-section", json={
        "systemId": doc["id"], "revision": 0, "componentKey": "promo-card"})
    assert sec.status_code == 200, sec.text
    section = sec.json()["section"]
    assert section["type"] == "source-block" and section["id"] == "ds-promo-card"
    inner = section["children"][0]
    ref = inner["sourceMeta"]["componentRef"]
    assert ref["componentKey"] == "promo-card" and ref["systemId"] == doc["id"]
    assert ref["masterHash"].startswith("sha256:")
    probe = {"version": "1.1", "tokens": body["document"]["styleGuide"]["irTokens"], "tree": [section]}
    assert not [e for e in validate_ir(probe) if e.severity == "error"], validate_ir(probe)

    variant_section = client.post("/api/design-system/component-section", json={
        "systemId": doc["id"], "revision": 0, "componentKey": "promo-card", "variantKey": "user-1"})
    variant_body = variant_section.json()
    assert variant_body["section"]["children"][0]["children"][0]["text"] == "Promo · dark"
    assert variant_body["componentRef"]["masterHash"] == variant["masterHash"]
    assert variant_body["componentRef"]["masterHash"] != ref["masterHash"]
    missing = client.post("/api/design-system/variant/save", json={
        "systemId": doc["id"], "componentKey": "nope", "ir": edited})
    assert missing.status_code == 404
