#!/usr/bin/env python3
"""Pure release-readiness rules and deterministic report writers."""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal


RuleSeverity = Literal["blocker", "warning", "info"]
RuleStatus = Literal["pass", "fail", "not_applicable"]
ReportStatus = Literal["pass", "warning", "blocked"]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    severity: RuleSeverity
    status: RuleStatus
    evidence: str
    remediation: str

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("readiness rule ID cannot be empty")
        if self.severity not in {"blocker", "warning", "info"}:
            raise ValueError(f"invalid rule severity: {self.severity}")
        if self.status not in {"pass", "fail", "not_applicable"}:
            raise ValueError(f"invalid rule status: {self.status}")


@dataclass(frozen=True)
class ReadinessReport:
    subject: str
    status: ReportStatus
    rules: tuple[RuleResult, ...]

    @classmethod
    def from_results(cls, subject: str, rules: Iterable[RuleResult]) -> "ReadinessReport":
        items = tuple(rules)
        identifiers = [item.rule_id for item in items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"duplicate readiness rule for {subject}")
        return cls(subject=subject, status=aggregate_status(items), rules=items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "status": self.status,
            "rules": [asdict(rule) for rule in self.rules],
        }


@dataclass(frozen=True)
class ReportPaths:
    json: Path
    csv: Path
    markdown: Path


def aggregate_status(rules: Iterable[RuleResult]) -> ReportStatus:
    failed = [rule for rule in rules if rule.status == "fail"]
    if any(rule.severity == "blocker" for rule in failed):
        return "blocked"
    if failed:
        return "warning"
    return "pass"


def aggregate_report_status(reports: Iterable[ReadinessReport]) -> ReportStatus:
    statuses = [report.status for report in reports]
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    return "pass"


def evaluate_release(subject: str, *rule_groups: Iterable[RuleResult]) -> ReadinessReport:
    rules = [rule for group in rule_groups for rule in group]
    return ReadinessReport.from_results(subject, rules)


def _review_rule(rule_id: str, enabled: bool, status: str | None) -> RuleResult:
    approved = not enabled or status == "approved"
    return RuleResult(
        rule_id,
        "warning",
        "pass" if approved else "fail",
        f"enabled={enabled}; review_status={status or 'not-recorded'}",
        "review and approve the generated creative asset" if not approved else "",
    )


