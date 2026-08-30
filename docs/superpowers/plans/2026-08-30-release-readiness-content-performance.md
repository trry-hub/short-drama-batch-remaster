# Release Readiness, Content Quality, and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic publishing-readiness gates, optional content-quality assets, and safe batch acceleration to the authorized short-drama remaster workflow.

**Architecture:** Keep `remaster_job.py` as the durable controller and split new behavior into focused Python modules for delivery profiles, readiness rules, media analysis, enhancement assets, encoder selection, caching, and bounded execution. `build_release_pack.py` orchestrates those modules, while only the parent process writes job and manifest state.

**Tech Stack:** Python 3 standard library, FFmpeg/ffprobe, optional faster-whisper/Whisper, Pillow, `srt`, `unittest`, JSON/CSV/Markdown reports.

## Global Constraints

- Process only material with rights status `owned`, `licensed`, `client-provided`, or `authorized`.
- Do not remove watermarks, conceal attribution, defeat content matching, or claim platform-review approval.
- Preserve current one-to-one, target-duration, mapping-CSV, resume, Codex, OpenCode, and WorkBuddy behavior.
- Keep current default transform values `1080x1920`, `1.050x`, H.264/AAC, and `6500k` unless the selected profile explicitly overrides them.
- Treat changeable platform requirements as versioned profile data with a source date; use warnings for unverified limits.
- Creative copy, covers, narration, attribution, AI disclosure, and publication require explicit human review.
- Only the parent process may write `.job/job.json`, final manifests, release queues, or aggregate reports.
- Retry mechanical encode or repair failures at most twice.
- Cache reuse requires matching keys, files, hashes, and prior stage validation.

---

### Task 1: Delivery Profiles and Backward-Compatible Job Options

**Files:**
- Create: `scripts/delivery_profiles.py`
- Modify: `scripts/remaster_job_core.py:17-333`
- Modify: `references/interactive-intake.md`
- Test: `tests/test_delivery_profiles.py`
- Test: `tests/test_remaster_job_core.py`

**Interfaces:**
- Produces: `DeliveryProfile`, `load_delivery_profile(name: str, version: int = 1) -> DeliveryProfile`, and `normalize_job(job: dict[str, Any]) -> dict[str, Any]`.
- Produces job fields: `delivery_profile`, `execution`, expanded `enhancements`, and `release_readiness`.
- Consumed by Tasks 2, 6, 7, and 8.

- [ ] **Step 1: Verify the current public platform requirements**

Search official Tencent or WeChat documentation for current Video Channels upload requirements. Record official source URLs and access date in the built-in profile. When no public official value is available, retain the existing local delivery default and set `verified=False`; do not infer a platform limit from third-party marketing pages.

- [ ] **Step 2: Write failing profile and migration tests**

```python
class DeliveryProfileTests(unittest.TestCase):
    def test_builtin_video_channels_profile_is_versioned(self) -> None:
        profile = load_delivery_profile("video-channels", 1)
        self.assertEqual(profile.name, "video-channels")
        self.assertEqual(profile.version, 1)
        self.assertEqual((profile.width, profile.height), (1080, 1920))
        self.assertFalse(profile.platform_approval_guarantee)

    def test_old_job_gets_backward_compatible_defaults(self) -> None:
        old = new_job(Path("/tmp/out"))
        old.pop("execution", None)
        normalized = normalize_job(old)
        self.assertEqual(normalized["execution"]["workers"], "auto")
        self.assertEqual(normalized["execution"]["encoder"], "auto")
        self.assertTrue(normalized["execution"]["cache"])
        self.assertEqual(normalized["release_readiness"]["status"], "pending")
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `python3 -m unittest tests.test_delivery_profiles tests.test_remaster_job_core -v`

Expected: FAIL because `delivery_profiles` and `normalize_job` do not exist.

- [ ] **Step 4: Implement the profile and normalization APIs**

```python
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


