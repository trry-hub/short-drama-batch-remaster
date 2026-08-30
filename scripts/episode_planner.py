#!/usr/bin/env python3
"""Chronological episode planning over files, scenes, and time ranges."""

from __future__ import annotations

import csv
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


EPSILON = 1e-6


@dataclass(frozen=True)
class SourceMedia:
    path: str
    duration_s: float
    scene_changes_s: tuple[float, ...] = ()


@dataclass(frozen=True)
class SourceSegment:
    path: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TimelineItem:
    path: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Timeline:
    items: tuple[TimelineItem, ...]
    boundaries: tuple[float, ...]
    total_duration_s: float


@dataclass(frozen=True)
class PlannedEpisode:
    output_episode: int
    segments: tuple[SourceSegment, ...]
    estimated_duration_s: float
    short_final: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_episode": self.output_episode,
            "segments": [segment.to_dict() for segment in self.segments],
            "estimated_duration_s": self.estimated_duration_s,
            "short_final": self.short_final,
        }


def _build_timeline(media: Sequence[SourceMedia]) -> Timeline:
    items: list[TimelineItem] = []
    boundaries: set[float] = set()
    cursor = 0.0
    for source in media:
        if source.duration_s <= 0:
            raise ValueError(f"source duration must be greater than zero: {source.path}")
        start = cursor
        end = start + source.duration_s
        items.append(TimelineItem(source.path, start, end))
        for scene in source.scene_changes_s:
            if EPSILON < scene < source.duration_s - EPSILON:
                boundaries.add(round(start + scene, 6))
        boundaries.add(round(end, 6))
        cursor = end
    return Timeline(tuple(items), tuple(sorted(boundaries)), cursor)


def _segments_for_range(timeline: Timeline, start_s: float, end_s: float) -> list[SourceSegment]:
    segments: list[SourceSegment] = []
    for item in timeline.items:
        overlap_start = max(start_s, item.start_s)
        overlap_end = min(end_s, item.end_s)
        if overlap_end - overlap_start <= EPSILON:
            continue
        segments.append(
            SourceSegment(
                path=item.path,
                start_s=round(overlap_start - item.start_s, 6),
                end_s=round(overlap_end - item.start_s, 6),
            )
        )
    return segments


def plan_one_to_one(media: Sequence[SourceMedia], *, speed: float, episode_start: int) -> list[PlannedEpisode]:
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    if episode_start <= 0:
        raise ValueError("episode start must be greater than zero")
    return [
        PlannedEpisode(
            output_episode=episode_start + index,
            segments=(SourceSegment(source.path, 0.0, source.duration_s),),
            estimated_duration_s=round(source.duration_s / speed, 3),
        )
        for index, source in enumerate(media)
    ]


def plan_target_duration(
    media: Sequence[SourceMedia],
    target_duration_s: float,
    min_duration_s: float,
    max_duration_s: float,
    *,
    speed: float,
    episode_start: int,
) -> list[PlannedEpisode]:
    if not 0 < min_duration_s <= target_duration_s <= max_duration_s:
        raise ValueError("duration band must satisfy 0 < min <= target <= max")
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    if episode_start <= 0:
        raise ValueError("episode start must be greater than zero")

    timeline = _build_timeline(media)
    total_source_s = timeline.total_duration_s
    cursor = 0.0
    output_episode = episode_start
    result: list[PlannedEpisode] = []
    while cursor < total_source_s - EPSILON:
        remaining_final_s = (total_source_s - cursor) / speed
        if remaining_final_s <= max_duration_s + EPSILON:
            cut = total_source_s
        else:
            lower = cursor + min_duration_s * speed
            desired = cursor + target_duration_s * speed
            upper = min(total_source_s, cursor + max_duration_s * speed)
            candidates = [boundary for boundary in timeline.boundaries if lower - EPSILON <= boundary <= upper + EPSILON]
            cut = min(candidates, key=lambda value: (abs(value - desired), value)) if candidates else upper

        segments = tuple(_segments_for_range(timeline, cursor, cut))
        final_duration = (cut - cursor) / speed
        result.append(
            PlannedEpisode(
                output_episode=output_episode,
                segments=segments,
                estimated_duration_s=round(final_duration, 3),
                short_final=final_duration < min_duration_s - EPSILON,
            )
        )
        cursor = cut
        output_episode += 1
    return result


def probe_scene_changes(path: Path, threshold: float = 0.35) -> tuple[float, ...]:
    if not 0 < threshold < 1:
        raise ValueError("scene threshold must be between zero and one")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-filter:v",
        f"select=gt(scene\\,{threshold:.6f}),showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"scene detection failed for {path}")
    values = {float(match) for match in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", proc.stdout)}
    return tuple(sorted(values))


def write_episode_plan_csv(path: Path, episodes: Sequence[PlannedEpisode]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["output_episode", "estimated_duration_s", "short_final", "segments"],
        )
        writer.writeheader()
        for episode in episodes:
            segments = "+".join(
                f"{segment.path}@{segment.start_s:.3f}-{segment.end_s:.3f}" for segment in episode.segments
            )
            writer.writerow(
                {
                    "output_episode": episode.output_episode,
                    "estimated_duration_s": f"{episode.estimated_duration_s:.3f}",
                    "short_final": str(episode.short_final).lower(),
                    "segments": segments,
                }
            )
