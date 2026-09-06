"""Opt-in live account smoke; never collected by pytest and never submits website forms."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from time import monotonic

from ir.timeline import build, revert_change_set, validate
from timeline_director import direct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["codex", "claude"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ir = {"version": "1.1", "frame": {"width": 1440}, "tree": [
        {"id": "hero", "sourceKey": "hero", "type": "hero", "variant": "center",
         "props": {"heading": "Разместите своё объявление", "subheading": "Расскажите о товаре и найдите покупателя", "cta": "Разместить объявление"}},
    ]}
    timeline = build(ir, {"duration": 8000})
    before = copy.deepcopy(timeline)
    prompt = "Плавно приблизь первый блок в начале ролика. Больше ничего не меняй."
    started = monotonic()
    edited, changes, meta = direct(timeline, prompt, provider=args.provider, effort="medium", require_llm=True)
    assert timeline == before, "AI modified the input"
    assert meta["planSource"] == "llm"
    assert validate(edited) == []
    reverted = revert_change_set(edited, changes)
    assert reverted["layers"] == before["layers"]
    result = {"provider": args.provider, "seconds": round(monotonic() - started, 2),
              "ir": ir, "before": before, "timeline": edited, "changeSet": changes,
              "prompt": prompt, **meta}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"provider": args.provider, "seconds": result["seconds"], "planSource": meta["planSource"], "operations": len(changes["operations"]), "output": str(args.output)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
