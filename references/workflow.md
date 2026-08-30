# Short Drama Batch Remaster Workflow

This reference captures the requested log-shaped workflow for authorized short-drama batch optimization. Apply it as a deterministic production route unless the user changes the configuration.

## Default Profile

Use these defaults because they are explicit in the sample log:

| Field | Default |
| --- | --- |
| Canvas | `1080x1920` vertical |
| Speed | `1.050x` |
| Target bitrate | `6500k` |
| Output duration band | about `55-65s` per episode |
| Audio route | small pitch/EQ/loudness adjustment for authorized remastering |
| Visual route | frame-level tone styling and light texture/noise for versioned authorized derivatives |
| Metadata route | clean metadata rewrite with manifest provenance |
| Storyboard chunking | random `2-8s` segments, exact total duration |
| Speech model | Whisper/faster-whisper `small` |
| Release metadata | editable title, description, tags, cover candidates, and queue rows |
| Jianying route | Jianying Professional `5.9` when available |
| Storyboard evidence count | default `4` sample episodes unless user requests all |

## One-Command Local Tool

Use `scripts/build_release_pack.py` when the user wants a concrete tool that follows the log-shaped batch route for authorized material. The tool performs FFmpeg remastering, writes a release folder, and generates local QC artifacts:

```bash
python3 scripts/build_release_pack.py /path/to/source \
  --output-root /path/to/release-pack \
  --source-series "Source Series" \
  --output-series "Output Series" \
  --rights-status owned \
  --install-missing
```

For mapped episode combinations, provide a CSV with `output_episode` and `sources` columns. The `sources` value may use `+`, `;`, or `|` separators and may contain relative paths or episode numbers inferred from filenames.

The tool's local difference report proves only that generated files are not byte-identical to their source inputs and records media-property changes for internal duplicate management. Do not describe this as platform fingerprint evasion or a Video Channels approval guarantee.

## Required Inputs

Collect or infer these before processing:

- source root folder;
- output root folder;
- source series name;
- output series name;
- source episode range and output episode range;
- source-to-output mapping rules, for example `67+68 -> 84`;
- rights status: owned, licensed, client-provided, or otherwise authorized;
- whether to create subtitles, cover candidates, release metadata, process images, timestamp image, cost image, Jianying screenshots, and publishing tasks.

If filenames contain episode numbers, infer the mapping and show a short preview before encoding. If mapping cannot be inferred safely, ask for a CSV or plain-text mapping.

## Stage 0: Rights-Safe Transformation Gate

Read `references/rights-safe-transformations.md` when a request mentions watermark handling, reposting, deduplication, rights, attribution, or platform checks.

Record in the manifest:

- rights status;
- source owner or provider when known;
- allowed transformation category;
- attribution requirements;
- platform target;
- whether publication is approved.

Continue only with permitted transformations. Stop any operation whose purpose is to remove third-party attribution, conceal source identity, defeat content matching, or bypass platform enforcement.

## Stage 1: Episode Remaster

For each output episode:

1. Resolve source episode files.
2. If multiple sources map to one output, concatenate or trim in mapped order.
3. Normalize geometry to `1080x1920`; choose crop, pad, or scale based on user preference and visible-subject preservation.
4. Apply speed `1.050x`.
5. Apply authorized audio adjustment. Keep speech intelligible; do not create distorted audio.
6. Apply authorized visual styling. Keep faces, subtitles, and plot-critical details readable.
7. Write clean export metadata and record source provenance in the manifest.
8. Encode H.264/AAC MP4 with a `6500k` target video bitrate.

Log each planned remaster in this shape:

```text
[YYYY-MM-DD HH:MM:SS] Remaster: source episodes -> output episode (source duration / 1.050x -> estimated final duration; tone=frame-level; audio adjusted; texture level=N; metadata normalized)
[YYYY-MM-DD HH:MM:SS] Output 1080x1920, 1.050x -> about Ns, audio adjusted
[YYYY-MM-DD HH:MM:SS] Target bitrate 6500k (estimated duration Ns)
```

## Stage 2: QC

Use `ffprobe` or equivalent after every encode.

QC must check:

- container is readable;
- video stream exists;
- audio stream exists unless the user intentionally requests silent output;
- duration is within expected tolerance;
- resolution is exactly `1080x1920`;
- bitrate is close to the target profile;
- file size is plausible for the duration and bitrate.

Log pass in this shape:

```text
[YYYY-MM-DD HH:MM:SS] QC pass; duration: 61.98s; resolution: 1080x1920; bitrate: 6.53Mbps; size: 49.26MB
[YYYY-MM-DD HH:MM:SS] Source Series -> Output Series Episode NN complete
```

Retry failed encodes no more than two times. Do not publish or package failed-QC outputs as usable.

## Stage 3: Production Enhancement Pack

Read `references/production-enhancements.md` when preparing a publishable batch. Default to creating editable drafts, not final creative approvals.

