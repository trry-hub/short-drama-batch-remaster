#!/usr/bin/env python3
"""Portable job state and intake rules for short-drama remastering."""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
RIGHTS_STATUSES = {"owned", "licensed", "client-provided", "authorized"}
PLANNING_MODES = {"one-to-one", "target-duration", "mapping-csv"}
JOB_STATES = {"draft", "ready", "running", "needs_input", "failed", "complete"}


@dataclass(frozen=True)
class Question:
    field: str
    prompt: str
    default: str | None = None
    choices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_path_for_output(output_root: Path) -> Path:
    return output_root.expanduser() / ".job" / "job.json"


def new_job(output_root: Path) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": uuid.uuid4().hex,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "output_root": str(output_root.expanduser().resolve()),
        "source_root": None,
        "source_series": None,
        "output_series": None,
        "rights_status": None,
        "planning": {
            "mode": None,
            "target_duration_s": 60.0,
            "min_duration_s": 45.0,
            "max_duration_s": 75.0,
            "mapping_csv": None,
        },
        "episode_start": 1,
        "source_limit": None,
        "profile": {
            "mode": "default",
            "width": 1080,
            "height": 1920,
            "speed": 1.05,
            "video_bitrate": "6500k",
            "audio_bitrate": "192k",
            "maxrate": "7500k",
            "bufsize": "13000k",
        },
        "enhancements": {
            "covers": True,
            "subtitles": False,
            "metadata": True,
            "evidence": True,
        },
        "platform": "WeChat Channels",
        "account": "",
        "publishing": {"prepare": False, "approved": False},
        "answered_fields": [],
        "source_inventory": [],
        "episode_plan": [],
        "episodes": {},
        "last_error": None,
        "needs_input": None,
    }


def load_job(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported job schema: {payload.get('schema_version')}")
    if payload.get("status") not in JOB_STATES:
        raise ValueError(f"invalid job status: {payload.get('status')}")
    return payload


def save_job(path: Path, job: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = utc_now()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def _require_text(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty")
    return text


def _existing_directory(value: str) -> str:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"source folder does not exist: {path}")
    return str(path)


def _existing_file(value: str) -> str:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    return str(path)


def _choice(value: str, choices: set[str], label: str) -> str:
    normalized = value.strip().lower()
    if normalized not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(choices))}")
    return normalized


def _positive_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _optional_positive_int(value: str) -> int | None:
    if value.strip().lower() in {"", "all", "none", "no"}:
        return None
    return _positive_int(value, "source limit")


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1", "on"}:
        return True
    if normalized in {"no", "n", "false", "0", "off"}:
        return False
    raise ValueError("value must be yes or no")


def _bitrate(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"\d+(?:\.\d+)?[km]?", normalized):
        raise ValueError("bitrate must look like 6500k or 6.5m")
    return normalized


def _field_parser(field: str) -> Callable[[str], Any]:
    parsers: dict[str, Callable[[str], Any]] = {
        "source_root": _existing_directory,
        "source_series": lambda value: _require_text(value, "source series"),
        "output_series": lambda value: _require_text(value, "output series"),
        "rights_status": lambda value: _choice(value, RIGHTS_STATUSES, "rights status"),
        "planning.mode": lambda value: _choice(value, PLANNING_MODES, "planning mode"),
        "planning.target_duration_s": lambda value: _positive_float(value, "target duration"),
        "planning.min_duration_s": lambda value: _positive_float(value, "minimum duration"),
        "planning.max_duration_s": lambda value: _positive_float(value, "maximum duration"),
        "planning.mapping_csv": _existing_file,
        "episode_start": lambda value: _positive_int(value, "episode start"),
        "source_limit": _optional_positive_int,
        "profile.mode": lambda value: _choice(value, {"default", "custom"}, "profile mode"),
        "profile.width": lambda value: _positive_int(value, "width"),
        "profile.height": lambda value: _positive_int(value, "height"),
        "profile.speed": lambda value: _positive_float(value, "speed"),
        "profile.video_bitrate": _bitrate,
        "profile.audio_bitrate": _bitrate,
        "enhancements.covers": _boolean,
        "enhancements.subtitles": _boolean,
        "enhancements.metadata": _boolean,
        "enhancements.evidence": _boolean,
        "platform": lambda value: _require_text(value, "platform"),
        "account": lambda value: value.strip(),
        "publishing.prepare": _boolean,
    }
    if field not in parsers:
        raise ValueError(f"unknown job field: {field}")
    return parsers[field]


