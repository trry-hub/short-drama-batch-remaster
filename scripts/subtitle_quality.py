#!/usr/bin/env python3
"""Structured subtitle timing and text-quality checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import srt

from release_readiness import RuleResult


@dataclass(frozen=True)
class SubtitleFinding:
    code: str
    severity: str
    cue_index: int | None
    evidence: str
    remediation: str


RULES = {
    "subtitle.parse": ("blocker", "repair the subtitle file so it can be parsed"),
    "subtitle.non_monotonic": ("blocker", "sort or retime subtitle cues"),
    "subtitle.overlap": ("blocker", "remove overlapping subtitle cue timing"),
    "subtitle.out_of_range": ("blocker", "keep subtitle cues inside the video duration"),
    "subtitle.empty": ("warning", "add text or remove the empty cue"),
    "subtitle.line_length": ("warning", "wrap the subtitle into shorter readable lines"),
    "subtitle.too_short": ("warning", "extend the cue duration for readability"),
    "subtitle.uncertain": ("warning", "review the uncertain transcription against the audio"),
    "subtitle.review_term": ("warning", "review the configured term in context"),
}


def _finding(code: str, cue_index: int | None, evidence: str) -> SubtitleFinding:
    severity, remediation = RULES[code]
    return SubtitleFinding(code, severity, cue_index, evidence, remediation)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def inspect_subtitles(path: Path, duration_s: float, review_terms: Iterable[str] = ()) -> list[SubtitleFinding]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        cues = list(srt.parse(text, ignore_errors=False))
    except (OSError, srt.SRTParseError, ValueError) as exc:
        return [_finding("subtitle.parse", None, str(exc))]
    if not cues:
        return [_finding("subtitle.parse", None, "subtitle file contains no cues")]

    findings: list[SubtitleFinding] = []
    previous = None
    uncertain_markers = ("[?]", "??", "[inaudible]", "（听不清）", "[听不清]")
    normalized_terms = tuple(term for term in review_terms if term)
    for position, cue in enumerate(cues, start=1):
        cue_index = cue.index if cue.index is not None else position
        start_s = cue.start.total_seconds()
        end_s = cue.end.total_seconds()
        if previous is not None:
            if start_s < previous.start.total_seconds():
                findings.append(_finding("subtitle.non_monotonic", cue_index, f"cue starts at {start_s:.3f}s"))
            if start_s < previous.end.total_seconds():
                findings.append(_finding("subtitle.overlap", cue_index, f"cue starts at {start_s:.3f}s before the previous cue ends"))
        if start_s < 0 or end_s > duration_s + 0.05:
            findings.append(_finding("subtitle.out_of_range", cue_index, f"cue={start_s:.3f}-{end_s:.3f}s; video={duration_s:.3f}s"))
        content = cue.content.strip()
        if not content:
            findings.append(_finding("subtitle.empty", cue_index, "empty subtitle cue"))
        for line in content.splitlines() or [""]:
            limit = 22 if _contains_cjk(line) else 42
            if len(line) > limit:
                findings.append(_finding("subtitle.line_length", cue_index, f"line length {len(line)} exceeds {limit}"))
                break
        if end_s - start_s < 0.35:
            findings.append(_finding("subtitle.too_short", cue_index, f"cue duration is {end_s - start_s:.3f}s"))
        if any(marker.lower() in content.lower() for marker in uncertain_markers):
            findings.append(_finding("subtitle.uncertain", cue_index, content))
        matched_terms = [term for term in normalized_terms if term.lower() in content.lower()]
        if matched_terms:
            findings.append(_finding("subtitle.review_term", cue_index, ", ".join(matched_terms)))
        previous = cue
    return findings


def subtitle_rules(findings: Iterable[SubtitleFinding]) -> list[RuleResult]:
    grouped: dict[str, list[SubtitleFinding]] = {code: [] for code in RULES}
    for finding in findings:
        grouped.setdefault(finding.code, []).append(finding)
    rules = []
    for code, (severity, remediation) in RULES.items():
        items = grouped.get(code, [])
        evidence = "; ".join(
            f"cue {item.cue_index}: {item.evidence}" if item.cue_index is not None else item.evidence for item in items
        )
        rules.append(
            RuleResult(
                code,
                severity,
                "fail" if items else "pass",
                evidence or "no findings",
                remediation if items else "",
            )
        )
    return rules