Generate:

- subtitle files: `.srt`, `.vtt`, and `.txt` when Whisper/transcript output exists;
- subtitle QA report with uncertain words, likely homophones, and timing problems;
- three title candidates per episode, one short Video Channels description, and suggested hashtags;
- at least three cover frame candidates per episode, plus composed cover images when a template is available;
- `release_queue.csv` and `release_queue.jsonl` with platform, account placeholder, file path, cover path, title, description, tags, schedule status, QC status, and review status;
- internal duplicate inventory for the output folder when more than one episode exists.

Run `scripts/check_release_pack.py` against the output folder when possible and include the JSON or CSV report in the manifest.

When using `scripts/build_release_pack.py`, the tool creates `release_queue.csv`, `release_queue.jsonl`, `manifests/manifest.json`, `logs/batch.log`, `reports/release_pack_validation.*`, cover candidates, and evidence artifacts automatically.

## Stage 4: Process Evidence

After episode remastering succeeds:

1. Generate process images/contact sheets from representative frames.
2. Save a JSON manifest and optional CSV summary with input paths, output paths, durations, dimensions, bitrate, file size, processing parameters, timestamps, and QC result.
3. Log completion before starting certificate/cost artifacts.

Expected log shape:

```text
[Series] Process images complete, continuing
```

## Stage 5: Timestamp Certificate

Generate a JPG certificate containing:

- output series name;
- batch date/time;
- output folder;
- manifest hash;
- episode range;
- tool route used;
- a plain rights/provenance statement such as "authorized source material".

Expected output filename:

```text
<output-series>-timestamp.jpg
```

## Stage 6: Cost Image

Generate a cost/configuration JPG.

Preferred route:

1. Load configured signature and seal assets if present.
2. Use a DOCX template if configured.
3. Export through WPS Office when detected.
4. Overlay signature/seal on the exported PDF when required.
5. Convert to JPG.

Fallback route:

1. Use Python and Pillow/reportlab/PyMuPDF.
2. Render the same fields directly to JPG.
3. State the fallback in logs.

Expected filename:

```text
cost-config.jpg
```

## Stage 7: Jianying Storyboard Mode 2

Default to four selected episodes for engineering screenshots unless the user requests all episodes.

For each selected episode:

1. Split the episode into random `2-8s` micro-storyboard segments. The segment durations must sum exactly to the source duration after planning.
2. Re-encode or reference segments as required by the selected draft tool.
3. Write a seven-track Jianying timeline. Use the available draft writer's closest equivalent while preserving the evidence purpose:
   - main video segments;
   - timing/segment marker track;
   - subtitle track;
   - title/episode label track;
   - audio track;
   - optional visual adjustment/effect track;
   - optional evidence/sidecar marker track.
4. Run Whisper/faster-whisper `small`.
5. Import recognized subtitles as SRT or native text items.
6. Calculate a sidecar timestamp for inspection, typically an early conflict/action point.
7. Open the draft in Jianying 5.9.
8. Wait until the edit page is ready.
9. Press Home or equivalent timeline-start command.
10. Seek frame-accurately to the sidecar timestamp.
11. Zoom the timeline twice.
12. Save a screenshot named `<output-series>-episode-NN-engineering.jpg`.
13. Close Jianying after all screenshots.
14. Delete temporary draft folders.

Expected log phrases:

```text
[Series] Jianying storyboard mode 2: N episodes; Jianying 5.9 -> draft + auto-position screenshot
[Episode] Split into random 2-8s segments
[Episode] Writing seven-track timeline
[Episode] Whisper/small recognizing subtitles
[Episode] Imported Whisper subtitles
[Episode] Auto-position sidecar 15.9s / 59.1s
[Episode] Storyboard mode 2 draft ready (11 shots / seven tracks)
[Series] Jianying 5.9 -> fully auto-open "Episode"
[Series] Home + frame-step to 15.9s (478 frames)
[Series] Timeline zoom x2
[Series] Storyboard mode 2 engineering image saved: <file>
[Series] All storyboard mode 2 succeeded, cleaned N Jianying draft folders
```

## Stage 8: Optional Publishing

Publishing is not part of the sample log's completed action, but this workflow may continue into Video Channels or another platform only after explicit user confirmation.

Use `social-auto-upload`, MatrixMedia, or another approved uploader. Confirm:

- platform;
- account;
- title;
- description;
- tags/topics;
- cover;
- schedule time or immediate publish;
- rights status.

Do not publish failed-QC videos.

## Final Report

Return:

- number of successful and failed series;
- number of episodes generated;
- output folder;
- QC summary;
- subtitles and subtitle QA report;
- title/description/tag drafts;
- cover candidates;
- release queue;
- platform validation report;
- process images;
- timestamp certificate;
- cost image;
- Jianying engineering screenshots;
- cleanup status;
- publishing status if applicable.
