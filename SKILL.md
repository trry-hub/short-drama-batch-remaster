---
name: short-drama-batch-remaster
description: Batch remaster authorized short-drama episodes into vertical release packs with FFmpeg/OpenCV/Whisper, QC logs, process evidence images, timestamp/cost images, and Jianying 5.9 storyboard draft screenshots. Use for short-drama batch optimization, remastering, release-package preparation, or Video Channels-ready deliverables; do not use for unauthorized reposting, watermark removal, or evading platform/copyright detection.
---

# Short Drama Batch Remaster

## Purpose

Use this skill to reproduce the local short-drama batch workflow represented by the user's sample log: remaster many authorized source episodes into a vertical delivery folder, validate each output, generate evidence images, create Jianying storyboard drafts for selected episodes, import Whisper subtitles, capture engineering screenshots, then clean temporary drafts.

The skill is a workflow orchestrator. Use the best available local tools and installed open-source projects rather than forcing one implementation. Install missing first-use dependencies automatically when that can be done without credentials, paid accounts, or unsafe privilege escalation.

## Boundaries

- Work only on material the user owns or has permission to process and publish.
- Do not remove watermarks, hide attribution, defeat copyright matching, or help bypass platform anti-abuse systems.
- If the user asks for "搬运", "去重", "洗", "过检测", or similar wording, restate the lawful boundary and proceed only as authorized remastering, format normalization, accessibility/subtitle generation, archival, or publishing preparation.
- Preserve originals. Write derived files into a new output folder with a manifest and logs.
- Before publishing or uploading, require the user to confirm account, platform, title/description, rights status, and whether immediate or scheduled publication is intended.

## First-Use Tooling

Before starting a real batch, read [references/workflow.md](references/workflow.md). Then run:

```bash
python3 scripts/ensure_tools.py --install --features core,whisper,jianying,docs,ui
```

If publishing is requested, include the publish feature:

```bash
python3 scripts/ensure_tools.py --install --features core,whisper,jianying,docs,ui,publish
```

Use the script's report to decide the tool route. If a dependency needs administrator approval, login credentials, an API key, or a platform account, stop at that step and ask for the specific missing input.

For requests that mention watermark handling, reposting, deduplication, rights, attribution, or platform checks, also read [references/rights-safe-transformations.md](references/rights-safe-transformations.md) before choosing tools or writing commands.

## Default Workflow

Follow the log-shaped workflow unless the user explicitly changes settings:

1. **Intake and manifest**: identify source folder, source series name, output series name, episode range, source-to-output episode mapping, rights status, output root, and whether publishing is included.
2. **Rights-safe transformation gate**: record whether the request involves watermark handling, attribution, reposting, or duplicate-asset management. Route only to the permitted alternatives in `references/rights-safe-transformations.md`.
3. **Batch remaster**: for each output episode, assemble the mapped source episode(s), normalize to `1080x1920`, apply the configured `1.050x` speed change, audio adjustment, visual styling, and clean export metadata for authorized derivatives.
4. **Encoding target**: encode toward `6500k` video bitrate, H.264/AAC MP4 unless the user requires another delivery profile.
5. **Per-episode QC**: use `ffprobe` or equivalent to verify duration, resolution, bitrate, file size, stream presence, and readable output. Retry an encoding failure at most twice, then report the episode as failed.
6. **Process evidence**: after the batch, generate process images/contact sheets and a machine-readable manifest that records inputs, outputs, parameters, timestamps, and QC results.
7. **Timestamp certificate**: generate a timestamp image containing the output title, folder, generation time, manifest hash, and operator/tool note.
8. **Cost image**: use WPS/DOCX template export when available; otherwise generate a visually simple image from the same fields. Apply configured signature/seal assets only when the user provided them or they exist in the configured cache path.
9. **Jianying storyboard mode 2**: for the selected sample episodes, generate Jianying 5.9 drafts, split each episode into random `2-8s` micro-storyboard segments with exact total duration, write a seven-track timeline, run Whisper `small`, import subtitles, open Jianying, seek to the sidecar timestamp, zoom the timeline twice, capture one engineering screenshot per draft, then close Jianying and delete the temporary drafts.
10. **Delivery**: return the output folder, counts, QC summary, failed items, evidence images, timestamp image, cost image, storyboard screenshots, and any publishing status.

## Tool Routing

Prefer these routes when available:

- **Video processing**: FFmpeg/ffprobe for concat, trim, scale/crop/pad, speed, audio filters, bitrate control, metadata rewrite, and final validation.
- **Frame analysis or visual transforms**: OpenCV/Pillow when FFmpeg filters are insufficient.
- **Speech recognition**: faster-whisper or Whisper `small`; reuse a loaded model inside a batch.
- **Jianying draft generation**: `pyJianYingDraft`, `jianying-editor-skill`, CapCut Mate, or an existing local Jianying draft writer. Prefer Jianying Professional 5.9 on Windows for automatic opening/export/screenshot workflows.
- **Jianying UI automation**: native UI automation, Playwright only when it controls a web UI, or computer-use for desktop interactions.
- **DOCX/PDF/JPG cost image**: WPS Office if available, otherwise Python `python-docx`/Pillow/PyMuPDF/reportlab.
- **Publishing**: `social-auto-upload`, MatrixMedia, or another user-approved local uploader, after explicit publishing confirmation.

## Log Style

Mirror the concise progress style of the sample log. Include lines for:

- source series to output series and episode completion;
- remaster parameters, output geometry, bitrate target, and metadata handling;
- QC pass/fail with duration, resolution, bitrate, and size;
- process image, timestamp, cost image, and Jianying storyboard stages;
- Whisper model, segment count, sidecar timestamp, engineering screenshot path, draft cleanup, and batch summary.

Use neutral wording such as "authorized derivative metadata rewrite" or "metadata normalization" in new logs unless the user is quoting a legacy log.

## Failure Handling

- If source mapping is ambiguous, infer only when filenames clearly encode episode numbers; otherwise ask for a mapping CSV or episode range.
- If a tool is missing, run `scripts/ensure_tools.py --install` for the needed feature before giving up.
- If Jianying 5.9 is unavailable, still generate drafts when possible and report that UI screenshots/export are blocked.
- If WPS is unavailable, generate the cost image via Python and note the fallback.
- If Whisper confidence or transcript quality is poor, keep the draft but flag subtitles for review.
- Do not publish failed-QC videos.
- If a requested operation would remove third-party attribution, hide source identity, defeat content matching, or bypass platform enforcement, stop that operation and offer the closest permitted workflow: owned-brand replacement, attribution-preserving repost package, rights manifest, platform-spec validation, or duplicate-asset inventory.