def _set_nested(job: dict[str, Any], field: str, value: Any) -> None:
    parts = field.split(".")
    target: dict[str, Any] = job
    for part in parts[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[parts[-1]] = value


def set_job_field(job: dict[str, Any], field: str, raw_value: str) -> dict[str, Any]:
    updated = copy.deepcopy(job)
    parsed = _field_parser(field)(raw_value)
    _set_nested(updated, field, parsed)
    answered = updated.setdefault("answered_fields", [])
    if field not in answered:
        answered.append(field)
    updated["status"] = "draft"
    updated["last_error"] = None
    updated["needs_input"] = None
    updated["updated_at"] = utc_now()
    return updated


def _question_table(job: dict[str, Any]) -> list[Question]:
    mode = job.get("planning", {}).get("mode")
    profile_mode = job.get("profile", {}).get("mode")
    questions = [
        Question("source_root", "Authorized source folder"),
        Question("source_series", "Source series name"),
        Question("output_series", "Output series name"),
        Question("rights_status", "Rights status", choices=tuple(sorted(RIGHTS_STATUSES))),
        Question("planning.mode", "Episode planning mode", choices=("target-duration", "one-to-one", "mapping-csv")),
    ]
    if mode == "target-duration":
        questions.extend(
            [
                Question("planning.target_duration_s", "Target output duration in seconds", "60"),
                Question("planning.min_duration_s", "Minimum output duration in seconds", "45"),
                Question("planning.max_duration_s", "Maximum output duration in seconds", "75"),
            ]
        )
    elif mode == "mapping-csv":
        questions.append(Question("planning.mapping_csv", "Mapping CSV path"))
    questions.extend(
        [
            Question("episode_start", "Starting output episode", "1"),
            Question("source_limit", "Maximum source files or all", "all"),
            Question("profile.mode", "Use default or custom delivery profile", "default", ("default", "custom")),
        ]
    )
    if profile_mode == "custom":
        questions.extend(
            [
                Question("profile.width", "Output width", "1080"),
                Question("profile.height", "Output height", "1920"),
                Question("profile.speed", "Playback speed", "1.05"),
                Question("profile.video_bitrate", "Video bitrate", "6500k"),
                Question("profile.audio_bitrate", "Audio bitrate", "192k"),
            ]
        )
    questions.extend(
        [
            Question("enhancements.covers", "Generate cover candidates", "yes"),
            Question("enhancements.subtitles", "Generate subtitle drafts", "no"),
            Question("enhancements.metadata", "Generate release metadata drafts", "yes"),
            Question("enhancements.evidence", "Generate evidence artifacts", "yes"),
            Question("platform", "Target platform", "WeChat Channels"),
            Question("account", "Publishing account label, or leave blank", ""),
            Question("publishing.prepare", "Prepare publishing tasks", "no"),
        ]
    )
    return questions


def next_question(job: dict[str, Any]) -> Question | None:
    answered = set(job.get("answered_fields", []))
    for question in _question_table(job):
        if question.field not in answered:
            return question
    return None


def validate_job(job: dict[str, Any], require_ready: bool = False) -> list[str]:
    problems: list[str] = []
    if job.get("schema_version") != SCHEMA_VERSION:
        problems.append("unsupported job schema")
    source_root = job.get("source_root")
    if source_root and not Path(source_root).is_dir():
        problems.append("source folder does not exist")
    mode = job.get("planning", {}).get("mode")
    if mode and mode not in PLANNING_MODES:
        problems.append("invalid planning mode")
    if mode == "target-duration":
        planning = job.get("planning", {})
        minimum = planning.get("min_duration_s")
        target = planning.get("target_duration_s")
        maximum = planning.get("max_duration_s")
        if not all(isinstance(value, (int, float)) and value > 0 for value in (minimum, target, maximum)):
            problems.append("duration values must be greater than zero")
        elif not minimum <= target <= maximum:
            problems.append("target duration must be between minimum and maximum")
    if mode == "mapping-csv":
        mapping = job.get("planning", {}).get("mapping_csv")
        if not mapping or not Path(mapping).is_file():
            problems.append("mapping CSV does not exist")
    if require_ready:
        question = next_question(job)
        if question is not None:
            problems.append(f"missing intake field: {question.field}")
        if not job.get("episode_plan"):
            problems.append("episode plan has not been generated")
    return problems
