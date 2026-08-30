# Release Readiness, Content Quality, and Performance Design

Date: 2026-08-30
Status: approved architecture, pending written-spec approval

## Context

The skill already provides durable intake, duration-aware episode planning, FFmpeg remastering, per-episode checkpoints, basic media QC, and release-pack artifacts. The next revision must improve three areas together:

- make locally verifiable publishing problems visible before upload;
- produce stronger editable subtitles, covers, copy, and optional narration assets for authorized material;
- reduce repeated work and batch duration without weakening determinism or resume safety.

The pipeline may improve the probability that an authorized package is mechanically ready for Video Channels, but it must not predict approval, conceal source identity, or optimize for defeating content or copyright matching.

## Goals

- Produce one deterministic release-readiness verdict for every episode and for the whole batch.
- Separate hard blockers from warnings and human-review items.
- Add optional content-quality stages without making credentials or heavyweight models mandatory for basic remastering.
- Add bounded episode-level concurrency, hardware-encoder selection, and content-addressed caching.
- Preserve the existing controller, job file, output layout, resume behavior, and legacy CLI.
- Keep Codex, OpenCode, and Tencent WorkBuddy behavior identical.

## Non-Goals

- Guaranteeing platform approval, distribution, traffic, or copyright clearance.
- Watermark removal, attribution concealment, anti-abuse bypass, or perceptual-fingerprint evasion.
- Automatically rewriting plot order without an explicit editorial mapping.
- Automatically publishing videos or approving creative copy.
- Requiring a live Video Channels account in automated tests.

## Chosen Approach

Use a layered, backward-compatible extension of the current pipeline:

1. A release-readiness evaluator consumes existing probes and new analysis results.
2. A content-enhancement stage generates optional editable artifacts and review findings.
3. A controlled executor runs independent episode work concurrently and reuses only hash-valid cache entries.

This is preferred over patching every concern into `build_release_pack.py`, which would make rule testing and future platform-profile updates difficult. It is preferred over a full task-graph rewrite because the durable controller and checkpoint model already provide a stable foundation.

## Pipeline

The canonical data flow becomes:

```text
intake -> episode plan -> transform -> media analysis -> content enhancement
       -> release-readiness gate -> release pack -> optional publishing confirmation
```

Each stage writes structured results. The parent process is the only writer of the job file and final manifest, so worker completion cannot corrupt shared state.

## Components

### 1. Versioned Delivery Profile

Add a versioned profile document for target-platform expectations. It contains:

- container, video codec, audio codec, geometry, frame-rate, bitrate, and duration expectations;
- audio loudness and true-peak targets;
- cover and publishing-metadata requirements;
- AI-content disclosure and rights-review fields;
- rule severity and whether a mechanical repair is permitted.

The built-in `video-channels` profile records its source date and treats unverified or changeable platform rules as warnings. A custom profile may override mechanical thresholds. Profile changes invalidate only analysis and outputs whose encoded parameters changed.

### 2. Release-Readiness Evaluator

Add `scripts/evaluate_release_readiness.py`. It accepts a manifest, episode file, or job file and writes:

- `reports/release_readiness.json` for automation;
- `reports/release_readiness.csv` for batch scanning;
- `reports/release_readiness.md` for human review.

Every rule returns a stable rule ID, severity, status, evidence, and remediation. Aggregate status is:

- `pass`: no unresolved blocker or warning;
- `warning`: mechanically usable, but one or more review items remain;
- `blocked`: a required file, right, disclosure, stream, or delivery invariant failed.

Rule groups are:

**Media integrity**

- readable container and complete probe;
- required video and audio streams;
- expected codec, geometry, orientation, pixel format, and frame-rate range;
- duration, bitrate, and file-size constraints from the selected profile.

**Audio and visual quality**

- integrated loudness and true peak;
- extended silence, black frames, frozen frames, truncated frames, and decode errors;
- suspiciously empty or near-static output reported for review rather than silently accepted.

**Subtitle and text quality**

- parseable SRT/VTT timing, monotonic cues, no overlaps, and no cues beyond video duration;
- empty, excessively long, or implausibly short cues;
- uncertain transcription, sensitive claims, and user-configured review terms;
- title, description, and tag presence when publishing preparation is enabled.

**Rights and disclosure readiness**

- supported rights status and optional evidence reference;
- required attribution preserved when supplied;
- AI-content disclosure decision recorded when applicable;
- creative copy, cover, and publishing action remain unapproved until explicit user review.

`blocked` prevents a job from becoming publishing-ready. A processing job may still finish as `complete` when all media outputs exist, while its separate release status remains `blocked` or `warning`.

### 3. Content-Enhancement Stage

Add `scripts/enhance_release_assets.py` as an optional orchestrator. Features are independently selectable so basic processing remains lightweight.

**Subtitles**

- generate SRT, VTT, and plain-text transcripts with faster-whisper or Whisper;
- preserve model confidence and uncertain tokens in a QA sidecar;
- normalize punctuation and line wrapping without silently changing names or meaning;
- render a subtitle preview contact sheet when requested.

**Covers and copy**

- rank representative, non-black, non-blurred frames and export at least three candidates;
- compose covers only when a user template or configured style is available;
- generate editable title, description, and tag drafts from the approved transcript and episode summary;
- mark all generated copy and covers as `needs_review`.

**Narration and editorial assets**