def rights_and_review_rules(context: dict[str, Any]) -> list[RuleResult]:
    rights_status = context.get("rights_status")
    valid_rights = rights_status in {"owned", "licensed", "client-provided", "authorized"}
    rights_evidence = str(context.get("rights_evidence", "")).strip()
    attribution = context.get("attribution", {})
    attribution_required = bool(attribution.get("required"))
    attribution_text = str(attribution.get("text", "")).strip()
    attribution_approved = bool(attribution.get("approved"))
    disclosure = context.get("disclosure", {})
    ai_content = disclosure.get("ai_content")
    ai_label = disclosure.get("ai_label")
    enhancements = context.get("enhancements", {})
    reviews = context.get("artifact_reviews", {})
    publishing = context.get("publishing", {})

    if not attribution_required:
        attribution_rule = RuleResult("attribution.required", "blocker", "pass", "attribution not required", "")
    elif not attribution_text:
        attribution_rule = RuleResult(
            "attribution.required",
            "blocker",
            "fail",
            "required attribution text is missing",
            "record and preserve the required attribution text",
        )
    elif not attribution_approved:
        attribution_rule = RuleResult(
            "attribution.required",
            "warning",
            "fail",
            f"attribution recorded but not approved: {attribution_text}",
            "confirm that the required attribution is present in the release package",
        )
    else:
        attribution_rule = RuleResult("attribution.required", "blocker", "pass", attribution_text, "")

    if ai_content is True and ai_label not in {"planned", "applied"}:
        disclosure_rule = RuleResult(
            "disclosure.ai",
            "blocker",
            "fail",
            "AI-generated content is declared but label status is missing",
            "record a planned or applied AI-content label",
        )
    elif ai_content is True and ai_label == "planned":
        disclosure_rule = RuleResult(
            "disclosure.ai",
            "warning",
            "fail",
            "AI-content label is planned but not yet applied",
            "apply and confirm the required AI-content label before publishing",
        )
    elif ai_content is True:
        disclosure_rule = RuleResult("disclosure.ai", "blocker", "pass", "AI-content label applied", "")
    elif ai_content is False:
        disclosure_rule = RuleResult("disclosure.ai", "blocker", "pass", "content declared as not AI-generated", "")
    else:
        disclosure_rule = RuleResult(
            "disclosure.ai",
            "blocker",
            "fail",
            "AI-content decision is not recorded",
            "record whether the content contains AI-generated material",
        )

    publish_requested = bool(publishing.get("prepare"))
    publish_approved = bool(publishing.get("approved"))
    return [
        RuleResult(
            "rights.status",
            "blocker",
            "pass" if valid_rights else "fail",
            f"rights_status={rights_status}",
            "record a supported rights status" if not valid_rights else "",
        ),
        RuleResult(
            "rights.evidence",
            "warning",
            "pass" if rights_evidence else "fail",
            rights_evidence or "no rights evidence reference recorded",
            "attach or reference the ownership, license, or client authorization record" if not rights_evidence else "",
        ),
        attribution_rule,
        disclosure_rule,
        _review_rule("cover.review", bool(enhancements.get("covers")), reviews.get("cover")),
        _review_rule("copy.review", bool(enhancements.get("copy") or enhancements.get("metadata")), reviews.get("copy")),
        _review_rule("narration.review", bool(enhancements.get("narration")), reviews.get("narration")),
        RuleResult(
            "publishing.approval",
            "blocker",
            "pass" if not publish_requested or publish_approved else "fail",
            f"prepare={publish_requested}; approved={publish_approved}",
            "obtain explicit publication approval" if publish_requested and not publish_approved else "",
        ),
    ]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def write_readiness_reports(reports: Iterable[ReadinessReport], output_dir: Path) -> ReportPaths:
    report_list = list(reports)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": aggregate_report_status(report_list),
        "reports": [report.to_dict() for report in report_list],
    }
    json_path = output_dir / "release_readiness.json"
    csv_path = output_dir / "release_readiness.csv"
    markdown_path = output_dir / "release_readiness.md"
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=("subject", "report_status", "rule_id", "severity", "status", "evidence", "remediation"),
    )
    writer.writeheader()
    for report in report_list:
        for item in report.rules:
            writer.writerow(
                {
                    "subject": report.subject,
                    "report_status": report.status,
                    **asdict(item),
                }
            )
    _atomic_write(csv_path, buffer.getvalue())

    lines = [
        "# Release Readiness",
        "",
        f"Aggregate status: **{payload['status']}**",
        "",
        "| Subject | Result | Rule | Severity | Rule status | Evidence | Remediation |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for report in report_list:
        for item in report.rules:
            lines.append(
                "| "
                + " | ".join(
                    _markdown_cell(str(value))
                    for value in (
                        report.subject,
                        report.status,
                        item.rule_id,
                        item.severity,
                        item.status,
                        item.evidence,
                        item.remediation,
                    )
                )
                + " |"
            )
    _atomic_write(markdown_path, "\n".join(lines) + "\n")
    return ReportPaths(json=json_path, csv=csv_path, markdown=markdown_path)


def reports_from_manifest(manifest: dict[str, Any]) -> list[ReadinessReport]:
    embedded = manifest.get("release_readiness", {}).get("reports", [])
    if embedded:
        reports = []
        for raw in embedded:
            rules = [RuleResult(**item) for item in raw.get("rules", [])]
            reports.append(ReadinessReport.from_results(str(raw.get("subject", "unknown")), rules))
        return reports

    reports = []
    for episode in manifest.get("episodes", []):
        number = episode.get("episode_number", "unknown")
        passed = episode.get("status") == "complete" and episode.get("qc_status") == "pass"
        reports.append(
            ReadinessReport.from_results(
                f"episode-{number}",
                [
                    RuleResult(
                        "media.processing",
                        "blocker",
                        "pass" if passed else "fail",
                        f"status={episode.get('status')}; qc={episode.get('qc_status')}",
                        "rebuild the episode and pass local QC" if not passed else "",
                    )
                ],
            )
        )
    return reports
