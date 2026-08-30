---
name: short-drama-batch-remaster
description: Use when authorized short-drama videos need batch remastering, duration-based episode regrouping, vertical release packaging, QC, subtitles, covers, metadata, or Video Channels delivery preparation; excludes unauthorized reposting, watermark removal, and platform-check evasion.
---

# Short Drama Batch Remaster

## Purpose

Use this skill to reproduce the local short-drama batch workflow represented by the user's sample log: remaster many authorized source episodes into a vertical delivery folder, validate each output, generate subtitles, covers, titles, descriptions, release queues, evidence images, Jianying storyboard drafts for selected episodes, imported Whisper subtitles, engineering screenshots, then clean temporary drafts.

The skill is a workflow orchestrator. Use the best available local tools and installed open-source projects rather than forcing one implementation. Install missing first-use dependencies automatically when that can be done without credentials, paid accounts, or unsafe privilege escalation.

For a new execution request, prefer the durable controller in `scripts/remaster_job.py`. It collects and validates inputs, plans episodes, invokes `scripts/build_release_pack.py`, persists per-episode QC checkpoints, resumes interrupted jobs, generates optional creative assets, and writes release-readiness reports. Treat local difference and readiness reports as local evidence only; they are not a platform review guarantee.

## Interactive Intake and Execution

This contract is host-neutral and applies in Codex, OpenCode, and Tencent WorkBuddy. Read [references/interactive-intake.md](references/interactive-intake.md) before starting an interactive or resumable job.

For an execution request:

1. If the user has not supplied an output root, ask for it first. Create the job with `python3 scripts/remaster_job.py init --output-root <path>`.
2. Read the job with `status --json`. Ask only its `next_question`, and ask one question at a time.
3. Persist each accepted answer immediately with `remaster_job.py set`. Reject an invalid value and repeat only that question.
4. When `next_question` is null, run `plan`. Show the episode count, source ranges, estimated durations, warnings, and saved plan path.
5. Obtain one explicit execution confirmation, then run `run --confirm`. Do not ask the intake questions again.
6. Stay with the process until the job is `complete`, `failed`, or `needs_input`. If interrupted, use `resume --confirm` with the same job file.

When chat-based local execution is unavailable, run `python3 scripts/remaster_job.py wizard` in a terminal. Do not replace the durable state machine with host-specific memory or a platform-specific question API.

## Boundaries

- Work only on material the user owns or has permission to process and publish.
- Do not remove watermarks, hide attribution, defeat copyright matching, or help bypass platform anti-abuse systems.
- If the user asks for "搬运", "去重", "洗", "过检测", or similar wording, restate the lawful boundary and proceed only as authorized remastering, format normalization, accessibility/subtitle generation, archival, or publishing preparation.
- Preserve originals. Write derived files into a new output folder with a manifest and logs.
- Before publishing or uploading, require the user to confirm account, platform, title/description, rights status, and whether immediate or scheduled publication is intended.

## First-Use Tooling

Before starting a real batch, read [references/workflow.md](references/workflow.md). Then run:

```bash
python3 scripts/ensure_tools.py --install --features core,quality,vision,whisper,jianying,docs,ui
```

If publishing is requested, include the publish feature:

```bash
python3 scripts/ensure_tools.py --install --features core,quality,vision,whisper,jianying,docs,ui,publish
```

Use the script's report to decide the tool route. If a dependency needs administrator approval, login credentials, an API key, or a platform account, stop at that step and ask for the specific missing input.

For requests that mention watermark handling, reposting, deduplication, rights, attribution, or platform checks, also read [references/rights-safe-transformations.md](references/rights-safe-transformations.md) before choosing tools or writing commands.

For requests that need subtitle QA, sensitive-word review, title/description/hashtag generation, cover packs, Video Channels validation, release queues, or internal library duplicate management, read [references/production-enhancements.md](references/production-enhancements.md).

## Default Workflow

Follow the log-shaped workflow unless the user explicitly changes settings:

1. **Intake and manifest**: use `scripts/remaster_job.py` to collect source folder, source/output series names, episode planning mode, duration band or mapping, rights status, output root, delivery profile, enhancements, and publishing preparation.
2. **Rights-safe transformation gate**: record whether the request involves watermark handling, attribution, reposting, or duplicate-asset management. Route only to the permitted alternatives in `references/rights-safe-transformations.md`.
3. **Batch remaster**: for each output episode, assemble the mapped source episode(s), normalize to `1080x1920`, apply the configured `1.050x` speed change, audio adjustment, visual styling, and clean export metadata for authorized derivatives.
4. **Encoding target**: encode toward `6500k` video bitrate, H.264/AAC MP4 unless the user requires another delivery profile.
5. **Per-episode QC**: use `ffprobe` or equivalent to verify duration, resolution, bitrate, file size, stream presence, and readable output. Retry an encoding failure at most twice, then report the episode as failed.
6. **Content enhancement pack**: create requested subtitles, ranked cover candidates, editable copy, approved-script narration assets, and scene/pacing recommendations. Keep generated creative assets at `needs_review` until the user approves them.
7. **Release-readiness gate**: analyze loudness, black/frozen/silent sections, decode errors, subtitle timing, rights evidence, attribution, AI-content labeling, and creative approval. Write `reports/release_readiness.json`, `.csv`, and `.md` with `pass`, `warning`, or `blocked` status.
8. **Process evidence**: after the batch, generate process images/contact sheets and a machine-readable manifest that records inputs, outputs, parameters, timestamps, QC results, content metadata, cache/encoder provenance, and release status.
9. **Timestamp certificate**: generate a timestamp image containing the output title, folder, generation time, manifest hash, and operator/tool note.
10. **Cost image**: use WPS/DOCX template export when available; otherwise generate a visually simple image from the same fields. Apply configured signature/seal assets only when the user provided them or they exist in the configured cache path.
11. **Jianying storyboard mode 2**: for the selected sample episodes, generate Jianying 5.9 drafts, split each episode into random `2-8s` micro-storyboard segments with exact total duration, write a seven-track timeline, run Whisper `small`, import subtitles, open Jianying, seek to the sidecar timestamp, zoom the timeline twice, capture one engineering screenshot per draft, then close Jianying and delete the temporary drafts.
12. **Delivery**: return the output folder, counts, QC summary, failed items, subtitles, covers, release metadata, release queue, evidence images, timestamp image, cost image, storyboard screenshots, and any publishing status.

