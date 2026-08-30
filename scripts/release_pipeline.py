#!/usr/bin/env python3
"""Combine media, subtitle, rights, and review evidence into release reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from delivery_profiles import DeliveryProfile, load_delivery_profile
from media_analysis import MediaAnalysis, analyze_media, media_rules
from release_readiness import (
    ReadinessReport,
    ReportPaths,
    RuleResult,
    aggregate_report_status,
    evaluate_release,
    rights_and_review_rules,
    write_readiness_reports,
)
from subtitle_quality import inspect_subtitles, subtitle_rules


Analyzer = Callable[[Path], MediaAnalysis]


@dataclass(frozen=True)
class ReleasePipelineResult:
    status: str
    reports: tuple[ReadinessReport, ...]
    paths: ReportPaths


def _artifact_value(artifact: Any, field: str, default: Any = None) -> Any:
    if isinstance(artifact, dict):
        return artifact.get(field, default)
    return getattr(artifact, field, default)


def _artifact_reviews(artifacts: Iterable[Any]) -> dict[str, str]:
    reviews: dict[str, str] = {}
    kind_map = {"cover": "cover", "copy": "copy", "narration": "narration"}
    for artifact in artifacts:
        kind = kind_map.get(str(_artifact_value(artifact, "kind", "")))
        if not kind:
            continue
        status = str(_artifact_value(artifact, "review_status", "needs_review"))
        if reviews.get(kind) != "approved":
            reviews[kind] = status
    return reviews


def _subtitle_rules(
    episode: dict[str, Any],
    context: dict[str, Any],
    artifacts: Iterable[Any],
) -> list[RuleResult]:
    requested = bool(context.get("enhancements", {}).get("subtitles"))
    srt_path = next(
        (
            Path(str(_artifact_value(artifact, "path")))
            for artifact in artifacts
            if _artifact_value(artifact, "kind") == "srt"
        ),
        None,
    )
    if not requested:
        return [RuleResult("subtitle.required", "blocker", "pass", "subtitle generation not selected", "")]
    if srt_path is None or not srt_path.is_file():
        return [
            RuleResult(
                "subtitle.required",
                "blocker",
                "fail",
                "subtitle generation was selected but no SRT artifact exists",
                "generate and review the required subtitle artifact",
            )
        ]
    duration = episode.get("output_probe", {}).get("duration_s") if isinstance(episode.get("output_probe"), dict) else None
    duration_s = float(duration or 0.0)
    return [
        RuleResult("subtitle.required", "blocker", "pass", str(srt_path), ""),
        *subtitle_rules(inspect_subtitles(srt_path, duration_s)),
    ]


def build_episode_report(
    episode: dict[str, Any],
    context: dict[str, Any],
    artifacts: Iterable[Any],
    *,
    profile: DeliveryProfile | None = None,
    analyzer: Analyzer = analyze_media,
) -> ReadinessReport:
    profile = profile or load_delivery_profile(
        context.get("delivery_profile", {}).get("name", "video-channels"),
        int(context.get("delivery_profile", {}).get("version", 1)),
    )
    output_path = Path(str(episode.get("output_path") or ""))
    analysis = analyzer(output_path)
    artifact_list = list(artifacts)
    review_context = dict(context)
    review_context["artifact_reviews"] = _artifact_reviews(artifact_list)
    number = int(episode.get("episode_number", 0))
    enhancement_error = context.get("enhancement_errors", {}).get(number)
    enhancement_rule = RuleResult(
        "enhancement.required",
        "blocker",
        "fail" if enhancement_error else "pass",
        enhancement_error or "selected enhancement stages completed",
        "provide the missing input or tool and resume the enhancement stage" if enhancement_error else "",
    )
    return evaluate_release(
        f"episode-{number:03d}",
        media_rules(analysis, profile),
        _subtitle_rules(episode, context, artifact_list),
        [enhancement_rule],
        rights_and_review_rules(review_context),
    )


def _batch_report(episodes: list[dict[str, Any]], reports: list[ReadinessReport]) -> ReadinessReport:
    media_complete = all(
        episode.get("status") == "complete" and episode.get("qc_status") == "pass" for episode in episodes
    )
    episode_status = aggregate_report_status(reports)
    if episode_status == "blocked":
        readiness_rule = RuleResult(
            "batch.episode_readiness",
            "blocker",
            "fail",
            "one or more episode reports are blocked",
            "resolve the blocking episode findings before publishing",
        )
    elif episode_status == "warning":
        readiness_rule = RuleResult(
            "batch.episode_readiness",
            "warning",
            "fail",
            "one or more episode reports need review",
            "review and approve all warning findings",
        )
    else:
        readiness_rule = RuleResult("batch.episode_readiness", "info", "pass", "all episode reports pass", "")
    return ReadinessReport.from_results(
        "batch",
        [
            RuleResult(
                "batch.media_complete",
                "blocker",
                "pass" if media_complete else "fail",
                f"complete={sum(1 for item in episodes if item.get('status') == 'complete')}; total={len(episodes)}",
                "finish and validate every planned episode" if not media_complete else "",
            ),
            readiness_rule,
        ],
    )


def run_readiness_pipeline(
    manifest: dict[str, Any],
    context: dict[str, Any],
    artifacts_by_episode: dict[int, list[Any]],
    reports_dir: Path,
    *,
    analyzer: Analyzer = analyze_media,
) -> ReleasePipelineResult:
    profile = load_delivery_profile(
        context.get("delivery_profile", {}).get("name", "video-channels"),
        int(context.get("delivery_profile", {}).get("version", 1)),
    )
    episode_reports = [
        build_episode_report(
            episode,
            context,
            artifacts_by_episode.get(int(episode.get("episode_number", 0)), []),
            profile=profile,
            analyzer=analyzer,
        )
        for episode in manifest.get("episodes", [])
    ]
    batch = _batch_report(manifest.get("episodes", []), episode_reports)
    reports = [*episode_reports, batch]
    paths = write_readiness_reports(reports, reports_dir)
    return ReleasePipelineResult(
        status=aggregate_report_status(reports),
        reports=tuple(reports),
        paths=paths,
    )
