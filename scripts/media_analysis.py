#!/usr/bin/env python3
"""FFmpeg-backed media analysis for local release-readiness evidence."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from delivery_profiles import DeliveryProfile
from release_readiness import RuleResult


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MediaAnalysis:
    path: str
    readable: bool = False
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    bitrate_mbps: float | None = None
    size_mb: float | None = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    pixel_format: str | None = None
    black_ranges: tuple[tuple[float, float], ...] = ()
    freeze_ranges: tuple[tuple[float, float], ...] = ()
    silence_ranges: tuple[tuple[float, float], ...] = ()
    integrated_lufs: float | None = None
    true_peak_db: float | None = None
    decode_errors: tuple[str, ...] = ()
    analysis_warnings: tuple[str, ...] = ()


Runner = Callable[[list[str]], CommandResult]


def run_command(command: list[str]) -> CommandResult:
    try:
        process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(127, "", str(exc))
    return CommandResult(process.returncode, process.stdout, process.stderr)


def _number(value: object, divisor: float = 1.0) -> float | None:
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return None


def _frame_rate(value: object) -> float | None:
    text = str(value or "")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        bottom = _number(denominator)
        top = _number(numerator)
        if top is None or not bottom:
            return None
        return top / bottom
    return _number(text)


def _paired_ranges(text: str, start_name: str, end_name: str) -> tuple[tuple[float, float], ...]:
    starts = [float(value) for value in re.findall(rf"{re.escape(start_name)}\s*:\s*(-?\d+(?:\.\d+)?)", text)]
    ends = [float(value) for value in re.findall(rf"{re.escape(end_name)}\s*:\s*(-?\d+(?:\.\d+)?)", text)]
    return tuple((start, end) for start, end in zip(starts, ends) if end >= start)


def _loudness(text: str) -> tuple[float | None, float | None]:
    candidates = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, flags=re.DOTALL)
    if not candidates:
        return None, None
    try:
        payload = json.loads(candidates[-1])
    except json.JSONDecodeError:
        return None, None
    return _number(payload.get("input_i")), _number(payload.get("input_tp"))


def _analysis_command(path: Path, *, video_filter: str | None = None, audio_filter: str | None = None) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-i", str(path)]
    if video_filter:
        command.extend(["-vf", video_filter, "-an"])
    if audio_filter:
        command.extend(["-af", audio_filter, "-vn"])
    command.extend(["-f", "null", "-"])
    return command


def analyze_media(path: Path, runner: Runner = run_command) -> MediaAnalysis:
    probe = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    if probe.returncode != 0:
        return MediaAnalysis(
            path=str(path),
            readable=False,
            decode_errors=tuple(line for line in probe.stderr.splitlines() if line.strip()),
        )
    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        return MediaAnalysis(path=str(path), readable=False, decode_errors=(str(exc),))

    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    container = payload.get("format", {})
    warnings: list[str] = []

    analyses = {
        "black": runner(_analysis_command(path, video_filter="blackdetect=d=1.0:pix_th=0.10")),
        "freeze": runner(_analysis_command(path, video_filter="freezedetect=n=-50dB:d=2.0")),
        "silence": runner(_analysis_command(path, audio_filter="silencedetect=n=-50dB:d=3.0")),
        "loudness": runner(_analysis_command(path, audio_filter="loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json")),
    }
    for name, result in analyses.items():
        if result.returncode != 0:
            warnings.append(f"{name} analysis failed: {(result.stderr or result.stdout).strip()}")

    decode = runner(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"])
    decode_text = "\n".join(part for part in (decode.stdout, decode.stderr) if part).strip()
    decode_errors = tuple(line.strip() for line in decode_text.splitlines() if line.strip())
    if decode.returncode != 0 and not decode_errors:
        decode_errors = (f"decode command exited {decode.returncode}",)

    def output(name: str) -> str:
        result = analyses[name]
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    integrated_lufs, true_peak_db = _loudness(output("loudness"))
    return MediaAnalysis(
        path=str(path),
        readable=True,
        duration_s=_number(container.get("duration")),
        width=video.get("width"),
        height=video.get("height"),
        frame_rate=_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        bitrate_mbps=_number(container.get("bit_rate"), 1_000_000),
        size_mb=_number(container.get("size"), 1024 * 1024),
        has_video=bool(video),
        has_audio=bool(audio),
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        pixel_format=video.get("pix_fmt"),
        black_ranges=_paired_ranges(output("black"), "black_start", "black_end"),
        freeze_ranges=_paired_ranges(output("freeze"), "freeze_start", "freeze_end"),
        silence_ranges=_paired_ranges(output("silence"), "silence_start", "silence_end"),
        integrated_lufs=integrated_lufs,
        true_peak_db=true_peak_db,
        decode_errors=decode_errors,
        analysis_warnings=tuple(warnings),
    )


def _result(
    rule_id: str,
    passed: bool,
    evidence: str,
    remediation: str,
    severity: str = "warning",
) -> RuleResult:
    return RuleResult(rule_id, severity, "pass" if passed else "fail", evidence, "" if passed else remediation)


def _longest(ranges: tuple[tuple[float, float], ...]) -> float:
    return max((end - start for start, end in ranges), default=0.0)


def media_rules(analysis: MediaAnalysis, profile: DeliveryProfile) -> list[RuleResult]:
    bitrate_ok = analysis.bitrate_mbps is not None and abs(analysis.bitrate_mbps - profile.target_bitrate_mbps) <= profile.bitrate_tolerance_mbps
    frame_rate_ok = analysis.frame_rate is not None and profile.min_frame_rate <= analysis.frame_rate <= profile.max_frame_rate
    loudness_ok = analysis.integrated_lufs is not None and abs(analysis.integrated_lufs - profile.loudness_lufs) <= 2.0
    file_size_ok = profile.max_file_size_mb is None or (
        analysis.size_mb is not None and analysis.size_mb <= profile.max_file_size_mb
    )
    return [
        _result("media.readable", analysis.readable, f"readable={analysis.readable}", "replace or repair the unreadable file", "blocker"),
        _result(
            "media.streams",
            analysis.has_video and analysis.has_audio,
            f"video={analysis.has_video}; audio={analysis.has_audio}",
            "provide both a video stream and an audio stream",
            "blocker",
        ),
        _result(
            "media.geometry",
            (analysis.width, analysis.height) == (profile.width, profile.height),
            f"actual={analysis.width}x{analysis.height}; expected={profile.width}x{profile.height}",
            "re-encode to the selected delivery geometry",
            "blocker",
        ),
        _result(
            "media.codec",
            (analysis.video_codec, analysis.audio_codec) == (profile.video_codec, profile.audio_codec),
            f"actual={analysis.video_codec}/{analysis.audio_codec}; expected={profile.video_codec}/{profile.audio_codec}",
            "re-encode with the selected video and audio codecs",
            "blocker",
        ),
        _result("media.frame_rate", frame_rate_ok, f"frame_rate={analysis.frame_rate}", "use a frame rate inside the selected profile"),
        _result(
            "media.bitrate",
            bitrate_ok,
            f"bitrate={analysis.bitrate_mbps}; target={profile.target_bitrate_mbps}±{profile.bitrate_tolerance_mbps}Mbps",
            "adjust the video bitrate target",
        ),
        _result("media.file_size", file_size_ok, f"size_mb={analysis.size_mb}; max={profile.max_file_size_mb}", "reduce file size"),
        _result(
            "audio.loudness",
            loudness_ok,
            f"integrated_lufs={analysis.integrated_lufs}; target={profile.loudness_lufs}±2",
            "normalize audio loudness and re-check true peak",
        ),
        _result(
            "video.black",
            _longest(analysis.black_ranges) <= profile.max_black_s,
            f"longest_black_s={_longest(analysis.black_ranges):.3f}",
            "review or trim the extended black section",
        ),
        _result(
            "video.freeze",
            _longest(analysis.freeze_ranges) <= profile.max_freeze_s,
            f"longest_freeze_s={_longest(analysis.freeze_ranges):.3f}",
            "review the extended frozen section",
        ),
        _result(
            "audio.silence",
            _longest(analysis.silence_ranges) <= profile.max_silence_s,
            f"longest_silence_s={_longest(analysis.silence_ranges):.3f}",
            "review the extended silent section",
        ),
        _result(
            "media.decode",
            not analysis.decode_errors,
            "; ".join(analysis.decode_errors) or "no decode errors",
            "repair or re-encode the damaged media",
            "blocker",
        ),
        _result(
            "media.analysis",
            not analysis.analysis_warnings,
            "; ".join(analysis.analysis_warnings) or "all analyzers completed",
            "install or repair the required FFmpeg analyzers",
        ),
    ]
