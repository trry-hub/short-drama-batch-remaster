#!/usr/bin/env python3
"""Lightweight structural self-test for the skill package."""

from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    required = [
        ROOT / "SKILL.md",
        ROOT / "references" / "workflow.md",
        ROOT / "references" / "tooling.md",
        ROOT / "references" / "production-enhancements.md",
        ROOT / "references" / "rights-safe-transformations.md",
        ROOT / "references" / "interactive-intake.md",
        ROOT / "scripts" / "build_release_pack.py",
        ROOT / "scripts" / "check_release_pack.py",
        ROOT / "scripts" / "episode_planner.py",
        ROOT / "scripts" / "ensure_tools.py",
        ROOT / "scripts" / "install_skill.py",
        ROOT / "scripts" / "remaster_job.py",
        ROOT / "scripts" / "remaster_job_core.py",
        ROOT / "scripts" / "batch_executor.py",
        ROOT / "scripts" / "content_enhancements.py",
        ROOT / "scripts" / "delivery_profiles.py",
        ROOT / "scripts" / "encoder_selection.py",
        ROOT / "scripts" / "evaluate_release_readiness.py",
        ROOT / "scripts" / "media_analysis.py",
        ROOT / "scripts" / "release_pipeline.py",
        ROOT / "scripts" / "release_readiness.py",
        ROOT / "scripts" / "stage_cache.py",
        ROOT / "scripts" / "subtitle_quality.py",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        for path in missing:
            print(f"MISSING {path}")
        return 1

    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for token in [
        "authorized",
        "Jianying",
        "Whisper",
        "QC",
        "one question at a time",
        "Codex",
        "OpenCode",
        "WorkBuddy",
        "ensure_tools.py",
        "build_release_pack.py",
        "remaster_job.py",
        "production-enhancements.md",
        "release_readiness",
    ]:
        if token not in text:
            print(f"MISSING TOKEN {token}")
            return 1

    modules = (
        "batch_executor",
        "content_enhancements",
        "delivery_profiles",
        "encoder_selection",
        "media_analysis",
        "release_pipeline",
        "release_readiness",
        "stage_cache",
        "subtitle_quality",
    )
    for module in modules:
        importlib.import_module(module)

    from delivery_profiles import load_delivery_profile
    from release_readiness import ReadinessReport, RuleResult, write_readiness_reports

    profile = load_delivery_profile("video-channels")
    if profile.platform_approval_guarantee:
        print("INVALID PROFILE GUARANTEE")
        return 1
    with tempfile.TemporaryDirectory() as raw:
        report = ReadinessReport.from_results(
            "selftest",
            [RuleResult("selftest.ready", "info", "pass", "ok", "")],
        )
        paths = write_readiness_reports([report], Path(raw))
        if not all(path.is_file() for path in (paths.json, paths.csv, paths.markdown)):
            print("MISSING READINESS REPORT")
            return 1

    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
