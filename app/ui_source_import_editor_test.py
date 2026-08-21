"""Source Import 2.0 -> DNA Editor responsive interaction checks."""
from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []

SOURCE_IR = {
    "version": "1.0",
    "meta": {"name": "Responsive imported header"},
    "frame": {"width": 800, "height": 72, "layout": "auto", "direction": "row"},
    "responsive": {"viewports": {
        "desktop": {"width": 800, "height": 72, "preview": "data:image/png;base64,reference"},
        "tablet": {"width": 768, "height": 72, "preview": "data:image/png;base64,reference"},
        "mobile": {"width": 390, "height": 180, "preview": "data:image/png;base64,reference"},
    }},
    "tokens": {"color": {"background": "#ffffff", "text": "#111111"}},
    "tree": [{
        "id": "imported-block", "type": "source-block", "variant": "dom-capture", "sourceKey": "root",
        "frame": {"width": 800, "height": 72, "layout": "auto", "direction": "row", "gap": 12,
                  "padding": [14, 16, 14, 16], "clip": True},
        "responsive": {
            "tablet": {"visible": True, "frame": {"width": 768, "height": 72, "layout": "auto",
                                                         "direction": "row", "gap": 10, "padding": [14, 12, 14, 12]}},
            "mobile": {"visible": True, "frame": {"width": 390, "height": 180, "layout": "auto",
                                                         "direction": "column", "gap": 8, "padding": 10}},
        },
        "children": [
            {"type": "card", "role": "brand", "sourceKey": "root/div:1",
             "frame": {"width": 160, "height": 44, "layout": "auto", "direction": "row", "gap": 8},
             "children": [{"type": "text", "text": "Market", "sourceKey": "root/div:1::text0",
                           "frame": {"width": 80, "height": 20}}]},
            {"type": "input", "placeholder": "Search", "sourceKey": "root/input:1",
             "frame": {"width": "fill", "height": 44, "layout": "auto", "direction": "row", "padding": [0, 12]},
             "children": [{"type": "text", "text": "Search", "sourceKey": "root/input:1::value",
                           "frame": {"width": "hug", "height": "hug"}}]},
            {"type": "button", "text": "Find", "variant": "primary", "sourceKey": "root/button:1",
             "sourceMeta": {"kind": "dom", "componentBoundary": True,
                            "componentRole": "button", "componentLabel": "Search CTA"},
             "style": {"background": "#f97316", "color": "#ffffff", "borderRadius": 8},
             "frame": {"width": 100, "height": 44, "layout": "auto", "direction": "row", "padding": [0, 18],
                       "justify": "center", "align": "center"},
             "responsive": {"mobile": {"visible": True, "frame": {"width": 120, "height": 44,
                 "layout": "auto", "direction": "row", "padding": [0, 18], "justify": "center", "align": "center"}}},
             "children": [{"type": "text", "text": "Find", "sourceKey": "root/button:1::text0",
                           "style": {"color": "#ffffff"}, "frame": {"width": 32, "height": 18}}]},
            {"type": "image", "src": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
             "alt": "canvas", "sourceKey": "root/canvas:1",
             "editable": False, "lockedReason": "canvas: raster surface",
             "style": {"objectFit": "fill"},
             "frame": {"width": 80, "height": 44}},
        ],
    }],
}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.route(
            "**/api/project/load",
            lambda route: route.fulfill(status=200, content_type="application/json",
                                        body='{"project":null,"updated_at":null}'),
        )
        page.route(
            "**/api/project/save",
            lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'),
        )
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && window.IRRenderer && window.DNAEditor")
        node_id = page.evaluate("window.GraphDev.add('edit', 80, 60).id")
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": node_id, "ir": SOURCE_IR})
        page.wait_for_function(
            "(id) => document.querySelector(`.svelte-flow__node[data-id=\"${id}\"] .edit-preview-card .ir-preview`)?.offsetHeight < 100",
            arg=node_id,
        )
        compact_preview = page.evaluate("""(id) => {
          const preview=document.querySelector(`.svelte-flow__node[data-id="${id}"] .edit-preview-card .ir-preview`);
          const art=preview.querySelector('[data-design-width]');
          return {previewHeight:preview.offsetHeight, renderedHeight:art.getBoundingClientRect().height};
        }""", node_id)
        check("Edit node preview hugs the rendered source artboard",
              compact_preview["previewHeight"] < 100 and
              abs(compact_preview["previewHeight"] - compact_preview["renderedHeight"]) <= 2,
              json.dumps(compact_preview))
        page.click(f'.svelte-flow__node[data-id="{node_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor [data-ir-path="root/button:1::text0"]')
        layers_text = page.locator(".dna-editor .fe-layers-tree").inner_text()
        check("component boundaries are named in Layers outliner",
              "компонент · Search CTA" in layers_text, layers_text)

        desktop = page.evaluate("""() => ({
          art: [document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]').offsetWidth,
                document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]').offsetHeight],
          underlays: document.querySelectorAll('.dna-editor .source-underlay').length,
          viewportVisible: !document.querySelector('.dna-editor .fe-viewports').hidden,
          buttonChildren: document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]').querySelectorAll('[data-ir-path]').length,
          sectionLayout: getComputedStyle(document.querySelector('.dna-editor [data-ir-sec="0"]')).display,
          canonicalLayout: window.GraphDev.node(%d).data.ir.tree[0].frame.layout,
          activeLayout: window.DNAEditor.getIR().tree[0].frame.layout,
        })""" % node_id)
        check("desktop artboard uses source viewport", desktop["art"] == [800, 72], json.dumps(desktop))
        check("source screenshot is not an editor underlay", desktop["underlays"] == 0, json.dumps(desktop))
        check("responsive viewport control is visible", desktop["viewportVisible"], json.dumps(desktop))
        check("button renders its real nested text layer", desktop["buttonChildren"] == 1, json.dumps(desktop))
        check("source section renders as auto-layout",
              desktop["sectionLayout"] == "flex" and desktop["canonicalLayout"] == "auto" and desktop["activeLayout"] == "auto",
              json.dumps(desktop))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(150)
        mobile = page.evaluate("""() => {
          const art = document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]');
          const button = document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]');
          return {art:[art.offsetWidth,art.offsetHeight], buttonWidth:button.offsetWidth,
                  buttonCss:button.getAttribute('style'), buttonFrame:window.DNAEditor.getIR().tree[0].children[2].frame,
                  active:document.querySelector('[data-viewport="mobile"]').classList.contains('active')};
        }""")
        check("mobile switches the same artboard to 390x180", mobile["art"] == [390, 180], json.dumps(mobile))
        check("mobile frame override is applied", mobile["buttonWidth"] == 120 and mobile["active"], json.dumps(mobile))

        page.click('.dna-editor [data-viewport="tablet"]')
        page.wait_for_timeout(150)
        tablet = page.evaluate("""() => {
          const art = document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]');
          const section = document.querySelector('.dna-editor [data-ir-sec="0"]');
          return {art:[art.offsetWidth,art.offsetHeight], display:getComputedStyle(section).display,
                  direction:getComputedStyle(section).flexDirection,
                  activeLayout:window.DNAEditor.getIR().tree[0].frame.layout};
        }""")
        check("tablet keeps imported auto-layout",
              tablet["art"] == [768, 72] and tablet["display"] == "flex" and
              tablet["direction"] == "row" and tablet["activeLayout"] == "auto",
              json.dumps(tablet))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(120)

        point = page.evaluate("""() => {
          const el=document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1::text0"]'); const r=el.getBoundingClientRect();
          return {x:r.left+r.width/2,y:r.top+r.height/2};
        }""")
        page.mouse.click(point["x"], point["y"])
        selected_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        check("single click selects the component container", selected_label.startswith("button"), selected_label)

        # editable:false (raster fallback Source Import): слой selectable/inspectable,
        # но renderer помечает его data-ir-locked, а geoedit отказывает мутации.
        locked_mark = page.evaluate("""() => {
          const el=document.querySelector('.fe-canvas-inner [data-ir-path="root/canvas:1"]');
          return el ? el.getAttribute('data-ir-locked') : null;
        }""")
        check("locked raster layer is marked data-ir-locked", locked_mark == "canvas: raster surface", str(locked_mark))

        lpoint = page.evaluate("""() => {
          const el=document.querySelector('.fe-canvas-inner [data-ir-path="root/canvas:1"]'); const r=el.getBoundingClientRect();
          return {x:r.left+r.width/2,y:r.top+r.height/2};
        }""")
        page.mouse.click(lpoint["x"], lpoint["y"])
        page.wait_for_timeout(120)
        locked_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        check("locked raster layer stays selectable", locked_label.startswith("image"), locked_label)

        page.mouse.move(lpoint["x"], lpoint["y"])
        page.mouse.down()
        page.mouse.move(lpoint["x"] + 30, lpoint["y"] + 6, steps=4)
        page.mouse.up()
        page.wait_for_timeout(120)
        locked_frame = page.evaluate("window.DNAEditor.getIR().tree[0].children[3].frame")
        check("locked raster layer refuses geometry drag",
              locked_frame.get("x") is None and locked_frame.get("absolute") is not True, json.dumps(locked_frame))

        page.mouse.dblclick(lpoint["x"], lpoint["y"])
        page.wait_for_timeout(120)
        locked_editing = page.evaluate("""!!document.querySelector('.fe-canvas-inner [data-ir-path="root/canvas:1"].editing')""")
        check("locked raster layer refuses inline text editing", not locked_editing, "")
        before = page.evaluate("""() => { const r=document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]').getBoundingClientRect(); return [r.left,r.top]; }""")
        page.mouse.move(point["x"], point["y"])
        page.mouse.down()
        page.mouse.move(point["x"] + 35, point["y"] + 8, steps=5)
        page.mouse.up()
        page.wait_for_timeout(120)
        drag_state = page.evaluate("""() => {
          const ir=window.DNAEditor.getIR(); const button=ir.tree[0].children[2];
          const r=document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]').getBoundingClientRect();
          return {parentLayout:ir.tree[0].frame.layout, absolute:button.frame.absolute, x:button.frame.x,
                  moved:[r.left,r.top]};
        }""")
        check("free drag keeps the parent auto-layout", drag_state["parentLayout"] == "auto", json.dumps(drag_state))
        check("free drag detaches only the selected component", drag_state["absolute"] is True and drag_state["x"] >= 0,
              json.dumps({"before": before, **drag_state}))

        page.evaluate("window.DNAEditor.getIR().tree[0].children[1].children[0].text = 'Search everywhere'")
        page.click('.dna-editor [data-viewport="desktop"]')
        page.wait_for_timeout(120)
        desktop_after_edit = page.evaluate("""() => ({
          buttonFrame:window.DNAEditor.getIR().tree[0].children[2].frame,
          search:document.querySelector('.fe-canvas-inner [data-ir-path="root/input:1::value"]').textContent,
        })""")
        check("text edits are shared between viewports", desktop_after_edit["search"] == "Search everywhere",
              json.dumps(desktop_after_edit))
        check("mobile drag does not change desktop layout",
              desktop_after_edit["buttonFrame"].get("absolute") is not True, json.dumps(desktop_after_edit))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(120)
        mobile_after_return = page.evaluate("window.DNAEditor.getIR().tree[0].children[2].frame")
        check("breakpoint-specific layout survives viewport switching",
              mobile_after_return.get("absolute") is True and mobile_after_return.get("x") == drag_state["x"],
              json.dumps(mobile_after_return))

        # ---------- structural mutations on sourceKey-addressed layers ----------
        # Acceptance repair: editable Source Import layers (DOM/text/image/SVG)
        # must support delete/duplicate path-agnostically; editable:false raster
        # stays frozen for every structural mutation.
        page.click('.dna-editor [data-viewport="desktop"]')
        page.wait_for_timeout(150)

        def layer_point(sel: str):
            return page.evaluate("""(sel) => {
              const el=document.querySelector('.fe-canvas-inner [data-ir-path="'+sel+'"]');
              if(!el) return null;
              const r=el.getBoundingClientRect();
              return {x:r.left+r.width/2,y:r.top+r.height/2};
            }""", sel)

        def child_keys() -> list[str]:
            return page.evaluate("window.DNAEditor.getIR().tree[0].children.map(c => String(c.sourceKey || ''))")

        # 1) editable imported button: Delete removes it from IR and DOM
        bp = layer_point("root/button:1::text0")
        page.mouse.click(bp["x"], bp["y"])
        page.wait_for_timeout(120)
        sel_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        check("editable imported button is selected as a container", sel_label.startswith("button"), sel_label)
        page.keyboard.press("Delete")
        page.wait_for_timeout(150)
        keys_after_delete = child_keys()
        button_dom_gone = page.evaluate(
            '!document.querySelector(\'.fe-canvas-inner [data-ir-path="root/button:1"]\')')
        check("editable imported button delete succeeds",
              "root/button:1" not in keys_after_delete and button_dom_gone, json.dumps(keys_after_delete))

        # 2) undo restores the deleted layer
        page.keyboard.press("Control+z")
        page.wait_for_timeout(150)
        keys_after_undo = child_keys()
        check("undo restores the deleted imported button",
              "root/button:1" in keys_after_undo, json.dumps(keys_after_undo))

        # 3) Ctrl+D duplicates the editable button: unique sourceKey subtree,
        #    second node independently selectable
        bp = layer_point("root/button:1::text0")
        page.mouse.click(bp["x"], bp["y"])
        page.wait_for_timeout(120)
        page.keyboard.press("Control+d")
        page.wait_for_timeout(150)
        keys_after_dup = child_keys()
        original_keys = ["root/div:1", "root/input:1", "root/button:1", "root/canvas:1"]
        dup_keys = [k for k in keys_after_dup if k not in original_keys]
        dup_key = dup_keys[0] if len(dup_keys) == 1 else None
        check("duplicate adds exactly one new top-level layer with a unique sourceKey",
              dup_key is not None and len(keys_after_dup) == 5, json.dumps(keys_after_dup))
        dup_state = page.evaluate("""(dk) => {
          if(!dk) return null;
          const paths=[...document.querySelectorAll('.fe-canvas-inner [data-ir-path]')]
            .map(e=>e.getAttribute('data-ir-path'));
          return {dupDom:paths.includes(dk), dupTextDom:paths.includes(dk+'::text0'),
                  uniquePaths:new Set(paths).size===paths.length};
        }""", dup_key)
        check("duplicate renders with a unique DOM identity (no captured-key collision)",
              bool(dup_state) and dup_state["dupDom"] and dup_state["dupTextDom"] and dup_state["uniquePaths"],
              json.dumps({"dup_key": dup_key, **(dup_state or {})}))
        if dup_key:
            dp = layer_point(dup_key + "::text0")
            page.mouse.click(dp["x"], dp["y"])
            page.wait_for_timeout(120)
            dup_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
            check("duplicate is independently selectable as a button container",
                  dup_label.startswith("button"), dup_label)
            # cleanup: удалить дубликат — locked-проверки идут по исходному дереву
            page.keyboard.press("Delete")
            page.wait_for_timeout(150)

        # 4) editable:false raster fallback: delete/duplicate по-прежнему отказывают
        locked_keys_before = child_keys()
        lp = layer_point("root/canvas:1")
        page.mouse.click(lp["x"], lp["y"])
        page.wait_for_timeout(120)
        page.keyboard.press("Delete")
        page.wait_for_timeout(150)
        keys_after_locked_del = child_keys()
        check("locked raster layer delete is refused",
              keys_after_locked_del == locked_keys_before and "root/canvas:1" in keys_after_locked_del,
              json.dumps(keys_after_locked_del))
        page.mouse.click(lp["x"], lp["y"])
        page.wait_for_timeout(120)
        page.keyboard.press("Control+d")
        page.wait_for_timeout(150)
        keys_after_locked_dup = child_keys()
        check("locked raster layer duplicate is refused",
              keys_after_locked_dup == locked_keys_before, json.dumps(keys_after_locked_dup))
        # 5) editable:false raster: copy/paste и cut/paste отказывают — копия
        #    locked-слоя это отложенный дубликат; IR и буфер не меняются.
        lp = layer_point("root/canvas:1")
        page.mouse.click(lp["x"], lp["y"])
        page.wait_for_timeout(120)
        page.keyboard.press("Control+c")
        page.wait_for_timeout(150)
        copy_hint = page.evaluate("!!document.querySelector('.geo-overlay .geo-hint')")
        page.keyboard.press("Control+v")
        page.wait_for_timeout(150)
        keys_after_locked_copy = child_keys()
        check("locked raster copy is refused with a hint", copy_hint, "")
        check("locked raster copy+paste leaves the IR unchanged",
              keys_after_locked_copy == locked_keys_before, json.dumps(keys_after_locked_copy))
        page.keyboard.press("Control+x")
        page.wait_for_timeout(150)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(150)
        keys_after_locked_cut = child_keys()
        check("locked raster cut+paste leaves the IR unchanged",
              keys_after_locked_cut == locked_keys_before and "root/canvas:1" in keys_after_locked_cut,
              json.dumps(keys_after_locked_cut))

        # 6) editable button: copy/paste разрешены — ровно один новый слой с
        #    уникальным sourceKey; вставленная копия сразу выделена → cleanup Delete.
        bp = layer_point("root/button:1::text0")
        page.mouse.click(bp["x"], bp["y"])
        page.wait_for_timeout(120)
        page.keyboard.press("Control+c")
        page.wait_for_timeout(120)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(150)
        keys_after_paste = child_keys()
        pasted = [k for k in keys_after_paste if k not in locked_keys_before]
        check("editable button copy+paste inserts exactly one unique layer",
              len(pasted) == 1 and len(keys_after_paste) == len(locked_keys_before) + 1,
              json.dumps(keys_after_paste))
        if pasted:
            page.keyboard.press("Delete")
            page.wait_for_timeout(150)
        check("pasted copy is cleaned up", child_keys() == locked_keys_before, json.dumps(child_keys()))

        # 7) group/ungroup на sourceKey-слоях: группа с ключом root/group~*,
        #    дети сохраняют ключи и selectable identity, locked raster не
        #    включается; ungroup восстанавливает валидного родителя.
        # Клик через scrollIntoView: после цикла mobile→desktop канвас может
        # остаться проскролленным так, что крайний левый слой оказывается под
        # оверлейной панелью инструментов (elementFromPoint → rail button).
        def click_layer(sel: str, shift: bool = False) -> None:
            page.evaluate("""(sel) => {
              const el=document.querySelector('.fe-canvas-inner [data-ir-path="'+sel+'"]');
              if(el) el.scrollIntoView({block:'nearest', inline:'center'});
            }""", sel)
            page.wait_for_timeout(80)
            pt = layer_point(sel)
            if shift:
                page.keyboard.down("Shift")
            page.mouse.click(pt["x"], pt["y"])
            if shift:
                page.keyboard.up("Shift")
            page.wait_for_timeout(120)

        click_layer("root/button:1::text0")
        # div:1 — крайний левый слой, после цикла mobile→desktop он под
        # оверлейной панелью инструментов; второй сиблинг — input (центр канваса)
        click_layer("root/input:1::value", shift=True)
        page.keyboard.press("Control+g")
        page.wait_for_timeout(150)
        grouped = page.evaluate("""() => {
          const kids = window.DNAEditor.getIR().tree[0].children;
          const grp = kids.find(c => String(c.sourceKey||'').startsWith('root/group~'));
          const paths = [...document.querySelectorAll('.fe-canvas-inner [data-ir-path]')]
            .map(e => e.getAttribute('data-ir-path'));
          return {topKeys: kids.map(c => String(c.sourceKey||'')),
                  groupKey: grp ? String(grp.sourceKey) : null,
                  groupKids: grp ? grp.children.map(c => String(c.sourceKey||'')) : null,
                  uniquePaths: new Set(paths).size === paths.length,
                  chips: [...document.querySelectorAll('.geo-box.selected .geo-chip')].map(e => e.textContent),
                  hint: document.querySelector('.geo-overlay .geo-hint')?.textContent || null};
        }""")
        check("grouping two editable siblings creates one sourceKey group",
              bool(grouped["groupKey"]) and grouped["groupKids"] is not None and
              sorted(grouped["groupKids"]) == ["root/button:1", "root/input:1"] and
              len(grouped["topKeys"]) == 3, json.dumps(grouped))
        check("group keeps unique selectable identities and excludes the locked raster",
              grouped["uniquePaths"] and "root/canvas:1" in grouped["topKeys"] and
              grouped["groupKids"] is not None and "root/canvas:1" not in grouped["groupKids"],
              json.dumps(grouped))
        page.keyboard.press("Control+Shift+G")
        page.wait_for_timeout(150)
        ungrouped = page.evaluate("""() => {
          const kids = window.DNAEditor.getIR().tree[0].children;
          return {topKeys: kids.map(c => String(c.sourceKey||'')),
                  hasGroup: kids.some(c => String(c.sourceKey||'').startsWith('root/group~'))};
        }""")
        check("ungroup restores the children with a valid top-level parent",
              not ungrouped["hasGroup"] and sorted(ungrouped["topKeys"]) == sorted(locked_keys_before),
              json.dumps(ungrouped))

        # 8) locked exclusion: выделение locked raster + editable button →
        #    группировка отказывает (после фильтра locked остаётся < 2), IR
        #    не меняется. Первый клик по canvas схлопывает мультивыделение,
        #    оставшееся после ungroup.
        click_layer("root/canvas:1")
        click_layer("root/button:1::text0", shift=True)
        page.keyboard.press("Control+g")
        page.wait_for_timeout(150)
        keys_after_locked_group = child_keys()
        check("grouping with a locked raster layer is refused",
              sorted(keys_after_locked_group) == sorted(locked_keys_before) and
              not any(k.startswith("root/group~") for k in keys_after_locked_group),
              json.dumps(keys_after_locked_group))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SOURCE IMPORT EDITOR CHECKS PASSED")


if __name__ == "__main__":
    main()
