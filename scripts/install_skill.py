#!/usr/bin/env python3
"""Install the canonical skill package into supported agent hosts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable


SKILL_NAME = "short-drama-batch-remaster"
HOST_ROOTS: dict[str, Callable[[Path], Path]] = {
    "codex": lambda home: home / ".codex" / "skills",
    "opencode": lambda home: home / ".config" / "opencode" / "skills",
    "workbuddy": lambda home: home / ".workbuddy" / "skills",
}


def default_skill_root(host: str, home: Path, system: str | None = None) -> Path:
    del system
    if host not in HOST_ROOTS:
        raise ValueError(f"unsupported host: {host}")
    if host == "workbuddy" and os.environ.get("WORKBUDDY_SKILLS_DIR"):
        return Path(os.environ["WORKBUDDY_SKILLS_DIR"]).expanduser()
    return HOST_ROOTS[host](home.expanduser())


def _backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = target.with_name(f"{target.name}.backup-{stamp}")
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = target.with_name(f"{target.name}.backup-{stamp}-{counter}")
        counter += 1
    return candidate


def install_skill(source: Path, target_root: Path, *, mode: str, force: bool) -> Path:
    source = source.expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"source is not a skill directory: {source}")
    if mode not in {"copy", "link"}:
        raise ValueError("mode must be copy or link")

    target = target_root.expanduser().resolve() / source.name
    if target == source:
        return target
    if target.exists() or target.is_symlink():
        if not force:
            raise FileExistsError(f"skill already exists: {target}")
        target.replace(_backup_path(target))

    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        target.symlink_to(source, target_is_directory=True)
    else:
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
        )
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install this skill for Codex, OpenCode, or WorkBuddy.")
    parser.add_argument("--host", choices=["codex", "opencode", "workbuddy", "all"], required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target", type=Path, help="Override the host skills root; valid with one host only.")
    parser.add_argument("--mode", choices=["copy", "link"], default="copy")
    parser.add_argument("--force", action="store_true", help="Back up and replace an existing installation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host == "all" and args.target:
        raise SystemExit("--target can only be used with one host")
    hosts = list(HOST_ROOTS) if args.host == "all" else [args.host]
    results = []
    for host in hosts:
        target_root = args.target or default_skill_root(host, Path.home(), platform.system().lower())
        try:
            installed = install_skill(args.source, target_root, mode=args.mode, force=args.force)
            results.append({"host": host, "ok": True, "path": str(installed)})
        except Exception as exc:
            results.append({"host": host, "ok": False, "error": str(exc), "target_root": str(target_root)})
    print(json.dumps({"ok": all(item["ok"] for item in results), "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
