#!/usr/bin/env python3
"""Lightweight structural self-test for the skill package."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    ]:
        if token not in text:
            print(f"MISSING TOKEN {token}")
            return 1

    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
