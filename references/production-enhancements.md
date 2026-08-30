# Production Enhancements

Use this reference when a short-drama batch needs publish-ready polish beyond raw remastering.

## Subtitle QA

Create subtitle outputs from Whisper or faster-whisper results:

- `.srt` for Jianying and platform upload;
- `.vtt` for web review;
- `.txt` transcript for copywriting and search.

QA checks:

- empty or overly long subtitle segments;
- overlapping timestamps;
- segments shorter than `0.3s` or longer than `6s`;
- obvious ASR homophones in character names, places, money amounts, and plot-critical nouns;
- profanity, slurs, medical/financial/legal claims, and platform-sensitive words for human review.

Do not silently change story meaning. Record original text, suggested correction, confidence, and reason.

## Title, Description, And Tags

Generate editable drafts for each episode:

- three title candidates: conflict-driven, plot-driven, and curiosity-driven;
- one Video Channels description, usually one or two short sentences;
- five to twelve tags, prioritizing series name, genre, protagonist, conflict, and update cadence.

Short-drama title rules:

- put the emotional conflict or reversal early;
- avoid generic words such as "精彩", "好看", or "来了" unless paired with a concrete plot hook;
- keep episode number consistent;
- never claim official authorization, exclusive status, or performance facts unless present in the manifest.

Mark generated copy as `review_status=draft` until the user approves it.

## Cover Pack

For each episode, extract at least three candidate frames:

- early conflict frame;
- clearest protagonist/reaction close-up;
- highest visual stakes frame.

When a cover template exists, compose cover candidates with:

- series title;
- episode number;
- 6-12 character hook text;
- optional protagonist/genre label;
- safe margins for mobile cropping.

Do not cover required attribution or platform-required marks.

## Video Channels Validation

Check each output for:

- readable MP4 container;
- H.264 video and AAC audio when possible;
- `1080x1920` vertical canvas unless user chose another profile;
- plausible duration and file size;
- bitrate close to target profile;
- title/description length;
- cover exists and matches the intended episode;
- QC status is pass before publication.

Write a validation report and fix only mechanical delivery issues automatically. Creative copy and publication remain user-approved.

The enhanced pipeline writes three synchronized readiness reports under `reports/`:

- `release_readiness.json` for agents and automation;
- `release_readiness.csv` for batch filtering;
- `release_readiness.md` for human review.

Every finding has a stable rule ID, severity, evidence, and remediation. `blocked` prevents publishing preparation, `warning` requires review, and `pass` only describes locally verifiable readiness.

For AI-generated or fictionalized content, record the applicable content-label decision and whether the label is planned or applied. Preserve source metadata and required attribution; do not strip AI provenance or third-party credit as a delivery optimization.

## Release Queue

Create both:

- `release_queue.csv` for manual review;
- `release_queue.jsonl` for automation.

Required fields:

```text
series_name,episode_number,video_path,cover_path,title,description,tags,platform,account,status,schedule_time,qc_status,review_status,rights_status,notes
```

Use statuses:

- `draft`: generated but not reviewed;
- `ready`: user-approved and QC-passed;
- `review`: media passed but readiness warnings or generated creative assets still need approval;
- `scheduled`: queued for a publishing tool;
- `published`: uploader reported success;
- `blocked`: missing rights, QC failure, platform blocker, or user decision.

## Internal Duplicate Inventory

For owned or authorized libraries, compute internal duplicate signals:

- file hash;
- duration;
- resolution;
- representative thumbnails;
- transcript fingerprint when available;
- optional perceptual hash if image libraries are installed.

Use this to prevent accidental repeated uploads and to group legitimate variations. Do not use it for bypassing external content matching or platform review.

## Manifest Additions

Add these fields when the production enhancement pack runs:

```json
{
  "subtitle_files": [],
  "subtitle_qa": [],
  "title_candidates": [],
  "description": "",
  "tags": [],
  "cover_candidates": [],
  "release_queue_row": {},
  "platform_validation": {},
  "internal_duplicate_group": null,
  "review_status": "draft"
}
```
