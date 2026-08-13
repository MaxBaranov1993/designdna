from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import scraper  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def diff_px(a: dict, b: dict) -> float:
    return max(abs(a[k] - b[k]) for k in ("x", "y", "width", "height"))


def main() -> None:
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/source_import_header.html"
    original_validate = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        captured, _tokens = scraper.capture_block_irs(
            url,
            [{"name": "header", "label": "Header", "kind": "header", "selector": "#fixture-header"}],
            return_tokens=True,
            timeout_ms=5000,
        )
    finally:
        scraper.validate_public_url = original_validate

    ir = captured["#fixture-header"]["ir"]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            source = browser.new_page(viewport={"width": 1440, "height": 500})
            source.goto(url)
            source.wait_for_selector("#fixture-header")
            expected = source.evaluate(
                """() => {
                  const root = document.querySelector('#fixture-header').getBoundingClientRect();
                  const box = (selector) => {
                    const r = document.querySelector(selector).getBoundingClientRect();
                    return {x:Math.round(r.left-root.left), y:Math.round(r.top-root.top),
                      width:Math.round(r.width), height:Math.round(r.height)};
                  };
                  return {
                    brand: box('.brand'),
                    catalog: box('.catalog'),
                    search: box('.search'),
                    find: box('.search .find'),
                    links: box('.links'),
                    publish: box('.publish'),
                  };
                }"""
            )

            render = browser.new_page(viewport={"width": 1500, "height": 500})
            render.set_content('<div id="preview" style="width:1440px"></div>')
            render.add_script_tag(path=str(ROOT / "app" / "static" / "renderer.js"))
            render.evaluate("(ir) => window.IRRenderer.renderIR(document.querySelector('#preview'), ir)", ir)
            render.wait_for_selector('[data-ir-sec="0"]')
            actual = render.evaluate(
                """() => {
                  const root = document.querySelector('[data-ir-sec="0"]').getBoundingClientRect();
                  const all = [...document.querySelector('[data-ir-sec="0"]').children];
                  const box = (el) => {
                    const r = el.getBoundingClientRect();
                    return {x:Math.round(r.left-root.left), y:Math.round(r.top-root.top),
                      width:Math.round(r.width), height:Math.round(r.height)};
                  };
                  const byText = (text) => all.find(el => (el.textContent || '').includes(text));
                  return {
                    brand: box(all[0]),
                    catalog: box(byText('Catalog')),
                    search: box(all.find(el => (el.textContent || '').includes('Belgrade') && (el.textContent || '').includes('Find'))),
                    find: box([...document.querySelectorAll('[data-ir-path]')]
                      .filter(el => (el.textContent || '').trim() === 'Find')
                      .map(el => el.closest('a,button,[data-ir-frame],div'))
                      .find(el => el && el.getBoundingClientRect().width >= 60 && el.getBoundingClientRect().height >= 30)),
                    links: box(all.find(el => (el.textContent || '').includes('Journal') && (el.textContent || '').includes('EN'))),
                    publish: box(byText('Publish listing')),
                  };
                }"""
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    for key in ("brand", "catalog", "search", "find", "links", "publish"):
        check(f"{key} bbox within 3px", diff_px(expected[key], actual[key]) <= 3,
              json.dumps({"expected": expected[key], "actual": actual[key]}, ensure_ascii=False))

    section_frame = ir["tree"][0]["frame"]
    check("source-block keeps measured auto-layout",
          section_frame.get("layout") == "auto" and section_frame.get("direction") == "row" and section_frame.get("align") == "center",
          str(section_frame))

    # QA-контур парсера: предупреждения — только формата «flow drift -> free»,
    # а корневая раскладка здоровой фикстуры остаётся auto (без ложного пиннинга корня)
    qa = ir["meta"].get("qaWarnings") or []
    check("qa-пасс: предупреждения только в контрактном формате",
          all(isinstance(w, str) and w.startswith("qa: flow drift") for w in qa), str(qa))
    check("qa-пасс: корень фикстуры не запиннен", section_frame.get("layout") == "auto")

    # контракт захвата: у каждого узла сняты x/y (нужны QA-пассу для пиннинга)
    def all_frames(nodes):
        for n in nodes:
            yield n.get("frame") or {}
            yield from all_frames(n.get("children") or [])
    frames = list(all_frames(ir["tree"][0].get("children") or []))
    check("qa-контракт: все кадры несут числовые x/y",
          len(frames) > 0 and all(isinstance(f.get("x"), (int, float)) and isinstance(f.get("y"), (int, float)) for f in frames),
          f"кадров={len(frames)}")

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SOURCE IMPORT PIXEL CHECKS PASSED")


if __name__ == "__main__":
    main()
