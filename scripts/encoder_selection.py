#!/usr/bin/env python3
"""Probe FFmpeg encoders and choose a verified H.264 route."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from media_analysis import CommandResult


@dataclass(frozen=True)
class EncoderChoice:
    mode: str
    codec: str
    ffmpeg_args: tuple[str, ...]
    hardware: bool
    fallback_reason: str | None = None


Runner = Callable[[list[str]], CommandResult]
HARDWARE_CANDIDATES = ("h264_videotoolbox", "h264_nvenc", "h264_qsv")


def run_command(command: list[str]) -> CommandResult:
    process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return CommandResult(process.returncode, process.stdout, process.stderr)


def _software(reason: str | None = None) -> EncoderChoice:
    return EncoderChoice("software", "libx264", ("-c:v", "libx264"), False, reason)


def _encoder_args(codec: str) -> tuple[str, ...]:
    if codec == "h264_videotoolbox":
        return ("-c:v", codec, "-allow_sw", "0")
    return ("-c:v", codec)


def _probe(codec: str, runner: Runner) -> CommandResult:
    return runner(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x284:r=30:d=1",
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            codec,
            "-f",
            "null",
            "-",
        ]
    )


def select_encoder(mode: str, runner: Runner = run_command) -> EncoderChoice:
    normalized = mode.strip().lower()
    if normalized not in {"auto", "software", "hardware"}:
        raise ValueError("encoder mode must be auto, software, or hardware")
    if normalized == "software":
        return _software()

    listing = runner(["ffmpeg", "-hide_banner", "-encoders"])
    available = {
        candidate
        for candidate in HARDWARE_CANDIDATES
        if re.search(rf"\b{re.escape(candidate)}\b", listing.stdout + "\n" + listing.stderr)
    }
    failures: list[str] = []
    for codec in HARDWARE_CANDIDATES:
        if codec not in available:
            continue
        probe = _probe(codec, runner)
        if probe.returncode == 0:
            return EncoderChoice("hardware", codec, _encoder_args(codec), True)
        failures.append(f"probe failed for {codec}: {(probe.stderr or probe.stdout).strip()}")

    reason = "; ".join(failures) if failures else "no supported hardware encoder was reported by FFmpeg"
    if normalized == "hardware":
        raise RuntimeError(f"hardware encoder unavailable: {reason}")
    return _software(reason)
