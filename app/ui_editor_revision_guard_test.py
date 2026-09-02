"""Editor draft persistence, stale proposal rejection and CAS-save regression."""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def document(text: str, gap: int = 13) -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1200, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": "hero", "type": "hero", "variant": "default",
            "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": gap},
            "children": [{"type": "text", "text": text, "frame": {"width": 300, "height": 40}}],
        }],
    }


def main() -> None:
    original = document("Original")
    fixed = document("Original", 16)
    upstream = document("Upstream replacement", 24)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        page.route("**/api/quality-gate", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "passed": False,
                "violations": [{"rule": "grid-8", "path": "tree.0.frame.gap", "severity": "minor"}],
                "fixed_ir": fixed,
                "journal": [{"path": "tree.0.frame.gap", "from": 13, "to": 16}],
            }),
        ))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && window.DNAEditor")
        edit_id = page.evaluate("window.GraphDev.add('edit', 200, 120).id")
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {ir:v.ir})", {"id": edit_id, "ir": original})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')

        page.click('[data-act="quality-gate"]')
        page.wait_for_selector('[data-act="apply-quality-fixes"]')
        page.click('[data-act="apply-quality-fixes"]')
        page.wait_for_function("id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.[0]?.frame?.gap === 16", arg=edit_id)
        check("applied proposal is isolated in persisted draft", page.evaluate(
            "id => window.GraphDev.node(id).data._editorDraft.ir.tree[0].frame.gap === 16", edit_id))
        check("canonical IR is untouched before Save", page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].text === 'Original'", edit_id))

        page.wait_for_function(
            "() => { const saved = localStorage.getItem('designai-flow-pages-v1') || ''; return saved.includes('_editorDraft') && saved.includes('\"gap\":16'); }",
            timeout=3000,
        )
        saved = page.evaluate("localStorage.getItem('designai-flow-pages-v1') || ''")
        check("draft mutation changes Zustand identity and reaches autosave", "_editorDraft" in saved and '"gap":16' in saved)

        # An upstream replacement after open invalidates the editor's CAS base.
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {ir:v.ir})", {"id": edit_id, "ir": upstream})
        page.click('.dna-editor [data-act="save"]')
        check("CAS conflict keeps editor open", page.evaluate("window.DNAEditor.isOpen()"))
        check("CAS conflict preserves upstream IR", page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].text === 'Upstream replacement'", edit_id))
        check("CAS conflict preserves recoverable draft", page.evaluate(
            "id => window.GraphDev.node(id).data._editorDraft.ir.tree[0].frame.gap === 16", edit_id))

        page.click('.dna-editor [data-act="close"]')
        # защита черновика: редактор с правками спрашивает — закрываем без сохранения
        try:
            page.wait_for_selector('[data-act="close-discard"]', timeout=1000).click()
        except Exception:
            pass
        check("Cancel closes without restoring the opening snapshot", not page.evaluate("window.DNAEditor.isOpen()"))
        check("Cancel keeps upstream IR and only clears draft", page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].text === 'Upstream replacement' && !window.GraphDev.node(id).data._editorDraft", edit_id))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL EDITOR REVISION GUARD CHECKS PASSED")


if __name__ == "__main__":
    main()