def load_delivery_profile(name: str, version: int = 1) -> DeliveryProfile:
    key = (name.strip().lower(), version)
    if key not in BUILTIN_PROFILES:
        raise ValueError(f"unsupported delivery profile: {name}@{version}")
    return BUILTIN_PROFILES[key]
```

`normalize_job` must deep-copy the document and apply these exact defaults without erasing existing values:

```python
job.setdefault("delivery_profile", {"name": "video-channels", "version": 1})
job.setdefault("execution", {"workers": "auto", "enhancement_workers": 1, "encoder": "auto", "cache": True})
job.setdefault("enhancements", {}).setdefault("copy", False)
job["enhancements"].setdefault("narration", False)
job["enhancements"].setdefault("mix_narration", False)
job["enhancements"].setdefault("editorial_recommendations", True)
job.setdefault("rights_evidence", "")
job.setdefault("attribution", {"required": False, "text": "", "approved": False})
job.setdefault("disclosure", {"ai_content": False, "ai_label": "not-applicable"})
job.setdefault("release_readiness", {"status": "pending", "report": None})
```

Add field parsers and intake questions for:

```text
delivery_profile.name = video-channels
execution.workers = auto or a positive integer
execution.enhancement_workers = a positive integer, default 1
execution.encoder = auto | software | hardware
execution.cache = yes | no
enhancements.copy = yes | no
enhancements.narration = yes | no
enhancements.mix_narration = yes | no
enhancements.editorial_recommendations = yes | no
rights_evidence = optional local path, URL, or reference text
attribution.required = yes | no
attribution.text = required when attribution.required is yes
disclosure.ai_content = yes | no
disclosure.ai_label = planned | applied when disclosure.ai_content is yes
```

`new_job` leaves `disclosure.ai_content` unanswered so new interactive jobs ask the user. `normalize_job` gives pre-upgrade jobs the backward-compatible value `False` only when the entire disclosure object is absent. Any changed profile, execution encoder, or enhancement field invalidates affected readiness results; media-affecting changes also invalidate episode checkpoints.

- [ ] **Step 5: Run profile and core tests and verify GREEN**

Run: `python3 -m unittest tests.test_delivery_profiles tests.test_remaster_job_core -v`

Expected: PASS.

- [ ] **Step 6: Commit the profile layer**

```bash
git add scripts/delivery_profiles.py scripts/remaster_job_core.py references/interactive-intake.md tests/test_delivery_profiles.py tests/test_remaster_job_core.py
git commit -m "Add versioned delivery profiles and execution options"
```

### Task 2: Pure Release-Readiness Rule Engine and Reports

**Files:**
- Create: `scripts/release_readiness.py`
- Create: `scripts/evaluate_release_readiness.py`
- Test: `tests/test_release_readiness.py`

**Interfaces:**
- Consumes: `DeliveryProfile` from Task 1 and JSON-compatible episode evidence.
- Produces: `RuleResult`, `ReadinessReport`, `aggregate_status`, `evaluate_release`, and `write_readiness_reports`.
- Consumed by Tasks 3, 4, and 8.

- [ ] **Step 1: Write failing aggregation and report tests**

```python
class ReleaseReadinessTests(unittest.TestCase):
    def test_blocker_wins_over_warning(self) -> None:
        results = [
            RuleResult("media.geometry", "blocker", "pass", "1080x1920", ""),
            RuleResult("rights.status", "blocker", "fail", "missing", "record rights status"),
            RuleResult("copy.review", "warning", "fail", "draft", "review release copy"),
        ]
        self.assertEqual(aggregate_status(results), "blocked")

    def test_reports_share_stable_rule_ids(self) -> None:
        report = ReadinessReport.from_results("episode-001", [passing_rule()])
        paths = write_readiness_reports([report], Path(self.tempdir.name))
        payload = json.loads(paths.json.read_text())
        self.assertEqual(payload["reports"][0]["rules"][0]["rule_id"], "media.readable")
        self.assertIn("media.readable", paths.markdown.read_text())
