"""Deterministic acceptance checks and asset materialization for generated IR."""
from __future__ import annotations

import base64
import copy
import html
import json
import os
import re
import urllib.request
from hashlib import sha256


CARD_WORDS = ("card", "cards", "карточ", "товар", "product", "marketplace", "каталог")
IMAGE_WORDS = ("image", "photo", "picture", "изображ", "фото", "картин")
NUMBER_WORDS = {
    "one": 1, "одна": 1, "один": 1,
    "two": 2, "две": 2, "два": 2,
    "three": 3, "три": 3,
    "four": 4, "четыре": 4,
    "five": 5, "пять": 5,
    "six": 6, "шесть": 6,
}


def _walk_elements(ir: dict):
    def walk(nodes, path):
        for index, node in enumerate(nodes or []):
            if not isinstance(node, dict):
                continue
            node_path = f"{path}.{index}"
            yield node_path, node
            yield from walk(node.get("children"), node_path + ".children")

    for section_index, section in enumerate(ir.get("tree") or []):
        if not isinstance(section, dict):
            continue
        yield f"tree.{section_index}", section
        yield from walk(section.get("children"), f"tree.{section_index}.children")


def _walk_asset_nodes(ir: dict):
    """Find element images plus semantic media objects such as hero.props.media."""
    seen: set[int] = set()

    def walk(value, path):
        if isinstance(value, dict):
            is_asset = value.get("type") in {"image", "product-card"} or "imagePrompt" in value or "src" in value and "alt" in value
            if is_asset and id(value) not in seen:
                seen.add(id(value))
                yield path, value
            for key, child in value.items():
                if key in {"responsive", "provenance"}:
                    continue
                yield from walk(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}.{index}" if path else str(index))

    yield from walk(ir.get("tree") if isinstance(ir, dict) else [], "tree")


def _expected_card_count(brief: str) -> int:
    low = (brief or "").lower()
    numeric = re.search(r"(?<!\d)([1-9])(?!\d)\s*(?:карточ|товар|card|product)", low)
    if numeric:
        return min(int(numeric.group(1)), 8)
    for word, count in NUMBER_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low) and any(token in low for token in CARD_WORDS):
            return count
    return 3 if any(token in low for token in CARD_WORDS) else 0


def semantic_validate(ir: dict, brief: str, require_resolved_assets: bool = True) -> list[dict]:
    """Validate meaning/completeness that JSON Schema cannot express."""
    issues: list[dict] = []
    tree = ir.get("tree") if isinstance(ir, dict) else None
    if not isinstance(tree, list) or not tree:
        return [{"code": "empty-document", "severity": "critical", "path": "tree",
                 "message": "Генерация не содержит ни одной секции."}]

    expected_cards = _expected_card_count(brief)
    cards: list[tuple[str, dict]] = []
    images: list[tuple[str, dict]] = list(_walk_asset_nodes(ir))
    for path, node in _walk_elements(ir):
        node_type = node.get("type")
        if node_type in {"card", "product-card"}:
            cards.append((path, node))
        if node_type == "feature-grid" and len(node.get("children") or []) < 2:
            issues.append({"code": "empty-grid", "severity": "critical", "path": path + ".children",
                           "message": "Сетка должна содержать минимум 2 содержательных элемента."})

    if expected_cards and len(cards) < expected_cards:
        issues.append({"code": "missing-cards", "severity": "critical", "path": "tree",
                       "message": f"Бриф требует минимум {expected_cards} карточки, найдено {len(cards)}."})

    low = (brief or "").lower()
    expects_images = expected_cards > 0 or any(token in low for token in IMAGE_WORDS)
    if expects_images and not images:
        issues.append({"code": "missing-images", "severity": "critical", "path": "tree",
                       "message": "Бриф требует изображения, но в IR нет ни одного image-ассета."})

    for path, card in cards:
        descendants = list(_walk_nested(card.get("children") or [], path + ".children"))
        title = str(card.get("title") or card.get("text") or "").strip()
        if not title:
            title = next((str(n.get("text") or n.get("title") or "").strip()
                          for _, n in descendants if n.get("type") == "heading"), "")
        if not title:
            issues.append({"code": "card-title", "severity": "major", "path": path,
                           "message": "Карточка не содержит понятного названия."})
        card_images = [(p, n) for p, n in descendants if n.get("type") == "image"]
        if card.get("type") == "product-card" and (card.get("src") or card.get("imagePrompt")):
            card_images.append((path, card))
        if expected_cards and not card_images:
            issues.append({"code": "card-image", "severity": "critical", "path": path,
                           "message": "Товарная карточка не содержит изображения."})

    if require_resolved_assets:
        for path, image in images:
            src = str(image.get("src") or "").strip()
            if not src:
                issues.append({"code": "unresolved-asset", "severity": "critical", "path": path + ".src",
                               "message": "imagePrompt не преобразован в готовый src."})
    return issues


def _walk_nested(nodes, path):
    for index, node in enumerate(nodes or []):
        if not isinstance(node, dict):
            continue
        node_path = f"{path}.{index}"
        yield node_path, node
        yield from _walk_nested(node.get("children"), node_path + ".children")


def _palette(ir: dict) -> tuple[str, str, str]:
    colors = ((ir.get("tokens") or {}).get("color") or {}) if isinstance(ir, dict) else {}
    primary = str(colors.get("primary") or "#335cff")
    surface = str(colors.get("surface") or "#f2f4f8")
    background = str(colors.get("background") or "#ffffff")
    valid = re.compile(r"^#[0-9a-fA-F]{6}$")
    return tuple(c if valid.match(c) else fallback for c, fallback in (
        (primary, "#335cff"), (surface, "#f2f4f8"), (background, "#ffffff")))


