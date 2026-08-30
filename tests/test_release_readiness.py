from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_readiness import (  # noqa: E402
    ReadinessReport,
    RuleResult,
    aggregate_status,
    evaluate_release,
    write_readiness_reports,
    rights_and_review_rules,
)


def rule(rule_id: str, severity: str = "info", status: str = "pass") -> RuleResult:
    return RuleResult(rule_id, severity, status, "evidence", "fix it" if status == "fail" else "")


class ReleaseReadinessTests(unittest.TestCase):
    def test_blocker_wins_over_warning(self) -> None:
        results = [
            rule("media.geometry", "blocker", "pass"),
            rule("rights.status", "blocker", "fail"),
            rule("copy.review", "warning", "fail"),
        ]
        self.assertEqual(aggregate_status(results), "blocked")

    def test_warning_is_reported_without_blocker(self) -> None:
        self.assertEqual(aggregate_status([rule("copy.review", "warning", "fail")]), "warning")
        self.assertEqual(aggregate_status([rule("media.readable")]), "pass")

    def test_evaluate_release_combines_rule_groups(self) -> None:
        report = evaluate_release(
            "episode-001",
            [rule("media.readable")],
            [rule("copy.review", "warning", "fail")],
        )
        self.assertEqual(report.subject, "episode-001")
        self.assertEqual(report.status, "warning")
        self.assertEqual([item.rule_id for item in report.rules], ["media.readable", "copy.review"])

    def test_reports_share_stable_rule_ids_and_aggregate_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            reports = [
                ReadinessReport.from_results("episode-001", [rule("media.readable")]),
                ReadinessReport.from_results("episode-002", [rule("rights.status", "blocker", "fail")]),
            ]
            paths = write_readiness_reports(reports, output)

            payload = json.loads(paths.json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reports"][0]["rules"][0]["rule_id"], "media.readable")
            self.assertIn("media.readable", paths.markdown.read_text(encoding="utf-8"))
            self.assertIn("rights.status", paths.csv.read_text(encoding="utf-8"))
            self.assertEqual(list(output.glob("*.tmp")), [])

    def test_duplicate_rule_ids_are_rejected_per_subject(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate readiness rule"):
            ReadinessReport.from_results("episode-001", [rule("media.readable"), rule("media.readable")])

    def test_missing_required_ai_decision_blocks_readiness(self) -> None:
        context = {"rights_status": "owned", "disclosure": {"ai_content": True, "ai_label": None}}
        rules = {item.rule_id: item for item in rights_and_review_rules(context)}
        self.assertEqual((rules["disclosure.ai"].severity, rules["disclosure.ai"].status), ("blocker", "fail"))

    def test_planned_ai_label_and_missing_rights_evidence_are_warnings(self) -> None:
        context = {
            "rights_status": "owned",
            "rights_evidence": "",
            "disclosure": {"ai_content": True, "ai_label": "planned"},
        }
        rules = {item.rule_id: item for item in rights_and_review_rules(context)}
        self.assertEqual((rules["disclosure.ai"].severity, rules["disclosure.ai"].status), ("warning", "fail"))
        self.assertEqual((rules["rights.evidence"].severity, rules["rights.evidence"].status), ("warning", "fail"))

    def test_publication_requires_approval(self) -> None:
        context = {
            "rights_status": "licensed",
            "rights_evidence": "license-42",
            "disclosure": {"ai_content": False, "ai_label": "not-applicable"},
            "publishing": {"prepare": True, "approved": False},
        }
        rules = {item.rule_id: item for item in rights_and_review_rules(context)}
        self.assertEqual((rules["publishing.approval"].severity, rules["publishing.approval"].status), ("blocker", "fail"))


if __name__ == "__main__":
    unittest.main()