```

- [ ] **Step 2: Run the rule tests and verify RED**

Run: `python3 -m unittest tests.test_release_readiness -v`

Expected: FAIL because the readiness module does not exist.

- [ ] **Step 3: Implement stable rule types, aggregation, and writers**

```python
@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    severity: Literal["blocker", "warning", "info"]
    status: Literal["pass", "fail", "not_applicable"]
    evidence: str
    remediation: str


@dataclass(frozen=True)
class ReadinessReport:
    subject: str
    status: Literal["pass", "warning", "blocked"]
    rules: tuple[RuleResult, ...]

    @classmethod
    def from_results(cls, subject: str, rules: Iterable[RuleResult]) -> "ReadinessReport":
        items = tuple(rules)
        return cls(subject=subject, status=aggregate_status(items), rules=items)


def aggregate_status(rules: Iterable[RuleResult]) -> str:
    failed = [rule for rule in rules if rule.status == "fail"]
    if any(rule.severity == "blocker" for rule in failed):
        return "blocked"
    if failed:
        return "warning"
    return "pass"
```

`write_readiness_reports` must atomically produce JSON, CSV, and Markdown and return a `ReportPaths` dataclass. The CLI must accept `--manifest`, `--output-dir`, and optional `--profile-name`/`--profile-version` and exit `0` for pass/warning, `2` for blocked, and `1` for malformed input.

- [ ] **Step 4: Run readiness tests and verify GREEN**

Run: `python3 -m unittest tests.test_release_readiness -v`

Expected: PASS.

- [ ] **Step 5: Commit the rule engine**

```bash
git add scripts/release_readiness.py scripts/evaluate_release_readiness.py tests/test_release_readiness.py
git commit -m "Add deterministic release readiness reports"
```

### Task 3: FFmpeg Media Analysis Rules

**Files:**
- Create: `scripts/media_analysis.py`
- Modify: `scripts/release_readiness.py`
- Test: `tests/test_media_analysis.py`

**Interfaces:**
- Produces: `MediaAnalysis` and `analyze_media(path: Path, runner=run_command) -> MediaAnalysis`.
- Produces stable rules `media.readable`, `media.streams`, `media.geometry`, `media.codec`, `audio.loudness`, `audio.silence`, `video.black`, `video.freeze`, and `media.decode`.
- Consumed by Task 8.

- [ ] **Step 1: Write failing parser and rule tests**

```python
def test_analysis_parses_quality_events(self) -> None:
    runner = FakeRunner(
        probe=PROBE_1080X1920,
        blackdetect="black_start:2 black_end:4 black_duration:2",
        freezedetect="freeze_start:8\nfreeze_duration:3",
        silencedetect="silence_start:12\nsilence_end:17 | silence_duration:5",
        loudnorm='{"input_i":"-25.0","input_tp":"-3.2"}',
        decode="",
    )
    result = analyze_media(Path("episode.mp4"), runner=runner)
    self.assertEqual(result.black_ranges, ((2.0, 4.0),))
    self.assertEqual(result.freeze_ranges, ((8.0, 11.0),))
    self.assertEqual(result.silence_ranges, ((12.0, 17.0),))
    self.assertEqual(result.integrated_lufs, -25.0)

def test_missing_audio_is_a_blocker(self) -> None:
    rules = media_rules(MediaAnalysis(has_video=True, has_audio=False), profile())
    self.assertEqual(rule_by_id(rules, "media.streams").severity, "blocker")
    self.assertEqual(rule_by_id(rules, "media.streams").status, "fail")
