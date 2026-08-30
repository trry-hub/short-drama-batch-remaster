#!/usr/bin/env python3
"""Build an authorized short-drama release pack from local source videos.

This tool is intentionally scoped to release-package production and local QC.
It can prove that an output file is not a byte-identical copy of its source
inputs, but it does not claim to bypass or predict any platform review system.
"""

from __future__ import annotations

import argparse
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
    sources: list[Path]


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
            jobs.append(EpisodeJob(output_episode=output_episode, sources=sources))
    return jobs


def hash_file(path: Path) -> dict[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


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


def encode_episode(input_path: Path, output_path: Path, source_probe: ProbeInfo, args: argparse.Namespace) -> None:
    video_chain = (
        f"setpts=PTS/{args.speed:.6f},"
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
        f"crop={args.width}:{args.height},"
        f"eq=contrast={args.contrast:.4f}:brightness={args.brightness:.4f}:saturation={args.saturation:.4f},"
        "format=yuv420p"
    )
    common_output = [
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
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
    videos = discover_videos(args.source_root)
    if not videos:
        raise SystemExit(f"No source videos found under {args.source_root}")
    episode_index = build_episode_index(videos)

    if args.mapping_csv:
        jobs = parse_mapping_csv(args.mapping_csv, args.source_root, episode_index)
    else:
        selected = videos[: args.limit] if args.limit else videos
        jobs = [EpisodeJob(output_episode=args.episode_start + index, sources=[path]) for index, path in enumerate(selected)]
    return sorted(jobs, key=lambda item: item.output_episode)


def safe_output_root(path: Path, force: bool, dry_run: bool) -> None:
    if path.exists() and any(path.iterdir()) and not force and not dry_run:
        raise SystemExit(f"Output root is not empty: {path}. Use --force or choose a new folder.")
    path.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an authorized short-drama release pack with local QC reports.")
    parser.add_argument("source_root", type=Path, help="Folder containing authorized source videos.")
    parser.add_argument("--output-root", type=Path, required=True, help="Release-pack output folder.")
    parser.add_argument("--source-series", default="Source Series")
    parser.add_argument("--output-series", required=True)
    parser.add_argument("--rights-status", required=True, choices=["owned", "licensed", "client-provided", "authorized"])
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
    parser.add_argument("--platform", default="WeChat Channels")
    parser.add_argument("--account", default="")
    parser.add_argument("--install-missing", action="store_true")
    parser.add_argument("--skip-covers", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.source_root = args.source_root.resolve()
    args.output_root = args.output_root.resolve()
    if not args.source_root.exists():
        raise SystemExit(f"Source root does not exist: {args.source_root}")

    require_core_tools(args.install_missing)
    safe_output_root(args.output_root, args.force, args.dry_run)

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

    try:
        for job in jobs:
            result = EpisodeResult(
                episode_number=job.output_episode,
                sources=[str(path) for path in job.sources],
                output_path=None,
                status="planned" if args.dry_run else "started",
                qc_status="not_run",
            )
            logger.line(
                f"Remaster: {', '.join(path.name for path in job.sources)} -> "
                f"{args.output_series} episode {job.output_episode:03d}"
            )

            try:
                result.source_hashes = [hash_file(path) for path in job.sources]
                result.source_probe = [probe_video(path) for path in job.sources]
            except Exception as exc:
                result.status = "failed"
                result.problems.append(str(exc))
                logger.line(f"Episode {job.output_episode:03d}: source probe failed: {exc}")
                manifest["episodes"].append(asdict(result))
                continue

            output_path = videos_dir / f"{slugify(args.output_series)}-episode-{job.output_episode:03d}.mp4"
            result.output_path = str(output_path)
            result.title_candidates = title_candidates(args.output_series, job.output_episode)

            if args.dry_run:
                result.status = "planned"
                manifest["episodes"].append(asdict(result))
                continue

            try:
                concat_input = make_concat_input(job.sources, temp_dir, logger, job.output_episode)
                concat_probe = probe_video(concat_input)
                logger.line(
                    f"Output {args.width}x{args.height}, {args.speed:.3f}x; "
                    f"target bitrate {args.video_bitrate}; metadata normalized for authorized release"
                )
                encode_episode(concat_input, output_path, concat_probe, args)
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
                if result.qc_status == "pass" and result.local_difference.get("status") == "pass":
                    result.status = "complete"
                    logger.line(
                        f"QC pass; duration: {result.output_probe.duration_s:.2f}s; "
                        f"resolution: {result.output_probe.width}x{result.output_probe.height}; "
                        f"bitrate: {result.output_probe.bitrate_mbps:.2f}Mbps; "
                        f"size: {result.output_probe.size_mb:.2f}MB"
                    )
                else:
                    result.status = "failed"
                    logger.line(f"Episode {job.output_episode:03d}: QC/local difference failed")

                if not args.skip_covers and result.output_probe:
                    covers = extract_cover_candidates(
                        output_path,
                        covers_dir,
                        job.output_episode,
                        result.output_probe.duration_s,
                        logger,
                    )
                    result.cover_candidates = [str(path) for path in covers]
                    all_cover_paths.extend(covers[:1])
            except Exception as exc:
                result.status = "failed"
                result.qc_status = "fail"
                result.problems.append(str(exc))
                logger.line(f"Episode {job.output_episode:03d}: failed: {exc}")

            cover_path = result.cover_candidates[0] if result.cover_candidates else ""
            release_rows.append(
                {
                    "series_name": args.output_series,
                    "episode_number": f"{job.output_episode:03d}",
                    "video_path": result.output_path or "",
                    "cover_path": cover_path,
                    "title": result.title_candidates[0] if result.title_candidates else "",
                    "description": f"Draft release copy for {args.output_series} episode {job.output_episode:03d}.",
                    "tags": f"{args.output_series},short drama,episode {job.output_episode:03d}",
                    "platform": args.platform,
                    "account": args.account,
                    "status": "draft" if result.status == "complete" else "blocked",
                    "schedule_time": "",
                    "qc_status": result.qc_status,
                    "review_status": "draft",
                    "rights_status": args.rights_status,
                    "notes": "Generated for authorized release review.",
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
