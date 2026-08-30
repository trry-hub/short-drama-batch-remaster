# Tooling Routes

Use this reference when selecting or installing tools for the short-drama batch remaster workflow.

## Core Tools

- `ffmpeg` and `ffprobe`: required for encoding, concatenation, speed changes, audio filters, metadata rewrite, and QC.
- Python 3.9 or newer: required for orchestration scripts.
- `scripts/build_release_pack.py`: one-command authorized release-pack builder that remasters videos, generates cover candidates, release queues, manifests, logs, timestamp/cost artifacts, and local non-identity reports.
- `opencv-python`, `numpy`, and `Pillow`: useful for frame analysis, process images, and fallback image generation.
- `faster-whisper` or `openai-whisper`: subtitle recognition; prefer faster-whisper when GPU/CPU compatibility is good.
- `scripts/check_release_pack.py`: deterministic output-folder validation for MP4 duration, resolution, bitrate, file size, stream presence, and release-readiness reporting.
- `scripts/media_analysis.py`: FFmpeg black/freeze/silence, loudness, stream, geometry, codec, and decode analysis.
- `scripts/release_pipeline.py`: combines media, subtitle, rights, attribution, AI disclosure, and review evidence.
- `scripts/evaluate_release_readiness.py`: standalone JSON/CSV/Markdown readiness report CLI.
- `scripts/content_enhancements.py`: optional subtitle, ranked cover, editable copy, approved narration, and editorial-recommendation artifacts.
- `scripts/encoder_selection.py`: short synthetic hardware probe with `libx264` fallback in auto mode.
- `scripts/stage_cache.py`: content-addressed cache with SHA-256 and validation checks.
- `srt`: structured SRT parsing for timing and text QA; install through the `quality` feature.

## Jianying Tools

Prefer these in order:

1. Existing project-specific Jianying draft writer if the user has one.
2. `pyJianYingDraft` for draft generation, tracks, effects, and SRT import.
3. `jianying-editor-skill` if installed as an agent skill and the task is natural-language editing in Jianying.
4. CapCut Mate when a local API service is available.

Jianying Professional 5.9 on Windows is the most compatible route for automatic draft opening, timeline navigation, screenshots, and automatic export. On macOS, draft generation may work but UI/export automation is more likely to need manual confirmation.

## Document and Image Tools

- WPS Office is preferred for DOCX-template cost image export when installed.
- Use `python-docx`, `reportlab`, `PyMuPDF`, and `Pillow` as a fallback for cost/timestamp images.
- Only use signature and seal assets from paths the user provided or from an existing configured cache path.
- Use FFmpeg frame extraction plus Pillow/OpenCV for cover candidates and process contact sheets.

## Publishing Tools

- `social-auto-upload`: mature route for multi-platform uploads including Video Channels.
- MatrixMedia: useful for GUI + CLI + HTTP API matrix publishing.
- Use platform uploaders only after explicit user confirmation.

## Auto-Install Policy

Run `scripts/ensure_tools.py --install` with the needed features. The script may install missing Python packages and attempt package-manager installs for FFmpeg. If a dependency requires administrator elevation, account login, GUI setup, or API keys, report the exact blocker and continue only for stages that do not depend on it.
