"""Opt-in, destructive-only-to-owned-clone live desktop UI regression.

Run ONLY after fresh Source/DS documents are ready and all AI/build runs finish:
  .venv/Scripts/python app/ui_source_sites_kit_test.py --run-live

Attaches to CDP9345; no mocks, launches, imports, AI calls, promotions, DS saves,
page switches, global restore or graph clearing. Existing four nodes are never
edited deliberately. One tagged temporary EDIT clone at a time is removed by
exact ID in finally. A failed preservation check is reported, never "repaired"
by overwriting user data. Importing this module does not connect to the app.
"""

import argparse
import copy
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "source-sites-qa"
TITLE = "Source QA — SLSBMB + RSALE"
SITES = ("slsbmb", "rsale")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def snapshot(page):
    return page.evaluate("""() => {
      const s = window.__flowStore.getState();
      return {pageId:s.activePageId, pages:window.GraphDev.pages(), nodes:s.nodes,
        edges:s.edges, busy:s.busy};
    }""")


def node(page, node_id):
    return page.evaluate("id => window.GraphDev.node(id)", node_id)


def document(page, data):
    return page.evaluate("""async data => {
      const r = await fetch('/api/design-system/get', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({systemId:data.systemId, revision:data.revision || 0})});
      const value = await r.json();
      if (!r.ok || value.error || !value.document) throw Error(JSON.stringify(value));
      return value.document;
    }""", {"systemId": data["systemId"], "revision": data.get("revision", 0)})


def protected(state):
    """Canonical state, excluding measured geometry/selection and UI cache state."""
    result = {}
    for item in state["nodes"]:
        data = item["data"]
        keys = ("blocks", "sourceArtifact", "tokens", "url", "importedUrl", "aiProvider",
                "pipelineStatus", "activeViewport") if item["type"] == "sourceimport" else (
                    "systemId", "revision", "contentHash", "aiProvider", "autoPublish",
                    "pipelineStatus", "sourceNodeId", "_sourceFingerprint", "sourceUpdate")
        result[str(item["id"])] = {"type": item["type"], "position": item["position"],
                                   "data": {key: data.get(key) for key in keys}}
    return result


def attr(name, value):
    return f'[{name}={json.dumps(str(value))}]'


def sibling_pair(ir):
    """Find two independently addressable unlocked sibling layers, without fixtures."""
    for si, section in enumerate(ir.get("tree", [])):
        if section.get("editable") is False:
            continue
        addressed = section.get("type") == "source-block" or section.get("variant") == "dom-capture"

        def walk(parent, path):
            children = parent.get("children", [])
            candidates = [(i, child) for i, child in enumerate(children)
                          if child.get("editable") is not False]
            if len(candidates) >= 2:
                refs = []
                for index, child in candidates[:2]:
                    child_path = path + ["children", index]
                    key = child.get("sourceKey") if addressed else None
                    refs.append({"path": ["tree", si] + child_path,
                                 "layer": f"{si}:{key or '.'.join(map(str, child_path))}"})
                return refs
            for index, child in candidates:
                found = walk(child, path + ["children", index])
                if found:
                    return found
            return None

        found = walk(section, [])
        if found:
            return found
    return None


def at(value, path):
    for key in path:
        value = value[key]
    return value


def screenshot(page, run_id, name):
    path = OUT / f"ui-kit-{run_id}-{name}.png"
    page.screenshot(path=str(path), full_page=False)
    return str(path)


