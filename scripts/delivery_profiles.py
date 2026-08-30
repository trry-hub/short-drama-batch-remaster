#!/usr/bin/env python3
"""Versioned local delivery profiles for release-readiness checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DeliveryProfile:
    name: str
    version: int
    width: int
    height: int
    video_codec: str
    audio_codec: str
    target_bitrate_mbps: float
    bitrate_tolerance_mbps: float
    min_frame_rate: float
    max_frame_rate: float
    max_file_size_mb: float | None
    loudness_lufs: float
    true_peak_db: float
    max_black_s: float
    max_freeze_s: float
    max_silence_s: float
    require_cover_for_publish: bool
    require_metadata_for_publish: bool
    require_ai_label_when_ai: bool
    auto_repairable_rule_ids: tuple[str, ...]
    source_url: str | None
    source_date: str
    verified_fields: tuple[str, ...]
    platform_approval_guarantee: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_PROFILES = {
    ("video-channels", 1): DeliveryProfile(
        name="video-channels",
        version=1,
        width=1080,
        height=1920,
        video_codec="h264",
        audio_codec="aac",
        target_bitrate_mbps=6.5,
        bitrate_tolerance_mbps=1.2,
        min_frame_rate=24.0,
        max_frame_rate=60.0,
        max_file_size_mb=None,
        loudness_lufs=-16.0,
        true_peak_db=-1.5,
        max_black_s=1.0,
        max_freeze_s=2.0,
        max_silence_s=3.0,
        require_cover_for_publish=False,
        require_metadata_for_publish=True,
        require_ai_label_when_ai=True,
        auto_repairable_rule_ids=(
            "media.geometry",
            "media.codec",
            "audio.loudness",
        ),
        source_url="https://www.cac.gov.cn/2026-05/12/c_1780328273108117.htm",
        source_date="2026-08-30",
        verified_fields=("content_labels", "ai_disclosure"),
    )
}


def load_delivery_profile(name: str, version: int = 1) -> DeliveryProfile:
    key = (name.strip().lower(), version)
    try:
        return BUILTIN_PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported delivery profile: {name}@{version}") from exc