```

- [ ] **Step 2: Run media tests and verify RED**

Run: `python3 -m unittest tests.test_media_analysis -v`

Expected: FAIL because `media_analysis` does not exist.

- [ ] **Step 3: Implement FFmpeg analysis and threshold mapping**

Run ffprobe once, then bounded FFmpeg analysis commands using these filters:

```python
ANALYSIS_FILTERS = {
    "black": "blackdetect=d=1.0:pix_th=0.10",
    "freeze": "freezedetect=n=-50dB:d=2.0",
    "silence": "silencedetect=n=-50dB:d=3.0",
    "loudness": "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
}
```

Decode validation runs `ffmpeg -v error -i <path> -f null -`. Parse events into immutable ranges. Rule evaluation must use profile geometry/codecs, block missing streams/decode errors, warn on loudness deviation over `2 LU`, and warn on black/freeze/silence events over configured durations. Analysis command failure produces an evidence-bearing warning unless the file itself is unreadable.

- [ ] **Step 4: Add a real synthetic-media smoke test**

Generate a five-second color-and-tone MP4 when FFmpeg is available, call `analyze_media`, and assert video/audio presence and finite loudness. Skip only when `ffmpeg` or `ffprobe` is unavailable.

- [ ] **Step 5: Run media tests and verify GREEN**

Run: `python3 -m unittest tests.test_media_analysis -v`

Expected: PASS, including the FFmpeg smoke test on this host.

- [ ] **Step 6: Commit media analysis**

```bash
git add scripts/media_analysis.py scripts/release_readiness.py tests/test_media_analysis.py
git commit -m "Add FFmpeg media quality analysis"
```

### Task 4: Subtitle, Rights, Attribution, and Disclosure Gates

**Files:**
- Create: `scripts/subtitle_quality.py`
- Modify: `scripts/release_readiness.py`
- Modify: `scripts/ensure_tools.py`
- Test: `tests/test_subtitle_quality.py`
- Test: `tests/test_release_readiness.py`

**Interfaces:**
- Produces: `SubtitleFinding`, `inspect_subtitles(path: Path, duration_s: float) -> list[SubtitleFinding]`, `subtitle_rules`, and `rights_and_review_rules`.
- Consumed by Tasks 5 and 8.

- [ ] **Step 1: Write failing subtitle and rights tests**

```python
def test_overlapping_and_out_of_range_cues_are_reported(self) -> None:
    path = self.write_srt("""1\n00:00:01,000 --> 00:00:04,000\nFirst\n\n2\n00:00:03,500 --> 00:00:12,000\nSecond\n""")
    findings = inspect_subtitles(path, duration_s=10.0)
    self.assertEqual({item.code for item in findings}, {"subtitle.overlap", "subtitle.out_of_range"})

def test_missing_required_ai_decision_blocks_readiness(self) -> None:
    context = {"rights_status": "owned", "ai_content": True, "ai_disclosure": None}
    rule = rule_by_id(rights_and_review_rules(context), "disclosure.ai")
    self.assertEqual((rule.severity, rule.status), ("blocker", "fail"))
```

- [ ] **Step 2: Run quality tests and verify RED**

Run: `python3 -m unittest tests.test_subtitle_quality tests.test_release_readiness -v`

Expected: FAIL because subtitle and review APIs do not exist.

- [ ] **Step 3: Implement structured SRT parsing and rule conversion**

Add feature `quality` to `ensure_tools.py` with Python dependency `srt`. `inspect_subtitles` uses `srt.parse`, sorts cues, and emits findings for parse errors, empty text, overlap, non-monotonic timing, duration overflow, over `22` Chinese characters or `42` Latin characters per line, display duration under `0.35s`, uncertain markers, and user-configured review terms.

Implement these exact rights/review rule IDs:

```text
rights.status
rights.evidence
attribution.required
disclosure.ai
cover.review
copy.review
narration.review
publishing.approval
```

Missing rights status and missing required attribution/disclosure are blockers. Missing evidence for a declared owned/licensed asset is a warning unless the selected organization policy marks it required. Unapproved creative assets are warnings; an unapproved publishing action is a blocker only when publication is requested.

- [ ] **Step 4: Run subtitle and rule tests and verify GREEN**

Run: `python3 -m unittest tests.test_subtitle_quality tests.test_release_readiness -v`

Expected: PASS.

- [ ] **Step 5: Commit text and rights gates**

```bash
git add scripts/subtitle_quality.py scripts/release_readiness.py scripts/ensure_tools.py tests/test_subtitle_quality.py tests/test_release_readiness.py
git commit -m "Add subtitle and publishing review gates"
```

### Task 5: Optional Content-Enhancement Assets

**Files:**
- Create: `scripts/enhance_release_assets.py`
- Create: `scripts/content_enhancements.py`
- Modify: `scripts/ensure_tools.py`
- Test: `tests/test_content_enhancements.py`

**Interfaces:**
- Produces: `EnhancementRequest`, `EnhancementArtifact`, and `enhance_episode(request: EnhancementRequest) -> list[EnhancementArtifact]`.
- Outputs per episode under `subtitles/`, `covers/`, `copy/`, and `narration/`, plus `reports/content_enhancements.json`.
- Consumed by Task 8.

- [ ] **Step 1: Write failing enhancement routing tests**

```python
def test_features_are_independently_selectable(self) -> None:
    request = request_for(subtitles=True, covers=False, copy=True, narration=False)
    artifacts = enhance_episode(request, adapters=fake_adapters())
    self.assertEqual({item.kind for item in artifacts}, {"srt", "vtt", "transcript", "copy"})
    self.assertTrue(all(item.review_status == "needs_review" for item in artifacts))