def check_kit(page, timeout):
    frame_element = page.locator("[data-ds-kit-frame]")
    frame_element.wait_for(state="visible", timeout=timeout)
    frame = frame_element.element_handle().content_frame()
    require(frame is not None, "Kit iframe has no document")
    frame.wait_for_load_state("domcontentloaded", timeout=timeout)
    frame.wait_for_function("document.body && document.body.innerText.trim().length > 20", timeout=timeout)
    frame.wait_for_function("document.documentElement.dataset.ddnaReady === '1'", timeout=timeout)
    require(frame.locator("[data-component-key]").count() > 0, "Kit contains no component cards")
    before_url = frame.url
    frame.locator('nav.toc a[href="#rules"]').click()
    frame.wait_for_function("Math.abs(document.getElementById('rules').getBoundingClientRect().top) < 80", timeout=timeout)
    require(frame.url == before_url, "Kit fragment link replaced the live blob document")
    require(frame.evaluate("document.documentElement.dataset.ddnaReady === '1'"),
            "Kit navigation discarded rendered document")
    frame.evaluate("window.scrollTo(0,0)")
    viewport_results = {}
    for viewport in ("desktop", "tablet", "mobile"):
        frame.locator(".vpbar button" + attr("data-vp", viewport)).click()
        frame.wait_for_function("vp => window.DDNA.viewport === vp && [...document.querySelectorAll('[data-ddna-render]')].every(e => e.dataset.rendered === '1' && e.childElementCount > 0)", arg=viewport, timeout=timeout)
        viewport_results[viewport] = frame.locator('[data-ddna-render][data-rendered="1"]').count()
        require(viewport_results[viewport] > 0, f"{viewport}: no live kit masters rendered")
    frame.locator('.vpbar button[data-vp="desktop"]').click()
    # Scroll actual lazy images into view. Do not fake load/decode state or replace URLs.
    for image in frame.locator("img").all():
        if image.is_visible():
            image.scroll_into_view_if_needed(timeout=timeout)
    frame.evaluate("window.scrollTo(0,0)")
    frame.wait_for_function("[...document.images].every(i => i.complete)", timeout=timeout)
    frame.wait_for_function("document.fonts.status === 'loaded'", timeout=timeout)
    fonts = frame.evaluate("""() => {
      const faces = [...document.fonts];
      return {status:document.fonts.status, faces:faces.map(f => ({family:f.family,
        weight:f.weight, style:f.style, status:f.status})),
        expected:window.DDNA.fontSpecs || [],
        used:[...new Set([...document.querySelectorAll('body *')]
          .filter(e=>e.children.length===0 && e.textContent.trim() && e.getBoundingClientRect().width)
          .map(e=>getComputedStyle(e).fontFamily))]};
    }""")
    images = frame.evaluate("""() => [...document.images].map(i => ({
      src:(i.currentSrc || i.src).slice(0,180), complete:i.complete,
      width:i.naturalWidth,height:i.naturalHeight}))""")
    require(not any(not im["width"] or not im["height"] for im in images),
            f"Kit broken images: {[im for im in images if not im['width'] or not im['height']]}")
    require(fonts["status"] == "loaded" and not any(f["status"] == "error" for f in fonts["faces"]),
            f"Kit font load failure: {fonts}")
    for spec in fonts["expected"]:
        require(any(face["family"].strip("\"'") == spec["family"] and face["status"] == "loaded"
                    for face in fonts["faces"]), f"Expected embedded kit font not loaded: {spec}")
    require(bool(fonts["used"]), "No rendered text/font usage in kit")
    return {"imageCount": len(images), "images": images, "fonts": fonts, "renderedByViewport": viewport_results,
            "fontEvidence": "FontFaceSet and rendered CSS families; no visual glyph-fidelity claim",
            "childFrames": len(frame.child_frames), "fragmentNavigationPreservedDocument": True}


def close_editor(page):
    editor = page.locator(".dna-editor:visible")
    if editor.count():
        editor.locator('[data-act="close"]').click()
        discard = page.locator('[data-act="close-discard"]:visible')
        if discard.count():
            discard.click()
        editor.wait_for(state="hidden")


