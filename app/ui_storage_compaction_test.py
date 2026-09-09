"""Persistence compacts presentation screenshots and preserves canonical IR and blob evidence."""
from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE + "/flow")
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")

        result = page.evaluate("""() => {
          const heavy = 'data:image/jpeg;base64,' + 'A'.repeat(1800000);
          const evidenceRef = 'ddna://blobs/' + 'a'.repeat(64) + '.png';
          const editableSrc = 'data:image/svg+xml;base64,PHN2Zy8+';
          // Canonical IR (including evidence-looking fields) is a hash input.
          // Large disposable screenshots belong to Source presentation fields.
          const canonicalPreview = 'data:image/png;base64,Y2Fub25pY2Fs';
          const ir = {
            version:'1.0', sourcePreview:canonicalPreview,
            responsive:{viewports:{
              desktop:{width:1440,height:100,preview:canonicalPreview},
              tablet:{width:768,height:120,preview:canonicalPreview},
              mobile:{width:390,height:180,preview:canonicalPreview},
            }},
            tree:[{id:'imported-block',type:'source-block',variant:'dom-capture',preview:canonicalPreview,
              props:{sourcePreview:canonicalPreview},frame:{width:1440,height:100,layout:'auto',direction:'row'},
              children:[{type:'image',src:editableSrc,frame:{width:24,height:24}}]}],
          };
          const source=window.GraphDev.add('sourceimport',80,60);
          window.GraphDev.patchData(source.id,{blocks:[{name:'header',lit:true,ir,preview:heavy,
            previews:{desktop:heavy,tablet:evidenceRef,mobile:heavy}}]});
          const edit=window.GraphDev.add('edit',440,60);
          window.GraphDev.setIR(edit.id,ir);
          return {source:source.id,edit:edit.id,editableSrc,evidenceRef,ir};
        }""")
        page.wait_for_timeout(2200)

        stored = page.evaluate("""(evidenceRef) => {
          const raw=localStorage.getItem('designai-flow-pages-v1')||'';
          const payload=raw ? JSON.parse(raw) : null;
          const text=JSON.stringify(payload);
          return {
            bytes:raw.length,
            hasDataScreenshot:text.includes('data:image/jpeg;base64,'),
            hasEvidenceRef:text.includes(evidenceRef),
            hasEditableSrc:text.includes('data:image/svg+xml;base64,PHN2Zy8+'),
            legacy:localStorage.getItem('designai-flow-v1')||'',
            quotaToast:[...document.querySelectorAll('*')].some(el => /localStorage.*переполнен/i.test(el.textContent||'')),
          };
        }""", result["evidenceRef"])
        check("project save stays compact", stored["bytes"] < 100_000, json.dumps(stored))
        check("source screenshot references are not persisted", not stored["hasDataScreenshot"], json.dumps(stored))
        check("content-addressed Source evidence survives autosave", stored["hasEvidenceRef"], json.dumps(stored))
        check("editable image src is preserved", stored["hasEditableSrc"], json.dumps(stored))
        check("legacy graph key is no longer written", len(stored["legacy"]) == 0, json.dumps(stored))
        check("quota warning is not shown", not stored["quotaToast"], json.dumps(stored))
        local_ir = page.evaluate("""id => JSON.parse(localStorage.getItem('designai-flow-pages-v1'))
          .pages.flatMap(page => page.graph.nodes).find(node => node.id === id).data.ir""", result["edit"])
        check("localStorage preserves the complete canonical IR", local_ir == result["ir"])

        db_saved = page.evaluate("""async (evidenceRef) => {
          const resp = await fetch('/api/project/load', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({}),
          });
          const data = await resp.json();
          const text = JSON.stringify(data.project || {});
          return {
            hasDataScreenshot:text.includes('data:image/jpeg;base64,'),
            hasEvidenceRef:text.includes(evidenceRef),
            hasEditableSrc:text.includes('data:image/svg+xml;base64,PHN2Zy8+'),
          };
        }""", result["evidenceRef"])
        check("sqlite retains inline Source evidence when blob offload is unavailable",
              db_saved["hasDataScreenshot"], json.dumps(db_saved))
        check("sqlite keeps compact Source evidence handles", db_saved["hasEvidenceRef"], json.dumps(db_saved))
        check("sqlite project keeps editable IR", db_saved["hasEditableSrc"], json.dumps(db_saved))

        page.reload()
        page.wait_for_function("window.GraphDev")
        page.wait_for_function("id => window.GraphDev.node(id)?.data?.blocks?.[0]?.previews?.desktop?.startsWith('data:image/jpeg;base64,')", arg=result["source"])
        restored = page.evaluate("(id) => window.GraphDev.node(id)?.data?.ir?.tree?.[0]?.children?.[0]?.src", result["edit"])
        check("compact project restores editable IR", restored == result["editableSrc"], str(restored))
        check("reload preserves canonical evidence and geometry exactly",
              page.evaluate("id => window.GraphDev.node(id)?.data?.ir", result["edit"]) == result["ir"])
        restored_evidence = page.evaluate("(id) => window.GraphDev.node(id)?.data?.blocks?.[0]?.previews?.tablet", result["source"])
        check("compact project restores Source comparison evidence", restored_evidence == result["evidenceRef"], str(restored_evidence))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL STORAGE COMPACTION CHECKS PASSED")


if __name__ == "__main__":
    main()
