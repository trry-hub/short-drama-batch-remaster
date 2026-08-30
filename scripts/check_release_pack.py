#!/usr/bin/env python3
"""Validate MP4 files in a short-drama release folder with ffprobe."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class VideoReport:
    path: str
    ok: bool
    duration_s: float | None
    width: int | None
    height: int | None
    bitrate_mbps: float | None
    size_mb: float
    has_video: bool
    has_audio: bool
    problems: list[str]


def run_ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:stream=codec_type,width,height,codec_name",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ffprobe failed")
    return json.loads(proc.stdout)


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_video(path: Path, width: int, height: int, target_mbps: float, tolerance_mbps: float) -> VideoReport:
    problems: list[str] = []
    duration_s: float | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    bitrate_mbps: float | None = None
    has_video = False
    has_audio = False
    size_mb = path.stat().st_size / 1024 / 1024

    try:
        info = run_ffprobe(path)
    except Exception as exc:
        return VideoReport(str(path), False, None, None, None, None, size_mb, False, False, [str(exc)])

    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and not has_video:
            has_video = True
            actual_width = int(stream.get("width") or 0) or None
            actual_height = int(stream.get("height") or 0) or None
        elif stream.get("codec_type") == "audio":
            has_audio = True

    fmt = info.get("format", {})
    duration_s = to_float(fmt.get("duration"))
    bit_rate = to_float(fmt.get("bit_rate"))
    if bit_rate is not None:
        bitrate_mbps = bit_rate / 1_000_000

    if not has_video:
        problems.append("missing video stream")
    if not has_audio:
        problems.append("missing audio stream")
    if actual_width != width or actual_height != height:
        problems.append(f"resolution {actual_width}x{actual_height}, expected {width}x{height}")
    if duration_s is None or duration_s <= 0:
        problems.append("invalid duration")
    if bitrate_mbps is None:
        problems.append("missing bitrate")
    elif abs(bitrate_mbps - target_mbps) > tolerance_mbps:
        problems.append(f"bitrate {bitrate_mbps:.2f}Mbps outside target {target_mbps:.2f}+/-{tolerance_mbps:.2f}")
    if size_mb <= 0:
        problems.append("empty file")

    return VideoReport(
        path=str(path),
        ok=not problems,
        duration_s=duration_s,
        width=actual_width,
        height=actual_height,
        bitrate_mbps=bitrate_mbps,
        size_mb=size_mb,
        has_video=has_video,
        has_audio=has_audio,
        problems=problems,
    )


def write_csv(path: Path, reports: list[VideoReport]) -> None:
    fields = list(asdict(reports[0]).keys()) if reports else list(VideoReport.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            row = asdict(report)
            row["problems"] = "; ".join(report.problems)
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a short-drama MP4 release folder.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--target-mbps", type=float, default=6.5)
    parser.add_argument("--tolerance-mbps", type=float, default=1.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    args = parser.parse_args()

    if not shutil.which("ffprobe"):
        raise SystemExit("ffprobe is required. Run scripts/ensure_tools.py --install --features core")

    videos = sorted(args.folder.rglob("*.mp4"))
    reports = [validate_video(path, args.width, args.height, args.target_mbps, args.tolerance_mbps) for path in videos]
    payload = {
        "folder": str(args.folder),
        "total": len(reports),
        "passed": sum(1 for report in reports if report.ok),
        "failed": sum(1 for report in reports if not report.ok),
        "reports": [asdict(report) for report in reports],
    }

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.csv_output:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.csv_output, reports)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