def test_narration_requires_an_approved_script(self) -> None:
    request = request_for(narration=True, narration_script=None)
    with self.assertRaisesRegex(NeedsInput, "approved narration script"):
        enhance_episode(request, adapters=fake_adapters())
```

- [ ] **Step 2: Run enhancement tests and verify RED**

Run: `python3 -m unittest tests.test_content_enhancements -v`

Expected: FAIL because content enhancement modules do not exist.

- [ ] **Step 3: Implement enhancement dataclasses and adapters**

```python
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
    narration_script: Path | None = None
```

Subtitle adapters prefer faster-whisper, then Whisper, and raise `NeedsInput` only when subtitles were requested and neither is available. Cover ranking rejects frames that are mostly black or have low Laplacian sharpness, then exports three candidates. Copy output is editable JSON/Markdown based on the approved transcript and episode identity and remains `needs_review`. Narration accepts only an approved script; use macOS `say` when available, otherwise require a configured provider or pre-rendered audio. Export narration separately unless the job explicitly requests mixing. When editorial recommendations are enabled, write an `editorial_recommendations` artifact containing scene boundaries, unusually long shots, rapid subtitle-density windows, and pacing suggestions; never alter scene order until an explicit mapping is supplied.

- [ ] **Step 4: Add provenance and fallback tests**

Assert every artifact contains the source episode, tool, parameters, timestamp, and review state. Assert a missing optional provider does not affect unselected features.

- [ ] **Step 5: Run enhancement tests and verify GREEN**

Run: `python3 -m unittest tests.test_content_enhancements -v`

Expected: PASS.

- [ ] **Step 6: Commit content enhancements**

```bash
git add scripts/enhance_release_assets.py scripts/content_enhancements.py scripts/ensure_tools.py tests/test_content_enhancements.py
git commit -m "Add optional content enhancement assets"
```

### Task 6: Encoder Selection and Content-Addressed Stage Cache

**Files:**
- Create: `scripts/encoder_selection.py`
- Create: `scripts/stage_cache.py`
- Test: `tests/test_encoder_selection.py`
- Test: `tests/test_stage_cache.py`

**Interfaces:**
- Produces: `EncoderChoice`, `select_encoder(mode: str, runner=run_command) -> EncoderChoice`.
- Produces: `build_cache_key`, `StageCache.lookup`, `StageCache.store`, and `StageCache.prune`.
- Consumed by Task 7.

- [ ] **Step 1: Write failing encoder and cache tests**

```python
def test_auto_selects_probed_hardware_and_falls_back(self) -> None:
    runner = EncoderRunner(available={"h264_videotoolbox"}, probe_ok=False)
    choice = select_encoder("auto", runner=runner)
    self.assertEqual(choice.codec, "libx264")
    self.assertIn("probe failed", choice.fallback_reason)

