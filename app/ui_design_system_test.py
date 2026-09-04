"""Browser regression: Design System lifecycle actions (build/publish/default/picker/preview/apply/undo)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
FAILS: list[str] = []

SOURCE_IR = {
    "version": "1.1",
    "tokens": {
        "color": {"primary": "#f97316", "background": "#ffffff", "text": "#111111", "surface": "#f8fafc", "border": "#e2e8f0"},
        "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}},
        "radius": {"button": 8},
    },
    "tree": [{
        "id": "imported-block", "type": "source-block", "sourceKey": "root",
        "children": [{
            "type": "button", "text": "Find", "sourceKey": "root/button:1",
            "sourceMeta": {"kind": "dom", "componentBoundary": True, "componentRole": "button", "componentLabel": "Search CTA"},
            "style": {"background": "#f97316", "color": "#ffffff", "borderRadius": 8},
            "children": [{"type": "text", "text": "Find", "sourceKey": "root/button:1::text0"}],
        }],
    }],
}


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("[OK] " if cond else "[FAIL] ") + name + (f" - {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_ready(page, base: str) -> None:
    for _ in range(40):
        try:
            page.goto(base + "/flow", timeout=2000)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server not ready")


def main() -> None:
    base = os.environ.get("DESIGNAI_UI_BASE", "").rstrip("/")
    proc = None
    if not base:
        tmp = tempfile.mkdtemp(prefix="ds-ui-")
        port = free_port()
        env = os.environ.copy()
        env["DESIGNDNA_DATA_DIR"] = tmp
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 950})
            page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
            page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
            # The panel starts both AI reviews automatically. This lifecycle test
            # covers deterministic UI actions, so keep those background calls
            # local and immediate instead of invoking an account-backed LLM.
            page.route("**/api/design-system/style-review", lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"error":"disabled in deterministic UI lifecycle test"}',
            ))
            page.route("**/api/design-system/master-review", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"reviewed":0,"approved":0,"results":[]}',
            ))
            wait_ready(page, base)
            page.evaluate("localStorage.clear()")
            page.reload()
            page.wait_for_function("window.GraphDev && window.__flowStore")
            page.evaluate("window.GraphDev.clear()")

            ids = page.evaluate("""(ir) => {
              const source = window.GraphDev.add('sourceimport', 40, 40);
              window.GraphDev.patchData(source.id, {
                url: 'https://example.com/ds',
                tokens: ir.tokens,
                blocks: [
                  {name:'Header', selector:'header', ir, lit:true},
                  {name:'Search', selector:'form', kind:'form', lit:true, ir: {
                    version: '1.1', tokens: ir.tokens,
                    tree: [{type:'input', sourceKey:'search/input', style:{background:'#ffffff', color:'#111111'}}],
                  }},
                ],
              });
              const generator = window.GraphDev.add('generator', 40, 420);
              const reskin = window.GraphDev.add('reskin', 460, 420);
              return {source: source.id, generator: generator.id, reskin: reskin.id};
            }""", SOURCE_IR)

            ds_id = page.evaluate("""async (sourceId) => {
              return await window.__flowStore.getState().createDesignSystemFromSource(sourceId, {name: 'UI Kit · ds'});
            }""", ids["source"])
            check("build from Source creates node", isinstance(ds_id, int) and ds_id > 0, str(ds_id))
            page.wait_for_function("id => window.GraphDev.node(id)?.data?.systemId", arg=ds_id)
            node = page.evaluate("id => window.GraphDev.node(id).data", ds_id)
            check("autopublish defaults on", node.get("autoPublish") is True)
            check("draft document persisted on node", bool(node.get("document") and node.get("status") == "draft"))
            summary = node.get("summary") or {}
            check("summary has catalog components", int(summary.get("catalogComponents") or 0) >= 1, json.dumps(summary))
            check("Source masters stay review-gated", int(summary.get("reviewMasters") or 0) >= 1, json.dumps(summary))
            check("review gate leaves an explanatory draft status",
                  "ждут ревью" in page.locator(f'.n-designsystem[data-id="{ds_id}"] .n-status').inner_text())

            open_btn = page.locator(f'.n-designsystem[data-id="{ds_id}"] [data-ds-action="open"]')
            check("open has accessible label", (open_btn.get_attribute("aria-label") or "").startswith("Открыть"))

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            check("open editor panel", page.locator("[data-ds-editor]").count() == 1)
            pub_btn = page.locator("[data-ds-editor] [data-ds-action='publish']")
            def_btn = page.locator("[data-ds-editor] [data-ds-action='default']")
            check("publish has accessible label", "Опубликовать" in (pub_btn.get_attribute("aria-label") or ""))
            check("review-only draft cannot publish", pub_btn.is_disabled())
            check("default disabled until published", def_btn.is_disabled())
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)

            # Source masters remain review-gated. Seed an explicit semantic
            # suggestion so this lifecycle test does not try to promote an exact
            # Source master that correctly failed the fidelity gate.
            page.evaluate("""async (id) => {
              const state = window.__flowStore.getState();
              const doc = structuredClone(window.GraphDev.node(id).data.document);
              doc.suggestions ||= {};
              doc.suggestions['semantic-promo'] = {
                componentKey: 'semantic-promo', canonicalRole: 'content',
                name: 'Semantic promo', category: 'content',
                description: 'Explicit semantic test suggestion',
                origin: 'suggested', status: 'draft', confidence: 0.8, confirmed: false,
                templateIr: {
                  version: '1.1', tokens: doc.styleGuide?.irTokens || {},
                  tree: [{type:'card', children:[{type:'text', typeRole:'body', text:'Promo'}]}],
                },
                variants: {}, states: {}, dependencies: [], mockBindings: [],
                provenance: {extraction: 'semantic-suggestion-test'},
              };
              await state.saveDesignSystemDocument(id, doc);
            }""", ds_id)
            page.locator("[data-ds-editor] [data-ds-tab='suggestions']").click()
            page.locator("[data-ds-editor] [data-ds-suggestion='semantic-promo']").click()
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)
            promote_btn = page.locator("[data-ds-editor] [data-ds-action='promote']")
            check("semantic suggestion can be explicitly promoted", promote_btn.is_enabled())
            promote_btn.click()
            page.wait_for_function("id => Object.keys(window.GraphDev.node(id)?.data?.document?.components || {}).length > 0", arg=ds_id)
            page.evaluate("""async (id) => {
              const state = window.__flowStore.getState();
              const doc = structuredClone(window.GraphDev.node(id).data.document);
              const key = Object.keys(doc.components || {})[0];
              doc.components[key].states = Object.assign({}, doc.components[key].states || {}, {
                hover: {origin: 'generated', confirmed: false, diff: {opacity: 0.92}},
              });
              await state.saveDesignSystemDocument(id, doc);
            }""", ds_id)
            page.locator("[data-ds-editor] [data-ds-action='publish']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.status === 'published'", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.evaluate("""id => {
              const data = window.GraphDev.node(id).data;
              const doc = structuredClone(data.document);
              const key = Object.keys(doc.components || {})[0];
              doc.components[key].states = Object.assign({}, doc.components[key].states || {}, {
                hover: {origin: 'generated', confirmed: false, diff: {opacity: 0.92}},
              });
              window.__flowStore.getState().setNodeData(id, {document: doc});
            }""", ds_id)
            page.locator("[data-ds-editor] [data-ds-action='validate']").click()
            page.wait_for_selector("[data-ds-validation]")
            check("validate action runs", page.locator("[data-ds-validation]").count() == 1)

            page.locator("[data-ds-editor] [data-ds-tab='source']").click()
            page.locator("[data-ds-editor] [data-catalog-component] button").first.click()
            page.wait_for_selector("[data-ds-editor] [data-ds-component]")
            first_comp = page.locator("[data-ds-editor] [data-ds-component][data-ds-pool='components']").first
            first_comp.click()
            page.wait_for_selector("[data-ds-preview-host]")
            page.locator("[data-ds-viewport='tablet']").click()
            page.wait_for_function("""() => {
              const btn = document.querySelector("[data-ds-viewport='tablet']");
              const preview = document.querySelector("[data-ds-preview]");
              return btn?.getAttribute('aria-pressed') === 'true' && preview?.getAttribute('data-ds-preview') === 'tablet';
            }""")
            check(
                "preview viewport tablet",
                page.locator("[data-ds-viewport='tablet'][aria-pressed='true']").count() == 1
                and page.locator("[data-ds-preview='tablet']").count() >= 1,
            )
            page.locator("[data-ds-field='preview-fixture']").select_option("short")
            page.wait_for_function("() => document.querySelector('[data-ds-preview-host]')?.getAttribute('data-ds-preview-fixture') === 'short'")
            check("preview fixture action", page.locator("[data-ds-preview-host][data-ds-preview-fixture='short']").count() == 1)

            unconfirmed = page.locator("[data-ds-editor] [data-ds-state].unconfirmed").first
            check("draft has unconfirmed generated states", unconfirmed.count() > 0)
            state_name = unconfirmed.get_attribute("data-ds-state") or ""
            system_id = page.evaluate("id => window.GraphDev.node(id).data.systemId", ds_id)
            unconfirmed.click()
            page.wait_for_function(
                """({id, name}) => {
                  const comps = Object.values(window.GraphDev.node(id)?.data?.document?.components || {});
                  return comps.some(c => c?.states?.[name]?.confirmed === true);
                }""",
                arg={"id": ds_id, "name": state_name},
            )
            persisted_state = page.evaluate(
                """async ({systemId, name}) => {
                  const got = await (await fetch('/api/design-system/get', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({systemId, revision: 0}),
                  })).json();
                  const comps = Object.values(got.document?.components || {});
                  const state = comps.map(c => c?.states?.[name]).find(Boolean);
                  return {confirmed: !!(state && state.confirmed === true), origin: state && state.origin};
                }""",
                {"systemId": system_id, "name": state_name},
            )
            check(
                "confirm generated state persists",
                bool(persisted_state.get("confirmed")) and persisted_state.get("origin") == "generated",
                json.dumps(persisted_state),
            )

            undo_btn = page.locator("[data-ds-editor] [data-ds-action='undo']")
            undo_btn.wait_for(state="visible")
            page.wait_for_function("() => { const b = document.querySelector(\"[data-ds-editor] [data-ds-action='undo']\"); return b && !b.disabled; }")
            undo_btn.click()
            page.wait_for_function(
                """({id, name}) => {
                  const comps = Object.values(window.GraphDev.node(id)?.data?.document?.components || {});
                  const state = comps.map(c => c?.states?.[name]).find(Boolean);
                  return !state || state.confirmed !== true;
                }""",
                arg={"id": ds_id, "name": state_name},
            )
            restored_state = page.evaluate(
                """({id, name}) => {
                  const comps = Object.values(window.GraphDev.node(id)?.data?.document?.components || {});
                  const state = comps.map(c => c?.states?.[name]).find(Boolean);
                  return {confirmed: !!(state && state.confirmed), origin: state && state.origin};
                }""",
                {"id": ds_id, "name": state_name},
            )
            check("undo restores confirmed state", restored_state.get("confirmed") is False, json.dumps(restored_state))
            page.evaluate("""({id, name}) => {
              const data = window.GraphDev.node(id).data;
              const doc = structuredClone(data.document);
              const key = Object.keys(doc.components || {})[0];
              doc.components[key].states = Object.assign({}, doc.components[key].states || {}, {
                [name]: {origin: 'generated', confirmed: false, diff: {opacity: 0.92}},
              });
              window.__flowStore.getState().setNodeData(id, {document: doc});
            }""", {"id": ds_id, "name": state_name})
            page.wait_for_selector(f"[data-ds-editor] [data-ds-state='{state_name}'].unconfirmed")

            page.locator("[data-ds-editor] [data-ds-action='apply']").click()
            page.wait_for_function("""() => window.GraphDev.state().nodes.some(n => n.type === 'edit')""")
            page.wait_for_function("""() => {
              const el = document.querySelector('.dna-editor');
              return el && el.style.display === 'flex';
            }""")
            applied = page.evaluate("""() => {
              const edit = window.__flowStore.getState().nodes.find(n => n.type === 'edit');
              const editorOpen = document.querySelector('.dna-editor')?.style.display === 'flex';
              const ir = edit && edit.data && edit.data.ir;
              return {
                hasIr: !!ir,
                editorOpen,
                master: edit && edit.data && edit.data._dsMaster,
                treeType: ir && ir.tree && ir.tree[0] && ir.tree[0].type,
              };
            }""")
            check(
                "apply to DNA Editor opens correct IR",
                bool(applied.get("hasIr")) and bool(applied.get("editorOpen")) and bool(applied.get("master")),
                json.dumps(applied),
            )

            if page.locator(".dna-editor [data-act='close']").count():
                page.locator(".dna-editor [data-act='close']").click()
                # защита черновика: редактор с правками спрашивает — закрываем без сохранения
                try:
                    page.wait_for_selector('[data-act="close-discard"]', timeout=1000).click()
                except Exception:
                    pass
                page.wait_for_function("() => { const el = document.querySelector('.dna-editor'); return !el || getComputedStyle(el).display === 'none'; }")
            page.wait_for_function("() => { const b = document.querySelector(\"[data-ds-editor] [data-ds-action='undo']\"); return b && !b.disabled; }")
            undo_btn.click()
            page.wait_for_function("""() => {
              const edit = window.__flowStore.getState().nodes.find(n => n.type === 'edit');
              return edit && !edit.data?.ir;
            }""")
            undone_apply = page.evaluate("""() => {
              const edit = window.__flowStore.getState().nodes.find(n => n.type === 'edit');
              return {hasIr: !!(edit && edit.data && edit.data.ir)};
            }""")
            check("undo restores DNA Editor apply", undone_apply.get("hasIr") is False, json.dumps(undone_apply))

            page.evaluate("""({id, name}) => {
              const data = window.GraphDev.node(id).data;
              const doc = structuredClone(data.document);
              const key = Object.keys(doc.components || {})[0];
              doc.components[key].states = Object.assign({}, doc.components[key].states || {}, {
                [name]: {origin: 'generated', confirmed: false, diff: {opacity: 0.92}},
              });
              window.__flowStore.getState().setNodeData(id, {document: doc});
            }""", {"id": ds_id, "name": state_name})
            page.wait_for_selector(f"[data-ds-editor] [data-ds-state='{state_name}'].unconfirmed")
            page.locator("[data-ds-editor] [data-ds-state].unconfirmed").first.click()
            page.wait_for_function(
                """({id, name}) => {
                  const comps = Object.values(window.GraphDev.node(id)?.data?.document?.components || {});
                  return comps.some(c => c?.states?.[name]?.confirmed === true);
                }""",
                arg={"id": ds_id, "name": state_name},
            )
            page.locator("[data-ds-editor] [data-ds-action='cancel']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            rolled_back = page.evaluate(
                """({id, name}) => {
                  const comps = Object.values(window.GraphDev.node(id)?.data?.document?.components || {});
                  const state = comps.map(c => c?.states?.[name]).find(Boolean);
                  return {confirmed: !!(state && state.confirmed === true), editorOpen: !!document.querySelector('[data-ds-editor]')};
                }""",
                {"id": ds_id, "name": state_name},
            )
            check(
                "cancel rolls back document and closes",
                rolled_back.get("confirmed") is False and rolled_back.get("editorOpen") is False,
                json.dumps(rolled_back),
            )

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            save_draft_hits: list[str] = []
            page.on("request", lambda req: save_draft_hits.append(req.url) if "/api/design-system/save-draft" in req.url else None)
            page.locator("[data-ds-editor] [data-ds-action='publish']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.status === 'published'", arg=ds_id)
            before_close = len(save_draft_hits)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            published = page.evaluate("id => window.GraphDev.node(id).data", ds_id)
            check("close after in-panel publish does not save-draft", len(save_draft_hits) == before_close, str(len(save_draft_hits) - before_close))
            check(
                "close after publish keeps published lifecycle",
                published.get("status") == "published" and int(published.get("revision") or 0) >= 1,
                json.dumps({"status": published.get("status"), "revision": published.get("revision")}),
            )

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='default']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.defaultSet === true", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            listed = page.evaluate("async () => (await (await fetch('/api/design-system/list')).json())")
            check("set default persists in registry", bool(listed.get("defaultSystemRef") and listed["defaultSystemRef"]["systemId"] == published["systemId"]), json.dumps(listed.get("defaultSystemRef")))

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.locator("[data-ds-editor] [data-ds-tab='source']").click()
            page.locator("[data-ds-editor] [data-catalog-component] button").first.click()
            page.wait_for_selector("[data-ds-editor] [data-ds-component]")
            page.locator("[data-ds-editor] [data-ds-component][data-ds-pool='components']").first.click()
            before_edit = page.evaluate(
                """id => {
                  const n = window.GraphDev.node(id).data;
                  return {
                    status: n.status, revision: n.revision, defaultSet: n.defaultSet,
                    hash: n.document && n.document.contentHash, systemId: n.systemId,
                  };
                }""",
                ds_id,
            )
            page.evaluate(
                """id => {
                  const data = window.GraphDev.node(id).data;
                  const doc = JSON.parse(JSON.stringify(data.document));
                  const key = Object.keys(doc.components || {})[0];
                  doc.components[key].states = Object.assign({}, doc.components[key].states || {}, {
                    hover: {label: 'hover', origin: 'generated', confirmed: false},
                  });
                  window.__flowStore.getState().setNodeData(id, {document: doc});
                }""",
                ds_id,
            )
            page.wait_for_selector("[data-ds-editor] [data-ds-state='hover'].unconfirmed")
            page.locator("[data-ds-editor] [data-ds-state='hover'].unconfirmed").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.status === 'draft'", arg=ds_id)
            after_edit_drafts = len(save_draft_hits)
            page.locator("[data-ds-editor] [data-ds-action='cancel']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            check(
                "cancel after published edit does not save-draft",
                len(save_draft_hits) == after_edit_drafts,
                str(len(save_draft_hits) - after_edit_drafts),
            )
            restored_node = page.evaluate(
                """id => {
                  const n = window.GraphDev.node(id).data;
                  const comps = Object.values(n.document?.components || {});
                  return {
                    status: n.status, revision: n.revision, defaultSet: n.defaultSet,
                    hash: n.document && n.document.contentHash,
                    confirmedHover: comps.some(c => c?.states?.hover?.confirmed === true),
                  };
                }""",
                ds_id,
            )
            check(
                "cancel restores published status and revision",
                restored_node.get("status") == "published"
                and int(restored_node.get("revision") or 0) == int(before_edit.get("revision") or 0),
                json.dumps({"before": before_edit, "after": restored_node}),
            )
            check("cancel restores contentHash", restored_node.get("hash") == before_edit.get("hash"))
            check("cancel keeps project default flag", restored_node.get("defaultSet") is True)
            check("cancel drops persisted generated confirm", restored_node.get("confirmedHover") is False)
            after_cancel = page.evaluate(
                """async ({systemId, revision}) => {
                  const list = await (await fetch('/api/design-system/list')).json();
                  const pinned = await (await fetch('/api/design-system/get', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({systemId, revision}),
                  })).json();
                  const working = await (await fetch('/api/design-system/get', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({systemId, revision: 0}),
                  })).json();
                  return {list, pinned: pinned.document, working: working.document};
                }""",
                {"systemId": published["systemId"], "revision": before_edit["revision"]},
            )
            listed_entry = next((s for s in after_cancel["list"]["systems"] if s.get("systemId") == published["systemId"]), {})
            check(
                "reload keeps published registry after cancel",
                listed_entry.get("status") == "published" and int(listed_entry.get("revision") or 0) == int(before_edit.get("revision") or 0),
                json.dumps(listed_entry),
            )
            check(
                "pinned published revision preserved after cancel",
                (after_cancel.get("pinned") or {}).get("status") == "published"
                and int((after_cancel.get("pinned") or {}).get("revision") or 0) == int(before_edit.get("revision") or 0)
                and (after_cancel.get("pinned") or {}).get("contentHash") == before_edit.get("hash"),
            )
            check(
                "working copy restored to published after cancel",
                (after_cancel.get("working") or {}).get("status") == "published"
                and int((after_cancel.get("working") or {}).get("revision") or 0) == int(before_edit.get("revision") or 0)
                and (after_cancel.get("working") or {}).get("contentHash") == before_edit.get("hash"),
            )
            check(
                "default survives published cancel",
                (after_cancel["list"].get("defaultSystemRef") or {}).get("systemId") == published["systemId"]
                and int((after_cancel["list"].get("defaultSystemRef") or {}).get("revision") or 0) == int(before_edit.get("revision") or 0)
                and (after_cancel["list"].get("defaultSystemRef") or {}).get("contentHash") == before_edit.get("hash"),
                json.dumps(after_cancel["list"].get("defaultSystemRef")),
            )

            reloaded = page.evaluate(
                """async (id) => {
                  const n = window.GraphDev.node(id).data;
                  const list = await (await fetch('/api/design-system/list')).json();
                  const working = await (await fetch('/api/design-system/get', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({systemId: n.systemId, revision: 0}),
                  })).json();
                  const entry = (list.systems || []).find(s => s.systemId === n.systemId) || {};
                  window.__flowStore.getState().setNodeData(id, {
                    document: working.document,
                    status: entry.status,
                    revision: entry.revision,
                    defaultSet: !!(list.defaultSystemRef && list.defaultSystemRef.systemId === n.systemId),
                  });
                  const after = window.GraphDev.node(id).data;
                  return {
                    status: after.status,
                    revision: after.revision,
                    hash: after.document && after.document.contentHash,
                    defaultSet: after.defaultSet,
                  };
                }""",
                ds_id,
            )
            check(
                "published status and revision preserved after reload",
                reloaded.get("status") == "published"
                and int(reloaded.get("revision") or 0) == int(before_edit.get("revision") or 0)
                and reloaded.get("hash") == before_edit.get("hash")
                and reloaded.get("defaultSet") is True,
                json.dumps(reloaded),
            )

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)
            reopened_meta = page.locator("[data-ds-editor] .ds-editor-meta").inner_text()
            check(
                "reopen after cancel still shows published revision",
                "Опубликовано" in reopened_meta and f"v{before_edit.get('revision')}" in reopened_meta,
                reopened_meta,
            )
            reopen_drafts = len(save_draft_hits)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            check(
                "clean reopen/close after restore does not save-draft",
                len(save_draft_hits) == reopen_drafts,
                str(len(save_draft_hits) - reopen_drafts),
            )

            ds_id2 = page.evaluate("""async (sourceId) => {
              const id = await window.__flowStore.getState().createDesignSystemFromSource(sourceId, {name: 'UI Kit · sibling'});
              if (id) window.__flowStore.getState().moveNode(id, 780, 40);
              return id;
            }""", ids["source"])
            check("sibling design system created", isinstance(ds_id2, int) and ds_id2 > 0, str(ds_id2))
            page.wait_for_function("id => window.GraphDev.node(id)?.data?.systemId", arg=ds_id2)
            open_btn2 = page.locator(f'.n-designsystem[data-id="{ds_id2}"] [data-ds-action="open"]')
            open_btn2.click()
            page.wait_for_selector("[data-ds-editor]")
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id2)
            page.evaluate("""async (id) => {
              const state = window.__flowStore.getState();
              const doc = structuredClone(window.GraphDev.node(id).data.document);
              doc.suggestions ||= {};
              doc.suggestions['semantic-promo'] = {
                componentKey: 'semantic-promo', canonicalRole: 'content',
                name: 'Semantic promo', category: 'content',
                origin: 'suggested', status: 'draft', confidence: 0.8, confirmed: false,
                templateIr: {
                  version: '1.1', tokens: doc.styleGuide?.irTokens || {},
                  tree: [{type:'card', children:[{type:'text', typeRole:'body', text:'Promo'}]}],
                },
                variants: {}, states: {}, dependencies: [], mockBindings: [],
                provenance: {extraction: 'semantic-suggestion-test'},
              };
              await state.saveDesignSystemDocument(id, doc);
            }""", ds_id2)
            page.locator("[data-ds-editor] [data-ds-tab='suggestions']").click()
            page.locator("[data-ds-editor] [data-ds-suggestion='semantic-promo']").click()
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id2)
            page.locator("[data-ds-editor] [data-ds-action='promote']").click()
            page.wait_for_function("id => Object.keys(window.GraphDev.node(id)?.data?.document?.components || {}).length > 0", arg=ds_id2)
            page.locator("[data-ds-editor] [data-ds-action='publish']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.status === 'published'", arg=ds_id2)
            page.locator("[data-ds-editor] [data-ds-action='default']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.defaultSet === true", arg=ds_id2)
            page.wait_for_function("id => window.GraphDev.node(id).data.defaultSet === false", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")
            sibling_flags = page.evaluate(
                """ids => ({
                  first: window.GraphDev.node(ids[0]).data.defaultSet,
                  second: window.GraphDev.node(ids[1]).data.defaultSet,
                })""",
                [ds_id, ds_id2],
            )
            check("sibling defaultSet cleared", sibling_flags.get("first") is False and sibling_flags.get("second") is True, json.dumps(sibling_flags))
            # restore first as project default for the remaining picker/reload checks
            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='default']").click()
            page.wait_for_function("id => window.GraphDev.node(id).data.defaultSet === true", arg=ds_id)
            page.locator("[data-ds-editor] [data-ds-action='close']").click()
            page.wait_for_selector("[data-ds-editor]", state="detached")

            # пикер убран из ноды Генератора (перегружала ноду) — выбор
            # дизайн-системы для генерации живёт на project default;
            # контракт пикера проверяем на Reskin-ноде
            page.locator(".n-reskin [data-ds-field='selection']").select_option(published["systemId"])
            page.locator(".n-reskin [data-ds-field='usage']").select_option("strict")
            reskin_data = page.evaluate("id => window.GraphDev.node(id).data", ids["reskin"])
            check("picker reference selection persisted (reskin)", reskin_data.get("designSystemSelection") == published["systemId"], json.dumps(reskin_data))
            check("picker strict usage persisted (reskin)", reskin_data.get("designSystemUsageMode") == "strict")
            gen = page.evaluate("id => window.GraphDev.node(id).data", ids["generator"])
            check("generator node has no picker state overrides", "designSystemSelection" not in gen, json.dumps(gen))

            persisted = page.evaluate("""async (systemId) => {
              const list = await (await fetch('/api/design-system/list')).json();
              const got = await (await fetch('/api/design-system/get', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({systemId, revision: 1})})).json();
              return {list, got};
            }""", published["systemId"])
            check(
                "reload persistence via registry+revision",
                any(s.get("systemId") == published["systemId"] for s in persisted["list"]["systems"]) and bool(persisted["got"].get("document")),
                json.dumps({"systems": [s.get("systemId") for s in persisted["list"]["systems"]], "hasDoc": bool(persisted["got"].get("document"))}),
            )

            page.route("**/api/design-system/publish", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"document": {"revision": 1, "contentHash": "auto-published"}, "summary": {"components": 0, "variants": 0}}),
            ))
            imported_id = page.evaluate("window.GraphDev.add('designsystem', 900, 420).id")
            imported_ok = page.evaluate("""async (id) => {
              return await window.__flowStore.getState().importDesignSystemDocument(id, {
                color: {primary: {$type:'color', $value:'#7c3aed'}, background: {$type:'color', $value:'#ffffff'}}
              }, 'tokens.json');
            }""", imported_id)
            page.wait_for_function("id => window.GraphDev.node(id)?.data?.status === 'published'", arg=imported_id)
            imported_data = page.evaluate("id => window.GraphDev.node(id).data", imported_id)
            check("review-free JSON import auto-publishes",
                  bool(imported_ok) and imported_data.get("status") == "published" and int(imported_data.get("revision") or 0) >= 1,
                  json.dumps(imported_data))

            open_btn.click()
            page.wait_for_selector("[data-ds-editor]")
            page.wait_for_function("id => !window.GraphDev.node(id)?.data?.busyAction", arg=ds_id)
            busy_pub = page.locator("[data-ds-editor] [data-ds-action='publish']")
            check("publish button remains labeled after lifecycle", "Опубликовать" in (busy_pub.get_attribute("aria-label") or ""))
            browser.close()
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL DESIGN SYSTEM UI CHECKS PASSED")


if __name__ == "__main__":
    main()
