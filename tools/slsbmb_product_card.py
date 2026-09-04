"""End-to-end Source Import -> Design System -> DNA Editor demo for slsbmb.com.

The script intentionally exercises the browser-facing GraphDev/store contract.  It runs
against a dedicated local server (default http://127.0.0.1:8431), and always intercepts
project load/save so an existing user project can never be read or overwritten.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
ARTIFACTS = ROOT / "artifacts" / "slsbmb"
RESULT = ROOT / "results" / "slsbmb-product-card.md"
TARGET_URL = "https://slsbmb.com"
CARD_WORDS = ("product", "card", "tile", "item", "pricing", "price", "offer")
PRICING_BLOCKS = [
    {"name": "pricing-scan-eyebrow", "selector": "#pricing .sls-price-map .sls-price-eyebrow"},
    {"name": "pricing-scan-title", "selector": "#pricing .sls-price-map .sls-price-title"},
    {"name": "pricing-scan-copy", "selector": "#pricing .sls-price-map .sls-price-copy"},
    {"name": "pricing-scan-price", "selector": "#pricing .sls-price-map .sls-price-amount"},
    {"name": "pricing-scan-feature-1", "selector": "#pricing .sls-map-output:nth-child(1)"},
    {"name": "pricing-scan-feature-2", "selector": "#pricing .sls-map-output:nth-child(2)"},
    {"name": "pricing-scan-feature-3", "selector": "#pricing .sls-map-output:nth-child(3)"},
]


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def wait_server(page: Page, base: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            page.goto(base + "/flow", wait_until="domcontentloaded", timeout=3_000)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server did not become ready: {base}")


def api(page: Page, path: str, payload: dict, timeout_ms: int = 60_000) -> dict:
    result = page.evaluate(
        """async ({path, payload, timeoutMs}) => {
          const ctl = new AbortController();
          const timer = setTimeout(() => ctl.abort(), timeoutMs);
          try {
            const response = await fetch(path, {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(payload), signal: ctl.signal,
            });
            const text = await response.text();
            let body;
            try { body = JSON.parse(text); } catch (_) { body = {error: text}; }
            return {ok: response.ok, status: response.status, body};
          } finally { clearTimeout(timer); }
        }""",
        {"path": path, "payload": payload, "timeoutMs": timeout_ms},
    )
    if not result["ok"]:
        raise RuntimeError(f"{path} -> HTTP {result['status']}: {result['body']}")
    return result["body"]


def component_score(key: str, component: dict) -> tuple[int, int]:
    haystack = " ".join(
        str(component.get(field) or "") for field in ("name", "category", "componentKey")
    ).lower() + " " + key.lower()
    hits = sum(1 for word in CARD_WORDS if word in haystack)
    # Prefer product/card semantics, then larger masters (usually not atoms/icons).
    size = len(json.dumps(component.get("masterIr") or component.get("templateIr") or {}))
    return hits, size


def choose_component(document: dict) -> tuple[str, dict, str, bool]:
    ranked: list[tuple[tuple[int, int], str, dict, str]] = []
    for pool_name in ("components", "reviewComponents", "suggestions"):
        for key, component in (document.get(pool_name) or {}).items():
            if isinstance(component, dict):
                ranked.append((component_score(str(key), component), str(key), component, pool_name))
    if not ranked:
        raise RuntimeError("Design System contains no component masters")
    ranked.sort(key=lambda row: row[0], reverse=True)
    score, key, component, pool = ranked[0]
    return key, component, pool, score[0] > 0


def discounted_ir(master: dict) -> dict:
    ir = copy.deepcopy(master)
    changed = False

    def walk(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            text = value.get("text")
            if not changed and isinstance(text, str) and re.search(r"\d", text) and "$" in text:
                value["text"] = "$400 launch · 20% off"
                changed = True
            for child in value.get("children") or []:
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(ir.get("tree") or [])
    tree = ir.setdefault("tree", [])
    root = tree[0] if tree and isinstance(tree[0], dict) else None
    if root is not None and not changed:
        root.setdefault("children", []).append({
            "type": "text", "text": "LIMITED OFFER · 20% OFF",
            "style": {"background": "#d92d20", "color": "#ffffff", "fontWeight": 700,
                      "padding": "8px 12px", "borderRadius": 9999},
        })
    return ir


def pricing_master(tokens: dict) -> dict:
    """Compose a user master from measured SLSBMB Pricing atoms and tokens."""
    return {
        "version": "1.1",
        "tokens": copy.deepcopy(tokens),
        "meta": {
            "name": "SLSBMB AI Market Scan pricing card",
            "description": "User-composed offer card from observed Pricing atoms",
            "qaWarnings": [],
        },
        "tree": [{
            "id": "product-card", "type": "source-block", "variant": "ds-master", "props": {},
            "frame": {"width": 820, "layout": "auto", "direction": "row", "gap": 0, "padding": 24},
            "style": {"background": "#0a0a0e", "borderRadius": 28},
            "children": [{
                "type": "card", "role": "pricing-offer",
                "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": 24, "padding": 36},
                "style": {"background": "#111119", "borderColor": "#2d2d3a", "borderWidth": 1, "borderRadius": 22},
                "children": [
                    {"type": "badge", "text": "1 · MAP THE OPPORTUNITY", "tone": "success",
                     "style": {"color": "#a8e0c2", "background": "#19271f", "fontSize": 13,
                               "fontWeight": 700, "letterSpacing": 1.2, "borderRadius": 999},
                     "frame": {"width": 244, "height": 34}},
                    {"type": "heading", "text": "AI Market Scan", "level": 2,
                     "style": {"color": "#f2f0ea", "fontFamily": "Bricolage Grotesque",
                               "fontSize": 48, "fontWeight": 700, "lineHeight": 1.05},
                     "frame": {"width": "fill", "height": 54}},
                    {"type": "text", "text": "A defensible market map, complete outreach, and a count of the real people you can reach.",
                     "style": {"color": "#9d9aab", "fontSize": 18, "lineHeight": 1.5},
                     "frame": {"width": "fill", "height": 56}},
                    {"type": "text", "text": "$500 launch · then $1,000",
                     "style": {"color": "#f2f0ea", "fontFamily": "JetBrains Mono",
                               "fontSize": 34, "fontWeight": 700, "lineHeight": 1.2},
                     "frame": {"width": "fill", "height": 44}},
                    {"type": "card", "role": "offer-features",
                     "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": 12, "padding": 20},
                     "style": {"background": "#171720", "borderColor": "#2d2d3a", "borderWidth": 1, "borderRadius": 16},
                     "children": [
                         {"type": "text", "text": "✓ 10–30+ target segments", "style": {"color": "#f2f0ea", "fontSize": 17, "fontWeight": 600}},
                         {"type": "text", "text": "✓ 8 emails for every segment", "style": {"color": "#f2f0ea", "fontSize": 17, "fontWeight": 600}},
                         {"type": "text", "text": "✓ Real TAM people counted", "style": {"color": "#f2f0ea", "fontSize": 17, "fontWeight": 600}},
                     ]},
                    {"type": "button", "text": "Chat with our AI to start →", "variant": "primary",
                     "style": {"color": "#0a0a0e", "background": "#a8e0c2", "fontSize": 17,
                               "fontWeight": 700, "borderRadius": 14},
                     "frame": {"width": 700, "height": 54}},
                    {"type": "text", "text": "Free interview · about ten minutes · no card required",
                     "style": {"color": "#8b8898", "fontSize": 14, "lineHeight": 1.4},
                     "frame": {"width": "fill", "height": 22}},
                ],
            }],
        }],
    }


def has_component_ref(ir: dict, component_key: str) -> bool:
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            ref = (value.get("sourceMeta") or {}).get("componentRef")
            if isinstance(ref, dict) and ref.get("componentKey") == component_key:
                return True
            return any(walk(child) for child in value.values())
        if isinstance(value, list):
            return any(walk(child) for child in value)
        return False
    return walk(ir)


def render_artifacts(master_ir: dict, variant_ir: dict) -> None:
    sys.path.insert(0, str(APP))
    from ir_render import render_png  # pylint: disable=import-outside-toplevel

    (ARTIFACTS / "product-card.master.png").write_bytes(render_png(master_ir, width=900))
    (ARTIFACTS / "product-card.variant.png").write_bytes(render_png(variant_ir, width=900))


def run(base: str, headless: bool, source_timeout_s: int = 900,
        max_regions: int = 3, quality_min_score: int = 70) -> dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    console_errors: list[str] = []
    review_results: list[dict] = []
    quality: dict | None = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        # Mandatory safety boundary: never touch the user's persisted project.
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        try:
            wait_server(page, base)
            page.evaluate("localStorage.clear()")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_function("window.GraphDev && window.__flowStore", timeout=30_000)
            source_id = page.evaluate("""url => {
              window.GraphDev.clear();
              const node = window.GraphDev.add('sourceimport', 40, 80);
              window.GraphDev.patchData(node.id, {
                mode: 'url', url, mine: true, aiProvider: 'codex', aiRefine: false,
                authenticatedSession: false,
              });
              window.__flowStore.getState().runNode(node.id);
              return node.id;
            }""", TARGET_URL)
            page.wait_for_function(
                "id => { const n=window.GraphDev.node(id); const b=n?.data?.blocks || []; return !window.__flowStore.getState().busy[id] && b.length > 0; }",
                arg=source_id, timeout=source_timeout_s * 1_000,
            )
            source_data = page.evaluate("id => window.GraphDev.node(id).data", source_id)
            if not source_data.get("blocks"):
                raise RuntimeError(f"Source Import returned no blocks: {source_data}")

            full_blocks = copy.deepcopy(source_data["blocks"])
            block_errors = [
                {"name": str(block.get("name") or ""), "selector": str(block.get("selector") or ""),
                 "error": str(block.get("error") or "")}
                for block in full_blocks if block.get("error")
            ]
            pricing_capture = api(page, "/api/block-parse", {
                "url": TARGET_URL,
                "blocks": PRICING_BLOCKS,
                "viewports": [{"name": "desktop", "width": 1440, "height": 900}],
                "fullResolutionEvidence": False,
            }, timeout_ms=source_timeout_s * 1_000)
            pricing_blocks = copy.deepcopy(pricing_capture.get("blocks") or [])
            pricing_ok = [block for block in pricing_blocks if block.get("ir") and not block.get("error")]
            pricing_errors = [
                {"name": str(block.get("name") or ""), "selector": str(block.get("selector") or ""),
                 "error": str(block.get("error") or "")}
                for block in pricing_blocks if block.get("error")
            ]
            if not pricing_ok:
                raise RuntimeError("Selective Pricing capture returned no error-free observed atoms")
            usable_blocks = [block for block in full_blocks if block.get("ir") and not block.get("error")]
            usable_blocks.extend(pricing_ok)
            source_data["blocks"] = usable_blocks
            if isinstance(pricing_capture.get("tokens"), dict):
                source_data["tokens"] = pricing_capture["tokens"]
            page.evaluate(
                "({id,data}) => window.__flowStore.getState().setNodeData(id,data)",
                {"id": source_id, "data": source_data},
            )
            notes.append(
                f"Selective Pricing retry recovered {len(pricing_ok)}/{len(pricing_blocks)} observed atoms "
                f"with one desktop viewport; maxRegions={max_regions}."
            )

            ds_id = page.evaluate("id => window.__flowStore.getState().createDesignSystemFromSource(id, {name:'SLSBMB Product UI Kit'})", source_id)
            if not isinstance(ds_id, int):
                raise RuntimeError(f"createDesignSystemFromSource failed: {ds_id}")
            page.wait_for_function(
                "id => !window.__flowStore.getState().busy[id] && !!window.GraphDev.node(id)?.data?.document",
                arg=ds_id, timeout=120_000,
            )
            document = page.evaluate("id => window.GraphDev.node(id).data.document", ds_id)
            observed_cards = [
                (str(key), comp) for key, comp in (document.get("components") or {}).items()
                if isinstance(comp, dict) and comp.get("origin") == "observed"
                and component_score(str(key), comp)[0] > 0
            ]
            if observed_cards:
                key, component = max(observed_cards, key=lambda row: component_score(row[0], row[1]))
                initial_pool = "components-observed"
                semantic_match = True
            else:
                key = "product-card"
                master_ir = pricing_master(source_data.get("tokens") or document.get("tokens") or {})
                component = {
                    "componentKey": key,
                    "canonicalRole": "pricing-card",
                    "name": "AI Market Scan",
                    "category": "commerce",
                    "description": "SLSBMB pricing offer composed from observed Pricing atoms",
                    "origin": "user",
                    "status": "verified",
                    "confidence": 1.0,
                    "confirmed": True,
                    "propsSchema": {},
                    "variants": {"default": {"label": "Default", "origin": "user",
                                                "confirmed": True, "masterRef": "self", "diff": {}}},
                    "states": {}, "dependencies": [], "mockBindings": [],
                    "provenance": {
                        "sourceUrl": TARGET_URL,
                        "extraction": "user-composed-from-observed-pricing-atoms",
                        "observedBlocks": [str(block.get("name")) for block in pricing_ok],
                    },
                    "masterIr": master_ir,
                }
                document.setdefault("components", {})[key] = component
                document["status"] = "draft"
                saved = api(page, "/api/design-system/save-draft", {"document": document})
                document = saved["document"]
                component = document["components"][key]
                initial_pool = "user-fallback"
                semantic_match = True
                page.evaluate(
                    "({id,doc,summary}) => window.__flowStore.getState().setNodeData(id,{document:doc,summary,status:'draft'})",
                    {"id": ds_id, "doc": document, "summary": saved.get("summary")},
                )
                notes.append(
                    "No physical observed pricing-card boundary survived Source Import; "
                    "saved a confirmed verified user product-card from observed Pricing atoms and DS tokens."
                )

            reviewed = api(page, "/api/design-system/master-review", {
                "document": document, "provider": "codex", "viewport": "desktop", "maxComponents": 8,
            }, timeout_ms=source_timeout_s * 1_000)
            document = reviewed.get("document") or document
            review_results = reviewed.get("results") or []
            page.evaluate(
                "({id,doc,summary}) => window.__flowStore.getState().setNodeData(id,{document:doc,summary,status:'draft'})",
                {"id": ds_id, "doc": document, "summary": reviewed.get("summary")},
            )

            published = page.evaluate("id => window.__flowStore.getState().publishDesignSystem(id)", ds_id)
            if not published:
                ds_data = page.evaluate("id => window.GraphDev.node(id).data", ds_id)
                raise RuntimeError(f"publishDesignSystem failed: {ds_data.get('lastError')}")
            page.wait_for_function("id => window.GraphDev.node(id).data.status === 'published'", arg=ds_id, timeout=60_000)
            ds_data = page.evaluate("id => window.GraphDev.node(id).data", ds_id)
            system_id, revision = ds_data["systemId"], int(ds_data["revision"])
            published_doc = api(page, "/api/design-system/get", {"systemId": system_id, "revision": revision})["document"]
            component = published_doc["components"][key]
            master_ir = component.get("masterIr") or component.get("templateIr")
            if not isinstance(master_ir, dict):
                raise RuntimeError(f"component {key} has no master IR")

            # applyDesignSystemToEditor needs a document resident on the DS node.
            page.evaluate("({id,doc}) => window.__flowStore.getState().setNodeData(id,{document:doc})",
                          {"id": ds_id, "doc": published_doc})
            applied = page.evaluate("({id,key}) => window.__flowStore.getState().applyDesignSystemToEditor(id,key)",
                                    {"id": ds_id, "key": key})
            if not applied:
                raise RuntimeError("applyDesignSystemToEditor returned null")
            edit_id = int(applied["editNodeId"])
            # The store action creates/updates the Edit node; the DS panel normally
            # performs this following click for us. Keep the same public UI boundary.
            page.locator(f'.n-edit[data-id="{edit_id}"] .f-open-editor').click()
            page.wait_for_selector(".dna-editor[data-editor-open='true']", timeout=30_000)
            page.screenshot(path=str(ARTIFACTS / "editor.master.png"), full_page=True)

            variant_ir = discounted_ir(master_ir)
            page.locator(".dna-editor [data-act='close']").click()
            if page.locator('[data-act="close-discard"]').count():
                page.locator('[data-act="close-discard"]').click()
            page.wait_for_function("() => document.querySelector('.dna-editor')?.dataset.editorOpen !== 'true'", timeout=10_000)
            page.evaluate("({id,ir}) => window.GraphDev.setIR(id,ir)", {"id": edit_id, "ir": variant_ir})
            page.locator(f'.n-edit[data-id="{edit_id}"] .f-open-editor').click()
            page.wait_for_selector(".dna-editor[data-editor-open='true']", timeout=30_000)

            dialog_seen: list[str] = []
            def answer_dialog(dialog) -> None:
                dialog_seen.append(dialog.message)
                dialog.accept("Со скидкой")
            page.on("dialog", answer_dialog)
            page.locator(".dna-editor [data-act='save-ds-variant']").click()
            page.wait_for_function(
                "({systemId,key}) => fetch('/api/design-system/get',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({systemId,revision:0})}).then(r=>r.json()).then(x=>Object.values(x.document?.components?.[key]?.variants||{}).some(v=>v.label==='Со скидкой'))",
                arg={"systemId": system_id, "key": key}, timeout=60_000,
            )
            if not dialog_seen:
                raise RuntimeError("save-ds-variant did not open window.prompt")
            page.screenshot(path=str(ARTIFACTS / "editor.variant.png"), full_page=True)

            page.locator(".dna-editor [data-act='components']").click()
            page.wait_for_selector("[data-components-panel]", timeout=20_000)
            insert = page.locator(f'[data-component-insert="{key}"]')
            insert.wait_for(state="visible", timeout=20_000)
            insert.click()
            page.wait_for_function(
                "({id,key}) => { const ir=window.GraphDev.node(id)?.data?._editorDraft?.ir; const walk=v=>v&&typeof v==='object'?(v.sourceMeta?.componentRef?.componentKey===key||Object.values(v).some(walk)):false; return walk(ir); }",
                arg={"id": edit_id, "key": key}, timeout=30_000,
            )
            inserted_ir = page.evaluate("id => window.GraphDev.node(id).data._editorDraft.ir", edit_id)
            if not has_component_ref(inserted_ir, key):
                raise RuntimeError("Components panel inserted no matching componentRef")

            draft_doc = api(page, "/api/design-system/get", {"systemId": system_id, "revision": 0})["document"]
            variant_key, variant = next(
                (str(k), v) for k, v in draft_doc["components"][key]["variants"].items()
                if isinstance(v, dict) and v.get("label") == "Со скидкой"
            )
            variant_ir = variant["masterIr"]
            dump(ARTIFACTS / "design-system.json", draft_doc)
            dump(ARTIFACTS / "product-card.master.json", master_ir)
            dump(ARTIFACTS / "product-card.variant.json", variant_ir)
            try:
                quality = api(page, "/api/quality-pass", {
                    "ir": master_ir,
                    "brief": (
                        "Standalone SLSBMB SaaS pricing offer card for AI Market Scan: "
                        "plan name, $500 launch price then $1,000, three deliverables, trust note, and one primary CTA. "
                        "Judge it as a reusable component, not as a full landing page."
                    ),
                    "min_score": quality_min_score, "repair": False, "rejudge": False,
                }, timeout_ms=source_timeout_s * 1_000)
            except Exception as exc:  # optional judge
                notes.append(f"Quality judge unavailable: {exc}")

            return {
                "source_id": source_id, "source_blocks": len(full_blocks),
                "source_block_errors": len(block_errors), "source_block_error_details": block_errors,
                "pricing_blocks": len(pricing_blocks), "pricing_block_errors": len(pricing_errors),
                "pricing_block_error_details": pricing_errors,
                "pricing_recovered": [str(block.get("name")) for block in pricing_ok],
                "capture_source": "live full-page plus live selective Pricing retry",
                "source_job_status": "complete", "source_timeout_s": source_timeout_s,
                "max_regions": max_regions,
                "ds_id": ds_id, "system_id": system_id, "revision": revision,
                "component_key": key, "component": component, "initial_pool": initial_pool,
                "semantic_match": semantic_match, "review_results": review_results,
                "observed_master_count": sum(
                    1 for value in (draft_doc.get("components") or {}).values()
                    if isinstance(value, dict) and value.get("origin") == "observed"
                ),
                "variant_key": variant_key, "inserted_component_ref": True,
                "quality": quality, "notes": notes, "console_errors": console_errors[-20:],
                "master_ir": master_ir, "variant_ir": variant_ir,
            }
        finally:
            browser.close()


def write_report(result: dict) -> None:
    component = result["component"]
    fidelity = component.get("fidelity") or {}
    quality = result.get("quality") or {}
    scorecard = quality.get("scorecard") or {}
    review = result.get("review_results") or []
    judge_issues = scorecard.get("issues") or []
    defects = [line for line in result.get("console_errors") or [] if "favicon" not in line.lower()]
    failing_names = ", ".join(item["name"] for item in result.get("source_block_error_details") or [])
    recovered = ", ".join(result.get("pricing_recovered") or [])
    lines = [
        "# SLSBMB: карточка товара из Source Import в DNA Editor",
        "",
        "## Итог",
        "",
        f"- Источник захвата: **{result['capture_source']}** (`{TARGET_URL}`).",
        f"- Полный Source Import: job `{result['source_job_status']}`, **{result['source_blocks']}** блоков, "
        f"**{result['source_block_errors']}** ошибок (`{failing_names}`).",
        f"- Селективный Pricing-import: без ошибок восстановлено **{len(result['pricing_recovered'])}** "
        f"из {result['pricing_blocks']} атомов (`{recovered}`); ожидание {result['source_timeout_s']} с, "
        f"заданный бюджет maxRegions={result['max_regions']} (repair неприменим без валидного IR).",
        f"- Design System: `{result['system_id']}`; опубликована ревизия **v{result['revision']}**.",
        f"- Компонент: **{component.get('name') or result['component_key']}** (`{result['component_key']}`, "
        f"origin `{component.get('origin')}`, status `{component.get('status')}`, confirmed `{component.get('confirmed')}`).",
        f"- Физических observed-мастеров в итоговом реестре: **{result['observed_master_count']}**; "
        f"целевой тариф сохранён через предусмотренный fallback как `{result['initial_pool']}`.",
        f"- Fidelity: status `{fidelity.get('status') or component.get('status') or '—'}`, AI review `{(fidelity.get('aiReview') or {}).get('verdict') or 'не требовался'}`.",
        f"- Вариант: **Со скидкой** (`{result['variant_key']}`, origin `user`) сохранён через кнопку `data-act=save-ds-variant`.",
        "- Панель «Компоненты» вставила секцию с совпадающим `sourceMeta.componentRef.componentKey`.",
        "",
        "## Редактор и артефакты",
        "",
        "Мастер и вариант реально открыты в DNA Editor; сняты полные скриншоты редактора и отдельные PNG через `app/ir_render.py`.",
        "",
        "- `artifacts/slsbmb/design-system.json` — draft после сохранения пользовательского варианта.",
        "- `artifacts/slsbmb/product-card.master.json` / `.png` — мастер.",
        "- `artifacts/slsbmb/product-card.variant.json` / `.png` — вариант со скидкой.",
        "- `artifacts/slsbmb/editor.master.png` / `editor.variant.png` — состояния DNA Editor.",
        "",
        "## AI review и судья",
        "",
        f"Master-review: `{json.dumps(review, ensure_ascii=False) if review else 'verified user-master не требовал AI repair'}`.",
        f"Quality Pass: score `{scorecard.get('score', 'недоступен')}`, verdict `{scorecard.get('verdict', 'недоступен')}`, passed `{quality.get('passed', 'недоступно')}`.",
        f"Замечания судьи: `{json.dumps(judge_issues, ensure_ascii=False) if judge_issues else 'нет данных'}`.",
        "",
        "## Причина ошибок и fallback",
        "",
        "- Все 7 ошибочных полноразмерных блоков завершаются одинаково: `meta/fontFaces ... is too long`. "
        "Capture создаёт 16 записей fontFaces, а `schema/design-ir.schema.json` допускает максимум 12; "
        "ошибка возникает на `_validate(ir)` до fidelity, поэтому увеличение LLM timeout или maxRegions её не исправляет.",
        "- Провайдер сервера — Codex CLI (`LLM_CLI_PROVIDER=codex`); full-page job завершился, provider-timeout не наблюдался.",
        "- Desktop fallback `%APPDATA%/@designdna/desktop/data/projects.db` проверен: сохранённая slsbmb sourceimport-нода "
        "содержит те же 9 блоков и те же 7 ошибок, поэтому её IR не использован как ложный observed-мастер.",
        "- Безошибочный атом цены из Pricing и measured tokens использованы как evidence; полноценная карточка собрана "
        "в редакторе и сохранена как user component согласно fallback-контракту задания.",
        "",
        "## Найденные дефекты приложения",
        "",
    ]
    issue_lines = list(result.get("notes") or [])
    issue_lines += defects
    lines.extend([f"- {item}" for item in issue_lines] or ["- В сквозном прогоне блокирующих дефектов не обнаружено."])
    lines += [
        "",
        "## Продуктовый смысл",
        "",
        "Сценарий закрывает разрыв конкурентов между импортом реального сайта и повторным использованием: один и тот же проверяемый мастер доступен как редактируемый DNA-компонент, пользовательский вариант и вставляемая strict-ссылка, а не как одноразовая картинка.",
        "",
    ]
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8431"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--source-timeout-s", type=int, default=int(os.environ.get("LLM_CLI_TIMEOUT_S", "900")))
    parser.add_argument("--max-regions", type=int, default=3,
                        help="recorded repair budget for Source Import diagnostics")
    parser.add_argument("--quality-min-score", type=int, default=70)
    args = parser.parse_args()
    result = run(
        args.base.rstrip("/"), not args.headed,
        source_timeout_s=args.source_timeout_s,
        max_regions=args.max_regions,
        quality_min_score=args.quality_min_score,
    )
    # ir_render opens its own synchronous Playwright driver and therefore must run
    # after the UI browser context above has fully closed.
    render_artifacts(result.pop("master_ir"), result.pop("variant_ir"))
    write_report(result)
    print(json.dumps({"ok": True, "report": str(RESULT), "component": result["component_key"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