- accept a user-approved narration script and optional configured TTS provider;
- require credentials only when the selected provider needs them, otherwise move the job to `needs_input`;
- export narration as a separate asset by default and mix it only when explicitly enabled;
- generate scene-boundary and pacing recommendations, but require an explicit mapping before changing plot order.

All generated artifacts record their source episode, model/tool, parameters, timestamp, and review status in the manifest.

### 4. Controlled Parallel Executor

Extend the controller and release-pack builder with:

- `--workers N`, with `auto` selecting a conservative bounded value;
- one worker per independent output episode;
- serialized job/manifest updates in the parent process;
- immediate cancellation of new work when a fatal configuration error is detected;
- normal completion of already-running workers before terminal state is recorded;
- per-worker logs merged into deterministic episode order for the final batch log.

The default remains conservative on memory-constrained systems. Model-heavy subtitle work uses a separate worker limit so a Whisper model is not loaded once per video worker.

### 5. Hardware Encoding

Add encoder capability probing and `software`, `hardware`, or `auto` selection:

- macOS: VideoToolbox when available;
- NVIDIA: NVENC when available;
- Intel: Quick Sync when available;
- fallback: existing `libx264` path.

`auto` performs a short synthetic encode and decode probe before selecting an encoder. A failed hardware encode retries once with the software encoder. The selected encoder, effective bitrate controls, and fallback reason are written to the manifest. Hardware output must pass the same readiness rules as software output.

### 6. Content-Addressed Cache

Cache reusable stage artifacts under `<output-root>/.job/cache` using a key derived from:

- input SHA-256;
- source segment ranges and ordering;
- delivery profile and transformation parameters;
- subtitle/content-enhancement options;
- tool and cache schema version.

A hit is valid only when the cached file exists, its recorded SHA-256 matches, and its stage validation passed. Corrupt or stale entries are ignored and rebuilt. Cache writes use temporary files and atomic replacement. `--no-cache` disables reuse; a cache-prune command removes unreferenced entries without touching final outputs.

### 7. Job and Manifest Compatibility

New fields are optional and receive backward-compatible defaults:

```json
{
  "delivery_profile": {"name": "video-channels", "version": 1},
  "execution": {"workers": "auto", "encoder": "auto", "cache": true},
  "enhancements": {
    "subtitles": false,
    "covers": false,
    "copy": false,
    "narration": false
  },
  "release_readiness": {"status": "pending", "report": null}
}
```

Existing schema documents are migrated in memory and saved only through the normal atomic writer. Existing commands continue to work without specifying these fields.

### 8. Error Handling

- Mechanical format failures may be repaired automatically and re-evaluated at most twice.
- Rights, attribution, AI-disclosure, sensitive-claim, narration-script, and creative-approval findings never receive silent fixes.
- Missing optional tools disable only the selected enhancement and produce `needs_input` when the user requested it.
- Worker crashes affect only their episode unless the cause is a shared configuration error.
- Cache corruption is a miss, not a fatal error.
- Publishing remains blocked until local QC passes and required human-review fields are approved.

## Skill Guidance Changes

Update `SKILL.md` and references so an agent:

- asks whether to enable content enhancements, worker count, encoder mode, and cache;
- explains release-readiness results using rule evidence and remediation;
- repairs only mechanical failures automatically;
- never equates file-hash difference, local QC, or readiness status with platform approval;
- stays attached through analysis and packaging, then returns the three report paths and unresolved findings.

## Testing Strategy

Implementation follows test-first development.

- Profile tests: defaults, custom overrides, versioning, and unsupported values.
- Rule tests: pass, warning, and blocked aggregation with stable rule IDs.
- Synthetic-media tests: missing audio, black sections, freeze sections, silence, wrong geometry, and decode failure.
- Subtitle tests: malformed files, overlaps, out-of-range cues, long lines, and uncertain tokens.
- Rights/disclosure tests: missing rights, required attribution, AI decision, and review approval.
- Enhancement tests: optional-tool routing, artifact provenance, and `needs_review` state.
- Executor tests: bounded concurrency, deterministic result ordering, isolated episode failure, and parent-only state writes.
- Encoder tests: capability selection and hardware-to-software fallback using command stubs plus one real FFmpeg smoke test.
- Cache tests: hit, parameter invalidation, source invalidation, corruption, atomic writes, and disabled-cache behavior.
- Compatibility tests: all existing tests and legacy CLI examples continue to pass.
- End-to-end test: synthetic batch with two workers, cached resume, generated readiness reports, and a final aggregate status.

Tests do not require a live platform account, paid TTS provider, or publishing action.

## Acceptance Criteria

- Every completed batch contains JSON, CSV, and Markdown release-readiness reports.
- Every rule result has a stable ID, severity, evidence, and remediation.
- A hard media, rights, attribution, or required-disclosure failure blocks publishing readiness.
- Subtitle, cover, copy, and narration features can be enabled independently.
- Generated creative artifacts remain `needs_review` until explicitly approved.
- Episode-level concurrency never corrupts the job file or changes final episode ordering.
- Valid cache hits skip work; any source, segment, parameter, tool-version, or hash change invalidates the affected entry.
- Hardware encoding falls back to software and still passes the same QC gate.
- Existing job files, one-to-one planning, mapping CSV, target-duration planning, and resume behavior remain compatible.
- All existing and new automated tests pass, including real FFmpeg smoke coverage.
- Documentation and reports do not claim to guarantee Video Channels approval or bypass content recognition.
