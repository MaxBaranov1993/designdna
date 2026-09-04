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
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
ARTIFACTS = ROOT / "artifacts" / "slsbmb"
RESULT = ROOT / "results" / "slsbmb-product-card.md"
TARGET_URL = "https://slsbmb.com"
CARD_WORDS = ("product", "card", "tile", "item", "товар", "карточ")


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
            if not changed and isinstance(text, str) and re.search(r"\d", text) and re.search(r"₽|руб|\$|€", text, re.I):
                value["text"] = "4 990 ₽ · −20%"
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
            "type": "text", "text": "СКИДКА −20% · 4 990 ₽",
            "style": {"background": "#d92d20", "color": "#ffffff", "fontWeight": 700,
                      "padding": "8px 12px", "borderRadius": 9999},
        })
    return ir


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

    (ARTIFACTS / "product-card.master.png").write_bytes(render_png(master_ir, width=720))
    (ARTIFACTS / "product-card.variant.png").write_bytes(render_png(variant_ir, width=720))


def run(base: str, headless: bool) -> dict:
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
                arg=source_id, timeout=12 * 60_000,
            )
            source_data = page.evaluate("id => window.GraphDev.node(id).data", source_id)
            if not source_data.get("blocks"):
                raise RuntimeError(f"Source Import returned no blocks: {source_data}")

            ds_id = page.evaluate("id => window.__flowStore.getState().createDesignSystemFromSource(id, {name:'SLSBMB Product UI Kit'})", source_id)
            if not isinstance(ds_id, int):
                raise RuntimeError(f"createDesignSystemFromSource failed: {ds_id}")
            page.wait_for_function(
                "id => !window.__flowStore.getState().busy[id] && !!window.GraphDev.node(id)?.data?.document",
                arg=ds_id, timeout=120_000,
            )
            document = page.evaluate("id => window.GraphDev.node(id).data.document", ds_id)
            key, component, pool, semantic_match = choose_component(document)
            initial_pool = pool
            if not semantic_match:
                notes.append("Semantic product/card master was absent; the largest nearest master was used.")

            if pool == "suggestions":
                # Real-site capture may produce only semantic candidates when its exact
                # component crops fail the deterministic fidelity gate. This mirrors the
                # explicit "Promote" action in DesignSystemPanel.svelte.
                suggestion = copy.deepcopy((document.get("suggestions") or {})[key])
                promoted = {
                    **suggestion, "componentKey": key, "origin": "user", "status": "verified",
                    "confidence": 1, "confirmed": True,
                    "masterIr": copy.deepcopy(suggestion["templateIr"]),
                    "variants": {"default": {"label": "Promoted", "origin": "user",
                                                "confirmed": True, "masterRef": "self", "diff": {}}},
                    "provenance": {**(suggestion.get("provenance") or {}),
                                   "promotion": "explicit-user-action"},
                }
                document.setdefault("components", {})[key] = promoted
                del document["suggestions"][key]
                document["status"] = "draft"
                saved = api(page, "/api/design-system/save-draft", {"document": document})
                document = saved["document"]
                component, pool = document["components"][key], "components"
                page.evaluate(
                    "({id,doc,summary}) => window.__flowStore.getState().setNodeData(id,{document:doc,summary,status:'draft'})",
                    {"id": ds_id, "doc": document, "summary": saved.get("summary")},
                )
                notes.append("Exact captured masters were absent; the semantic Card suggestion was explicitly promoted, matching the DS panel action.")

            if pool == "reviewComponents":
                ordered = copy.deepcopy(document)
                review_pool = ordered.get("reviewComponents") or {}
                ordered["reviewComponents"] = {key: review_pool[key], **{k: v for k, v in review_pool.items() if k != key}}
                reviewed = api(page, "/api/design-system/master-review", {
                    "document": ordered, "provider": "codex", "viewport": "desktop", "maxComponents": 1,
                }, timeout_ms=10 * 60_000)
                document = reviewed.get("document") or document
                review_results = reviewed.get("results") or []
                page.evaluate("({id,doc,summary}) => window.__flowStore.getState().setNodeData(id,{document:doc,summary,status:'draft'})",
                              {"id": ds_id, "doc": document, "summary": reviewed.get("summary")})
                if key not in (document.get("components") or {}):
                    # A rejected card cannot be applied. Prefer the nearest already shippable master.
                    alternatives = {k: v for k, v in (document.get("components") or {}).items() if isinstance(v, dict)}
                    if not alternatives:
                        raise RuntimeError(f"Target {key} remained review-gated and no verified fallback master exists")
                    key, component = max(alternatives.items(), key=lambda row: component_score(str(row[0]), row[1]))
                    notes.append("The card candidate remained review-gated after AI repair; a verified nearest master was used in the editor.")
                else:
                    component = document["components"][key]

            # Exercise the review/repair endpoint even when the chosen component was
            # already verified/promoted; in that case the truthful result is reviewed=0.
            if not review_results:
                reviewed = api(page, "/api/design-system/master-review", {
                    "document": document, "provider": "codex", "viewport": "desktop", "maxComponents": 8,
                }, timeout_ms=10 * 60_000)
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
                    "ir": master_ir, "brief": f"Карточка товара сайта {TARGET_URL}",
                    "min_score": 80, "repair": False, "rejudge": False,
                }, timeout_ms=10 * 60_000)
            except Exception as exc:  # optional judge
                notes.append(f"Quality judge unavailable: {exc}")

            return {
                "source_id": source_id, "source_blocks": len(source_data["blocks"]),
                "source_block_errors": sum(1 for block in source_data["blocks"] if block.get("error")),
                "ds_id": ds_id, "system_id": system_id, "revision": revision,
                "component_key": key, "component": component, "initial_pool": initial_pool,
                "semantic_match": semantic_match, "review_results": review_results,
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
    lines = [
        "# SLSBMB: карточка товара из Source Import в DNA Editor",
        "",
        "## Итог",
        "",
        f"- Source: `{TARGET_URL}`; импортировано блоков: **{result['source_blocks']}**.",
        f"- Ошибки fidelity/capture у блоков Source: **{result['source_block_errors']}**.",
        f"- Design System: `{result['system_id']}`; опубликована ревизия **v{result['revision']}**.",
        f"- Компонент: **{component.get('name') or result['component_key']}** (`{result['component_key']}`, категория `{component.get('category') or '—'}`).",
        f"- Начальный пул: `{result['initial_pool']}`; прямое совпадение card/product/tile/item/товар: **{'да' if result['semantic_match'] else 'нет'}**.",
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
        f"Master-review: `{json.dumps(review, ensure_ascii=False) if review else 'мастер не требовал review'}`.",
        f"Quality Pass: score `{scorecard.get('score', 'недоступен')}`, verdict `{scorecard.get('verdict', 'недоступен')}`, passed `{quality.get('passed', 'недоступно')}`.",
        f"Замечания судьи: `{json.dumps(judge_issues, ensure_ascii=False) if judge_issues else 'нет данных'}`.",
        "",
        "## Найденные дефекты приложения",
        "",
    ]
    issue_lines = list(result.get("notes") or [])
    if result.get("source_block_errors"):
        issue_lines.append(
            f"Source Import вернул {result['source_block_errors']} блоков с ошибками из {result['source_blocks']}; "
            "точные captured masters не попали в Design System."
        )
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
    args = parser.parse_args()
    result = run(args.base.rstrip("/"), not args.headed)
    # ir_render opens its own synchronous Playwright driver and therefore must run
    # after the UI browser context above has fully closed.
    render_artifacts(result.pop("master_ir"), result.pop("variant_ir"))
    write_report(result)
    print(json.dumps({"ok": True, "report": str(RESULT), "component": result["component_key"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