def test_cache_rejects_hash_mismatch(self) -> None:
    cache = StageCache(Path(self.tempdir.name))
    key = build_cache_key([source_hash], segments, profile, options, "cache-v1")
    cache.store(key, produced_file, validation_status="pass")
    cache.entry_path(key).write_bytes(b"changed")
    self.assertIsNone(cache.lookup(key))
```

- [ ] **Step 2: Run encoder/cache tests and verify RED**

Run: `python3 -m unittest tests.test_encoder_selection tests.test_stage_cache -v`

Expected: FAIL because both modules do not exist.

- [ ] **Step 3: Implement encoder probing**

```python
@dataclass(frozen=True)
class EncoderChoice:
    mode: str
    codec: str
    ffmpeg_args: tuple[str, ...]
    hardware: bool
    fallback_reason: str | None = None
```

Parse `ffmpeg -encoders`, rank VideoToolbox, NVENC, then QSV when present, and verify the candidate with a one-second synthetic encode and decode. `software` always returns `libx264`; `hardware` raises when no hardware encoder passes; `auto` returns software with a fallback reason.

- [ ] **Step 4: Implement atomic hash-valid cache entries**

`build_cache_key` serializes normalized inputs with sorted keys and returns SHA-256. Each cache entry contains `artifact`, `metadata.json`, output SHA-256, validation status, and access timestamp. `store` writes into a sibling temporary directory and atomically renames it. `lookup` returns `CacheHit` only for a present artifact, matching hash, matching schema, and `validation_status == "pass"`. `prune(referenced_keys)` deletes only unreferenced cache-entry directories.

- [ ] **Step 5: Run encoder/cache tests and verify GREEN**

Run: `python3 -m unittest tests.test_encoder_selection tests.test_stage_cache -v`

Expected: PASS.

- [ ] **Step 6: Commit performance primitives**

```bash
git add scripts/encoder_selection.py scripts/stage_cache.py tests/test_encoder_selection.py tests/test_stage_cache.py
git commit -m "Add encoder probing and stage cache"
```

### Task 7: Bounded Parallel Episode Execution

**Files:**
- Create: `scripts/batch_executor.py`
- Modify: `scripts/build_release_pack.py:51-1074`
- Test: `tests/test_batch_executor.py`
- Modify: `tests/test_build_release_pack_plan.py`

**Interfaces:**
- Consumes: `EncoderChoice` and `StageCache` from Task 6.
- Produces: `resolve_worker_count(value: str | int, cpu_count: int | None = None) -> int` and `execute_episodes(jobs, worker, workers) -> list[EpisodeResult]`.
- `build_release_pack.py` produces deterministic results in episode order and updates checkpoints only from the parent process.

- [ ] **Step 1: Write failing concurrency and ordering tests**

```python
def test_executor_is_bounded_and_returns_episode_order(self) -> None:
    tracker = ConcurrencyTracker()
    jobs = [EpisodeJob(number, []) for number in (3, 1, 2)]
    results = execute_episodes(jobs, tracker.worker, workers=2)
    self.assertLessEqual(tracker.maximum, 2)
    self.assertEqual([item.episode_number for item in results], [1, 2, 3])

def test_worker_does_not_write_job_state(self) -> None:
    result = process_episode(job, context_with_job_writer(ForbiddenWriter()))
    self.assertEqual(result.status, "complete")
    self.assertEqual(ForbiddenWriter.calls, 0)
```

- [ ] **Step 2: Run executor tests and verify RED**

Run: `python3 -m unittest tests.test_batch_executor tests.test_build_release_pack_plan -v`

Expected: FAIL because the executor and worker boundary do not exist.

- [ ] **Step 3: Implement bounded execution and extract the episode worker**

```python
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import islice


def resolve_worker_count(value: str | int, cpu_count: int | None = None) -> int:
    if value != "auto":
        return max(1, int(value))
    available = cpu_count or os.cpu_count() or 1
    return max(1, min(4, available // 2 or 1))


def execute_episodes(jobs, worker, workers):
    pending_jobs = iter(sorted(jobs, key=lambda job: job.output_episode))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, job): job for job in islice(pending_jobs, workers)}
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                futures.pop(future)
                try:
                    results.append(future.result())
                except FatalConfigurationError:
                    for remaining in futures:
                        remaining.cancel()
                    raise
                next_job = next(pending_jobs, None)
                if next_job is not None:
                    futures[pool.submit(worker, next_job)] = next_job
    return sorted(results, key=lambda result: result.episode_number)
