"""Deterministic Chromium runner for hybrid Interaction IR capture."""
from __future__ import annotations

import contextlib
import copy
from urllib.parse import urljoin, urlsplit

from ir.interaction import build
from urlguard import install_playwright_url_guard, validate_public_url

ALLOWED_ACTIONS = {"click", "type", "scroll", "navigate", "focus", "submit"}
MAX_ACTIONS = 50
MAX_SELECTOR_LENGTH = 500


def _same_origin(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    port_a = a.port or (443 if a.scheme == "https" else 80)
    port_b = b.port or (443 if b.scheme == "https" else 80)
    return (a.scheme, a.hostname, port_a) == (b.scheme, b.hostname, port_b)


def _node_index(base_ir: dict) -> dict[str, tuple[dict, str]]:
    result: dict[str, tuple[dict, str]] = {}

    def visit(value, path: str):
        if isinstance(value, dict):
            key = value.get("sourceKey")
            if isinstance(key, str) and key and key not in result:
                result[key] = (value, path)
            for name, child in value.items():
                if name in {"responsive", "style", "frame", "tokens", "meta"}:
                    continue
                escaped = str(name).replace("~", "~0").replace("/", "~1")
                visit(child, f"{path}/{escaped}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")

    visit(base_ir.get("tree", []), "/tree")
    return result


def _upsert(patch: list[dict], item: dict) -> list[dict]:
    return [entry for entry in patch if entry.get("path") != item["path"]] + [item]


def _state_patch(base_ir: dict, index: dict[str, tuple[dict, str]], source_key: str,
                 state: dict, current: list[dict]) -> list[dict]:
    target = index.get(source_key)
    if not target:
        return current
    node, path = target
    out = list(current)
    node_type = str(node.get("type") or "")
    if node_type == "input":
        value_child = next((
            (child, child_index) for child_index, child in enumerate(node.get("children") or [])
            if isinstance(child, dict) and child.get("type") == "text"
        ), None)
        if value_child:
            child, child_index = value_child
            op = "replace" if "text" in child else "add"
            out = _upsert(out, {"op": op, "path": f"{path}/children/{child_index}/text", "value": state.get("value", "")})
        else:
            prop = "value"
            op = "replace" if prop in node else "add"
            out = _upsert(out, {"op": op, "path": f"{path}/{prop}", "value": state.get("value", "")})
    elif node_type in {"text", "heading", "button"} and isinstance(state.get("text"), str):
        prop = "text"
        op = "replace" if prop in node else "add"
        out = _upsert(out, {"op": op, "path": f"{path}/{prop}", "value": state["text"][:1000]})
    return out


def capture_live_flow(base_ir: dict, url: str, actions: list[dict], viewport: str = "desktop",
                      timeout_ms: int = 20000) -> dict:
    """Replay transient actions in Chromium and return sanitized Interaction IR."""
    from playwright.sync_api import sync_playwright

    safe_url = validate_public_url(url)
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"interaction capture is limited to {MAX_ACTIONS} actions")
    viewport_sizes = {
        "desktop": {"width": 1440, "height": 900},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 390, "height": 844},
    }
    viewport = viewport if viewport in viewport_sizes else "desktop"
    normalized: list[dict] = []
    for raw in actions:
        action_type = str(raw.get("type") or "").lower()
        if action_type not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported live action: {action_type}")
        selector = str(raw.get("selector") or "").strip()
        if action_type not in {"scroll", "navigate"} and not selector:
            raise ValueError(f"{action_type} action requires a selector")
        if len(selector) > MAX_SELECTOR_LENGTH:
            raise ValueError("interaction selector is too long")
        normalized.append({
            "type": action_type,
            "selector": selector,
            "targetSourceKey": str(raw.get("targetSourceKey") or selector or "document-root")[:300],
            "value": raw.get("value", ""),
            "y": int(raw.get("y") or 0),
            "url": str(raw.get("url") or ""),
        })

    index = _node_index(base_ir)
    scenes = [{"id": "scene-0", "viewport": viewport, "patch": []}]
    events = []
    cumulative_patch: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=viewport_sizes[viewport], service_workers="block",
        )
        install_playwright_url_guard(
            context,
            validate_public_url,
            allow_document_url=lambda candidate: _same_origin(safe_url, candidate),
        )
        page = context.new_page()
        try:
            page.goto(safe_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(500)
            if not _same_origin(safe_url, page.url):
                raise ValueError("live capture left the approved origin")
            page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}html{scroll-behavior:auto!important}")
            for step, action in enumerate(normalized, start=1):
                action_type = action["type"]
                locator = page.locator(action["selector"]).first if action["selector"] else None
                if locator is not None:
                    locator.wait_for(state="attached", timeout=min(timeout_ms, 8000))
                if action_type == "click":
                    locator.click()
                elif action_type == "type":
                    locator.fill(str(action["value"]))
                elif action_type == "focus":
                    locator.focus()
                elif action_type == "submit":
                    locator.evaluate("el => el.requestSubmit ? el.requestSubmit() : el.submit()")
                elif action_type == "scroll":
                    page.evaluate("y => window.scrollTo(0, y)", action["y"])
                elif action_type == "navigate":
                    destination = validate_public_url(urljoin(page.url, action["url"]))
                    if not _same_origin(safe_url, destination):
                        raise ValueError("cross-origin navigation is not allowed during live capture")
                    page.goto(destination, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(250)
                if not _same_origin(safe_url, page.url):
                    raise ValueError("live capture left the approved origin")

                state = {}
                if locator is not None and action_type not in {"click", "submit"}:
                    state = locator.evaluate("""el => ({
                      value: 'value' in el ? String(el.value || '') : '',
                      text: String(el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                      checked: 'checked' in el ? Boolean(el.checked) : null
                    })""")
                    cumulative_patch = _state_patch(base_ir, index, action["targetSourceKey"], state, cumulative_patch)
                scene_id = f"scene-{step}"
                scenes.append({"id": scene_id, "viewport": viewport, "patch": copy.deepcopy(cumulative_patch)})
                payload = {}
                if action_type == "type": payload["value"] = action["value"]
                if action_type == "scroll": payload["y"] = action["y"]
                if action_type == "navigate": payload["url"] = page.url
                events.append({
                    "id": f"event-{step}", "time": (step - 1) * 500,
                    "type": action_type, "targetSourceKey": action["targetSourceKey"],
                    "payload": payload, "resultingSceneId": scene_id,
                })
        finally:
            with contextlib.suppress(Exception):
                context.close()
            browser.close()

    return build(base_ir, {"kind": "hybrid", "url": safe_url}, scenes, events, {})
