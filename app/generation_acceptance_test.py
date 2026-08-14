"""Generator acceptance orchestration without network or Chromium."""
import sys
import time

import server
from generation_quality_test import sample_ir


def main():
    old_capture = server.visual_quality.capture_quality_bundle
    old_judge = server._visual_quality_scorecard
    old_repair = server._quality_repair
    try:
        server.visual_quality.capture_quality_bundle = lambda ir: {
            "montage": "data:image/png;base64,AA==",
            "metrics": {"desktop": {"overflowX": 0}, "mobile": {"overflowX": 0}},
        }
        server._visual_quality_scorecard = lambda ir, brief, bundle, issues, timeout: {
            "score": 91, "verdict": "pass", "summary": "rendered pass", "issues": [], "repair_instruction": ""
        }
        accepted, qa = server._run_generation_acceptance(
            sample_ir(), "три карточки товара с изображениями", 1, time.monotonic() + 20
        )
        assert accepted is not None, qa
        assert qa["score"] == 91 and qa["verdict"] == "pass", qa
        assert all(card.get("src") for card in accepted["tree"][0]["children"] if card.get("type") == "product-card")

        server._quality_repair = lambda *args, **kwargs: (None, "mock repair rejected")
        broken = sample_ir()
        broken["tree"][0]["children"] = broken["tree"][0]["children"][:2]
        rejected, rejected_qa = server._run_generation_acceptance(
            broken, "три карточки товара с изображениями", 2, time.monotonic() + 20
        )
        assert rejected is None
        assert rejected_qa["verdict"] == "rejected"
        assert any(issue.get("severity") == "critical" for issue in rejected_qa["issues"])
        print("ALL GENERATION ACCEPTANCE TESTS PASSED")
    finally:
        server.visual_quality.capture_quality_bundle = old_capture
        server._visual_quality_scorecard = old_judge
        server._quality_repair = old_repair


if __name__ == "__main__":
    main()
