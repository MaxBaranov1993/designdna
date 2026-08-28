"""Сквозная проверка цикла починки: настоящий браузер, настоящий замер.

Юнит-тесты доказывают логику на подставных функциях. Здесь проверяется то,
что они проверить не могут: связка с реальным рендером и то, что судья —
пиксельное сходство — действительно различает хорошую правку и плохую.

Роль модели играет скрипт: качество её диагнозов зависит от провайдера и в
тесте не проверяется. Проверяется КОНТУР — что верная правка измеримо
улучшает картинку и принимается, а вредная измеримо ухудшает и откатывается.
"""
from __future__ import annotations

import copy
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import fidelity_harness  # noqa: E402
import fidelity_repair  # noqa: E402
import scraper  # noqa: E402
from scraper import capture_block_irs  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK " if ok else "FAIL ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def capture() -> dict:
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(fixture_dir)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original = scraper.validate_public_url
    scraper.validate_public_url = lambda _url: None
    try:
        live, _tokens = capture_block_irs(
            f"http://127.0.0.1:{server.server_port}/source_import_accent_text.html",
            [{"name": "hero", "label": "Hero", "kind": "section", "selector": "#accent-hero"}],
            return_tokens=True, timeout_ms=30000)
    finally:
        scraper.validate_public_url = original
        server.shutdown()
        server.server_close()
    return live["#accent-hero"]


def find_node(ir: dict, needle: str) -> dict | None:
    for node in fidelity_repair._walk(ir.get("tree") or []):
        if needle in str(node.get("text") or ""):
            return node
    return None


def main() -> None:
    captured = capture()
    if "ir" not in captured:
        print("FAIL capture:", captured.get("error"))
        sys.exit(1)
    ir = captured["ir"]
    reference = captured.get("preview") or ""
    size = captured.get("size") or {}
    width = int(size.get("width") or captured.get("width") or 1440)
    height = int(size.get("height") or captured.get("height") or 900)
    if not reference.startswith("data:"):
        print("FAIL: capture returned no reference screenshot")
        sys.exit(1)
    reference_png = fidelity_harness._decode_data_url(reference)

    glow = find_node(ir, "finds your buyers")
    check("accent node is present in the capture", glow is not None)
    if glow is None:
        sys.exit(1)
    original_shadow = (glow.get("style") or {}).get("textShadow")
    check("capture carries the glow to begin with", bool(original_shadow), json.dumps(glow.get("style")))

    # Имитируем ровно ту потерю, которую цикл и должен чинить: канал был в
    # источнике, но не доехал в IR.
    damaged = copy.deepcopy(ir)
    damaged_glow = find_node(damaged, "finds your buyers")
    damaged_glow["style"].pop("textShadow", None)
    source_key = str(damaged_glow.get("sourceKey") or "")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            measure = fidelity_repair.make_browser_measurer(
                page, reference_png, "desktop", width, height)

            intact = measure(ir)
            broken = measure(damaged)
            check("the real judge produces a similarity score",
                  intact is not None and broken is not None, f"{intact} / {broken}")
            check("losing the glow measurably hurts similarity",
                  broken is not None and intact is not None and broken < intact,
                  f"intact={intact} damaged={broken}")

            # «Модель» ставит верный диагноз: канал потерян, вернуть его.
            correct = json.dumps({"hypothesis": "accent glow is missing", "operations": [
                {"op": "restore-style", "sourceKey": source_key,
                 "property": "textShadow", "value": str(original_shadow)}]})
            report_viewport = {"reference_size": [width, height],
                               "region_diffs": [{"region": [row, col], "mismatch_pct": 40.0}
                                                for row in range(3) for col in range(8)]}
            good = fidelity_repair.repair_block(
                damaged, block_name="hero", viewport="desktop",
                report_viewport=report_viewport, measure=measure,
                propose=lambda _m: correct, max_regions=6)
            check("a correct repair is accepted by the real measurement",
                  len(good["applied"]) >= 1 and good["gain"] > 0,
                  json.dumps({"gain": good["gain"], "applied": len(good["applied"]),
                              "rejected": len(good["rejected"])}))
            repaired_glow = find_node(good["ir"], "finds your buyers")
            check("the restored channel is in the repaired IR",
                  (repaired_glow.get("style") or {}).get("textShadow") == original_shadow)

            # Вредная правка: измеримо портит картинку — должна быть отклонена.
            harmful = json.dumps({"operations": [
                {"op": "restore-style", "sourceKey": source_key, "property": "opacity", "value": 0.05}]})
            bad = fidelity_repair.repair_block(
                ir, block_name="hero", viewport="desktop",
                report_viewport=report_viewport, measure=measure,
                propose=lambda _m: harmful, max_regions=2)
            check("a harmful repair is rejected by the real measurement",
                  bad["applied"] == [] and len(bad["rejected"]) >= 1,
                  json.dumps({"applied": len(bad["applied"]), "rejected": len(bad["rejected"])}))
            # opacity присутствует в каждом захвате (styleOf всегда его пишет),
            # поэтому проверяем не отсутствие ключа, а что вредное значение не применилось.
            check("the rejected repair left the IR untouched",
                  (find_node(bad["ir"], "finds your buyers").get("style") or {}).get("opacity") != 0.05)
        finally:
            browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL FIDELITY REPAIR LIVE CHECKS PASSED")


if __name__ == "__main__":
    main()
