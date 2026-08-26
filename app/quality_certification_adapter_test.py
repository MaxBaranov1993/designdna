"""Focused tests for the production Quality Certified adapter."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_certification_adapter import EVIDENCE_GATES, certify_from_reports


def request():
    return {
        "designIrHash": "sha256:" + "a" * 64,
        "designSystem": {"id": "ds-live", "revision": 4, "contentHash": "sha256:" + "b" * 64},
        "assetHashes": ["sha256:" + "c" * 64],
        "qualityGate": {"passed": True, "violations": []},
        "visualJudge": {
            "score": 91, "verdict": "pass", "summary": "ignored current-style summary",
            "issues": [], "repair_instruction": "", "model_route": "Codex app-server / quality_judge",
        },
        "lockReport": {"checked": True, "violations": [], "preservedLocks": ["brand.colors"]},
        "scopeReport": {
            "checked": True, "violations": [], "structuralMutations": [],
            "changedFacets": ["spacing"], "styleOnly": True,
        },
        "viewportReport": {
            "required": ["desktop", "mobile"],
            "results": {
                "desktop": {"score": 90, "violations": [], "warnings": []},
                "mobile": {"score": 88, "violations": [], "warnings": []},
            },
        },
        "evidence": {gate: [] for gate in EVIDENCE_GATES},
    }


class AdapterTests(unittest.TestCase):
    def test_current_style_reports_certify_and_allow(self):
        result = certify_from_reports(request())
        self.assertEqual("certified", result["certificate"]["status"])
        self.assertEqual({
            "applyAllowed": True, "exportAllowed": True, "overrideRequired": False,
            "certificationStatus": "certified", "override": None,
        }, result["decision"])
        self.assertNotIn("ignored current-style summary", repr(result))
        self.assertNotIn("repair_instruction", repr(result))

    def test_missing_reports_and_gates_block_explicitly(self):
        for source in ("qualityGate", "visualJudge", "lockReport", "scopeReport", "viewportReport", "evidence"):
            with self.subTest(source=source):
                value = request()
                del value[source]
                result = certify_from_reports(value)
                self.assertEqual("blocked", result["certificate"]["status"])
                self.assertFalse(result["decision"]["applyAllowed"])
                self.assertTrue(any(i["code"].startswith("evidence.missing.") for i in result["certificate"]["blockingIssues"]))
        for gate in EVIDENCE_GATES:
            with self.subTest(gate=gate):
                value = request()
                del value["evidence"][gate]
                result = certify_from_reports(value)
                self.assertIn(
                    f"evidence.missing.evidence.{gate}",
                    [i["code"] for i in result["certificate"]["blockingIssues"]],
                )

    def test_lock_scope_and_style_only_errors_block(self):
        value = request()
        value["lockReport"]["violations"] = [{"code": "brand-lock", "path": "tree.0"}]
        value["scopeReport"]["violations"] = [{"code": "outside-selection", "path": "tree.1"}]
        value["scopeReport"]["structuralMutations"] = [{"code": "tree-changed"}]
        result = certify_from_reports(value)
        self.assertEqual("blocked", result["certificate"]["status"])
        codes = [i["code"] for i in result["certificate"]["blockingIssues"]]
        self.assertIn("lockReport.brand-lock", codes)
        self.assertIn("scopeReport.outside-selection", codes)
        self.assertIn("scopeReport.tree-changed", codes)

    def test_quality_gate_and_viewport_failures_map_without_raw_message(self):
        value = request()
        value["qualityGate"] = {"passed": False, "violations": [
            {"rule": "contrast", "path": "tokens.color.text", "message": "raw ignored"},
        ]}
        value["viewportReport"]["results"]["mobile"]["violations"] = [
            {"rule": "frame-overflow", "path": "tree.0.frame"},
        ]
        result = certify_from_reports(value)
        self.assertEqual("blocked", result["certificate"]["status"])
        codes = [i["code"] for i in result["certificate"]["blockingIssues"]]
        self.assertIn("qualityGate.contrast", codes)
        self.assertIn("viewportReport.frame-overflow", codes)
        self.assertEqual("blocked", result["certificate"]["viewports"]["mobile"]["status"])
        self.assertNotIn("raw ignored", repr(result))

    def test_minor_and_viewport_warning_remain_non_blocking(self):
        value = request()
        value["visualJudge"]["issues"] = [
            {"category": "consistency", "severity": "minor", "path": "tree.0", "problem": "ignored"},
        ]
        value["viewportReport"]["results"]["desktop"]["warnings"] = [{"rule": "soft-note"}]
        result = certify_from_reports(value)
        self.assertEqual("certified_with_warnings", result["certificate"]["status"])
        self.assertTrue(result["decision"]["applyAllowed"])
        self.assertTrue(result["decision"]["exportAllowed"])

    def test_override_is_auditable_and_does_not_mutate_certificate(self):
        value = request()
        value["lockReport"]["violations"] = [{"code": "approved-exception"}]
        value["override"] = {"requested": True, "reason": "Approved by the project owner for this export."}
        result = certify_from_reports(value)
        self.assertEqual("blocked", result["certificate"]["status"])
        self.assertTrue(result["decision"]["applyAllowed"])
        self.assertTrue(result["decision"]["exportAllowed"])
        self.assertFalse(result["decision"]["overrideRequired"])
        self.assertTrue(result["decision"]["override"]["used"])
        self.assertTrue(result["decision"]["override"]["reasonHash"].startswith("sha256:"))

    def test_bad_override_and_malformed_hash_cannot_bypass(self):
        value = request()
        value["lockReport"]["violations"] = [{"code": "blocked"}]
        value["override"] = {"requested": True, "reason": "x" * 501}
        result = certify_from_reports(value)
        self.assertFalse(result["decision"]["applyAllowed"])
        self.assertTrue(result["decision"]["overrideRequired"])

        value = request()
        value["designIrHash"] = "sha256:not-a-hash"
        value["override"] = {"requested": True, "reason": "Owner accepts this malformed input."}
        result = certify_from_reports(value)
        self.assertEqual("blocked", result["certificate"]["status"])
        self.assertFalse(result["decision"]["applyAllowed"])
        self.assertFalse(result["decision"]["override"]["used"])

    def test_hashes_are_bound_and_secrets_are_not_echoed(self):
        baseline = certify_from_reports(request())
        changed = request()
        changed["assetHashes"] = ["sha256:" + "d" * 64]
        changed = certify_from_reports(changed)
        self.assertNotEqual(baseline["certificate"]["inputHash"], changed["certificate"]["inputHash"])

        secret = request()
        secret["visualJudge"]["openaiApiKey"] = "private-value"
        result = certify_from_reports(secret)
        self.assertEqual("blocked", result["certificate"]["status"])
        self.assertNotIn("private-value", repr(result))
        self.assertFalse(result["decision"]["applyAllowed"])

        raw_asset = request()
        raw_asset["qualityGate"]["rawAssets"] = ["data:image/png;base64,private"]
        result = certify_from_reports(raw_asset)
        self.assertEqual("blocked", result["certificate"]["status"])
        self.assertNotIn("base64,private", repr(result))


if __name__ == "__main__":
    unittest.main()