```

Extract the current loop body into `process_episode(job: EpisodeJob, context: EpisodeContext) -> EpisodeResult`. Give each worker its own temporary directory and in-memory log lines. Pass selected encoder args into `encode_episode`. On a valid cache hit, materialize the final file, probe it, and return a complete result with `cache_status="hit"`. On a miss, encode, QC, and atomically store the validated output.

After `execute_episodes` returns, the parent writes log lines in episode order, updates each checkpoint, release row, and manifest entry, and then writes aggregate artifacts. A `FatalConfigurationError` stops submitting new jobs and cancels work that has not started; an ordinary episode exception becomes only that episode's failed result.

- [ ] **Step 4: Add hardware fallback at the episode boundary**

When an automatically selected hardware encoder fails, retry the same attempt with `libx264`, record the hardware error and fallback reason, and continue through the same QC. Explicit `encoder=hardware` reports failure instead of silently selecting software.

- [ ] **Step 5: Run executor and existing builder tests and verify GREEN**

Run: `python3 -m unittest tests.test_batch_executor tests.test_build_release_pack_plan -v`

Expected: PASS.

- [ ] **Step 6: Commit parallel execution**

```bash
git add scripts/batch_executor.py scripts/build_release_pack.py tests/test_batch_executor.py tests/test_build_release_pack_plan.py
git commit -m "Add bounded cached episode execution"
```

### Task 8: Controller, Enhancement, and Readiness Integration

**Files:**
- Modify: `scripts/remaster_job.py:49-448`
- Modify: `scripts/build_release_pack.py:688-1074`
- Modify: `tests/test_remaster_job_cli.py`
- Modify: `tests/test_end_to_end_job.py`
- Create: `tests/test_release_pipeline.py`

**Interfaces:**
- Consumes all modules from Tasks 1-7.
- Produces final reports at `reports/release_readiness.json`, `.csv`, and `.md` and job field `release_readiness`.

- [ ] **Step 1: Write failing controller and release-pipeline tests**

```python
def test_completed_media_can_have_blocked_release_status(self) -> None:
    job_path = make_ready_job(publishing=True, ai_content=True, ai_disclosure=None)
    result = run_job(job_path)
    job = load_job(job_path)
    self.assertEqual(result.returncode, 0)
    self.assertEqual(job["status"], "complete")
    self.assertEqual(job["release_readiness"]["status"], "blocked")
    self.assertTrue(Path(job["release_readiness"]["report"]).is_file())

def test_cached_resume_and_reports_end_to_end(self) -> None:
    first = run_synthetic_batch(workers=2, cache=True)
    second = resume_synthetic_batch(first.job_path)
    self.assertEqual(second.cache_hits, first.episode_count)
    self.assertEqual(second.readiness_report_count, first.episode_count + 1)
