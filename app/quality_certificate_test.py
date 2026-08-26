"""Focused acceptance tests for deterministic Quality Certified decisions."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_certificate import ENGINE_VERSION, certify_quality


GLOBAL_GATES = (
    "schemaErrors", "lockViolations", "outOfScopeMutations", "lostSourceKeys",
    "lostComponentIdentities", "hierarchyErrors", "overflow", "clipping",
    "collisions", "brokenAssets", "placeholderContent", "forbiddenTokens",
    "forbiddenComponents", "forbiddenFonts", "forbiddenColors", "contrastBlockers",
    "accessibilityBlockers", "structuralMutations",
)
VIEWPORT_GATES = ("overflow", "clipping", "collisions", "contrastBlockers", "accessibilityBlockers")


def issue(code="test.blocker"):
    return {"code": code, "message": "Deterministic test issue.", "path": "tree.0"}


def warning(code="test.warning"):
    return {
        "code": code,
        "message": "Explicitly non-blocking test warning.",
        "blocking": False,
        "severity": "warning",
        "path": "tree.0",
    }


def request(score=90, critical=80):
    empty_global = {name: [] for name in GLOBAL_GATES}
    empty_viewport = {name: [] for name in VIEWPORT_GATES}
    return {
        "designIrHash": "sha256:" + "a" * 64,
        "designSystem": {
            "id": "ds-product",
            "revision": 7,
            "contentHash": "sha256:" + "b" * 64,
        },
        "assetHashes": ["sha256:" + "d" * 64, "sha256:" + "c" * 64],
        "report": {
            "score": score,
            "criticalSubscores": {
                "composition": critical,
                "visualHierarchy": 91,
                "responsiveComposition": 88,
            },
            "requiredViewports": ["mobile", "desktop"],
            "viewports": {
                "desktop": {"score": 91, "checks": copy.deepcopy(empty_viewport), "warnings": []},
                "mobile": {"score": 88, "checks": copy.deepcopy(empty_viewport), "warnings": []},
            },
            "checks": empty_global,
            "warnings": [],
            "preservedLocks": ["typography", "brand.colors"],
            "changedFacets": ["spacing"],
            "styleOnly": True,
        },
    }


class QualityCertificateTests(unittest.TestCase):
    def test_certified_positive_and_contract(self):
        result = certify_quality(request())
        self.assertEqual("certified", result["status"])
        self.assertEqual(90, result["score"])
        self.assertEqual([], result["blockingIssues"])
        self.assertEqual(ENGINE_VERSION, result["engineVersion"])
        self.assertTrue(result["certificateHash"].startswith("sha256:"))
        self.assertTrue(result["inputHash"].startswith("sha256:"))
        self.assertEqual(
            {"status", "score", "blockingIssues", "warnings", "preservedLocks",
             "changedFacets", "viewports", "certificateHash", "inputHash", "engineVersion"},
            set(result),
        )

    def test_explicit_warning_yields_certified_with_warnings(self):
        value = request()
        without_optional_path = warning()
        del without_optional_path["path"]
        value["report"]["warnings"] = [without_optional_path]
        result = certify_quality(value)
        self.assertEqual("certified_with_warnings", result["status"])
        self.assertEqual("test.warning", result["warnings"][0]["code"])

    def test_every_required_gate_blocks(self):
        for gate in GLOBAL_GATES:
            with self.subTest(gate=gate):
                value = request()
                value["report"]["checks"][gate] = [issue(gate)]
                result = certify_quality(value)
                self.assertEqual("blocked", result["status"])
                self.assertIn(gate, [item["code"] for item in result["blockingIssues"]])

    def test_viewport_blockers_and_missing_required_viewport_block(self):
        value = request()
        value["report"]["viewports"]["mobile"]["checks"]["clipping"] = [issue("mobile.clipping")]
        result = certify_quality(value)
        self.assertEqual("blocked", result["status"])
        self.assertEqual("blocked", result["viewports"]["mobile"]["status"])

        value = request()
        del value["report"]["viewports"]["mobile"]
        result = certify_quality(value)
        self.assertEqual("blocked", result["status"])
        self.assertIn("viewport.missing", [item["code"] for item in result["blockingIssues"]])

    def test_structural_mutation_blocks_only_during_style_only(self):
        value = request()
        value["report"]["checks"]["structuralMutations"] = [issue("structure.changed")]
        self.assertEqual("blocked", certify_quality(value)["status"])
        value["report"]["styleOnly"] = False
        self.assertEqual("certified", certify_quality(value)["status"])

    def test_malformed_and_sensitive_input_fail_closed_without_retention(self):
        cases = [None, {}, request() | {"unknown": True}]
        invalid_warning = request()
        invalid_warning["report"]["warnings"] = [{**warning(), "blocking": True}]
        cases.append(invalid_warning)
        secret = request()
        secret["report"]["prompt"] = "private raw prompt"
        cases.append(secret)
        for alias in ("openaiApiKey", "accessToken", "refreshToken"):
            secret_alias = request()
            secret_alias["report"][alias] = "private credential"
            cases.append(secret_alias)
        oversized = request()
        oversized["designIrHash"] = "x" * 20_000
        cases.append(oversized)
        for value in cases:
            with self.subTest(value_type=type(value).__name__):
                result = certify_quality(value)
                self.assertEqual("blocked", result["status"])
                self.assertEqual("input.malformed", result["blockingIssues"][0]["code"])
                self.assertNotIn("private raw prompt", repr(result))
                self.assertNotIn("prompt", result)

    def test_hashes_require_normalized_lowercase_sha256(self):
        invalid_values = (
            ("designIrHash", None, "sha256:short"),
            ("designIrHash", None, "sha256:" + "A" * 64),
            ("designSystem", "contentHash", "b" * 64),
            ("assetHashes", None, ["sha256:" + "g" * 64]),
        )
        for root, child, invalid in invalid_values:
            with self.subTest(root=root, child=child, invalid=invalid):
                value = request()
                if child is None:
                    value[root] = invalid
                else:
                    value[root][child] = invalid
                result = certify_quality(value)
                self.assertEqual("blocked", result["status"])
                self.assertEqual("input.malformed", result["blockingIssues"][0]["code"])

    def test_object_key_and_set_order_do_not_change_hashes(self):
        first = request()
        second = copy.deepcopy(first)
        second = dict(reversed(list(second.items())))
        second["designSystem"] = dict(reversed(list(second["designSystem"].items())))
        second["assetHashes"].reverse()
        second["report"]["requiredViewports"].reverse()
        second["report"]["preservedLocks"].reverse()
        result_a = certify_quality(first)
        result_b = certify_quality(second)
        self.assertEqual(result_a["inputHash"], result_b["inputHash"])
        self.assertEqual(result_a["certificateHash"], result_b["certificateHash"])

    def test_material_binding_changes_input_and_certificate_hash(self):
        baseline = certify_quality(request())
        changes = []
        for path, replacement in (
            (("designIrHash",), "sha256:" + "9" * 64),
            (("designSystem", "revision"), 8),
            (("designSystem", "contentHash"), "sha256:" + "e" * 64),
            (("assetHashes",), ["sha256:" + "f" * 64]),
        ):
            value = request()
            if len(path) == 1:
                value[path[0]] = replacement
            else:
                value[path[0]][path[1]] = replacement
            changes.append(certify_quality(value))
        for changed in changes:
            self.assertNotEqual(baseline["inputHash"], changed["inputHash"])
            self.assertNotEqual(baseline["certificateHash"], changed["certificateHash"])

    def test_score_and_critical_boundary_thresholds(self):
        self.assertEqual("certified", certify_quality(request(score=85, critical=75))["status"])
        low_score = certify_quality(request(score=84.999, critical=75))
        self.assertEqual("blocked", low_score["status"])
        self.assertIn("score.below_threshold", [item["code"] for item in low_score["blockingIssues"]])
        low_critical = certify_quality(request(score=85, critical=74.999))
        self.assertEqual("blocked", low_critical["status"])
        self.assertIn(
            "critical_subscore.below_threshold",
            [item["code"] for item in low_critical["blockingIssues"]],
        )

    def test_required_viewport_score_boundary(self):
        at_boundary = request()
        at_boundary["report"]["viewports"]["mobile"]["score"] = 75
        self.assertEqual("certified", certify_quality(at_boundary)["status"])

        below_boundary = request()
        below_boundary["report"]["viewports"]["mobile"]["score"] = 74.999
        result = certify_quality(below_boundary)
        self.assertEqual("blocked", result["status"])
        self.assertIn("viewport.score_below_threshold", [item["code"] for item in result["blockingIssues"]])


if __name__ == "__main__":
    unittest.main()
