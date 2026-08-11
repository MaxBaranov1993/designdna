"""Focused checks for opt-in normalization and Tailwind projection."""
from __future__ import annotations

import copy
import sys

import ir

FAILS: list[str] = []


def check(name: str, condition: bool, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def fixture() -> dict:
    return ir.ensure_current({
        "version": "1.1",
        "frame": {"width": 1440, "height": 120, "layout": "auto", "direction": "column"},
        "responsive": {"viewports": {
            "desktop": {"width": 1440, "height": 120},
            "tablet": {"width": 768, "height": 100},
            "mobile": {"width": 390, "height": 88},
        }},
        "tokens": {
            "mode": "light",
            "color": {"primary":"#ff691d", "secondary":"#ff691d", "accent":"#ff691d", "background":"#ffffff", "surface":"#f5f5f7", "text":"#171717", "textMuted":"#666666", "border":"#e0e0e0"},
            "font": {"display":{"family":"Inter", "weight":700}, "body":{"family":"Inter", "weight":400}, "scale":"default"},
            "radius": {"card":"lg", "button":"md", "input":"md"},
            "spacing": {"section":"lg", "container":"default"},
            "shadow": "none",
            "primitives": {"colors":["#ff691d", "#ffffff", "#171717"], "fonts":[{"family":"Inter", "weight":400}], "fontSizes":[15], "radii":[7], "spacings":[15]},
            "semantic": {"primary":"#ff691d", "secondary":"#ff691d", "accent":"#ff691d", "background":"#ffffff", "surface":"#f5f5f7", "text":"#171717", "textMuted":"#666666", "border":"#e0e0e0", "buttonRadius":8, "cardRadius":16, "inputRadius":8, "sectionGap":96, "containerWidth":1200, "displayFont":{"family":"Inter", "weight":700}, "bodyFont":{"family":"Inter", "weight":400}},
        },
        "tree": [{
            "id": "source-header", "type": "source-block", "variant": "dom-capture", "props": {},
            "sourceKey": "source/header", "frame": {"width":"fill", "layout":"auto", "direction":"row", "gap":15, "padding":[15, 17]},
            "children": [{
                "type":"button", "sourceKey":"source/header/button", "text":"Continue",
                "frame":{"width":137, "height":41},
                "style":{"background":"#ff691d", "color":"#ffffff", "fontSize":15, "borderRadius":7},
                "styleBindings":{"background":{"property":"background", "token":"semantic.primary", "origin":"imported"}},
                "responsive": {"mobile": {
                    "visible": True,
                    "style":{"background":"#ff691d", "fontSize":13},
                    "styleBindings":{"background":{"property":"background", "token":"semantic.primary", "origin":"imported"}},
                }},
            }],
        }],
    })


def main():
    source = fixture()
    frozen = copy.deepcopy(source)
    exact = ir.project_tailwind(source, "exact")
    normalized_projection = ir.project_tailwind(source, "normalized")
    check("projection does not mutate IR", source == frozen)
    check("projection is deterministic", exact == ir.project_tailwind(source, "exact"))
    button = next(node for node in exact["nodes"] if node["sourceKey"] == "source/header/button")
    check("exact projection keeps arbitrary color", "bg-[#ff691d]" in button["classes"]["mobile"], str(button))
    normalized_button = next(node for node in normalized_projection["nodes"] if node["sourceKey"] == "source/header/button")
    check("normalized projection uses semantic utility", "bg-primary" in normalized_button["classes"]["mobile"], str(normalized_button))
    check("responsive projection emits md/lg classes", any(value.startswith("md:") for value in button["classes"]["tablet"]) and any(value.startswith("lg:") for value in button["classes"]["desktop"]))

    preview = ir.preview_normalization(source)
    check("normalize preview does not mutate input", source == frozen)
    check("normalize snaps spacing/font/radius", preview["visualDelta"]["changedProperties"] >= 4, str(preview["patch"]))
    check("normalize keeps arbitrary width exact", preview["normalizedIr"]["tree"][0]["children"][0]["frame"]["width"] == 137)
    check("normalized IR passes schema", not ir.format_errors(ir.validate_ir(preview["normalizedIr"])), str(ir.format_errors(ir.validate_ir(preview["normalizedIr"]))))

    tokens = copy.deepcopy(source["tokens"])
    tokens["semantic"]["primary"] = "#00aa00"
    applied = ir.apply_tokens(source, tokens)
    mobile = applied["tree"][0]["children"][0]["responsive"]["mobile"]
    check("responsive Style DNA binding is applied", mobile["style"]["background"] == "#00aa00", str(mobile))

    fluid = ir.materialize_responsive(source, 900)
    check("fluid width resolves tablet", fluid["meta"]["activeViewport"] == "tablet" and fluid["frame"]["width"] == 900, str(fluid.get("meta")))
    check("fluid materialization does not mutate IR", source == frozen)

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL STYLE PROJECTION CHECKS PASSED")


if __name__ == "__main__":
    main()
