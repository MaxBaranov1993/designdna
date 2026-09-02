"""Browser regression for section-level incremental Design IR rendering.

Requires the local app server on http://127.0.0.1:8420.
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"project":null,"updated_at":null,"revision":"renderer-test"}',
        ))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}',
        ))

        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2_000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("server not ready")

        print("[RUN] waiting for renderer", flush=True)
        page.wait_for_function("window.IRRenderer && typeof window.IRRenderer.getRenderStats === 'function'")
        print("[RUN] exercising incremental renderer", flush=True)
        result = page.evaluate("""() => {
          const host = document.createElement('div');
          host.id = 'incremental-render-host';
          document.body.appendChild(host);
          const section = (id, text) => ({
            id, type: 'feature-grid', frame: { width: 'fill' },
            children: [{ type: 'card', children: [{ type: 'text', text }] }],
          });
          let ir = {
            version: '1.1',
            frame: { width: 1200, layout: 'auto', direction: 'column' },
            tokens: { color: { background: '#fff', text: '#111', primary: '#4f46e5' } },
            tree: [section('a', 'Alpha'), section('b', 'Beta'), section('c', 'Gamma')],
          };

          const firstStats = window.IRRenderer.renderIR(host, ir, { fit: false, viewport: 'desktop' });
          const root0 = host.querySelector('[class^="ir-"]');
          const section0 = root0.children[0];
          const firstCard = section0.querySelector('[data-ir-path="children.0"]');
          const section1 = root0.children[1];
          const changedCard = section1.querySelector('[data-ir-path="children.0"]');
          const changedText = section1.querySelector('[data-ir-path="children.0.children.0"]');
          const section2 = root0.children[2];

          ir = structuredClone(ir);
          ir.tree[1].children[0].children[0].text = 'Beta changed';
          const patchStats = window.IRRenderer.renderIR(host, ir, {
            fit: false, viewport: 'desktop', incremental: true,
          });
          const root1 = host.querySelector('[class^="ir-"]');
          const sectionPatch = {
            rootKept: root0 === root1,
            firstKept: section0 === root1.children[0],
            changedSectionKept: section1 === root1.children[1],
            unchangedParentKept: changedCard === root1.children[1].querySelector('[data-ir-path="children.0"]'),
            changedLeafReplaced: changedText !== root1.children[1].querySelector('[data-ir-path="children.0.children.0"]'),
            firstCardKept: firstCard === root1.children[0].querySelector('[data-ir-path="children.0"]'),
            thirdKept: section2 === root1.children[2],
            changedText: root1.children[1].textContent.includes('Beta changed'),
          };

          const beforeTokenSections = [...root1.children];
          ir = structuredClone(ir);
          ir.tokens.color.primary = '#dc2626';
          const tokenStats = window.IRRenderer.renderIR(host, ir, {
            fit: false, viewport: 'desktop', incremental: true,
          });
          const root2 = host.querySelector('[class^="ir-"]');
          const tokenSectionsKept = beforeTokenSections.every((node, index) => node === root2.children[index]);
          const tokenApplied = host.firstElementChild.textContent.includes('#dc2626');

          const sectionBeforeFrameOverride = root2.children[0];
          ir = structuredClone(ir);
          ir.tree[0]._frames = {
            'children.0': { x: 12, y: 18, width: 240, height: 96, absolute: true },
          };
          const frameStats = window.IRRenderer.renderIR(host, ir, {
            fit: false, viewport: 'desktop', incremental: true,
          });
          const root3 = host.querySelector('[class^="ir-"]');
          const frameSectionReplaced = sectionBeforeFrameOverride !== root3.children[0];
          const frameApplied = root3.children[0].querySelector('[data-ir-path^="children.0"]')
            .style.cssText.includes('position: absolute');

          const rootBeforeStructure = root3;
          ir = structuredClone(ir);
          ir.tree.push(section('d', 'Delta'));
          const structureStats = window.IRRenderer.renderIR(host, ir, {
            fit: false, viewport: 'desktop', incremental: true,
          });
          const rootAfterStructure = host.querySelector('[class^="ir-"]');

          const large = structuredClone(ir);
          large.frame = { width: 1440, height: 12000, layout: 'free' };
          large.tree = [{
            id: 'source-large', type: 'source-block', variant: 'dom-capture',
            frame: { width: 1440, height: 12000, layout: 'free' },
            children: Array.from({ length: 600 }, (_, index) => ({
              sourceKey: `layer:${index}`, type: 'card', role: 'source-layer',
              frame: { x: (index % 6) * 220, y: Math.floor(index / 6) * 110,
                       width: 200, height: 90, absolute: true },
              children: [{ sourceKey: `text:${index}`, type: 'text', text: `Item ${index}` }],
            })),
          }];
          window.IRRenderer.renderIR(host, large, { fit: false, viewport: 'desktop' });
          const samples = [];
          const largeSection = host.querySelector('[data-ir-sec="0"]');
          let working = large;
          let allLargePatchesWereLeaves = true;
          for (let i = 0; i < 30; i += 1) {
            working = structuredClone(working);
            working.tree[0].children[i].children[0].text = `Changed ${i}`;
            const stats = window.IRRenderer.renderIR(host, working, {
              fit: false, viewport: 'desktop', incremental: true,
            });
            allLargePatchesWereLeaves = allLargePatchesWereLeaves &&
              stats.mode === 'incremental' && stats.patchedNodes === 1 && stats.patchedSections === 0;
            samples.push(stats.durationMs);
          }
          samples.sort((a, b) => a - b);
          const p95 = samples[Math.ceil(samples.length * 0.95) - 1];
          const largeSectionKept = largeSection === host.querySelector('[data-ir-sec="0"]');

          host.remove();
          return {
            firstStats, patchStats, sectionPatch, tokenStats, tokenSectionsKept, tokenApplied,
            frameStats, frameSectionReplaced, frameApplied,
            structureStats, structureRootReplaced: rootBeforeStructure !== rootAfterStructure,
            p95, allLargePatchesWereLeaves, largeSectionKept,
          };
        }""")
        print("[RUN] browser assertions complete", flush=True)
        browser.close()

    assert result["firstStats"]["mode"] == "full", result
    assert result["patchStats"]["mode"] == "incremental", result
    assert result["patchStats"]["patchedSections"] == 0, result
    assert result["patchStats"]["patchedNodes"] == 1, result
    assert all(result["sectionPatch"].values()), result
    assert result["tokenStats"]["mode"] == "incremental", result
    assert result["tokenStats"]["patchedSections"] == 0, result
    assert result["tokenSectionsKept"] and result["tokenApplied"], result
    assert result["frameStats"]["mode"] == "incremental", result
    assert result["frameStats"]["patchedSections"] == 1, result
    assert result["frameSectionReplaced"] and result["frameApplied"], result
    assert result["structureStats"]["mode"] == "full", result
    assert result["structureRootReplaced"], result
    assert result["allLargePatchesWereLeaves"] and result["largeSectionKept"], result
    assert result["p95"] < 150, result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("ALL INCREMENTAL RENDERER CHECKS PASSED")


if __name__ == "__main__":
    main()