```

- [ ] **Step 2: Run integration tests and verify RED**

Run: `python3 -m unittest tests.test_remaster_job_cli tests.test_release_pipeline tests.test_end_to_end_job -v`

Expected: FAIL because the new fields and report pipeline are not integrated.

- [ ] **Step 3: Pass job options into the builder**

`apply_job_document` must map:

```python
args.workers = document["execution"]["workers"]
args.enhancement_workers = document["execution"]["enhancement_workers"]
args.encoder = document["execution"]["encoder"]
args.cache = document["execution"]["cache"]
args.delivery_profile_name = document["delivery_profile"]["name"]
args.delivery_profile_version = document["delivery_profile"]["version"]
args.enhancement_options = document["enhancements"]
args.rights_evidence = document["rights_evidence"]
args.attribution = document["attribution"]
args.disclosure = document["disclosure"]
```

Add equivalent legacy CLI flags: `--workers`, `--enhancement-workers`, `--encoder`, `--cache/--no-cache`, `--delivery-profile`, `--delivery-profile-version`, `--subtitles`, `--copy`, `--narration-script`, `--mix-narration`, `--editorial-recommendations`, `--rights-evidence`, `--attribution-text`, `--ai-content`, and `--ai-label`.

Add `remaster_job.py cache-prune --job <path>`; it computes referenced keys from current checkpoints and enhancement provenance, calls `StageCache.prune`, prints removed entry/byte counts as JSON, and never deletes final output files.

- [ ] **Step 4: Integrate enhancement and readiness stages**

After episode media processing:

1. Write a provisional manifest.
2. Run selected enhancement features for completed episodes with the separate `enhancement_workers` bound.
3. Analyze each output and convert media, subtitle, rights, attribution, disclosure, and review evidence into `ReadinessReport` objects.
4. Append one aggregate batch report.
5. Atomically write JSON, CSV, and Markdown reports.
6. Set release queue rows to `ready` only for report `pass` plus explicit creative approval; use `review` for warnings and `blocked` for blockers.
7. Save report paths and aggregate status to the manifest and job file.

The processing job becomes `complete` when required media outputs pass QC. Publishing remains disallowed while release readiness is `blocked`, creative review is pending, or `publishing.approved` is false.

- [ ] **Step 5: Run integration tests and verify GREEN**

Run: `python3 -m unittest tests.test_remaster_job_cli tests.test_release_pipeline tests.test_end_to_end_job -v`

Expected: PASS with real FFmpeg synthetic files and cache hits on resume.

- [ ] **Step 6: Commit pipeline integration**

```bash
git add scripts/remaster_job.py scripts/build_release_pack.py tests/test_remaster_job_cli.py tests/test_release_pipeline.py tests/test_end_to_end_job.py
git commit -m "Integrate content enhancement and release readiness"
```

### Task 9: Skill Guidance, Full Verification, and Publication

**Files:**
- Modify: `SKILL.md`
- Modify: `references/workflow.md`
- Modify: `references/production-enhancements.md`
- Modify: `references/tooling.md`
- Modify: `scripts/selftest.py`
- Modify: `README.md` only if it already exists; do not create one.

**Interfaces:**
- Documents the final agent contract and commands for Codex, OpenCode, and WorkBuddy.
- Produces no new runtime API.

- [ ] **Step 1: Update skill routing and workflow documentation**

Document the new intake questions, report statuses, automatic mechanical repair boundary, worker/encoder/cache options, enhancement review states, output paths, and these completion semantics:

```text
processing status = complete: all required media exists and passed local QC
release status = pass: no unresolved local readiness finding
release status = warning: usable output with human-review findings
release status = blocked: publishing must not proceed
```

State that none of these statuses predicts platform approval or evades content recognition.

- [ ] **Step 2: Expand the package self-test**

Require the new scripts and references, import every new module, load the built-in profile, create one passing `ReadinessReport`, and verify the three report writers return existing files in a temporary directory.

- [ ] **Step 3: Run the complete automated suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all existing and new tests PASS.

- [ ] **Step 4: Run syntax, skill, and whitespace validation**

Run: `python3 -m py_compile scripts/*.py tests/*.py`

Expected: exit `0`.

Run: `python3 scripts/selftest.py`

Expected: `selftest ok`.

Run: `python3 /Users/t/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/t/.codex/skills/short-drama-batch-remaster`

Expected: `Skill is valid!`.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Verify repository state and commit documentation**

```bash
git add SKILL.md references/workflow.md references/production-enhancements.md references/tooling.md scripts/selftest.py
git commit -m "Document release readiness optimization workflow"
git status --short --branch
```

Expected: clean branch ahead of `origin/main` only by the new implementation commits.

- [ ] **Step 6: Push the verified main branch**

```bash
git push origin main
git fetch origin main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
```

Expected: push succeeds and local `HEAD` equals `origin/main`.
