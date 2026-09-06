"""Opt-in live walkthrough generation and deterministic fixture export."""
import argparse
import json
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from video_story import build_pages, direct_story
from video_story_fixtures import pages_fixture, plan_fixture, PROMPT
from ir.timeline import validate, revert_change_set


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["codex", "claude", "fixture"], required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "results/video-stage2"
    output.mkdir(parents=True, exist_ok=True)
    before = build_pages(pages_fixture(), {"width": 960, "height": 640, "fps": 12, "duration": 8000})
    start = monotonic()
    if args.provider == "fixture":
        with patch("video_story.llm.chat", return_value=json.dumps(plan_fixture())):
            timeline, changes, meta = direct_story(before, PROMPT, "codex", "medium")
    else:
        timeline, changes, meta = direct_story(before, PROMPT, args.provider, "medium")
    assert validate(timeline) == []
    assert revert_change_set(timeline, changes) == before
    actions = timeline["story"]["actions"]
    assert {"type", "scroll", "click", "navigate"} <= {a["type"] for a in actions}
    assert any(a["type"] == "navigate" and a["toPageId"] == "page2" for a in actions)
    result = {"provider": args.provider, "seconds": round(monotonic() - start, 2), "prompt": PROMPT, "timeline": timeline, "changeSet": changes, **meta}
    (output / f"{args.provider}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"provider": args.provider, "actions": len(actions), "duration": timeline["composition"]["duration"], "seconds": result["seconds"]}), flush=True)


if __name__ == "__main__": main()