def run_site(page, initial, ds, doc, run_id, timeout, result, editor_only=False):
    ds_id = int(ds["id"])
    def progress(stage):
        print(json.dumps({'site':ds['data']['qaSite'], 'stage':stage, 'runId':run_id}), flush=True)
    progress('open-catalog')
    created_id = None
    clone = None
    owner = f"ui-kit-test:{run_id}:{ds_id}"
    expected_page = initial["pageId"]
    initial_ids = {str(n["id"]) for n in initial["nodes"]}
    candidates = [(key, comp.get("templateIr") or comp.get("masterIr"))
                  for key, comp in doc.get("components", {}).items()]
    candidates = [(key, ir) for key, ir in candidates if ir and sibling_pair(ir)]
    def all_viewports_visible(candidate):
        return all(not any(root.get('visible') is False or
            (root.get('responsive', {}).get(vp) or {}).get('visible') is False
            for root in candidate[1].get('tree', [])) for vp in ('desktop', 'tablet', 'mobile'))
    # Choose an actually responsive master for the three-view edit check. A
    # desktop-only search field legitimately has no tablet/mobile editable DOM.
    candidates.sort(key=lambda candidate: not all_viewports_visible(candidate))
    require(candidates, "No accepted component with two editable sibling layers; no promotion permitted")
    key, clone = candidates[0]
    result["componentKey"] = key
    try:
        # Existing app event, not a test hook. It opens exactly this DS panel.
        page.evaluate("id => window.dispatchEvent(new CustomEvent('designdna:open-ds-editor', {detail:{nodeId:id}}))", ds_id)
        panel = page.locator("[data-ds-editor]")
        panel.wait_for(state="visible")
        # After restart DS is only a persisted reference. The editor hydrates
        # its immutable document asynchronously; Source cards mount earlier.
        page.wait_for_function("id => !!window.GraphDev.node(id)?.data.document?.id",
                               arg=ds_id, timeout=timeout)
        panel.locator('[data-source-component-catalog] [data-catalog-component]').first.wait_for(
            state='attached', timeout=timeout)
        if not editor_only:
            progress('live-kit')
            panel.locator('[data-ds-action="styleguide"]').click()
            result["kit"] = check_kit(page, timeout)
            result["kit"]["exportStatus"] = panel.locator(".ds-kit-tools").inner_text()
            result["kitScreenshot"] = screenshot(page, run_id, f"{ds['data']['qaSite']}-kit")
            progress('live-kit-verified')
        else:
            result['kit'] = {'status':'not-run', 'reason':'Explicit editor-only diagnostic; no kit success implied'}
        page.evaluate("""() => {
          window.__qaCatalogClicks = [];
          window.__qaCatalogClickObserver = event => {
            const target=event.target.closest?.('button');
            if(target && target.closest('[data-ds-editor]')) window.__qaCatalogClicks.push({
              text:target.textContent, data:{...target.dataset}, x:event.clientX,y:event.clientY});
          };
          document.addEventListener('click',window.__qaCatalogClickObserver,true);
        }""")
        try:
            panel.locator('[data-ds-tab="source"]').click()
            panel.locator('[data-ds-source-view="catalog"]').click()
        finally:
            result['catalogClickEvidence'] = page.evaluate("""() => {
              document.removeEventListener('click',window.__qaCatalogClickObserver,true);
              delete window.__qaCatalogClickObserver;
              const clicks=window.__qaCatalogClicks; delete window.__qaCatalogClicks; return clicks;
            }""")
        panel.locator('[data-source-component-catalog]').wait_for(state='visible')
        progress('catalog-open')
        card = panel.locator(attr("data-catalog-component", key))
        if card.count():
            card.get_by_role("button", name="Открыть", exact=True).click()
        else:
            # A catalog family can contain this exact master as an instance.
            # Open its explicit existing key, never substitute the family master.
            instance = panel.get_by_title(f'Открыть экземпляр {key}', exact=True)
            require(instance.count() == 1, f'Exact component {key} missing from catalog: {panel.locator("[data-catalog-component]").evaluate_all("els=>els.map(e=>e.dataset.catalogComponent)")}')
            instance.click()
        selected = panel.locator(attr("data-ds-component", key) + '[data-ds-pool="components"]')
        require(selected.count() == 1, "Selected accepted component absent in component library")
        require("active" in selected.get_attribute("class").split(), "Catalog Open did not select the requested component")
        # Exercise a second real component when available, then return to the editor candidate.
        second = next((k for k in doc["components"] if k != key), None)
        if second:
            second_card = panel.locator(attr("data-ds-component", second) + '[data-ds-pool="components"]')
            second_card.click()
            require("active" in second_card.get_attribute("class").split(), "Second component selection failed")
            panel.locator("[data-ds-preview-host]").wait_for(state="visible")
            selected.click()
        result["selectedComponents"] = [k for k in [key, second] if k]
        progress('component-viewports')
        result["viewports"] = {}
        for viewport in ("desktop", "tablet", "mobile"):
            button = panel.locator(attr("data-ds-viewport", viewport))
            button.click()
            page.wait_for_function("vp => document.querySelector('[data-ds-viewport=\"'+vp+'\"]')?.getAttribute('aria-pressed') === 'true'", arg=viewport)
            host = panel.locator("[data-ds-preview-host]")
            host.wait_for(state="visible")
            hidden = all(root.get('visible') is False or
                (root.get('responsive', {}).get(viewport) or {}).get('visible') is False
                for root in clone.get('tree', []))
            if not hidden:
                host.locator("[data-ir-path]").first.wait_for(state='attached', timeout=timeout)
            require(host.locator("[data-ir-path]").count() == 0 if hidden else host.locator("[data-ir-path]").count() > 0,
                    f"{viewport}: master DOM contradicts captured visibility")
            result["viewports"][viewport] = {"box": host.bounding_box(),
                "sourceHidden": hidden,
                "screenshot": screenshot(page, run_id, f"{ds['data']['qaSite']}-{viewport}")}
        panel.locator('[data-ds-action="close"]').click()
        panel.wait_for(state="hidden")
        require(digest(document(page, ds["data"])) == digest(doc), "DS changed during panel inspection")

        # Explicit detached master clone: no _dsMaster pointer, so editor Save cannot
        # write a DS variant. Assign ownership atomically with creation in one JS turn.
        created_id = page.evaluate("""({ir, owner, pageId, ids}) => {
          const s=window.__flowStore.getState();
          if(s.activePageId!==pageId || s.nodes.length!==4 || s.nodes.some(n=>!ids.includes(String(n.id))))
            throw Error('Canvas changed before clone creation');
          const id=window.GraphDev.add('edit', 780, 500).id;
          window.GraphDev.patchData(id, {ir:JSON.parse(JSON.stringify(ir)), _qaKitOwner:owner});
          window.GraphDev.fit(); return id;
        }""", {"ir": clone, "owner": owner, "pageId": expected_page, "ids": sorted(initial_ids)})
        result["temporaryNodeId"] = created_id
        progress('edit-owned-clone')
        require(str(created_id) not in initial_ids, "Clone ID collides with original node")
        edit_button = page.locator(f'.svelte-flow__node{attr("data-id", created_id)} .f-open-editor')
        edit_button.click()
        editor = page.locator(".dna-editor:visible")
        editor.wait_for(state="visible")
        editor.locator('[data-act="zoom-fit"]').click()
        baseline = copy.deepcopy(node(page, created_id)["data"].get("_editorDraft", {}).get("ir") or node(page, created_id)["data"]["ir"])
        pair = sibling_pair(baseline)
        require(pair, "Editor clone has no editable sibling pair")
        result["layers"] = pair
        for ref in reversed(pair):
            row = editor.locator(".fe-layer" + attr("data-key", ref["layer"]))
            row.locator(".fe-ln").click()
            require(row.get_attribute("aria-pressed") == "true", f"Layer not independently selected: {ref}")
            require(editor.locator('.fe-layer[aria-pressed="true"]').count() == 1, "Selection unexpectedly includes siblings")
        details = editor.locator("details.manual-controls")
        if details.get_attribute("open") is None:
            details.locator("summary").click()
        field = editor.locator('[data-style-text="background"]')
        color = "#123abc" if at(baseline, pair[0]["path"]).get("style", {}).get("background") != "#123abc" else "#abc123"
        field.fill(color)
        field.press("Tab")
        result["editorScreenshot"] = screenshot(page, run_id, f"{ds['data']['qaSite']}-editor")
        editor.locator('[data-act="save"]').click()
        editor.wait_for(state="hidden")
        saved = node(page, created_id)["data"]["ir"]
        result['savedSelectionEvidence'] = {'baseline': baseline, 'saved': saved, 'selectedPath': pair[0]['path'], 'color': color}
        require(at(saved, pair[0]["path"]).get("style", {}).get("background") == color, "Editor Save did not commit selected layer color")
        # All other subtrees (not merely the chosen sibling) must remain identical.
        expected_tree = copy.deepcopy(baseline["tree"])
        target = at(expected_tree, pair[0]["path"][1:])
        target.setdefault("style", {})["background"] = color
        if saved["tree"] != expected_tree:
            result["unexpectedEdit"] = {"baselineTree": baseline["tree"], "expectedTree": expected_tree, "savedTree": saved["tree"]}
        require(saved["tree"] == expected_tree, "Edit changed siblings, hierarchy, or another property")
        require(at(saved, pair[1]["path"]) == at(baseline, pair[1]["path"]), "Sibling changed")
        edit_button.click()
        editor.wait_for(state="visible")
        require(node(page, created_id)["data"]["ir"]["tree"] == expected_tree, "Saved edit did not survive editor reopen")
        close_editor(page)
        result["editSave"] = {"passed": True, "changedProperty": "style.background",
                              "allOtherTreeDataUnchanged": True, "reopened": True}
        progress('save-reopen-verified')
    except Exception:
        import traceback
        result['traceback'] = traceback.format_exc()
        result['beforeCleanupScreenshot'] = screenshot(page, run_id, f"{ds['data']['qaSite']}-before-cleanup")
        raise
    finally:
        if created_id is not None:
            # Refuse to touch another page or a node whose ownership was replaced.
            current = snapshot(page)
            require(current["pageId"] == expected_page, "Page changed: refusing cleanup on another canvas")
            owned = node(page, created_id)
            if owned:
                require(str(created_id) not in initial_ids and owned["type"] == "edit"
                        and owned["data"].get("_qaKitOwner") == owner, "Clone ownership lost: refusing delete")
                close_editor(page)
                page.evaluate("""({id,owner,ir}) => {
                  const g=window.GraphDev;
                  if(g.node(id)?.data._qaKitOwner!==owner) throw Error('Clone ownership lost');
                  g.patchData(id,{ir});
                }""", {"id": created_id, "owner": owner, "ir": clone})
                require(node(page, created_id)["data"]["ir"] == clone, "Clone restoration failed")
                page.evaluate("""({id,owner}) => {
                  if(window.GraphDev.node(id)?.data._qaKitOwner!==owner) throw Error('Clone ownership lost');
                  window.__flowStore.getState().deleteNode(id);
                }""", {"id": created_id, "owner": owner})
            result["temporaryNodeRemoved"] = node(page, created_id) is None
        panel = page.locator("[data-ds-editor]:visible")
        if panel.count() and digest(document(page, ds["data"])) == digest(doc):
            panel.locator('[data-ds-action="close"]').click()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Explicitly opt in AFTER main confirms fresh idle documents")
    parser.add_argument("--cdp", default=os.environ.get("DESIGNDNA_CDP", "http://127.0.0.1:9345"))
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument('--site', choices=SITES, help='Retry one pair; preservation checks still cover both')
    parser.add_argument('--editor-only', action='store_true', help='Diagnose catalog/editor without repeating kit export; report marks kit not-run')
    args = parser.parse_args()
    if not args.run_live:
        parser.error("No live action taken. Wait for fresh documents, then pass --run-live.")
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    run_id = str(time.time_ns())
    report = {"runId": run_id, "cdp": args.cdp, "mocked": False, "sites": {}, "passed": False,
              'requestedSites': [args.site] if args.site else list(SITES)}
    report['scope'] = 'catalog-editor-only' if args.editor_only else 'kit-catalog-editor'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(args.cdp)
            pages = [pg for ctx in browser.contexts for pg in ctx.pages if pg.url.startswith("file:")]
            require(len(pages) == 1, "Expected exactly one desktop renderer; refusing ambiguous target")
            page = pages[0]
            page.set_default_timeout(args.timeout_ms)
            page.wait_for_function("window.GraphDev && window.__flowStore && window.designDNA")
            initial = snapshot(page)
            require(next(p for p in initial["pages"] if p["active"])["name"] == TITLE, "Wrong active QA canvas; will not switch pages")
            require(len(initial["nodes"]) == 4, "Expected exactly four initial nodes")
            require(not any(initial["busy"].values()) and not any(n["data"].get("busyAction") for n in initial["nodes"]), "Wait for all live AI/build runs to finish")
            require(not page.locator("[data-ds-editor]:visible, .dna-editor:visible").count(), "Close existing editors before QA")
            baseline = protected(initial)
            systems = {}
            for site in SITES:
                sources = [n for n in initial["nodes"] if n["type"] == "sourceimport" and n["data"].get("qaSite") == site]
                ds_nodes = [n for n in initial["nodes"] if n["type"] == "designsystem" and n["data"].get("qaSite") == site]
                require(len(sources) == len(ds_nodes) == 1, f"Expected one Source + one DS tagged {site}")
                ds = ds_nodes[0]
                require(any(str(e["source"]) == str(sources[0]["id"]) and str(e["target"]) == str(ds["id"])
                            and e.get("sourceHandle") == e.get("targetHandle") == "artifact" for e in initial["edges"]), f"{site}: missing actual artifact wire")
                doc = document(page, ds["data"])
                require(ds["data"].get("document") in (None, doc), f"{site}: live cache differs from server document")
                stages = ds["data"].get("pipelineStatus", {})
                require(not any(stage.get("status") == "running" for stage in stages.values()), f"{site}: persisted stage still running")
                require(doc.get("styleGuide", {}).get("review") or stages.get("style-review"), f"{site}: opening panel could start automatic paid style review")
                require(not doc.get("reviewComponents") or stages.get("master-review"), f"{site}: opening panel could start automatic paid master review")
                systems[site] = (ds, doc)
            report["initialNodeIds"] = sorted(baseline)
            try:
                for site, (ds, doc) in systems.items():
                    if args.site and site != args.site:
                        continue
                    result = report["sites"][site] = {"systemId": doc["id"], "beforeHash": digest(doc)}
                    try:
                        run_site(page, initial, ds, doc, run_id, args.timeout_ms, result, args.editor_only)
                        result["passed"] = True
                    except Exception as exc:
                        result.update(passed=False, error=str(exc))
                        result["failureScreenshot"] = screenshot(page, run_id, f"{site}-failure")
                        # Do not continue after graph/panel cleanup failure.
                        require(len(snapshot(page)["nodes"]) == 4 and not page.locator("[data-ds-editor]:visible, .dna-editor:visible").count(), "Cleanup incomplete; second site not attempted")
            finally:
                final = snapshot(page)
                report["cleanup"] = {"fourOriginalNodesOnly": sorted(str(n["id"]) for n in final["nodes"]) == sorted(baseline),
                    "samePage": final["pageId"] == initial["pageId"], "edgesPreserved": final["edges"] == initial["edges"],
                    "canonicalNodeDataPreserved": protected(final) == baseline,
                    "otherPageInventoryPreserved": final["pages"] == initial["pages"], "systems": {}}
                for site, (ds, doc) in systems.items():
                    after = document(page, ds["data"])
                    live = node(page, int(ds["id"]))["data"].get("document")
                    report["cleanup"]["systems"][site] = {"serverDocumentPreserved": after == doc,
                        "liveDocumentPreserved": live is None or live == doc, "afterHash": digest(after)}
                require(all(value is True for key, value in report["cleanup"].items() if key != "systems")
                        and all(s["serverDocumentPreserved"] and s["liveDocumentPreserved"] for s in report["cleanup"]["systems"].values()),
                        "Preservation invariant failed; no original data was automatically restored")
            report["passed"] = set(report['sites']) == set(report['requestedSites']) and all(s.get("passed") for s in report["sites"].values())
            # Do not browser.close(): this is the user's attached Electron process.
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        target = OUT / "ui-kit-test.json"
        if target.exists():
            shutil.copy2(target, OUT / f"ui-kit-test.previous-{run_id}.json")
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "report": str(target), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