## Tool Routing

Prefer these routes when available:

- **Video processing**: FFmpeg/ffprobe for concat, trim, scale/crop/pad, speed, audio filters, bitrate control, metadata rewrite, final validation, black/freeze/silence detection, and loudness measurement.
- **Durable interactive job**: `scripts/remaster_job.py` for one-question intake, target-duration planning, execution, checkpoints, status, and resume.
- **Low-level release pack**: `scripts/build_release_pack.py` for legacy direct arguments or a planned `--job-file` supplied by the durable controller.
- **Release readiness**: `scripts/release_pipeline.py`, `scripts/media_analysis.py`, `scripts/subtitle_quality.py`, and `scripts/evaluate_release_readiness.py` for stable evidence rules and JSON/CSV/Markdown reports.
- **Batch acceleration**: `scripts/batch_executor.py` for bounded episode workers, `scripts/encoder_selection.py` for verified hardware selection and software fallback, and `scripts/stage_cache.py` for hash-valid reuse. Use `remaster_job.py cache-prune` to remove only unreferenced cache entries.
- **Content enhancement**: `scripts/content_enhancements.py` and `scripts/enhance_release_assets.py` for optional subtitle, cover, copy, narration, and editorial-recommendation artifacts.
- **Frame analysis or visual transforms**: OpenCV/Pillow when FFmpeg filters are insufficient.
- **Speech recognition**: faster-whisper or Whisper `small`; reuse a loaded model inside a batch.
- **Subtitle and text QA**: generate SRT/VTT/TXT from Whisper output, correct obvious recognition errors only when context supports the edit, and flag uncertain segments for review.
- **Release metadata**: use local text generation or existing user templates for episode titles, descriptions, hashtags, and Video Channels copy. Keep drafts editable and mark them as unreviewed until the user approves.
- **Cover generation**: extract candidate frames with FFmpeg/OpenCV, compose simple covers with Pillow, and preserve existing brand templates when provided.
- **Jianying draft generation**: `pyJianYingDraft`, `jianying-editor-skill`, CapCut Mate, or an existing local Jianying draft writer. Prefer Jianying Professional 5.9 on Windows for automatic opening/export/screenshot workflows.
- **Jianying UI automation**: native UI automation, Playwright only when it controls a web UI, or computer-use for desktop interactions.
- **DOCX/PDF/JPG cost image**: WPS Office if available, otherwise Python `python-docx`/Pillow/PyMuPDF/reportlab.
- **Publishing**: `social-auto-upload`, MatrixMedia, or another user-approved local uploader, after explicit publishing confirmation.

## Log Style

Mirror the concise progress style of the sample log. Include lines for:

- source series to output series and episode completion;
- remaster parameters, output geometry, bitrate target, and metadata handling;
- QC pass/fail with duration, resolution, bitrate, and size;
- subtitle, cover, metadata, sensitive-word review, Video Channels validation, and release queue stages;
- process image, timestamp, cost image, and Jianying storyboard stages;
- Whisper model, segment count, sidecar timestamp, engineering screenshot path, draft cleanup, and batch summary.

Use neutral wording such as "authorized derivative metadata rewrite" or "metadata normalization" in new logs unless the user is quoting a legacy log.

## Failure Handling

- If source mapping is ambiguous, infer only when filenames clearly encode episode numbers; otherwise ask for a mapping CSV or episode range.
- If a tool is missing, run `scripts/ensure_tools.py --install` for the needed feature before giving up.
- If Jianying 5.9 is unavailable, still generate drafts when possible and report that UI screenshots/export are blocked.
- If WPS is unavailable, generate the cost image via Python and note the fallback.
- If Whisper confidence or transcript quality is poor, keep the draft but flag subtitles for review.
- If text or subtitles contain uncertain names, homophones, profanity, medical/financial/legal claims, or platform-sensitive wording, flag them in the review report instead of silently rewriting meaning.
- If platform validation fails, repair only delivery-format issues automatically; require user review for creative copy, cover choice, and publication.
- Do not publish failed-QC videos.
- Keep processing and release status separate: `complete` means all required media passed local QC; release `pass` means no local finding remains; `warning` requires human review; `blocked` prohibits publishing preparation.
- Disable encode-cache reuse when approved narration is mixed, then re-run output QC and readiness checks on the mixed file.
- If a requested operation would remove third-party attribution, hide source identity, defeat content matching, or bypass platform enforcement, stop that operation and offer the closest permitted workflow: owned-brand replacement, attribution-preserving repost package, rights manifest, platform-spec validation, or duplicate-asset inventory.
