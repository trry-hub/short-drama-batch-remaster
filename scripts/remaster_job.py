#!/usr/bin/env python3
"""Interactive and agent-friendly controller for durable remaster jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from build_release_pack import (
    build_episode_index,
    discover_videos,
    hash_file,
    parse_mapping_csv,
    probe_video,
    should_skip_episode,
)
from episode_planner import (
    PlannedEpisode,
    SourceMedia,
    plan_one_to_one,
    plan_target_duration,
    probe_scene_changes,
    write_episode_plan_csv,
)
from remaster_job_core import (
    job_path_for_output,
    load_job,
    new_job,
    next_question,
    save_job,
    set_job_field,
    validate_job,
)


SCRIPTS = Path(__file__).resolve().parent
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NEEDS_INPUT = 3


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def status_payload(job: dict[str, Any]) -> dict[str, Any]:
    question = next_question(job)
    return {
        "job": job,
        "next_question": question.to_dict() if question else None,
        "validation_errors": validate_job(job),
    }


def set_status(job_path: Path, status: str, *, error: str | None = None, needs_input: str | None = None) -> dict[str, Any]:
    job = load_job(job_path)
    job["status"] = status
    job["last_error"] = error
    job["needs_input"] = needs_input
    save_job(job_path, job)
    return job


def cmd_init(args: argparse.Namespace) -> int:
    job_path = job_path_for_output(args.output_root)
    if job_path.exists() and not args.force:
        raise ValueError(f"job already exists: {job_path}; use --force to replace it")
    job = new_job(args.output_root)
    save_job(job_path, job)
    print_json({"job_path": str(job_path.resolve()), "next_question": next_question(job).to_dict()})
    return EXIT_OK


def cmd_set(args: argparse.Namespace) -> int:
    job = load_job(args.job)
    updated = set_job_field(job, args.field, args.value)
    save_job(args.job, updated)
    question = next_question(updated)
    print_json(
        {
            "job_path": str(args.job.resolve()),
            "accepted_field": args.field,
            "next_question": question.to_dict() if question else None,
        }
    )
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    job = load_job(args.job)
    payload = status_payload(job)
    if args.json:
        print_json(payload)
    else:
        print(f"Job: {args.job}")
        print(f"Status: {job['status']}")
        question = payload["next_question"]
        print(f"Next question: {question['prompt']}" if question else "Intake complete")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    job = load_job(args.job)
    problems = validate_job(job, require_ready=args.ready)
    question = next_question(job)
    if question is not None:
        problems.append(f"missing intake field: {question.field}")
    print_json({"ok": not problems, "problems": list(dict.fromkeys(problems))})
    return EXIT_OK if not problems else EXIT_USAGE


def _source_inventory(job: dict[str, Any]) -> tuple[list[SourceMedia], list[dict[str, Any]], list[str]]:
    source_root = Path(job["source_root"])
    videos = discover_videos(source_root)
    limit = job.get("source_limit")
    if limit:
        videos = videos[: int(limit)]
    if not videos:
        raise ValueError(f"no source videos found under {source_root}")

    use_scenes = job.get("planning", {}).get("mode") == "target-duration"
    media: list[SourceMedia] = []
    inventory: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in videos:
        probe = probe_video(path)
        if not probe.has_video or probe.duration_s is None or probe.duration_s <= 0:
            raise ValueError(f"unsupported or unreadable source video: {path}")
        scenes: tuple[float, ...] = ()
        if use_scenes:
            try:
                scenes = probe_scene_changes(path)
            except Exception as exc:
                warnings.append(f"scene detection unavailable for {path.name}: {exc}")
        file_hash = hash_file(path)["sha256"]
        stat = path.stat()
        media.append(SourceMedia(str(path), probe.duration_s, scenes))
        inventory.append(
            {
                "path": str(path),
                "duration_s": probe.duration_s,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": file_hash,
                "scene_changes_s": list(scenes),
            }
        )
    return media, inventory, warnings


def _mapping_plan(job: dict[str, Any], media: Sequence[SourceMedia]) -> list[PlannedEpisode]:
    source_root = Path(job["source_root"])
    paths = [Path(item.path) for item in media]
    index = build_episode_index(paths)
    mapping_path = Path(job["planning"]["mapping_csv"])
    jobs = parse_mapping_csv(mapping_path, source_root, index)
    speed = float(job["profile"]["speed"])
    return [
        PlannedEpisode(
            output_episode=item.output_episode,
            segments=tuple(item.segments),
            estimated_duration_s=round(sum(segment.duration_s for segment in item.segments) / speed, 3),
        )
        for item in jobs
    ]


def plan_job(job_path: Path) -> dict[str, Any]:
    job = load_job(job_path)
    question = next_question(job)
    if question is not None:
        raise ValueError(f"missing intake field: {question.field}")
    problems = validate_job(job)
    if problems:
        raise ValueError("; ".join(problems))

    media, inventory, warnings = _source_inventory(job)
    mode = job["planning"]["mode"]
    speed = float(job["profile"]["speed"])
    episode_start = int(job["episode_start"])
    if mode == "target-duration":
        planning = job["planning"]
        plan = plan_target_duration(
            media,
            float(planning["target_duration_s"]),
            float(planning["min_duration_s"]),
            float(planning["max_duration_s"]),
            speed=speed,
            episode_start=episode_start,
        )
    elif mode == "mapping-csv":
        plan = _mapping_plan(job, media)
    else:
        plan = plan_one_to_one(media, speed=speed, episode_start=episode_start)

    job["source_inventory"] = inventory
    job["episode_plan"] = [episode.to_dict() for episode in plan]
    job["planning_warnings"] = warnings
    job["status"] = "ready"
    job["last_error"] = None
    job["needs_input"] = None
    save_job(job_path, job)
    plan_path = Path(job["output_root"]) / "manifests" / "episode_plan.csv"
    write_episode_plan_csv(plan_path, plan)
    return {
        "job_path": str(job_path.resolve()),
        "status": "ready",
        "episode_count": len(plan),
        "episode_plan_csv": str(plan_path),
        "episodes": job["episode_plan"],
        "warnings": warnings,
    }


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        payload = plan_job(args.job)
    except Exception as exc:
        set_status(args.job, "needs_input", error=str(exc), needs_input=str(exc))
        print_json({"ok": False, "status": "needs_input", "error": str(exc)})
        return EXIT_NEEDS_INPUT
    print_json(payload)
    return EXIT_OK


def _tool_check() -> tuple[bool, str]:
    command = [
        sys.executable,
        str(SCRIPTS / "ensure_tools.py"),
        "--install",
        "--features",
        "core",
        "--json",
    ]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode == 0:
        return True, ""
    try:
        payload = json.loads(proc.stdout)
        missing = [item for item in payload.get("results", []) if not item.get("present")]
        notes = [item.get("note") or item.get("name") for item in missing]
        return False, "; ".join(notes) or "core dependencies are unavailable"
    except json.JSONDecodeError:
        return False, proc.stdout.strip() or "core dependencies are unavailable"


def execute_job(job_path: Path, *, resume: bool, confirmed: bool) -> int:
    if not confirmed:
        print_json({"ok": False, "error": "run and resume require --confirm"})
        return EXIT_USAGE
    job = load_job(job_path)
    problems = validate_job(job, require_ready=True)
    if problems:
        message = "; ".join(problems)
        set_status(job_path, "needs_input", error=message, needs_input=message)
        print_json({"ok": False, "status": "needs_input", "error": message})
        return EXIT_NEEDS_INPUT

    tools_ok, tool_error = _tool_check()
    if not tools_ok:
        set_status(job_path, "needs_input", error=tool_error, needs_input=tool_error)
        print_json({"ok": False, "status": "needs_input", "error": tool_error})
        return EXIT_NEEDS_INPUT

    set_status(job_path, "running")
    command = [sys.executable, str(SCRIPTS / "build_release_pack.py"), "--job-file", str(job_path)]
    if resume:
        command.append("--resume")
    proc = subprocess.run(command)
    updated = load_job(job_path)
    planned_numbers = [str(item["output_episode"]) for item in updated.get("episode_plan", [])]
    complete = all(should_skip_episode(updated.get("episodes", {}).get(number)) for number in planned_numbers)
    if proc.returncode == 0 and planned_numbers and complete:
        updated["status"] = "complete"
        updated["last_error"] = None
        updated["needs_input"] = None
        exit_code = EXIT_OK
    else:
        updated["status"] = "failed"
        updated["last_error"] = f"release-pack builder exited with {proc.returncode}"
        exit_code = EXIT_FAILED
    save_job(job_path, updated)
    print_json(
        {
            "ok": exit_code == EXIT_OK,
            "status": updated["status"],
            "job_path": str(job_path),
            "output_root": updated["output_root"],
        }
    )
    return exit_code


def cmd_execute(args: argparse.Namespace) -> int:
    return execute_job(args.job, resume=args.command == "resume", confirmed=args.confirm)


def wizard(output_root: Path | None) -> int:
    if output_root is None:
        raw_output = input("Output root: ").strip()
        if not raw_output:
            print("Output root is required")
            return EXIT_USAGE
        output_root = Path(raw_output).expanduser()
    job_path = job_path_for_output(output_root)
    job = load_job(job_path) if job_path.exists() else new_job(output_root)
    save_job(job_path, job)

    while (question := next_question(job)) is not None:
        suffix = f" [{question.default}]" if question.default is not None else ""
        if question.choices:
            suffix += f" ({'/'.join(question.choices)})"
        raw = input(f"{question.prompt}{suffix}: ").strip()
        if not raw and question.default is not None:
            raw = question.default
        try:
            job = set_job_field(job, question.field, raw)
            save_job(job_path, job)
        except ValueError as exc:
            print(f"Invalid value: {exc}")

    payload = plan_job(job_path)
    print(f"Planned {payload['episode_count']} episode(s).")
    for item in payload["episodes"][:10]:
        print(f"  Episode {item['output_episode']:03d}: about {item['estimated_duration_s']:.2f}s")
    confirmation = input("Start processing now? [y/N]: ").strip().lower()
    if confirmation not in {"y", "yes"}:
        print(f"Job saved: {job_path}")
        return EXIT_OK
    return execute_job(job_path, resume=False, confirmed=True)


def cmd_wizard(args: argparse.Namespace) -> int:
    return wizard(args.output_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, plan, run, and resume a short-drama remaster job.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--output-root", type=Path, required=True)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=cmd_init)

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("--job", type=Path, required=True)
    set_parser.add_argument("field")
    set_parser.add_argument("value")
    set_parser.set_defaults(handler=cmd_set)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--job", type=Path, required=True)
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=cmd_status)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--job", type=Path, required=True)
    validate_parser.add_argument("--ready", action="store_true")
    validate_parser.set_defaults(handler=cmd_validate)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--job", type=Path, required=True)
    plan_parser.set_defaults(handler=cmd_plan)

    for command in ("run", "resume"):
        execute_parser = subparsers.add_parser(command)
        execute_parser.add_argument("--job", type=Path, required=True)
        execute_parser.add_argument("--confirm", action="store_true")
        execute_parser.set_defaults(handler=cmd_execute)

    wizard_parser = subparsers.add_parser("wizard")
    wizard_parser.add_argument("--output-root", type=Path)
    wizard_parser.set_defaults(handler=cmd_wizard)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        print_json({"ok": False, "error": str(exc)})
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
