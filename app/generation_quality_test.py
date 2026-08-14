"""Focused deterministic tests for generated-variant acceptance."""
import copy
import json
import sys

import generation_quality
import ir


FAILS = []


def check(name, condition, detail=""):
    print(("OK   " if condition else "FAIL ") + name + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILS.append(name)


def sample_ir():
    return {
        "version": "1.1",
        "meta": {"name": "Commerce QA"},
        "frame": {"width": 1440, "height": "hug"},
        "tokens": {
            "mode": "light",
            "color": {"primary": "#1f4ed8", "background": "#ffffff", "surface": "#f3f5f8",
                      "text": "#111827", "textMuted": "#4b5563", "border": "#d6dbe5"},
            "font": {"display": {"family": "Inter", "weight": 700},
                     "body": {"family": "Inter", "weight": 400}, "scale": "default"},
            "radius": {"card": "md", "button": "md", "input": "md"},
            "spacing": {"section": "md", "container": "default"}, "shadow": "sm",
        },
        "responsive": {"viewports": {"desktop": {"width": 1440, "height": 900},
                                      "tablet": {"width": 768, "height": 1024},
                                      "mobile": {"width": 390, "height": 844}}},
        "tree": [{
            "id": "products", "type": "feature-grid", "variant": "bento",
            "props": {"heading": "Товары для дома"},
            "children": [{"type": "heading", "text": "Товары для дома", "level": 1}] + [
                {"type": "product-card", "title": f"Товар {index}", "price": f"{index} 900 ₽",
                 "alt": f"Товар {index}", "imagePrompt": f"Предметная съёмка товара {index}",
                 "ctaText": "Купить", "gridSpan": {"columns": 2, "rows": 2} if index == 1 else {"columns": 1, "rows": 1}}
                for index in range(1, 4)
            ],
        }],
    }


def main():
    source = sample_ir()
    resolved, journal = generation_quality.resolve_assets(source)
    check("asset resolver does not mutate input", "src" not in source["tree"][0]["children"][1])
    check("all 3 imagePrompt values become src", len(journal) == 3 and all(
        str(card.get("src", "")).startswith("data:image/svg+xml;base64,")
        for card in resolved["tree"][0]["children"][1:]))
    errors = ir.format_errors(ir.validate_ir(resolved))
    check("resolved product-card IR passes schema", not errors, "; ".join(errors[:3]))
    issues = generation_quality.semantic_validate(resolved, "три карточки товара с картинками")
    check("complete commerce IR passes semantic validation", not issues, json.dumps(issues, ensure_ascii=False))

    incomplete = copy.deepcopy(resolved)
    incomplete["tree"][0]["children"] = incomplete["tree"][0]["children"][:2]
    issues = generation_quality.semantic_validate(incomplete, "три карточки товара с картинками")
    check("missing cards are blocking", any(i["code"] == "missing-cards" and i["severity"] == "critical" for i in issues))

    unresolved = copy.deepcopy(resolved)
    unresolved["tree"][0]["children"][1].pop("src")
    issues = generation_quality.semantic_validate(unresolved, "карточки товара", require_resolved_assets=True)
    check("unresolved imagePrompt is blocking", any(i["code"] == "unresolved-asset" for i in issues))

    dom_issues = generation_quality.dom_contract_audit({"mobile": {"overflowX": 18, "placeholderAssets": 1}})
    check("DOM overflow and placeholders are blocking", {i["code"] for i in dom_issues} == {"dom-overflow", "dom-placeholder"})

    if FAILS:
        print(f"FAILURES: {len(FAILS)}")
        sys.exit(1)
    print("ALL GENERATION QUALITY TESTS PASSED")


if __name__ == "__main__":
    main()
