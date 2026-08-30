#!/usr/bin/env python3
"""Optional, provenance-rich content enhancement assets for authorized videos."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import srt


class NeedsInput(RuntimeError):
    """Raised when a requested optional stage needs user-provided material."""


@dataclass(frozen=True)
class TranscriptSegment:
    start_s: float
    end_s: float
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class EnhancementArtifact:
    kind: str
    path: str
    source_episode: int
    tool: str
    parameters: dict[str, Any]
    created_at: str
    review_status: Literal["needs_review", "approved", "rejected"] = "needs_review"


@dataclass(frozen=True)
class EnhancementRequest:
    episode: int
    video_path: Path
    output_root: Path
    subtitles: bool
    covers: bool
    copy: bool
    narration: bool
    editorial_recommendations: bool
    narration_script: Path | None = None
    narration_script_approved: bool = False


@dataclass
class AdapterBundle:
    transcribe: Callable[[Path], list[TranscriptSegment]]
    extract_covers: Callable[[Path, Path, int], list[Path]]
    narrate: Callable[[str, Path], Path]
    scene_boundaries: Callable[[Path], list[float]]
    names: dict[str, str] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _artifact(kind: str, path: Path, request: EnhancementRequest, tool: str, **parameters: Any) -> EnhancementArtifact:
    return EnhancementArtifact(
        kind=kind,
        path=str(path),
        source_episode=request.episode,
        tool=tool,
        parameters=parameters,
        created_at=_now(),
    )


def _write_subtitles(
    request: EnhancementRequest,
    segments: list[TranscriptSegment],
    tool: str,
) -> list[EnhancementArtifact]:
    output_dir = request.output_root / "subtitles"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"episode-{request.episode:03d}"
    subtitles = [
        srt.Subtitle(
            index=index,
            start=timedelta(seconds=segment.start_s),
            end=timedelta(seconds=segment.end_s),
            content=segment.text.strip(),
        )
        for index, segment in enumerate(segments, start=1)
    ]
    srt_path = output_dir / f"{stem}.srt"
    srt_path.write_text(srt.compose(subtitles), encoding="utf-8")

    vtt_lines = ["WEBVTT", ""]
    for segment in segments:
        start = srt.timedelta_to_srt_timestamp(timedelta(seconds=segment.start_s)).replace(",", ".")
        end = srt.timedelta_to_srt_timestamp(timedelta(seconds=segment.end_s)).replace(",", ".")
        vtt_lines.extend((f"{start} --> {end}", segment.text.strip(), ""))
    vtt_path = output_dir / f"{stem}.vtt"
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    transcript_path = output_dir / f"{stem}.txt"
    transcript_path.write_text("\n".join(segment.text.strip() for segment in segments) + "\n", encoding="utf-8")
    parameters = {
        "segments": len(segments),
        "confidence_available": any(segment.confidence is not None for segment in segments),
    }
    return [
        _artifact("srt", srt_path, request, tool, **parameters),
        _artifact("vtt", vtt_path, request, tool, **parameters),
        _artifact("transcript", transcript_path, request, tool, **parameters),
    ]


def _write_copy(request: EnhancementRequest, segments: list[TranscriptSegment]) -> EnhancementArtifact:
    output_dir = request.output_root / "copy"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"episode-{request.episode:03d}.json"
    transcript = "".join(segment.text.strip() for segment in segments)
    hook = transcript[:36].strip("，。！？,.!?")
    payload = {
        "episode": request.episode,
        "title_candidates": [
            f"第{request.episode}集 {hook}" if hook else f"第{request.episode}集",
            f"剧情继续：第{request.episode}集",
            f"第{request.episode}集关键情节",
        ],
        "description_draft": transcript[:160],
        "tags_draft": ["短剧", f"第{request.episode}集"],
        "review_status": "needs_review",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _artifact("copy", path, request, "deterministic-copy-draft", transcript_chars=len(transcript))


def _write_editorial_recommendations(
    request: EnhancementRequest,
    boundaries: list[float],
    segments: list[TranscriptSegment],
    tool: str,
) -> EnhancementArtifact:
    output_dir = request.output_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"episode-{request.episode:03d}-editorial-recommendations.json"
    ordered = sorted(set(max(0.0, float(value)) for value in boundaries))
    long_shots = [
        {"start_s": start, "end_s": end, "duration_s": round(end - start, 3)}
        for start, end in zip(ordered, ordered[1:])
        if end - start > 8.0
    ]
    dense_subtitles = [
        {
            "start_s": segment.start_s,
            "end_s": segment.end_s,
            "characters_per_second": round(len(segment.text) / max(0.1, segment.end_s - segment.start_s), 2),
        }
        for segment in segments
        if len(segment.text) / max(0.1, segment.end_s - segment.start_s) > 12.0
    ]
    payload = {
        "episode": request.episode,
        "scene_boundaries_s": ordered,
        "long_shots": long_shots,
        "dense_subtitle_windows": dense_subtitles,
        "suggestions": [
            "Review long shots for pacing while preserving plot order.",
            "Review dense subtitle windows for readability.",
        ],
        "scene_order_changed": False,
        "review_status": "needs_review",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _artifact(
        "editorial_recommendations",
        path,
        request,
        tool,
        scene_count=max(0, len(ordered) - 1),
    )


def enhance_episode(request: EnhancementRequest, adapters: AdapterBundle | None = None) -> list[EnhancementArtifact]:
    adapters = adapters or default_adapters()
    artifacts: list[EnhancementArtifact] = []
    segments: list[TranscriptSegment] = []
    if request.subtitles or request.copy:
        try:
            segments = adapters.transcribe(request.video_path)
        except NeedsInput:
            raise
        except Exception as exc:
            raise NeedsInput(f"subtitle transcription is unavailable: {exc}") from exc
    if request.subtitles:
        artifacts.extend(_write_subtitles(request, segments, adapters.names.get("transcribe", "speech-recognition")))
    if request.covers:
        paths = adapters.extract_covers(request.video_path, request.output_root / "covers", request.episode)
        for index, path in enumerate(paths, start=1):
            artifacts.append(_artifact("cover", path, request, adapters.names.get("covers", "ffmpeg-cover-ranking"), rank=index))
    if request.copy:
        artifacts.append(_write_copy(request, segments))
    if request.narration:
        if request.narration_script is None or not request.narration_script.is_file() or not request.narration_script_approved:
            raise NeedsInput("an approved narration script is required")
        text = request.narration_script.read_text(encoding="utf-8").strip()
        if not text:
            raise NeedsInput("an approved narration script is required and cannot be empty")
        narration_path = request.output_root / "narration" / f"episode-{request.episode:03d}.m4a"
        produced = adapters.narrate(text, narration_path)
        artifacts.append(
            _artifact(
                "narration",
                produced,
                request,
                adapters.names.get("narrate", "configured-tts"),
                script=str(request.narration_script),
                mixed=False,
            )
        )
    if request.editorial_recommendations:
        boundaries = adapters.scene_boundaries(request.video_path)
        artifacts.append(
            _write_editorial_recommendations(
                request,
                boundaries,
                segments,
                adapters.names.get("scenes", "ffmpeg-scene-analysis"),
            )
        )
    return artifacts


def _default_transcribe(path: Path) -> list[TranscriptSegment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise NeedsInput("install faster-whisper or Whisper to generate subtitle drafts") from exc
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(path), vad_filter=True)
    return [
        TranscriptSegment(float(item.start), float(item.end), item.text.strip(), getattr(item, "avg_logprob", None))
        for item in segments
        if item.text.strip()
    ]


def _probe_duration(path: Path) -> float:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "ffprobe failed")
    return float(process.stdout.strip())


def _image_score(path: Path) -> tuple[bool, float]:
    try:
        import cv2
    except ImportError:
        return True, float(path.stat().st_size)
    image = cv2.imread(str(path))
    if image is None:
        return False, 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return brightness >= 10.0 and sharpness >= 20.0, sharpness


def _default_covers(video: Path, output_dir: Path, episode: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(video)
    candidates: list[tuple[Path, bool, float]] = []
    for index, ratio in enumerate((0.12, 0.27, 0.42, 0.58, 0.73, 0.88), start=1):
        path = output_dir / f"episode-{episode:03d}-candidate-{index}.jpg"
        process = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{duration * ratio:.3f}", "-i", str(video), "-frames:v", "1", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.returncode == 0 and path.is_file():
            accepted, score = _image_score(path)
            candidates.append((path, accepted, score))
    selected = sorted((item for item in candidates if item[1]), key=lambda item: item[2], reverse=True)
    if not selected:
        selected = sorted(candidates, key=lambda item: item[2], reverse=True)
    return [item[0] for item in selected[:3]]


def _default_narrate(text: str, output_path: Path) -> Path:
    if not shutil.which("say"):
        raise NeedsInput("no configured narration provider is available")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="narration-") as raw:
        text_path = Path(raw) / "script.txt"
        audio_path = Path(raw) / "speech.aiff"
        text_path.write_text(text, encoding="utf-8")
        say = subprocess.run(["say", "-f", str(text_path), "-o", str(audio_path)], capture_output=True, text=True)
        if say.returncode != 0:
            raise NeedsInput(say.stderr.strip() or "macOS narration synthesis failed")
        encode = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(audio_path), "-c:a", "aac", "-b:a", "192k", str(output_path)],
            capture_output=True,
            text=True,
        )
        if encode.returncode != 0:
            raise NeedsInput(encode.stderr.strip() or "narration audio encoding failed")
    return output_path


def _default_scene_boundaries(path: Path) -> list[float]:
    duration = _probe_duration(path)
    process = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-filter:v",
            "select=gt(scene\\,0.35),showinfo",
            "-f",
            "null",
            "-",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    times = [float(value) for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", process.stderr)]
    return sorted(set([0.0, *times, duration]))


def default_adapters() -> AdapterBundle:
    return AdapterBundle(
        transcribe=_default_transcribe,
        extract_covers=_default_covers,
        narrate=_default_narrate,
        scene_boundaries=_default_scene_boundaries,
        names={
            "transcribe": "faster-whisper/small",
            "covers": "ffmpeg-opencv-cover-ranking",
            "narrate": "macos-say",
            "scenes": "ffmpeg-scene-analysis",
        },
    )


def artifacts_to_dict(artifacts: list[EnhancementArtifact]) -> list[dict[str, Any]]:
    return [asdict(artifact) for artifact in artifacts]