def _svg_asset(prompt: str, alt: str, colors: tuple[str, str, str]) -> str:
    """Create a stable local asset when no external image provider is configured."""
    primary, surface, background = colors
    digest = sha256((prompt or alt or "asset").encode("utf-8")).hexdigest()
    angle = 18 + int(digest[:2], 16) % 44
    x = 110 + int(digest[2:4], 16) % 180
    y = 72 + int(digest[4:6], 16) % 90
    label = html.escape((alt or prompt or "Visual asset").strip()[:72])
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900" role="img" aria-label="{label}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{surface}"/><stop offset="1" stop-color="{background}"/></linearGradient><filter id="s"><feDropShadow dx="0" dy="28" stdDeviation="35" flood-opacity=".18"/></filter></defs>
<rect width="1200" height="900" fill="url(#g)"/><circle cx="980" cy="120" r="230" fill="{primary}" opacity=".10"/>
<g transform="translate({x} {y}) rotate({angle} 390 310)" filter="url(#s)"><rect x="90" y="60" width="650" height="520" rx="76" fill="{primary}" opacity=".88"/><rect x="165" y="135" width="500" height="370" rx="48" fill="{background}" opacity=".94"/><circle cx="415" cy="320" r="112" fill="{primary}" opacity=".18"/></g>
<text x="72" y="826" font-family="Inter,Arial,sans-serif" font-size="30" font-weight="600" fill="{primary}">{label}</text></svg>'''
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _remote_asset(prompt: str, alt: str) -> str:
    """Resolve an image through an optional OpenAI-style or {src} asset endpoint."""
    endpoint = os.environ.get("DESIGNAI_ASSET_ENDPOINT", "").strip()
    if not endpoint:
        return ""
    payload = json.dumps({"prompt": prompt, "alt": alt, "width": 1200, "height": 900,
                          "size": "1200x900", "response_format": "b64_json"}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.environ.get("DESIGNAI_ASSET_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=float(os.environ.get("DESIGNAI_ASSET_TIMEOUT_S", "45"))) as response:
        result = json.loads(response.read().decode("utf-8"))
    candidate = result.get("src") or result.get("url")
    if not candidate and isinstance(result.get("data"), list) and result["data"]:
        item = result["data"][0] if isinstance(result["data"][0], dict) else {}
        candidate = item.get("url")
        if not candidate and item.get("b64_json"):
            candidate = "data:image/png;base64," + str(item["b64_json"])
    candidate = str(candidate or "").strip()
    return candidate if candidate.startswith(("https://", "data:image/")) else ""


def resolve_assets(ir: dict) -> tuple[dict, list[dict]]:
    """Materialize every generated imagePrompt into a stable editable src asset."""
    output = copy.deepcopy(ir)
    journal: list[dict] = []
    colors = _palette(output)
    for path, node in _walk_asset_nodes(output):
        if str(node.get("src") or "").strip():
            continue
        prompt = str(node.get("imagePrompt") or "").strip()
        alt = str(node.get("alt") or node.get("title") or "").strip()
        if not prompt:
            continue
        source = "generated-asset"
        try:
            src = _remote_asset(prompt, alt)
        except Exception:
            src = ""
        if not src:
            src = _svg_asset(prompt, alt, colors)
            source = "procedural-svg-fallback"
        node["src"] = src
        journal.append({"path": path + ".src", "source": source, "prompt": prompt[:160]})
    return output, journal


def dom_contract_audit(metrics: dict) -> list[dict]:
    """Turn browser-measured desktop/mobile facts into blocking QA issues."""
    issues: list[dict] = []
    for viewport, data in (metrics or {}).items():
        if data.get("overflowX", 0) > 1:
            issues.append({"code": "dom-overflow", "severity": "critical", "path": viewport,
                           "message": f"Горизонтальный overflow {data['overflowX']}px в {viewport}."})
        if data.get("emptySections"):
            issues.append({"code": "dom-empty-section", "severity": "critical", "path": viewport,
                           "message": f"Пустых секций в DOM: {data['emptySections']}."})
        if data.get("missingAlt"):
            issues.append({"code": "dom-image-alt", "severity": "major", "path": viewport,
                           "message": f"Изображений без alt: {data['missingAlt']}."})
        if data.get("missingDimensions"):
            issues.append({"code": "dom-image-size", "severity": "major", "path": viewport,
                           "message": f"Изображений без width/height: {data['missingDimensions']}."})
        if data.get("tinyText"):
            issues.append({"code": "dom-tiny-text", "severity": "major", "path": viewport,
                           "message": f"Текстовых элементов меньше 12px: {data['tinyText']}."})
        if data.get("smallTargets"):
            issues.append({"code": "dom-touch-target", "severity": "major", "path": viewport,
                           "message": f"Интерактивных целей меньше 24px: {data['smallTargets']}."})
        if data.get("missingFocus"):
            issues.append({"code": "dom-focus", "severity": "major", "path": viewport,
                           "message": f"Интерактивных элементов без видимого focus: {data['missingFocus']}."})
        if data.get("unlabeledForms"):
            issues.append({"code": "dom-form-label", "severity": "major", "path": viewport,
                           "message": f"Полей формы без label/aria-label: {data['unlabeledForms']}."})
        if data.get("placeholderAssets"):
            issues.append({"code": "dom-placeholder", "severity": "critical", "path": viewport,
                           "message": "В готовом рендере остались placeholder-ассеты."})
    return issues
