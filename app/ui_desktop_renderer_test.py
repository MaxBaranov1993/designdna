"""Read-only desktop smoke and incremental-render regression via Electron CDP.

Launch Electron with ``--remote-debugging-port=9333`` first, or point
``DESIGNDNA_CDP`` at another development or packaged instance. The test never
mutates or saves the user's graph; its renderer fixture is mounted in a
temporary DOM host and removed before the screenshot.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CDP = os.environ.get("DESIGNDNA_CDP", "http://127.0.0.1:9333")
SHOT = pathlib.Path(os.environ.get(
    "DESIGNDNA_DESKTOP_SHOT",
    pathlib.Path(__file__).resolve().parent.parent / "results" / "ui_desktop_incremental.png",
))


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP)
        assert browser.contexts, "Electron CDP has no browser context"
        pages = [page for context in browser.contexts for page in context.pages]
        page = next((candidate for candidate in pages if candidate.url.startswith("file:")), None)
        assert page is not None, f"Electron renderer page not found: {[candidate.url for candidate in pages]}"
        console_messages: list[dict[str, str]] = []
        page.on("console", lambda message: console_messages.append({
            "type": message.type,
            "text": message.text,
        }))
        page.wait_for_function("window.GraphDev && window.IRRenderer && window.designDNA")

        shell = page.evaluate("""async () => ({
          url: location.href,
          title: document.title,
          visibility: document.visibilityState,
          focused: document.hasFocus(),
          electron: navigator.userAgent.includes('Electron/'),
          bridge: Boolean(window.designDNA?.engine?.status),
          graphReady: Boolean(window.GraphDev?.state),
          rendererReady: Boolean(window.IRRenderer?.getRenderStats),
          engine: await window.designDNA.engine.status(),
        })""")

        incremental = page.evaluate("""() => {
          const host = document.createElement('div');
          host.style.cssText = 'position:fixed;left:-20000px;top:0;width:1440px;height:12000px';
          document.body.appendChild(host);
          const layer = (index) => ({
            sourceKey: `layer:${index}`, type: 'card', role: 'source-layer',
            frame: { x: (index % 6) * 220, y: Math.floor(index / 6) * 110,
                     width: 200, height: 90, absolute: true },
            children: [{ sourceKey: `text:${index}`, type: 'text', text: `Item ${index}` }],
          });
          let ir = {
            version: '1.1',
            frame: { width: 1440, height: 12000, layout: 'free' },
            tokens: { color: { background: '#fff', text: '#111', primary: '#4f46e5' } },
            tree: [{ id: 'source-large', type: 'source-block', variant: 'dom-capture',
              frame: { width: 1440, height: 12000, layout: 'free' },
              children: Array.from({ length: 600 }, (_, index) => layer(index)) }],
          };
          window.IRRenderer.renderIR(host, ir, { fit: false, viewport: 'desktop' });
          const section = host.querySelector('[data-ir-sec="0"]');
          const parent = section.querySelector('[data-ir-path="layer:17"]');
          const leaf = section.querySelector('[data-ir-path="text:17"]');
          const samples = [];
          let leafPatchOnly = true;
          for (let index = 0; index < 20; index += 1) {
            ir = structuredClone(ir);
            ir.tree[0].children[index + 17].children[0].text = `Desktop changed ${index}`;
            const stats = window.IRRenderer.renderIR(host, ir, {
              fit: false, viewport: 'desktop', incremental: true,
            });
            leafPatchOnly = leafPatchOnly && stats.mode === 'incremental' &&
              stats.patchedNodes === 1 && stats.patchedSections === 0;
            samples.push(stats.durationMs);
          }
          samples.sort((a, b) => a - b);
          const currentSection = host.querySelector('[data-ir-sec="0"]');
          const result = {
            sectionKept: section === currentSection,
            parentKept: parent === currentSection.querySelector('[data-ir-path="layer:17"]'),
            firstLeafReplaced: leaf !== currentSection.querySelector('[data-ir-path="text:17"]'),
            leafPatchOnly,
            p95: samples[Math.ceil(samples.length * 0.95) - 1],
          };
          host.remove();
          return result;
        }""")

        # Real keyboard input and modal lifecycle prove that the visible desktop
        # renderer event loop is responsive without changing project data.
        page.keyboard.press("Shift+/")
        page.locator("[data-hotkey-cheatsheet]").wait_for(state="visible")
        page.wait_for_timeout(250)
        dialog_shape = page.locator("[data-hotkey-cheatsheet]").evaluate("""dialog => ({
          sections: dialog.querySelectorAll('.hk-section').length,
          shortcuts: dialog.querySelectorAll('kbd').length,
          closeLabel: dialog.querySelector('.hk-close')?.getAttribute('aria-label')?.length || 0,
        })""")
        SHOT.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOT))
        page.keyboard.press("Escape")
        page.locator("[data-hotkey-cheatsheet]").wait_for(state="detached")
        page.wait_for_timeout(100)

    assert shell["url"].startswith("file:"), shell
    assert shell["visibility"] == "visible", shell
    assert shell["electron"] and shell["bridge"] and shell["graphReady"] and shell["rendererReady"], shell
    assert incremental["sectionKept"] and incremental["parentKept"], incremental
    assert incremental["firstLeafReplaced"] and incremental["leafPatchOnly"], incremental
    assert incremental["p95"] < 150, incremental
    assert not any("svelte-put/shortcut" in item["text"] for item in console_messages), console_messages
    # Some Windows CDP/Python combinations replace non-ASCII accessibility text
    # even though pixels and the UTF-8 bundle are correct. Assert the semantic
    # dialog structure here; the screenshot is the visual Cyrillic check.
    assert dialog_shape["sections"] == 2 and dialog_shape["shortcuts"] >= 20 and dialog_shape["closeLabel"] > 0, dialog_shape
    print(json.dumps({"shell": shell, "incremental": incremental,
                      "dialog": dialog_shape, "console": console_messages,
                      "screenshot": str(SHOT)}, ensure_ascii=False, indent=2))
    print("ALL DESKTOP RENDERER CHECKS PASSED")


if __name__ == "__main__":
    main()
