"""Focused Design System lifecycle tests (build/validate/publish/default/resolve)."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="ds-lifecycle-")
os.environ["DESIGNDNA_DATA_DIR"] = TMP

from fastapi.testclient import TestClient  # noqa: E402

from design_system import builder, document as dsdoc, mock as dsmock, resolver, store  # noqa: E402
from ir.validate import format_errors, validate_ir  # noqa: E402
from server import app  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def fidelity_report() -> dict:
    metrics = {
        "pixel_similarity": 100.0,
        "paint_coverage": 100.0,
        "bbox_p95": 0.0,
        "grid_origin_error": 0.0,
        "unexplained_losses": 0,
        "size_match": True,
        "gate": {"passed": True, "reasons": []},
    }
    return {
        "viewports": {name: copy.deepcopy(metrics) for name in ("desktop", "tablet", "mobile")},
        "gate": {"passed": True, "reasons": []},
    }


def source_block(with_boundary: bool = True) -> dict:
    button = {
        "type": "button",
        "text": "Find",
        "sourceKey": "root/button:1",
        "style": {"background": "#f97316", "color": "#ffffff", "borderRadius": 8},
        "children": [{"type": "text", "text": "Find", "sourceKey": "root/button:1::text0"}],
    }
    if with_boundary:
        button["sourceMeta"] = {
            "kind": "dom", "componentBoundary": True,
            "componentRole": "button", "componentLabel": "Search CTA",
        }
    return {
        "name": "Header",
        "selector": "header",
        "previews": {name: f"data:image/png;base64,{name}" for name in ("desktop", "tablet", "mobile")},
        "sizes": {
            "desktop": {"width": 1440, "height": 120},
            "tablet": {"width": 768, "height": 120},
            "mobile": {"width": 390, "height": 120},
        },
        "fidelityReport": fidelity_report(),
        "ir": {
            "version": "1.1",
            "tokens": {
                "mode": "light",
                "color": {
                    "primary": "#f97316", "secondary": "#c2410c", "accent": "#fb923c",
                    "background": "#ffffff", "surface": "#f8fafc", "text": "#111111",
                    "textMuted": "#6b7280", "border": "#e5e7eb",
                },
                "font": {"display": {"family": "Inter", "weight": 700},
                         "body": {"family": "Inter", "weight": 400}, "scale": "default"},
                "radius": {"card": "md", "button": "md", "input": "md"},
                "spacing": {"section": "md", "container": "default"},
                "shadow": "sm",
            },
            "tree": [{
                "id": "header", "type": "source-block", "sourceKey": "root",
                "children": [button],
            }],
        },
    }


def main() -> None:
    tokens = source_block()["ir"]["tokens"]
    blocks = [source_block(True)]

    pack = builder.build_source_pack({"blocks": blocks, "tokens": tokens, "mode": "url", "url": "https://example.com"}, source_node_id=3)
    pack["_raw_blocks"] = blocks
    draft_a = builder.build_draft(pack, name="UI Kit · example")
    draft_b = builder.build_draft(copy.deepcopy(pack), name="UI Kit · example")
    check("deterministic document id", draft_a["id"] == draft_b["id"], draft_a["id"])
    check("deterministic content hash", dsdoc.content_hash(draft_a) == dsdoc.content_hash(draft_b))
    check("build observed component from boundary", any(c.get("origin") == "observed" for c in draft_a["components"].values()))
    check("generated states are unconfirmed", all(
        s.get("confirmed") is False
        for c in draft_a["components"].values()
        for s in (c.get("states") or {}).values()
        if s.get("origin") == "generated"
    ))

    # Каноническая таксономия — только метаданные; registry хранит точный Source master.
    keys = set(draft_a["components"])
    check("registry contains only observed boundary", keys == {"button"}, json.dumps(sorted(keys)))
    check("fully bounded source creates no synthetic gaps", not draft_a["suggestions"], json.dumps(sorted(draft_a["suggestions"])))
    check("canonical component names", draft_a["components"]["button"]["name"] == "Button", draft_a["components"]["button"]["name"])
    check("no garbage names (aria/classes) in registry", all(
        re.fullmatch(r"[A-Z][A-Za-z0-9 /·—-]{1,30}", str(c.get("name") or "")) for c in draft_a["components"].values()
    ), json.dumps([c.get("name") for c in draft_a["components"].values() if not re.fullmatch(r"[A-Z][A-Za-z0-9 /·—-]{1,30}", str(c.get("name") or ""))], ensure_ascii=False))
    check("boundary maps to canonical button", draft_a["components"]["button"]["provenance"].get("sourceBlock") == "Header", json.dumps(draft_a["components"]["button"]["provenance"], ensure_ascii=False))
    source_button = blocks[0]["ir"]["tree"][0]["children"][0]
    captured_button = draft_a["components"]["button"]["masterIr"]["tree"][0]
    check("observed master is exact source subtree", captured_button == source_button, json.dumps(captured_button, ensure_ascii=False))
    check("observed master passes fidelity gate", draft_a["components"]["button"]["status"] == "verified", json.dumps(draft_a["components"]["button"]["fidelity"], ensure_ascii=False))
    check("reference previews are deduplicated", len(draft_a.get("referenceAssets") or {}) == 1 and "referencePreviews" not in draft_a["components"]["button"]["sourceRef"])
    blob_blocks = [source_block(True)]
    blob_ref = "ddna://blobs/" + ("a" * 64) + ".png"
    blob_blocks[0]["previews"] = {name: blob_ref for name in ("desktop", "tablet", "mobile")}
    blob_pack = builder.build_source_pack(
        {"blocks": blob_blocks, "tokens": tokens, "mode": "url", "url": "https://example.com/blob"},
        source_node_id=30,
    )
    blob_pack["_raw_blocks"] = blob_blocks
    blob_draft = builder.build_draft(blob_pack, name="UI Kit · blob evidence")
    blob_evidence_key = blob_draft["components"]["button"]["sourceRef"]["evidenceKey"]
    check(
        "Design System keeps compact Source blob evidence",
        blob_draft["referenceAssets"][blob_evidence_key]["referencePreviews"]["desktop"] == blob_ref,
    )
    check("default variant references component master", draft_a["components"]["button"]["variants"]["default"].get("masterRef") == "self")
    check("observed master is stored once", "templateIr" not in draft_a["components"]["button"] and "masterIr" not in draft_a["components"]["button"]["variants"]["default"])
    check("all generated master previews validate against IR schema", all(
        not format_errors(validate_ir(dsdoc.preview_ir_for_master(c["masterIr"]))) for c in draft_a["components"].values()
    ), "; ".join(f"{k}: {format_errors(validate_ir(dsdoc.preview_ir_for_master(c['masterIr'])))[:1]}" for k, c in draft_a["components"].items() if format_errors(validate_ir(dsdoc.preview_ir_for_master(c["masterIr"])))))
    check("foundations radii from reference tokens", draft_a["foundations"]["radius"]["button"] == 8, json.dumps(draft_a["foundations"]["radius"]))
    check("foundations keep semantic palette", draft_a["foundations"]["colors"]["semantic"]["primary"] == "#f97316", json.dumps(draft_a["foundations"]["colors"]))
    button_schema = draft_a["mockData"]["schemas"].get("button-data") or {}
    button_enum = next((f.get("enum") for f in button_schema.get("fields", []) if f.get("name") in ("text", "label")), None)
    check("reference mock content harvested into enums", button_enum == ["Find"], json.dumps(button_schema, ensure_ascii=False))
    check("synthetic canonical library is not publishable", not ({"navbar", "product-card", "footer", "accordion"} & keys), json.dumps(sorted(keys)))

    weak_block = source_block(True)
    weak_block["name"] = "Weak Header"
    for metrics in weak_block["fidelityReport"]["viewports"].values():
        metrics["pixel_similarity"] = 90.0
        metrics["gate"] = {"passed": False, "reasons": ["pixel similarity below release threshold"]}
    mixed_blocks = [source_block(True), weak_block]
    mixed_pack = builder.build_source_pack(
        {"blocks": mixed_blocks, "tokens": tokens, "mode": "url", "url": "https://example.com/mixed"},
        source_node_id=31,
    )
    mixed_pack["_raw_blocks"] = mixed_blocks
    mixed = builder.build_draft(mixed_pack, name="UI Kit · mixed fidelity")
    review_components = {
        key: comp for key, comp in mixed["suggestions"].items() if comp.get("origin") == "observed"
    }
    check("fidelity failure is excluded from registry", set(mixed["components"]) == {"button"}, json.dumps(list(mixed["components"])))
    check("failed duplicate visual is not exposed as a second review component",
          not review_components, json.dumps(review_components, ensure_ascii=False))
    check("failed duplicate occurrence remains auditable in provenance",
          mixed["components"]["button"]["provenance"].get("unverifiedOccurrenceCount") == 1,
          json.dumps(mixed["components"]["button"]["provenance"], ensure_ascii=False))
    check("observed review master cannot use semantic Promote path", all(
        comp.get("templateIr") is None for comp in review_components.values()
    ))
    check("publish validation accepts verified registry while review pool stays isolated", not dsdoc.validate_document(mixed), json.dumps(dsdoc.validate_document(mixed), ensure_ascii=False))
    check("quality keeps all observed masters in fidelity denominator", mixed["quality"]["fidelityCoverage"] == 50, json.dumps(mixed["quality"]))

    review_only_block = source_block(True)
    review_only_block["ir"]["tree"][0]["children"][0]["style"]["background"] = "#111827"
    for metrics in review_only_block["fidelityReport"]["viewports"].values():
        metrics["pixel_similarity"] = 70.0
        metrics["gate"] = {"passed": False, "reasons": ["pixel similarity below release threshold"]}
    review_pack = builder.build_source_pack(
        {"blocks": [review_only_block], "tokens": tokens, "mode": "url", "url": "https://example.com/review"},
        source_node_id=32,
    )
    review_pack["_raw_blocks"] = [review_only_block]
    review_doc = builder.build_draft(review_pack, name="UI Kit · review catalog")
    check("failed exact master remains in visual review catalog",
          set(review_doc["reviewComponents"]) == {"button"},
          json.dumps(list(review_doc["reviewComponents"]), ensure_ascii=False))
    prepared_review = dsdoc.prepare_for_publish(review_doc)
    check("observed review catalog survives publish preparation",
          not prepared_review["suggestions"] and set(prepared_review["reviewComponents"]) == {"button"})
    review_summary = dsdoc.summary(prepared_review)
    check("summary separates visible catalog from accepted registry",
          review_summary["catalogComponents"] == 1
          and review_summary["reviewMasters"] == 1
          and review_summary["components"] == 0,
          json.dumps(review_summary, ensure_ascii=False))
    raster_metrics = {
        "pixelSimilarity": 90.11, "paintCoverage": 100.0, "bboxP95": 1.0,
        "originError": 0.09, "unexplainedLosses": 0, "sizeMatch": True,
        "sourceGatePassed": True,
    }
    check("raster-aware gate accepts exact geometry with calibrated photographic similarity",
          dsdoc.component_fidelity_status({
              "containsRaster": True, "requiredViewports": ["desktop"],
              "viewports": {"desktop": raster_metrics},
          })["passed"])
    check("non-raster master keeps strict 95 percent similarity gate",
          not dsdoc.component_fidelity_status({
              "containsRaster": False, "requiredViewports": ["desktop"],
              "viewports": {"desktop": raster_metrics},
          })["passed"])
    compact_metrics = {**raster_metrics, "pixelSimilarity": 82.33, "sourceGatePassed": False}
    check("compact control gate tolerates one-pixel antialiasing with exact structure",
          dsdoc.component_fidelity_status({
              "compactControl": True, "requiredViewports": ["mobile"],
              "viewports": {"mobile": compact_metrics},
          })["passed"])

    # Rsale-like repetitions collapse into semantic families. Content changes
    # are occurrences; measured structural/style changes remain variants.
    semantic_blocks = []
    for block_index, sale in enumerate((False, True), start=1):
        semantic = source_block(True)
        semantic["name"] = f"product-grid-{block_index}"
        semantic["kind"] = "product-grid"
        price_children = [{"type": "text", "text": "1 900 RSD", "sourceKey": f"price-{block_index}"}]
        if sale:
            price_children.append({"type": "text", "text": "-5%", "sourceKey": f"sale-{block_index}"})
        semantic["ir"]["tree"] = [{
            "id": f"grid-{block_index}", "type": "source-block", "sourceKey": "root", "children": [
                {"type": "button", "text": "Sve", "sourceKey": f"pill-active-{block_index}",
                 "style": {"background": "#7018e6", "color": "#ffffff", "borderWidth": 1, "borderRadius": 1000},
                 "frame": {"width": 53, "height": 44, "padding": [0, 16, 0, 16]},
                 "sourceMeta": {"componentBoundary": True, "componentRole": "radio", "componentLabel": "pill",
                                "repeatGroup": "filters"}},
                {"type": "button", "text": "Na popustu", "sourceKey": f"pill-soft-{block_index}",
                 "style": {"background": "#f1e8fc", "color": "#2b2b2b", "borderWidth": 1, "borderRadius": 1000},
                 "frame": {"width": 102, "height": 44, "padding": [0, 16, 0, 16]},
                 "sourceMeta": {"componentBoundary": True, "componentRole": "radio", "componentLabel": "pill",
                                "repeatGroup": "filters"}},
                {"type": "card", "sourceKey": f"service-{block_index}",
                 "style": {"color": "#000000", "borderRadius": 12},
                 "frame": {"width": 230, "height": 286.3},
                 "sourceMeta": {"componentBoundary": True, "componentRole": "article", "componentLabel": "card",
                                "repeatGroup": "service-cards"},
                 "children": price_children + [
                     {"type": "card", "sourceKey": f"service-{block_index}/meta", "text": "Beograd",
                      "style": {"color": "#666666"}, "frame": {"width": 180, "height": 19},
                      "sourceMeta": {"componentBoundary": True, "componentRole": "span", "componentLabel": "meta-item"}}
                 ]},
            ],
        }]
        semantic_blocks.append(semantic)
    semantic_pack = builder.build_source_pack(
        {"blocks": semantic_blocks, "tokens": tokens, "url": "https://rsale.net"}, source_node_id=32)
    semantic_pack["_raw_blocks"] = semantic_blocks
    semantic_doc = builder.build_draft(semantic_pack, name="UI Kit · semantic")
    semantic_context = resolver.resolve_context(
        semantic_doc, "точная карточка услуги", usage_mode="strict")
    primary = resolver.primary_component_for_brief(semantic_context, "точная карточка услуги")
    check("strict intent selects service card before prompt packing",
          primary is not None and primary.get("componentKey") == "service-card",
          json.dumps(primary or {}, ensure_ascii=False))
    check("semantic UI kit has no generic numbered Card duplicates",
          set(semantic_doc["components"]) == {"button", "service-card"},
          json.dumps(sorted(semantic_doc["components"])))
    check("repeated service content becomes standard and sale variants",
          len(semantic_doc["components"]["service-card"]["variants"]) == 2
          and {variant.get("semanticKey") for variant in semantic_doc["components"]["service-card"]["variants"].values()} == {"standard", "sale"},
          json.dumps(semantic_doc["components"]["service-card"]["variants"], ensure_ascii=False))
    button_backgrounds = {
        (variant.get("observedStyle") or {}).get("background")
        for variant in semantic_doc["components"]["button"]["variants"].values()
    }
    check("Button family keeps every observed color treatment once",
          button_backgrounds == {"#7018e6", "#f1e8fc"}
          and len(semantic_doc["components"]["button"]["variants"]) == 2,
          json.dumps(semantic_doc["components"]["button"]["variants"], ensure_ascii=False))
    check("nested metadata boundaries are absorbed by the service card",
          semantic_doc["extraction"].get("suppressedNestedBoundaryCount") == 2,
          json.dumps(semantic_doc["extraction"]))

    nested = source_block(True)
    nested["name"] = "Nested evidence"
    nested["kind"] = "product-grid"
    nested["ir"]["tree"] = [{
        "type": "source-block", "sourceKey": "nested-root",
        "frame": {"x": 100, "y": 40, "width": 600, "height": 300},
        "responsive": {"tablet": {"frame": {"x": 80, "y": 30}}},
        "children": [{
            "type": "card", "sourceKey": "nested-card",
            "frame": {"x": 50, "y": 20, "width": 230, "height": 286},
            "responsive": {"tablet": {"frame": {"x": 10, "y": 12}}},
            "sourceMeta": {"componentBoundary": True, "componentRole": "article", "componentLabel": "card"},
            "children": [],
        }],
    }]
    nested["fidelityReport"]["components"] = {"nested-card": fidelity_report()}
    nested_pack = builder.build_source_pack(
        {"blocks": [nested], "tokens": tokens, "url": "https://rsale.net"}, source_node_id=33)
    nested_pack["_raw_blocks"] = [nested]
    nested_doc = builder.build_draft(nested_pack, name="UI Kit · nested evidence")
    nested_bounds = nested_doc["components"]["service-card"]["sourceRef"]["boundsByViewport"]
    check("nested Source evidence bounds are absolute to the block root",
          nested_bounds["desktop"]["x"] == 150 and nested_bounds["desktop"]["y"] == 60
          and nested_bounds["tablet"]["x"] == 90 and nested_bounds["tablet"]["y"] == 42,
          json.dumps(nested_bounds, ensure_ascii=False))

    # качество мок-контента: служебка/персоналии/языковая когерентность
    junk_blocks = [{"name": "Header", "kind": "header", "ir": {"version": "1.1", "tree": [{
        "id": "h", "type": "source-block", "sourceKey": "root", "children": [
            {"type": "button", "text": "RU", "sourceKey": "lang",
             "sourceMeta": {"kind": "dom", "componentBoundary": True, "componentRole": "button"},
             "style": {}, "children": []},
            {"type": "text", "text": "Cookie", "sourceKey": "c1",
             "sourceMeta": {"kind": "dom", "componentBoundary": True, "componentRole": "nav"},
             "style": {}, "children": []},
            {"type": "button", "text": "Prove it →", "sourceKey": "cta", "style": {}, "children": []},
        ]}]}}]
    junk_blocks.append({"name": "Grid", "kind": "product-grid", "ir": {"version": "1.1", "tree": [{
        "id": "g", "type": "source-block", "sourceKey": "root", "children": [
            {"type": "card", "sourceKey": "card1", "style": {}, "children": [
                {"type": "text", "text": "Максим Баранов", "sourceKey": "t1", "style": {}},
                {"type": "text", "text": "Devlog", "sourceKey": "t2", "style": {}},
                {"type": "text", "text": "Compact Wireless Headphones", "sourceKey": "t3", "style": {}},
            ]},
            {"type": "card", "sourceKey": "card2", "style": {}, "children": [
                {"type": "text", "text": "Another Great Product", "sourceKey": "t4", "style": {}},
            ]},
        ]}]}})
    junk = builder.harvest_reference_content(junk_blocks)
    check("language switcher RU filtered from cta", "RU" not in junk["cta"], json.dumps(junk["cta"], ensure_ascii=False))
    check("cookie link filtered from nav", "Cookie" not in junk["nav"], json.dumps(junk["nav"], ensure_ascii=False))
    check("person names filtered from titles", "Максим Баранов" not in junk["title"], json.dumps(junk["title"], ensure_ascii=False))
    check("devlog rubric filtered from titles", "Devlog" not in junk["title"], json.dumps(junk["title"], ensure_ascii=False))
    check("latin-dominant source gets english defaults", junk["title"] == ["Compact Wireless Headphones", "Another Great Product"], json.dumps(junk["title"], ensure_ascii=False))
    check("brand derives from url host", builder._brand_from_url("https://rsale.net/ru") == "Rsale", builder._brand_from_url("https://rsale.net/ru"))

    ru_blocks = [{"name": "Header", "kind": "header", "ir": {"version": "1.1", "tree": [{
        "id": "h", "type": "source-block", "sourceKey": "root", "children": [
            {"type": "button", "text": "В корзину", "sourceKey": "cta", "style": {}, "children": []},
        ]}]}}]
    ru = builder.harvest_reference_content(ru_blocks)
    check("cyrillic-dominant source keeps russian defaults", ru["title"][0] == "Компактная модель", json.dumps(ru["title"], ensure_ascii=False))

    faq_blocks = [{"name": "FAQ", "kind": "faq", "ir": {"version": "1.1", "tree": [{
        "id": "f", "type": "source-block", "sourceKey": "root", "children": [
            {"type": "heading", "text": "Частые вопросы", "sourceKey": "h1", "style": {}, "children": []},
            {"type": "heading", "text": "Как оформить доставку?", "sourceKey": "h2", "style": {}, "children": []},
        ]}]}}]
    faq = builder.harvest_reference_content(faq_blocks)
    check("faq section heading is not a question", "Частые вопросы" not in faq["question"], json.dumps(faq["question"], ensure_ascii=False))
    check("real questions harvested", "Как оформить доставку?" in faq["question"], json.dumps(faq["question"], ensure_ascii=False))

    inferred_blocks = [source_block(False)]
    inferred_pack = builder.build_source_pack({"blocks": inferred_blocks, "tokens": tokens, "url": "https://example.com"}, source_node_id=4)
    inferred_pack["_raw_blocks"] = inferred_blocks
    inferred = builder.build_draft(inferred_pack, name="Inferred kit")
    check("no boundary means no publishable component", len(inferred["components"]) == 0, json.dumps(list(inferred["components"])))
    check("no boundary creates suggestions only", len(inferred["suggestions"]) >= 1, json.dumps(list(inferred["suggestions"])))

    pack_t1 = builder.build_source_pack(
        {"blocks": blocks, "tokens": tokens, "mode": "url", "url": "https://example.com/stable",
         "capturedAt": "2026-01-01T00:00:00Z"}, source_node_id=8)
    pack_t1["_raw_blocks"] = blocks
    draft_t1 = builder.build_draft(pack_t1, name="UI Kit · stable")
    changed_blocks = copy.deepcopy(blocks)
    changed_blocks[0]["ir"]["tree"][0]["children"][0]["text"] = "Go"
    pack_t2 = builder.build_source_pack(
        {"blocks": changed_blocks, "tokens": tokens, "mode": "url", "url": "https://example.com/stable",
         "capturedAt": "2026-08-23T12:00:00Z"}, source_node_id=8)
    pack_t2["_raw_blocks"] = changed_blocks
    draft_t2 = builder.build_draft(pack_t2, name="UI Kit · stable")
    check("identity stable across recapture content+capturedAt", draft_t1["id"] == draft_t2["id"], f"{draft_t1['id']} vs {draft_t2['id']}")
    check("recapture sourceRefs keep new capturedAt", (draft_t2.get("sourceRefs") or [{}])[0].get("capturedAt") == "2026-08-23T12:00:00Z")
    check(
        "recapture sourceRefs revisionHash changes",
        (draft_t1.get("sourceRefs") or [{}])[0].get("revisionHash") != (draft_t2.get("sourceRefs") or [{}])[0].get("revisionHash"),
    )

    schema = {"id": "cta-data", "fields": [{"name": "text", "format": "sentence", "type": "string"}]}
    fx1 = dsmock.make_fixture(schema, "typical")
    fx2 = dsmock.make_fixture(schema, "typical")
    check("mock fixtures are deterministic", fx1["data"] == fx2["data"] and fx1["seed"] == fx2["seed"])
    source_preview = dsmock.materialize_ir(draft_a["components"]["button"]["masterIr"], {"profile": "source", "data": {}})
    empty_preview = dsmock.materialize_ir(draft_a["components"]["button"]["masterIr"], dsmock.make_fixture(schema, "empty"))
    check("source preview preserves exact master", source_preview == draft_a["components"]["button"]["masterIr"])
    check("mock profile materializes visible content", empty_preview != source_preview and empty_preview["tree"][0].get("text") == "")

    with TestClient(app) as client:
        empty = client.post("/api/design-system/build", json={"name": "x", "blocks": []})
        check("build rejects empty source", empty.status_code == 422 and empty.json().get("error"))

        built = client.post("/api/design-system/build", json={
            "name": "UI Kit · example", "sourceNodeId": 3, "sourceUrl": "https://example.com",
            "blocks": blocks, "tokens": tokens,
        })
        check("build from source", built.status_code == 200, built.text)
        payload = built.json()
        document = payload["document"]
        system_id = document["id"]
        check("draft persisted as revision 0", document.get("status") == "draft")
        got_draft = client.post("/api/design-system/get", json={"systemId": system_id, "revision": 0})
        check("reload persistence of draft", got_draft.status_code == 200 and got_draft.json()["document"]["id"] == system_id)

        listed = client.get("/api/design-system/list").json()
        check("list includes draft", any(s["systemId"] == system_id for s in listed["systems"]))

        invalid = copy.deepcopy(document)
        invalid["components"] = {}
        blocked = client.post("/api/design-system/validate", json={"document": invalid})
        check("validate blocks empty components", blocked.status_code == 200 and blocked.json()["errors"])

        preview = client.post("/api/design-system/preview", json={
            "document": document, "componentKey": next(iter(document["components"])),
            "fixtureProfile": "source", "usageMode": "strict",
        })
        check("preview returns templateIr", preview.status_code == 200 and bool(preview.json().get("templateIr")))
        check("preview resolves deduplicated Source evidence", bool(preview.json().get("sourceRef", {}).get("referencePreviews", {}).get("desktop")), preview.text)
        preview_empty = client.post("/api/design-system/preview", json={
            "document": document, "componentKey": next(iter(document["components"])),
            "fixtureProfile": "empty", "usageMode": "strict",
        })
        check("preview applies selected mock profile", preview_empty.status_code == 200 and preview_empty.json().get("templateIr") != preview.json().get("templateIr"))

        unverified = copy.deepcopy(document)
        unverified_key = next(iter(unverified["components"]))
        unverified["components"][unverified_key]["fidelity"] = {"viewports": {}, "requiredViewports": ["desktop"]}
        fidelity_blocked = client.post("/api/design-system/validate", json={"document": unverified})
        check("publish validation fails closed without fidelity evidence", any(
            item.get("code") == "master-fidelity-failed" for item in fidelity_blocked.json().get("errors", [])
        ), fidelity_blocked.text)
        tampered = copy.deepcopy(document)
        tampered_key = next(iter(tampered["components"]))
        tampered["components"][tampered_key]["masterIr"]["tree"][0].setdefault("style", {})["background"] = "#000000"
        tamper_blocked = client.post("/api/design-system/validate", json={"document": tampered})
        check("stored Source master is content-hash pinned", any(
            item.get("code") == "observed-master-mutated" for item in tamper_blocked.json().get("errors", [])
        ), tamper_blocked.text)

        default_draft = client.post("/api/design-system/default", json={"systemId": system_id})
        check("set default rejects draft", default_draft.status_code == 404)

        first = client.post("/api/design-system/publish", json={"document": document})
        check("publish creates revision 1", first.status_code == 200, first.text)
        published = first.json()["document"]
        check("published is immutable revision", published["status"] == "published" and published["revision"] == 1)
        check("unconfirmed generated states stripped", all(
            not (s.get("origin") == "generated" and not s.get("confirmed"))
            for c in published["components"].values()
            for s in (c.get("states") or {}).values()
        ))
        check("unpromoted suggestions are not published", not published.get("suggestions"))

        again = client.post("/api/design-system/publish", json={"document": document})
        check("idempotent publish is duplicate", again.status_code == 200 and again.json().get("duplicate") is True)
        check("duplicate keeps same revision", again.json()["document"]["revision"] == published["revision"])

        got_pub = client.post("/api/design-system/get", json={"systemId": system_id, "revision": 1})
        check("get published revision", got_pub.status_code == 200 and got_pub.json()["document"]["revision"] == 1)
        check("published contentHash stable", got_pub.json()["document"]["contentHash"] == published["contentHash"])

        assigned = client.post("/api/design-system/default", json={"systemId": system_id})
        check("set default on published", assigned.status_code == 200 and assigned.json()["defaultSystemRef"]["systemId"] == system_id)
        listed2 = client.get("/api/design-system/list").json()
        check("default persists in list", listed2["defaultSystemRef"]["systemId"] == system_id)

        cleared = client.post("/api/design-system/default", json={"systemId": None})
        check("clear default", cleared.status_code == 200 and cleared.json()["defaultSystemRef"] is None)
        client.post("/api/design-system/default", json={"systemId": system_id})

        edited = copy.deepcopy(published)
        first_key = next(iter(edited["components"]))
        edited["components"][first_key]["description"] = "updated master copy"
        edited["status"] = "draft"
        saved = client.post("/api/design-system/save-draft", json={"document": edited})
        check("save-draft after publish", saved.status_code == 200)
        second = client.post("/api/design-system/publish", json={"document": edited})
        check("new content creates revision 2", second.status_code == 200 and second.json()["document"]["revision"] == 2, second.text)
        rev1 = client.post("/api/design-system/get", json={"systemId": system_id, "revision": 1}).json()["document"]
        check("revision 1 still immutable", rev1["components"][first_key]["description"] != "updated master copy")

        ctx_strict = client.post("/api/design-system/resolve-context", json={
            "ref": {"systemId": system_id, "revision": 2, "contentHash": second.json()["document"]["contentHash"]},
            "brief": "кнопка поиска", "usageMode": "strict",
        })
        check("resolve-context strict", ctx_strict.status_code == 200 and "STRICT" in ctx_strict.json()["promptBlock"])
        strict_payload = ctx_strict.json()
        strict_context = strict_payload["context"]
        strict_master = dsdoc.preview_ir_for_master(strict_context["components"][0]["masterIr"])
        missing_ref = resolver.validate_generation(strict_master, strict_context)
        check("strict rejects output without componentRef", any(
            item.get("code") == "no-component-refs" for item in missing_ref["errors"]
        ), json.dumps(missing_ref, ensure_ascii=False))
        strict_node = strict_master["tree"][0]["children"][0]
        strict_node.setdefault("sourceMeta", {})["componentRef"] = strict_payload["componentHandles"][0]
        check("componentRef is valid Design IR schema", not format_errors(validate_ir(strict_master)), "; ".join(format_errors(validate_ir(strict_master))[:3]))
        exact_ref = resolver.validate_generation(strict_master, strict_context)
        check("strict accepts pinned exact master handle", not any(
            item.get("code") in ("no-component-refs", "unregistered-component", "stale-component-ref", "mutated-exact-master")
            for item in exact_ref["errors"]
        ), json.dumps(exact_ref, ensure_ascii=False))
        mutated_master = copy.deepcopy(strict_master)
        mutated_master["tree"][0]["children"][0].setdefault("style", {})["background"] = "#000000"
        mutated_ref = resolver.validate_generation(mutated_master, strict_context)
        check("strict rejects a valid handle on mutated geometry/style", any(
            item.get("code") == "mutated-exact-master" for item in mutated_ref["errors"]
        ), json.dumps(mutated_ref, ensure_ascii=False))
        slop_master = copy.deepcopy(strict_master)
        slop_master["tree"][0]["children"].append({"type": "text", "text": "Invented", "children": []})
        slop_ref = resolver.validate_generation(slop_master, strict_context)
        check("strict rejects unregistered visual siblings", any(
            item.get("code") == "unregistered-visual-node" for item in slop_ref["errors"]
        ), json.dumps(slop_ref, ensure_ascii=False))
        strict_ref_request = {
            "systemId": system_id,
            "revision": 2,
            "contentHash": second.json()["document"]["contentHash"],
            "usageMode": "strict",
        }
        generated_without_ref = client.post("/api/generate", json={
            "brief": "кнопка поиска", "count": 1,
            "rawOutputs": [json.dumps(dsdoc.preview_ir_for_master(strict_context["components"][0]["masterIr"]), ensure_ascii=False)],
            "designSystem": strict_ref_request,
        })
        check("generate endpoint blocks strict output without refs", generated_without_ref.status_code == 422, generated_without_ref.text)
        generated_exact = client.post("/api/generate", json={
            "brief": "кнопка поиска", "count": 1,
            "rawOutputs": [json.dumps(strict_master, ensure_ascii=False)],
            "designSystem": strict_ref_request,
        })
        check("generate endpoint accepts exact pinned master", generated_exact.status_code == 200 and len(generated_exact.json().get("variants", [])) == 1, generated_exact.text)
        # Порт ноды ДС отдаёт плоскую shadcn-карту (styleGuide.tokens): раньше
        # сервер лочил из неё один ключ radius и IR падал на схеме tokens.
        flat_tokens = second.json()["document"]["styleGuide"]["tokens"]
        generated_flat = client.post("/api/generate", json={
            "brief": "кнопка поиска", "count": 1, "tokens": flat_tokens,
            "rawOutputs": [json.dumps(strict_master, ensure_ascii=False)],
            "designSystem": strict_ref_request,
        })
        check("generate with flat style-guide tokens on the port succeeds", generated_flat.status_code == 200, generated_flat.text[:300])
        flat_variant_tokens = (generated_flat.json().get("variants") or [{}])[0].get("tokens") or {}
        check("locked tokens are complete v1 from the design system",
              all(key in flat_variant_tokens for key in ("mode", "color", "font", "radius", "spacing", "shadow"))
              and flat_variant_tokens["color"]["primary"] == flat_tokens["primary"],
              json.dumps(flat_variant_tokens, ensure_ascii=False)[:300])
        prepared = client.post("/api/generate", json={
            "brief": "карточка тарифа", "count": 1, "tokens": flat_tokens, "prepareOnly": True,
            "designSystem": dict(strict_ref_request, usageMode="style-only"),
        })
        prepared_prompt = json.dumps(prepared.json(), ensure_ascii=False) if prepared.status_code == 200 else prepared.text
        check("prepared prompt carries the style profile / atmosphere block",
              prepared.status_code == 200 and "Style profile" in prepared_prompt and "атмосфера" in prepared_prompt,
              prepared_prompt[:300])
        check("prepared prompt carries the site brief and embed mode",
              "Сайт, в который встраивается" in prepared_prompt and "Режим встраивания" in prepared_prompt,
              prepared_prompt[-400:])
        ctx_ref = client.post("/api/design-system/resolve-context", json={
            "ref": {"systemId": system_id, "revision": 2},
            "brief": "кнопка поиска", "usageMode": "extend",
        })
        check("resolve-context extend (reference usage)", ctx_ref.status_code == 200 and "EXTEND" in ctx_ref.json()["promptBlock"])

        bad_hash = client.post("/api/design-system/resolve-context", json={
            "ref": {"systemId": system_id, "revision": 2, "contentHash": "sha256:dead"},
            "brief": "x", "usageMode": "strict",
        })
        check("contentHash mismatch is rejected", bad_hash.status_code == 422)

        generated = copy.deepcopy(published)
        generated["components"]["ghost"] = {
            "componentKey": "ghost", "name": "Ghost", "category": "content",
            "origin": "generated", "confirmed": False,
            "templateIr": {"version": "1.1", "tokens": {}, "tree": [{"type": "card", "children": []}]},
        }
        denied = client.post("/api/design-system/publish", json={"document": generated})
        check("unconfirmed generated component never ships", denied.status_code == 200 and "ghost" not in denied.json()["document"]["components"], denied.text)

        recapture_blocks = [source_block(True)]
        recapture_tokens = recapture_blocks[0]["ir"]["tokens"]
        first_cap = client.post("/api/design-system/build", json={
            "name": "UI Kit · recapture", "sourceNodeId": 9, "sourceUrl": "https://example.com/kit",
            "blocks": recapture_blocks, "tokens": recapture_tokens,
            "capturedAt": "2026-01-01T00:00:00Z",
        })
        check("recapture build", first_cap.status_code == 200, first_cap.text)
        cap_doc = first_cap.json()["document"]
        cap_id = cap_doc["id"]
        first_hash = (cap_doc.get("sourceRefs") or [{}])[0].get("revisionHash")
        pub_cap = client.post("/api/design-system/publish", json={"document": cap_doc})
        check("recapture publish v1", pub_cap.status_code == 200 and pub_cap.json()["document"]["revision"] == 1)
        def_cap = client.post("/api/design-system/default", json={"systemId": cap_id})
        check("recapture default pinned", def_cap.status_code == 200 and def_cap.json()["defaultSystemRef"]["systemId"] == cap_id)

        recapture_blocks2 = copy.deepcopy(recapture_blocks)
        recapture_blocks2[0]["ir"]["tree"][0]["children"][0]["text"] = "Search now"
        recapture_blocks2[0]["ir"]["tree"][0]["children"][0]["children"][0]["text"] = "Search now"
        second_cap = client.post("/api/design-system/build", json={
            "name": "UI Kit · recapture", "sourceNodeId": 9, "sourceUrl": "https://example.com/kit",
            "blocks": recapture_blocks2, "tokens": recapture_tokens,
            "capturedAt": "2026-08-23T18:00:00Z",
        })
        check("recapture keeps system id", second_cap.status_code == 200 and second_cap.json()["document"]["id"] == cap_id, second_cap.text)
        cap2 = second_cap.json()["document"]
        check("recapture stores new capturedAt", (cap2.get("sourceRefs") or [{}])[0].get("capturedAt") == "2026-08-23T18:00:00Z")
        check("recapture changes revisionHash", (cap2.get("sourceRefs") or [{}])[0].get("revisionHash") != first_hash)
        listed_cap = client.get("/api/design-system/list").json()
        check("default ref survives recapture", listed_cap.get("defaultSystemRef", {}).get("systemId") == cap_id)
        pub_cap2 = client.post("/api/design-system/publish", json={"document": cap2})
        pub_cap2_doc = pub_cap2.json().get("document") or {}
        check(
            "recapture publish is new revision of same system",
            pub_cap2.status_code == 200 and pub_cap2_doc.get("id") == cap_id and pub_cap2_doc.get("revision") == 2,
            pub_cap2.text,
        )
        still_default = client.get("/api/design-system/list").json()
        check("default still same system after new revision", still_default.get("defaultSystemRef", {}).get("systemId") == cap_id)
        old_rev = client.post("/api/design-system/get", json={"systemId": cap_id, "revision": 1})
        check("pinned revision 1 remains", old_rev.status_code == 200 and old_rev.json().get("document", {}).get("id") == cap_id)

        restore_blocks = [source_block(True)]
        restore_built = client.post("/api/design-system/build", json={
            "name": "UI Kit · restore-cancel", "sourceNodeId": 12, "sourceUrl": "https://example.com/restore",
            "blocks": restore_blocks, "tokens": restore_blocks[0]["ir"]["tokens"],
        })
        check("restore-cancel build", restore_built.status_code == 200, restore_built.text)
        restore_doc = restore_built.json()["document"]
        restore_id = restore_doc["id"]
        restore_pub = client.post("/api/design-system/publish", json={"document": restore_doc})
        restore_published = restore_pub.json()["document"]
        check("restore-cancel publish", restore_pub.status_code == 200 and restore_published.get("revision") == 1)
        restore_hash = restore_published.get("contentHash")
        client.post("/api/design-system/default", json={"systemId": restore_id})
        restore_edit = copy.deepcopy(restore_published)
        restore_key = next(iter(restore_edit["components"]))
        restore_edit["components"][restore_key]["states"] = {
            **(restore_edit["components"][restore_key].get("states") or {}),
            "hover": {"label": "hover", "origin": "generated", "confirmed": True},
        }
        restore_edit["status"] = "draft"
        restore_saved = client.post("/api/design-system/save-draft", json={"document": restore_edit})
        check("restore-cancel save-draft after publish", restore_saved.status_code == 200 and restore_saved.json()["document"]["status"] == "draft")
        working_draft = client.post("/api/design-system/get", json={"systemId": restore_id, "revision": 0}).json()["document"]
        check("working copy demoted after persisted edit", working_draft.get("status") == "draft")
        restored = client.post("/api/design-system/restore-published", json={"systemId": restore_id, "revision": 1})
        restored_doc = restored.json().get("document") or {}
        check(
            "restore-published returns published revision",
            restored.status_code == 200 and restored_doc.get("status") == "published"
            and restored_doc.get("revision") == 1 and restored_doc.get("contentHash") == restore_hash,
            restored.text,
        )
        working = client.post("/api/design-system/get", json={"systemId": restore_id, "revision": 0}).json()["document"]
        check(
            "restore rewrites working copy as published",
            working.get("status") == "published" and working.get("revision") == 1
            and working.get("contentHash") == restore_hash
            and not ((working.get("components") or {}).get(restore_key, {}).get("states") or {}).get("hover", {}).get("confirmed"),
        )
        pinned = client.post("/api/design-system/get", json={"systemId": restore_id, "revision": 1}).json()["document"]
        check(
            "pinned published revision unchanged",
            pinned.get("status") == "published" and pinned.get("revision") == 1 and pinned.get("contentHash") == restore_hash,
        )
        listed_restore = client.get("/api/design-system/list").json()
        listed_entry = next((s for s in listed_restore["systems"] if s.get("systemId") == restore_id), {})
        check("registry stays published after restore", listed_entry.get("status") == "published" and listed_entry.get("revision") == 1)
        check(
            "default survives restore-published",
            listed_restore.get("defaultSystemRef", {}).get("systemId") == restore_id
            and listed_restore.get("defaultSystemRef", {}).get("revision") == 1,
        )
        missing = client.post("/api/design-system/restore-published", json={"systemId": "ds-missing", "revision": 1})
        check("restore-published missing system is 404", missing.status_code == 404)

    # store-level: same hash does not bump
    store.save_draft(draft_a)
    first_pub = store.publish(draft_a)
    second_pub = store.publish(draft_a)
    check("store duplicate flag", first_pub.get("ok") and second_pub.get("duplicate") is True)
    check("store revision unchanged on duplicate", first_pub["document"]["revision"] == second_pub["document"]["revision"])

    dirty = copy.deepcopy(first_pub["document"])
    dirty_key = next(iter(dirty["components"]))
    dirty["status"] = "draft"
    dirty["components"][dirty_key]["description"] = "cancel-me"
    store.save_draft(dirty)
    restored_store = store.restore_published(first_pub["document"]["id"], first_pub["document"]["revision"])
    check("store restore-published status", restored_store.get("ok") and restored_store["document"]["status"] == "published")
    working_restored = store.get_revision(first_pub["document"]["id"], 0)
    check(
        "store restore rewrites revision 0",
        working_restored is not None and working_restored.get("status") == "published"
        and working_restored.get("contentHash") == first_pub["document"]["contentHash"]
        and working_restored["components"][dirty_key].get("description") != "cancel-me",
    )
    pinned_restored = store.get_revision(first_pub["document"]["id"], first_pub["document"]["revision"])
    check(
        "store restore keeps immutable revision",
        pinned_restored is not None and pinned_restored["components"][dirty_key].get("description") != "cancel-me",
    )

    # ---------- легаси-реестр: published + latest_revision=0 без rev0-снапшота ----------
    legacy_id = "ds-legacy0pin"
    legacy_doc = {
        "id": legacy_id, "name": "Legacy UI", "status": "published", "revision": 1,
        "components": {}, "suggestions": {}, "contentHash": "sha256:legacy-published",
    }
    with store._LOCK:
        con = store._conn()
        con.execute(
            "INSERT OR REPLACE INTO design_systems (system_id, project_id, name, status, latest_revision, source_url, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (legacy_id, "default", "Legacy UI", "published", 0, None, "2026-08-22T00:00:00+00:00"))
        con.execute(
            "INSERT OR REPLACE INTO design_system_revisions (system_id, revision, content_hash, document, created_at)"
            " VALUES (?,?,?,?,?)",
            (legacy_id, 1, legacy_doc["contentHash"], json.dumps(legacy_doc), "2026-08-22T00:00:00+00:00"))
        con.commit()
        con.close()
    systems = {s["systemId"]: s for s in store.list_systems()}
    check("legacy registry heals latest_revision to MAX(published)",
          systems.get(legacy_id, {}).get("revision") == 1,
          json.dumps(systems.get(legacy_id), ensure_ascii=False))
    healed_doc, healed_err = store.resolve_ref({"systemId": legacy_id, "revision": 0, "contentHash": "sha256:stale"})
    check("legacy pinned v0 resolves to latest published without hash failure",
          healed_doc is not None and healed_doc.get("revision") == 1 and healed_err is None,
          str(healed_err))
    with store._LOCK:
        con = store._conn()
        con.execute("INSERT OR REPLACE INTO design_system_meta (project_id, default_system_id, default_revision) VALUES (?,?,?)",
                    ("legacy-proj", legacy_id, 0))
        con.commit()
        con.close()
    default_ref = store.get_default("legacy-proj")
    check("legacy default meta v0 upgrades to published revision",
          default_ref is not None and default_ref["revision"] == 1
          and default_ref["contentHash"] == legacy_doc["contentHash"],
          json.dumps(default_ref))
    missing_doc, missing_err = store.resolve_ref({"systemId": "ds-does-not-exist", "revision": 0})
    check("missing system still fails loudly",
          missing_doc is None and "не найдена" in str(missing_err))

    # Пак записывает SOURCE_COMPILER_DEFAULT, когда нода не передала свою
    # версию. Расхождение с реальным конвейером (было dom-v31 против dom-v39)
    # помечало свежие захваты устаревшим парсером.
    import blockparse
    check("source compiler default matches the pipeline version",
          builder.SOURCE_COMPILER_DEFAULT == blockparse.SOURCE_COMPILER_VERSION,
          f"{builder.SOURCE_COMPILER_DEFAULT} != {blockparse.SOURCE_COMPILER_VERSION}")

    # Классификатор обязан работать на вёрстке, чьи имена классов ничего не
    # значат (Tailwind/CSS-modules/хеши): семейство выводится из роли, состава
    # содержимого и повторяемости, а не из componentLabel.
    def boundary(role, label, children=(), repeat=None, **extra):
        meta = {"componentBoundary": True, "componentRole": role, "componentLabel": label}
        if repeat:
            meta["repeatGroup"] = repeat
        return {"type": extra.pop("type", "card"), "sourceKey": extra.pop("key", label),
                "sourceMeta": meta, "children": list(children), **extra}

    hashed = source_block(True)
    hashed["name"] = "hashed"
    hashed["kind"] = "product-grid"
    hashed_cards = [
        boundary("article", "css-1x2y3z", repeat="g", key=f"c{i}", children=[
            {"type": "image", "sourceKey": f"c{i}-img"},
            {"type": "heading", "text": "Item", "sourceKey": f"c{i}-h"},
        ]) for i in range(3)
    ]
    hashed["ir"]["tree"] = [{"type": "source-block", "sourceKey": "root", "children": hashed_cards}]
    hashed["fidelityReport"]["components"] = {f"c{i}": fidelity_report() for i in range(3)}
    hashed_pack = builder.build_source_pack(
        {"blocks": [hashed], "tokens": tokens, "url": "https://example.com"}, source_node_id=90)
    hashed_pack["_raw_blocks"] = [hashed]
    hashed_doc = builder.build_draft(hashed_pack, name="UI Kit · hashed classes")
    check("hashed class names still classify as a card family",
          "service-card" in hashed_doc["components"],
          json.dumps(sorted(hashed_doc["components"])))

    # Вложенная поверхность раньше возвращала None и молча исчезала из кита.
    nested_surface = source_block(True)
    nested_surface["name"] = "nested-surface"
    nested_surface["kind"] = "section"
    nested_surface["ir"]["tree"] = [{
        "type": "source-block", "sourceKey": "root", "children": [
            boundary("region", "outer", key="outer", children=[
                boundary("panel", "inner", key="inner",
                         children=[{"type": "text", "text": "Inner surface copy", "sourceKey": "inner-t"}]),
            ]),
        ],
    }]
    nested_surface["fidelityReport"]["components"] = {
        "outer": fidelity_report(), "inner": fidelity_report()}
    nested_pack2 = builder.build_source_pack(
        {"blocks": [nested_surface], "tokens": tokens, "url": "https://example.com"}, source_node_id=91)
    nested_pack2["_raw_blocks"] = [nested_surface]
    nested_doc2 = builder.build_draft(nested_pack2, name="UI Kit · nested surface")
    check("a nested surface becomes its own component instead of vanishing",
          "nested-surface" in nested_doc2["components"],
          json.dumps(sorted(nested_doc2["components"])))

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL DESIGN SYSTEM CHECKS PASSED")


if __name__ == "__main__":
    main()
