#!/usr/bin/env python3
"""Build an authorized short-drama release pack from local source videos.

This tool is intentionally scoped to release-package production and local QC.
It can prove that an output file is not a byte-identical copy of its source
inputs, but it does not claim to bypass or predict any platform review system.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from batch_executor import execute_episodes, resolve_worker_count
from encoder_selection import EncoderChoice, select_encoder
from episode_planner import SourceSegment
from remaster_job_core import load_job, save_job
from stage_cache import StageCache, build_cache_key


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
RELEASE_QUEUE_FIELDS = [
    "series_name",
    "episode_number",
    "video_path",
    "cover_path",
    "title",
    "description",
    "tags",
    "platform",
    "account",
    "status",
    "schedule_time",
    "qc_status",
    "review_status",
    "rights_status",
    "notes",
]


@dataclass
class ProbeInfo:
    path: str
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    bitrate_mbps: float | None = None
    size_mb: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None


@dataclass
class EpisodeJob:
    output_episode: int
    segments: list[SourceSegment]

    @property
    def source_paths(self) -> list[Path]:
        return list(dict.fromkeys(Path(segment.path) for segment in self.segments))


@dataclass
class EpisodeResult:
    episode_number: int
    sources: list[str]
    output_path: str | None
    status: str
    qc_status: str
    source_probe: list[ProbeInfo] = field(default_factory=list)
    output_probe: ProbeInfo | None = None
    source_hashes: list[dict[str, str]] = field(default_factory=list)
    output_hashes: dict[str, str] | None = None
    local_difference: dict[str, Any] = field(default_factory=dict)
    cover_candidates: list[str] = field(default_factory=list)
    title_candidates: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    attempts: int = 0
    cache_status: str = "disabled"
    cache_key: str | None = None
    encoder: dict[str, Any] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeContext:
    args: argparse.Namespace
    videos_dir: Path
    covers_dir: Path
    temp_root: Path
    checkpoints: dict[int, dict[str, Any]]
    cache: StageCache | None
    encoder_choice: EncoderChoice


class EpisodeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, message: str) -> None:
        self.lines.append(message)


class BatchLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def line(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = f"[{stamp}] {message}"
        print(text)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"Command failed: {' '.join(cmd)}")
    return proc


def slugify(value: str, fallback: str = "series") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug or fallback


def bitrate_to_mbps(value: str) -> float:
    raw = value.strip().lower()
    if raw.endswith("k"):
        return float(raw[:-1]) / 1000
    if raw.endswith("m"):
        return float(raw[:-1])
    return float(raw) / 1_000_000


def parse_episode_number(path: Path) -> int | None:
    name = path.stem
    matches = re.findall(r"(?<!\d)(\d{1,4})(?!\d)", name)
    if not matches:
        return None
    return int(matches[-1])


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def discover_videos(source_root: Path) -> list[Path]:
    return sorted(
        [path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS],
        key=natural_key,
    )


def build_episode_index(videos: Iterable[Path]) -> dict[int, Path]:
    index: dict[int, Path] = {}
    for video in videos:
        number = parse_episode_number(video)
        if number is not None and number not in index:
            index[number] = video
    return index


def resolve_source_token(token: str, source_root: Path, episode_index: dict[int, Path]) -> Path:
    token = token.strip().strip('"').strip("'")
    if not token:
        raise ValueError("empty source token")

    candidate = Path(token)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    rooted = source_root / candidate
    if rooted.exists():
        return rooted

    if token.isdigit():
        episode = int(token)
        if episode in episode_index:
            return episode_index[episode]

    raise FileNotFoundError(f"Could not resolve source token: {token}")


def parse_mapping_csv(mapping_csv: Path, source_root: Path, episode_index: dict[int, Path]) -> list[EpisodeJob]:
    with mapping_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("mapping CSV has no header")
        source_field = "sources" if "sources" in reader.fieldnames else "source_paths"
        if "output_episode" not in reader.fieldnames or source_field not in reader.fieldnames:
            raise ValueError("mapping CSV requires output_episode and sources/source_paths columns")

        jobs: list[EpisodeJob] = []
        for row in reader:
            output_episode = int((row.get("output_episode") or "").strip())
            specs = [part for part in re.split(r"[+;|]", row.get(source_field, "")) if part.strip()]
            sources = [resolve_source_token(spec, source_root, episode_index) for spec in specs]
            if not sources:
                raise ValueError(f"episode {output_episode} has no sources")
            jobs.append(
                EpisodeJob(
                    output_episode=output_episode,
                    segments=[full_source_segment(path) for path in sources],
                )
            )
    return jobs


def parse_episode_plan(document: dict[str, Any]) -> list[EpisodeJob]:
    jobs: list[EpisodeJob] = []
    for item in document.get("episode_plan", []):
        segments = [SourceSegment(**segment) for segment in item.get("segments", [])]
        if not segments:
            raise ValueError(f"episode {item.get('output_episode')} has no planned segments")
        jobs.append(EpisodeJob(output_episode=int(item["output_episode"]), segments=segments))
    return jobs


def hash_file(path: Path) -> dict[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


def should_skip_episode(state: dict[str, Any] | None) -> bool:
    if not state or state.get("status") != "complete" or state.get("qc_status") != "pass":
        return False
    output_path = Path(state.get("output_path") or "")
    expected = state.get("output_sha256")
    return bool(expected and output_path.is_file() and hash_file(output_path)["sha256"] == expected)


def update_episode_checkpoint(job_path: Path, result: EpisodeResult) -> None:
    document = load_job(job_path)
    key = str(result.episode_number)
    previous = document.setdefault("episodes", {}).get(key, {})
    payload = asdict(result)
    payload["attempts"] = max(result.attempts, int(previous.get("attempts", 0)))
    payload["output_sha256"] = (result.output_hashes or {}).get("sha256")
    document["episodes"][key] = payload
    save_job(job_path, document)


def episode_result_from_checkpoint(state: dict[str, Any]) -> EpisodeResult:
    payload = {key: value for key, value in state.items() if key in EpisodeResult.__dataclass_fields__}
    payload["source_probe"] = [
        item if isinstance(item, ProbeInfo) else ProbeInfo(**item) for item in payload.get("source_probe", [])
    ]
    output_probe = payload.get("output_probe")
    if isinstance(output_probe, dict):
        payload["output_probe"] = ProbeInfo(**output_probe)
    return EpisodeResult(**payload)


def ffprobe_json(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        str(path),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"ffprobe failed for {path}")
    return json.loads(proc.stdout)


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_video(path: Path) -> ProbeInfo:
    info = ProbeInfo(path=str(path), size_mb=path.stat().st_size / 1024 / 1024)
    payload = ffprobe_json(path)
    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = stream.get("codec_name")
            info.width = int(stream.get("width") or 0) or None
            info.height = int(stream.get("height") or 0) or None
        elif stream.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = stream.get("codec_name")

    fmt = payload.get("format", {})
    info.duration_s = to_float(fmt.get("duration"))
    bit_rate = to_float(fmt.get("bit_rate"))
    if bit_rate is not None:
        info.bitrate_mbps = bit_rate / 1_000_000
    return info


def full_source_segment(path: Path) -> SourceSegment:
    info = probe_video(path)
    if info.duration_s is None or info.duration_s <= 0:
        raise ValueError(f"source has no readable duration: {path}")
    return SourceSegment(str(path), 0.0, info.duration_s)


def is_full_source_segment(segment: SourceSegment, source_duration_s: float | None) -> bool:
    return bool(
        source_duration_s is not None
        and segment.start_s <= 0.001
        and abs(segment.end_s - source_duration_s) <= 0.05
    )


def atempo_chain(speed: float) -> str:
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    values: list[float] = []
    remaining = speed
    while remaining > 2.0:
        values.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        values.append(0.5)
        remaining /= 0.5
    values.append(remaining)
    return ",".join(f"atempo={value:.6f}" for value in values)


def shell_quote_for_concat(path: Path) -> str:
    return str(path).replace("'", r"'\''")


def make_concat_input(sources: list[Path], temp_dir: Path, logger: BatchLogger, episode: int) -> Path:
    if len(sources) == 1:
        return sources[0]

    concat_list = temp_dir / f"episode-{episode:03d}-concat.txt"
    concat_input = temp_dir / f"episode-{episode:03d}-concat.mp4"
    with concat_list.open("w", encoding="utf-8") as handle:
        for source in sources:
            handle.write(f"file '{shell_quote_for_concat(source)}'\n")

    logger.line(f"Episode {episode:03d}: concatenating {len(sources)} authorized source files")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(concat_input)], check=True)
    return concat_input


def _intermediate_video_chain(args: argparse.Namespace) -> str:
    return (
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
        f"crop={args.width}:{args.height},fps=30,setsar=1,format=yuv420p"
    )


def encode_intermediate_segment(
    segment: SourceSegment,
    output_path: Path,
    source_probe: ProbeInfo,
    args: argparse.Namespace,
) -> None:
    if segment.end_s <= segment.start_s:
        raise ValueError(f"invalid source segment: {segment}")
    duration = segment.end_s - segment.start_s
    video_filter = (
        f"[0:v]trim=start={segment.start_s:.6f}:end={segment.end_s:.6f},"
        f"setpts=PTS-STARTPTS,{_intermediate_video_chain(args)}[v]"
    )
    command = ["ffmpeg", "-y", "-i", segment.path]
    if source_probe.has_audio:
        audio_filter = (
            f"[0:a]atrim=start={segment.start_s:.6f}:end={segment.end_s:.6f},"
            "asetpts=PTS-STARTPTS,aresample=48000[a]"
        )
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.6f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
        audio_filter = f"[1:a]atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a]"
    command.extend(
        [
            "-filter_complex",
            f"{video_filter};{audio_filter}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            args.preset,
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            args.audio_bitrate,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run(command, check=True)


def materialize_episode_input(
    job: EpisodeJob,
    temp_dir: Path,
    logger: BatchLogger,
    args: argparse.Namespace,
) -> Path:
    probes = {path: probe_video(path) for path in job.source_paths}
    if len(job.segments) == 1:
        segment = job.segments[0]
        source_path = Path(segment.path)
        if is_full_source_segment(segment, probes[source_path].duration_s):
            return source_path

    parts: list[Path] = []
    for index, segment in enumerate(job.segments, start=1):
        source_path = Path(segment.path)
        part = temp_dir / f"episode-{job.output_episode:03d}-part-{index:03d}.mp4"
        logger.line(
            f"Episode {job.output_episode:03d}: segment {index:03d} "
            f"{source_path.name} {segment.start_s:.3f}-{segment.end_s:.3f}s"
        )
        encode_intermediate_segment(segment, part, probes[source_path], args)
        parts.append(part)
    return make_concat_input(parts, temp_dir, logger, job.output_episode)


def encoder_output_args(args: argparse.Namespace) -> list[str]:
    choice: EncoderChoice = getattr(args, "encoder_choice", EncoderChoice("software", "libx264", ("-c:v", "libx264"), False))
    output = list(choice.ffmpeg_args)
    if not choice.hardware:
        output.extend(["-preset", args.preset])
    return output


def encode_episode(input_path: Path, output_path: Path, source_probe: ProbeInfo, args: argparse.Namespace) -> None:
    video_chain = (
        f"setpts=PTS/{args.speed:.6f},"
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
        f"crop={args.width}:{args.height},"
        f"eq=contrast={args.contrast:.4f}:brightness={args.brightness:.4f}:saturation={args.saturation:.4f},"
        "format=yuv420p"
    )
    common_output = [
        *encoder_output_args(args),
        "-b:v",
        args.video_bitrate,
        "-maxrate",
        args.maxrate,
        "-bufsize",
        args.bufsize,
        "-c:a",
        "aac",
        "-b:a",
        args.audio_bitrate,
        "-movflags",
        "+faststart",
        "-metadata",
        f"title={args.output_series}",
        "-metadata",
        "comment=Authorized release pack. Local QC only. No platform review guarantee.",
        str(output_path),
    ]

    if source_probe.has_audio:
        filter_complex = f"[0:v]{video_chain}[v];[0:a]{atempo_chain(args.speed)},loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *common_output,
        ]
    else:
        duration = (source_probe.duration_s or 1.0) / args.speed
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-f",
            "lavfi",
            "-t",
            f"{duration:.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex",
            f"[0:v]{video_chain}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-shortest",
            *common_output,
        ]

    run(cmd, check=True)


def qc_status(info: ProbeInfo, args: argparse.Namespace) -> tuple[str, list[str]]:
    problems: list[str] = []
    target_mbps = bitrate_to_mbps(args.video_bitrate)
    tolerance = args.bitrate_tolerance_mbps
    if info.duration_s is not None and info.duration_s < 10:
        tolerance = max(tolerance, 2.0)
    elif info.duration_s is not None and info.duration_s < 30:
        tolerance = max(tolerance, 1.5)

    if not info.has_video:
        problems.append("missing video stream")
    if not info.has_audio:
        problems.append("missing audio stream")
    if info.width != args.width or info.height != args.height:
        problems.append(f"resolution {info.width}x{info.height}, expected {args.width}x{args.height}")
    if info.duration_s is None or info.duration_s <= 0:
        problems.append("invalid duration")
    if info.bitrate_mbps is None:
        problems.append("missing bitrate")
    elif abs(info.bitrate_mbps - target_mbps) > tolerance:
        problems.append(f"bitrate {info.bitrate_mbps:.2f}Mbps outside {target_mbps:.2f}+/-{tolerance:.2f}")
    return ("pass" if not problems else "fail", problems)


def local_difference_report(
    source_hashes: list[dict[str, str]],
    output_hashes: dict[str, str] | None,
    source_probe: list[ProbeInfo],
    output_probe: ProbeInfo | None,
) -> dict[str, Any]:
    if output_hashes is None or output_probe is None:
        return {
            "status": "not_generated",
            "platform_review_guarantee": False,
            "scope": "local QC only",
        }

    output_matches_source_hash = any(
        output_hashes.get("md5") == item.get("md5") or output_hashes.get("sha256") == item.get("sha256")
        for item in source_hashes
    )
    media_property_changes = []
    if len(source_probe) != 1:
        media_property_changes.append("source_count_changed")
    elif source_probe:
        src = source_probe[0]
        if src.width != output_probe.width or src.height != output_probe.height:
            media_property_changes.append("resolution_changed")
        if src.duration_s is not None and output_probe.duration_s is not None and abs(src.duration_s - output_probe.duration_s) > 0.05:
            media_property_changes.append("duration_changed")
        if src.video_codec != output_probe.video_codec:
            media_property_changes.append("video_codec_changed")
        if src.audio_codec != output_probe.audio_codec:
            media_property_changes.append("audio_codec_changed")

    return {
        "status": "pass" if not output_matches_source_hash else "fail",
        "output_is_byte_identical_to_any_source": output_matches_source_hash,
        "file_hash_changed": not output_matches_source_hash,
        "media_property_changes": media_property_changes,
        "platform_review_guarantee": False,
        "scope": "local non-identity and internal duplicate management only",
        "note": "This report does not predict or bypass external platform matching, copyright review, or anti-abuse systems.",
    }


def extract_cover_candidates(video_path: Path, covers_dir: Path, episode: int, duration_s: float | None, logger: BatchLogger) -> list[Path]:
    if duration_s is None or duration_s <= 0:
        return []

    covers_dir.mkdir(parents=True, exist_ok=True)
    offsets = [max(0.1, duration_s * pct) for pct in (0.18, 0.45, 0.72)]
    results: list[Path] = []
    for index, offset in enumerate(offsets, start=1):
        cover_path = covers_dir / f"episode-{episode:03d}-cover-{index}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{offset:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(cover_path),
        ]
        proc = run(cmd)
        if proc.returncode == 0 and cover_path.exists():
            results.append(cover_path)
    logger.line(f"Episode {episode:03d}: cover candidates {len(results)}")
    return results


def episode_cache_key(
    job: EpisodeJob,
    source_hashes: list[dict[str, str]],
    args: argparse.Namespace,
    choice: EncoderChoice,
) -> str:
    profile = {
        "width": args.width,
        "height": args.height,
        "speed": args.speed,
        "video_bitrate": args.video_bitrate,
        "audio_bitrate": args.audio_bitrate,
        "maxrate": args.maxrate,
        "bufsize": args.bufsize,
        "brightness": args.brightness,
        "contrast": args.contrast,
        "saturation": args.saturation,
    }
    options = {
        "encoder": choice.codec,
        "output_series": args.output_series,
        "metadata_comment": "authorized-release-local-qc",
    }
    return build_cache_key(source_hashes, [asdict(segment) for segment in job.segments], profile, options, "release-pack-v2")


def _record_output(result: EpisodeResult, output_path: Path, args: argparse.Namespace) -> None:
    result.output_hashes = hash_file(output_path)
    result.output_probe = probe_video(output_path)
    result.qc_status, qc_problems = qc_status(result.output_probe, args)
    result.problems.extend(qc_problems)
    result.local_difference = local_difference_report(
        result.source_hashes,
        result.output_hashes,
        result.source_probe,
        result.output_probe,
    )
    if result.qc_status != "pass" or result.local_difference.get("status") != "pass":
        raise RuntimeError("QC/local difference failed")


def _encode_with_fallback(
    input_path: Path,
    output_path: Path,
    source_probe: ProbeInfo,
    args: argparse.Namespace,
    choice: EncoderChoice,
    logger: EpisodeLogger,
) -> EncoderChoice:
    selected_args = copy.copy(args)
    selected_args.encoder_choice = choice
    try:
        encode_episode(input_path, output_path, source_probe, selected_args)
        return choice
    except Exception as exc:
        if not choice.hardware or args.encoder != "auto":
            raise
        software = EncoderChoice(
            mode="software",
            codec="libx264",
            ffmpeg_args=("-c:v", "libx264"),
            hardware=False,
            fallback_reason=str(exc),
        )
        logger.line(f"Episode hardware encode failed; falling back to libx264: {exc}")
        output_path.unlink(missing_ok=True)
        selected_args.encoder_choice = software
        encode_episode(input_path, output_path, source_probe, selected_args)
        return software


def process_episode(job: EpisodeJob, context: EpisodeContext) -> EpisodeResult:
    args = context.args
    logger = EpisodeLogger()
    checkpoint = context.checkpoints.get(job.output_episode)
    if args.resume and should_skip_episode(checkpoint):
        result = episode_result_from_checkpoint(checkpoint or {})
        result.log_lines = [f"Episode {job.output_episode:03d}: checkpoint passed; skipping encode"]
        return result

    result = EpisodeResult(
        episode_number=job.output_episode,
        sources=[str(path) for path in job.source_paths],
        output_path=None,
        status="planned" if args.dry_run else "started",
        qc_status="not_run",
        cache_status="disabled" if context.cache is None else "miss",
        encoder={
            "requested_mode": args.encoder,
            "codec": context.encoder_choice.codec,
            "hardware": context.encoder_choice.hardware,
            "fallback_reason": context.encoder_choice.fallback_reason,
        },
    )
    logger.line(
        f"Remaster: {', '.join(path.name for path in job.source_paths)} -> "
        f"{args.output_series} episode {job.output_episode:03d}"
    )
    try:
        result.source_hashes = [hash_file(path) for path in job.source_paths]
        result.source_probe = [probe_video(path) for path in job.source_paths]
    except Exception as exc:
        result.status = "failed"
        result.qc_status = "fail"
        result.problems.append(str(exc))
        logger.line(f"Episode {job.output_episode:03d}: source probe failed: {exc}")
        result.log_lines = logger.lines
        return result

    output_path = context.videos_dir / f"{slugify(args.output_series)}-episode-{job.output_episode:03d}.mp4"
    result.output_path = str(output_path)
    result.title_candidates = title_candidates(args.output_series, job.output_episode)
    if args.dry_run:
        result.status = "planned"
        result.log_lines = logger.lines
        return result

    choice = context.encoder_choice
    key = episode_cache_key(job, result.source_hashes, args, choice)
    result.cache_key = key
    if context.cache is not None:
        hit = context.cache.lookup(key)
        if hit is not None:
            try:
                context.cache.materialize(hit, output_path)
                _record_output(result, output_path, args)
                result.status = "complete"
                result.cache_status = "hit"
                logger.line(f"Episode {job.output_episode:03d}: validated cache hit; skipping encode")
            except Exception as exc:
                result.problems.append(f"cached output rejected: {exc}")
                result.cache_status = "miss"
                output_path.unlink(missing_ok=True)

    worker_temp = Path(tempfile.mkdtemp(prefix=f"episode-{job.output_episode:03d}-", dir=context.temp_root))
    try:
        if result.status != "complete":
            for attempt in range(1, 3):
                result.attempts = attempt
                try:
                    episode_input = materialize_episode_input(job, worker_temp, logger, args)
                    input_probe = probe_video(episode_input)
                    logger.line(
                        f"Output {args.width}x{args.height}, {args.speed:.3f}x; "
                        f"target bitrate {args.video_bitrate}; metadata normalized for authorized release"
                    )
                    effective_choice = _encode_with_fallback(
                        episode_input,
                        output_path,
                        input_probe,
                        args,
                        choice,
                        logger,
                    )
                    result.encoder = {
                        "requested_mode": args.encoder,
                        "codec": effective_choice.codec,
                        "hardware": effective_choice.hardware,
                        "fallback_reason": effective_choice.fallback_reason,
                    }
                    result.cache_key = episode_cache_key(job, result.source_hashes, args, effective_choice)
                    _record_output(result, output_path, args)
                    result.status = "complete"
                    if context.cache is not None and result.cache_key:
                        context.cache.store(
                            result.cache_key,
                            output_path,
                            validation_status="pass",
                            metadata={"episode": job.output_episode, "encoder": result.encoder},
                        )
                        result.cache_status = "stored"
                    logger.line(
                        f"QC pass; duration: {result.output_probe.duration_s:.2f}s; "
                        f"resolution: {result.output_probe.width}x{result.output_probe.height}; "
                        f"bitrate: {result.output_probe.bitrate_mbps:.2f}Mbps; "
                        f"size: {result.output_probe.size_mb:.2f}MB"
                    )
                    break
                except Exception as exc:
                    result.status = "failed"
                    result.qc_status = "fail"
                    result.problems.append(str(exc))
                    if attempt < 2:
                        logger.line(f"Episode {job.output_episode:03d}: attempt {attempt} failed; retrying: {exc}")
                    else:
                        logger.line(f"Episode {job.output_episode:03d}: failed after {attempt} attempts: {exc}")
        if result.status == "complete" and not args.skip_covers and result.output_probe:
            covers = extract_cover_candidates(
                output_path,
                context.covers_dir,
                job.output_episode,
                result.output_probe.duration_s,
                logger,
            )
            result.cover_candidates = [str(path) for path in covers]
    finally:
        if not args.keep_temp:
            shutil.rmtree(worker_temp, ignore_errors=True)
    result.log_lines = logger.lines
    return result


def make_text_image(path: Path, title: str, lines: list[str]) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        text_path = path.with_suffix(".txt")
        text_path.write_text(title + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return text_path

    width, height = 1200, 900
    image = Image.new("RGB", (width, height), "#f7f7f4")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    y = 64
    draw.text((64, y), title, fill="#1f2933", font=font)
    y += 52
    for line in lines:
        draw.text((64, y), line[:150], fill="#334155", font=font)
        y += 28
        if y > height - 64:
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=92)
    return path


def make_contact_sheet(cover_paths: list[Path], output_path: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    if not cover_paths:
        return None

    thumbs = []
    for path in cover_paths[:12]:
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            continue
        image.thumbnail((180, 320))
        thumbs.append((path, image.copy()))

    if not thumbs:
        return None

    cols = 4
    rows = math.ceil(len(thumbs) / cols)
    cell_w, cell_h = 220, 360
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "#101820")
    draw = ImageDraw.Draw(sheet)
    for index, (path, image) in enumerate(thumbs):
        x = (index % cols) * cell_w + (cell_w - image.width) // 2
        y = (index // cols) * cell_h + 16
        sheet.paste(image, (x, y))
        draw.text((index % cols * cell_w + 16, y + image.height + 8), path.stem[:28], fill="#e5e7eb")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=90)
    return output_path


def title_candidates(series_name: str, episode: int) -> list[str]:
    return [
        f"{series_name} EP{episode:03d}: conflict escalates",
        f"{series_name} EP{episode:03d}: the choice changes everything",
        f"{series_name} EP{episode:03d}: one secret comes out",
    ]


def write_release_queue(path_csv: Path, path_jsonl: Path, rows: list[dict[str, str]]) -> None:
    path_csv.parent.mkdir(parents=True, exist_ok=True)
    with path_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RELEASE_QUEUE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with path_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def call_release_validator(output_root: Path, reports_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    checker = Path(__file__).resolve().with_name("check_release_pack.py")
    json_path = reports_dir / "release_pack_validation.json"
    csv_path = reports_dir / "release_pack_validation.csv"
    cmd = [
        sys.executable,
        str(checker),
        str(output_root / "videos"),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--target-mbps",
        f"{bitrate_to_mbps(args.video_bitrate):.3f}",
        "--tolerance-mbps",
        f"{args.bitrate_tolerance_mbps:.3f}",
        "--json-output",
        str(json_path),
        "--csv-output",
        str(csv_path),
    ]
    proc = run(cmd)
    return {
        "returncode": proc.returncode,
        "json_report": str(json_path) if json_path.exists() else None,
        "csv_report": str(csv_path) if csv_path.exists() else None,
    }


def maybe_install_core_tools() -> None:
    helper = Path(__file__).resolve().with_name("ensure_tools.py")
    proc = run([sys.executable, str(helper), "--install", "--features", "core"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or "core dependency installation failed")


def require_core_tools(install_missing: bool) -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing and install_missing:
        maybe_install_core_tools()
        missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        raise SystemExit("Missing ffmpeg/ffprobe. Run scripts/ensure_tools.py --install --features core")


def build_jobs(args: argparse.Namespace) -> list[EpisodeJob]:
    if getattr(args, "job_document", None) is not None:
        jobs = parse_episode_plan(args.job_document)
        if not jobs:
            raise SystemExit("Job file has no episode plan. Run remaster_job.py plan first.")
        return sorted(jobs, key=lambda item: item.output_episode)

    videos = discover_videos(args.source_root)
    if not videos:
        raise SystemExit(f"No source videos found under {args.source_root}")
    episode_index = build_episode_index(videos)

    if args.mapping_csv:
        jobs = parse_mapping_csv(args.mapping_csv, args.source_root, episode_index)
    else:
        selected = videos[: args.limit] if args.limit else videos
        jobs = [
            EpisodeJob(output_episode=args.episode_start + index, segments=[full_source_segment(path)])
            for index, path in enumerate(selected)
        ]
    return sorted(jobs, key=lambda item: item.output_episode)


def safe_output_root(path: Path, force: bool, dry_run: bool, job_mode: bool = False) -> None:
    if path.exists() and any(path.iterdir()) and not force and not dry_run and not job_mode:
        raise SystemExit(f"Output root is not empty: {path}. Use --force or choose a new folder.")
    path.mkdir(parents=True, exist_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an authorized short-drama release pack with local QC reports.")
    parser.add_argument("source_root", type=Path, nargs="?", help="Folder containing authorized source videos.")
    parser.add_argument("--output-root", type=Path, help="Release-pack output folder.")
    parser.add_argument("--source-series", default="Source Series")
    parser.add_argument("--output-series")
    parser.add_argument("--rights-status", choices=["owned", "licensed", "client-provided", "authorized"])
    parser.add_argument("--job-file", type=Path, help="Durable job JSON created by remaster_job.py.")
    parser.add_argument("--resume", action="store_true", help="Skip hash-matching episodes that already passed QC.")
    parser.add_argument("--mapping-csv", type=Path, help="CSV with output_episode and sources/source_paths columns.")
    parser.add_argument("--episode-start", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--speed", type=float, default=1.05)
    parser.add_argument("--video-bitrate", default="6500k")
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--maxrate", default="7500k")
    parser.add_argument("--bufsize", default="13000k")
    parser.add_argument("--bitrate-tolerance-mbps", type=float, default=1.2)
    parser.add_argument("--brightness", type=float, default=0.01)
    parser.add_argument("--contrast", type=float, default=1.02)
    parser.add_argument("--saturation", type=float, default=1.03)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--workers", default="auto", help="Episode worker count or auto.")
    parser.add_argument("--enhancement-workers", type=int, default=1)
    parser.add_argument("--encoder", choices=["auto", "software", "hardware"], default="auto")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument("--cache", dest="cache", action="store_true", default=True)
    cache_group.add_argument("--no-cache", dest="cache", action="store_false")
    parser.add_argument("--platform", default="WeChat Channels")
    parser.add_argument("--account", default="")
    parser.add_argument("--install-missing", action="store_true")
    parser.add_argument("--skip-covers", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)
    if not args.job_file:
        missing = [
            name
            for name, value in (
                ("source_root", args.source_root),
                ("--output-root", args.output_root),
                ("--output-series", args.output_series),
                ("--rights-status", args.rights_status),
            )
            if value is None
        ]
        if missing:
            parser.error(f"legacy mode requires: {', '.join(missing)}")
    return args


def apply_job_document(args: argparse.Namespace, document: dict[str, Any]) -> argparse.Namespace:
    profile = document.get("profile", {})
    enhancements = document.get("enhancements", {})
    args.source_root = Path(document["source_root"])
    args.output_root = Path(document["output_root"])
    args.source_series = document["source_series"]
    args.output_series = document["output_series"]
    args.rights_status = document["rights_status"]
    args.episode_start = int(document.get("episode_start", 1))
    args.limit = document.get("source_limit")
    args.width = int(profile.get("width", args.width))
    args.height = int(profile.get("height", args.height))
    args.speed = float(profile.get("speed", args.speed))
    args.video_bitrate = profile.get("video_bitrate", args.video_bitrate)
    args.audio_bitrate = profile.get("audio_bitrate", args.audio_bitrate)
    args.maxrate = profile.get("maxrate", args.maxrate)
    args.bufsize = profile.get("bufsize", args.bufsize)
    args.platform = document.get("platform", args.platform)
    args.account = document.get("account", args.account)
    args.skip_covers = not bool(enhancements.get("covers", True))
    execution = document.get("execution", {})
    args.workers = execution.get("workers", args.workers)
    args.enhancement_workers = int(execution.get("enhancement_workers", args.enhancement_workers))
    args.encoder = execution.get("encoder", args.encoder)
    args.cache = bool(execution.get("cache", args.cache))
    args.job_document = document
    return args


def main() -> int:
    args = parse_args()
    args.job_document = None
    if args.job_file:
        args.job_file = args.job_file.expanduser().resolve()
        args = apply_job_document(args, load_job(args.job_file))
    args.source_root = args.source_root.resolve()
    args.output_root = args.output_root.resolve()
    if not args.source_root.exists():
        raise SystemExit(f"Source root does not exist: {args.source_root}")

    require_core_tools(args.install_missing)
    args.encoder_choice = select_encoder(args.encoder)
    safe_output_root(args.output_root, args.force, args.dry_run, job_mode=args.job_file is not None)

    videos_dir = args.output_root / "videos"
    covers_dir = args.output_root / "covers"
    reports_dir = args.output_root / "reports"
    manifests_dir = args.output_root / "manifests"
    logs_dir = args.output_root / "logs"
    evidence_dir = args.output_root / "evidence"
    for folder in (videos_dir, covers_dir, reports_dir, manifests_dir, logs_dir, evidence_dir):
        folder.mkdir(parents=True, exist_ok=True)

    logger = BatchLogger(logs_dir / "batch.log")
    jobs = build_jobs(args)
    logger.line(
        f"{args.source_series} -> {args.output_series}: planned {len(jobs)} episode(s); "
        f"{args.width}x{args.height}, {args.speed:.3f}x, target {args.video_bitrate}"
    )
    logger.line(f"Rights status: {args.rights_status}; platform validation target: {args.platform}")

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(args.source_root),
        "output_root": str(args.output_root),
        "source_series": args.source_series,
        "output_series": args.output_series,
        "rights_status": args.rights_status,
        "platform_target": args.platform,
        "profile": {
            "width": args.width,
            "height": args.height,
            "speed": args.speed,
            "video_bitrate": args.video_bitrate,
            "audio_bitrate": args.audio_bitrate,
            "visual_profile": {
                "brightness": args.brightness,
                "contrast": args.contrast,
                "saturation": args.saturation,
            },
        },
        "execution": {
            "workers": args.workers,
            "enhancement_workers": args.enhancement_workers,
            "encoder": asdict(args.encoder_choice),
            "cache": args.cache,
        },
        "policy": {
            "scope": "authorized release pack and local QC",
            "platform_review_guarantee": False,
            "note": "Local file differences are not a promise of external platform review results.",
        },
        "episodes": [],
    }

    release_rows: list[dict[str, str]] = []
    all_cover_paths: list[Path] = []

    temp_context = tempfile.TemporaryDirectory(prefix="short-drama-pack-")
    temp_dir = Path(temp_context.name)
    checkpoints: dict[int, dict[str, Any]] = {}
    if args.resume and args.job_file:
        checkpoint_document = load_job(args.job_file)
        checkpoints = {int(key): value for key, value in checkpoint_document.get("episodes", {}).items()}
    cache = StageCache(args.output_root / ".job" / "cache") if args.cache and not args.dry_run else None
    context = EpisodeContext(
        args=args,
        videos_dir=videos_dir,
        covers_dir=covers_dir,
        temp_root=temp_dir,
        checkpoints=checkpoints,
        cache=cache,
        encoder_choice=args.encoder_choice,
    )
    worker_count = resolve_worker_count(args.workers)
    logger.line(
        f"Execution: {worker_count} video worker(s); encoder {args.encoder_choice.codec}; "
        f"cache {'enabled' if cache else 'disabled'}"
    )
    try:
        results = execute_episodes(jobs, lambda episode_job: process_episode(episode_job, context), worker_count)
        for result in results:
            for message in result.log_lines:
                logger.line(message)
            if args.job_file:
                update_episode_checkpoint(args.job_file, result)
            if result.cover_candidates:
                all_cover_paths.append(Path(result.cover_candidates[0]))
            cover_path = result.cover_candidates[0] if result.cover_candidates else ""
            release_rows.append(
                {
                    "series_name": args.output_series,
                    "episode_number": f"{result.episode_number:03d}",
                    "video_path": result.output_path or "",
                    "cover_path": cover_path,
                    "title": result.title_candidates[0] if result.title_candidates else "",
                    "description": f"Draft release copy for {args.output_series} episode {result.episode_number:03d}.",
                    "tags": f"{args.output_series},short drama,episode {result.episode_number:03d}",
                    "platform": args.platform,
                    "account": args.account,
                    "status": "draft" if result.status == "complete" else "blocked",
                    "schedule_time": "",
                    "qc_status": result.qc_status,
                    "review_status": "draft",
                    "rights_status": args.rights_status,
                    "notes": f"Generated for authorized release review; cache={result.cache_status}.",
                }
            )
            manifest["episodes"].append(asdict(result))
    finally:
        if args.keep_temp:
            logger.line(f"Temporary files kept: {temp_dir}")
        else:
            temp_context.cleanup()

    write_release_queue(args.output_root / "release_queue.csv", args.output_root / "release_queue.jsonl", release_rows)
    logger.line("Release queue files complete")

    if not args.dry_run:
        validation = call_release_validator(args.output_root, reports_dir, args)
        manifest["release_pack_validation"] = validation
        logger.line("Release pack validation report complete")

    sheet = make_contact_sheet(all_cover_paths, evidence_dir / "process-contact-sheet.jpg")
    if sheet:
        manifest["process_contact_sheet"] = str(sheet)
        logger.line("Process images complete, continuing")

    manifest_path = manifests_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_hash = hash_file(manifest_path)["sha256"]

    timestamp_artifact = make_text_image(
        evidence_dir / f"{slugify(args.output_series)}-timestamp.jpg",
        f"{args.output_series} timestamp certificate",
        [
            f"Generated: {manifest['generated_at']}",
            f"Output folder: {args.output_root}",
            f"Manifest SHA256: {manifest_hash}",
            f"Episodes: {len(jobs)}",
            f"Rights status: {args.rights_status}",
            "Scope: authorized release package and local QC",
        ],
    )
    cost_artifact = make_text_image(
        evidence_dir / "cost-config.jpg",
        "Release pack configuration",
        [
            f"Canvas: {args.width}x{args.height}",
            f"Speed: {args.speed:.3f}x",
            f"Video bitrate: {args.video_bitrate}",
            f"Audio bitrate: {args.audio_bitrate}",
            f"Platform target: {args.platform}",
            "Review guarantee: none",
        ],
    )
    manifest["timestamp_artifact"] = str(timestamp_artifact)
    manifest["cost_artifact"] = str(cost_artifact)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    succeeded = sum(1 for item in manifest["episodes"] if item["status"] == "complete")
    failed = sum(1 for item in manifest["episodes"] if item["status"] == "failed")
    logger.line(f"Batch summary: {succeeded} complete, {failed} failed, {len(jobs)} total")
    print(json.dumps({"output_root": str(args.output_root), "manifest": str(manifest_path), "complete": succeeded, "failed": failed}, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
