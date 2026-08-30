# Cross-Platform Interactive Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable one-question-at-a-time intake, duration-aware episode planning, checkpointed execution, and portable installation for Codex, OpenCode, and Tencent WorkBuddy.

**Architecture:** Keep one platform-neutral Python implementation. `remaster_job.py` owns intake and lifecycle state, `remaster_job_core.py` owns JSON persistence and field validation, `episode_planner.py` owns chronological time-range planning, and `build_release_pack.py` consumes persisted plans and updates per-episode checkpoints. Host compatibility is limited to `SKILL.md` instructions and `install_skill.py` target projection.

**Tech Stack:** Python 3.10+ standard library, FFmpeg/ffprobe, unittest, JSON/CSV, existing Pillow fallback artifacts.

## Global Constraints

- Process only material with `owned`, `licensed`, `client-provided`, or `authorized` rights status.
- Do not remove watermarks, conceal sources, defeat copyright matching, or promise platform-review approval.
- Ask one missing intake question at a time and persist every accepted answer.
- Default delivery profile is `1080x1920`, `1.050x`, H.264/AAC, `6500k` video, and `192k` audio.
- Default duration profile is target `60s`, minimum `45s`, maximum `75s`.
- Preserve chronological source order unless the user supplies an explicit mapping CSV.
- Retry each failed encode at most twice and never mark failed-QC output complete.
- Do not publish without a separate explicit confirmation.
- Keep all runtime dependencies optional except Python, FFmpeg, and ffprobe for core processing.

---

### Task 1: Durable Job Schema and Intake State

**Files:**
- Create: `scripts/remaster_job_core.py`
- Create: `tests/test_remaster_job_core.py`

**Interfaces:**
- Produces: `Question`, `new_job(output_root: Path) -> dict[str, Any]`, `load_job(path: Path) -> dict[str, Any]`, `save_job(path: Path, job: dict[str, Any]) -> None`, `set_job_field(job: dict[str, Any], field: str, raw_value: str) -> dict[str, Any]`, `next_question(job: dict[str, Any]) -> Question | None`, `validate_job(job: dict[str, Any], require_ready: bool = False) -> list[str]`, and `job_path_for_output(output_root: Path) -> Path`.
- Consumes: Python standard library only.

- [ ] **Step 1: Write failing schema and atomic-write tests**

```python
from pathlib import Path

from remaster_job_core import (
    job_path_for_output,
    load_job,
    new_job,
    next_question,
    save_job,
    set_job_field,
    validate_job,
)


def test_new_job_is_draft_and_uses_output_job_folder(tmp_path: Path) -> None:
    job = new_job(tmp_path / "release")
    assert job["schema_version"] == 1
    assert job["status"] == "draft"
    assert job["output_root"] == str((tmp_path / "release").resolve())
    assert job_path_for_output(tmp_path / "release") == tmp_path / "release" / ".job" / "job.json"


def test_save_job_round_trips_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "release" / ".job" / "job.json"
    job = new_job(tmp_path / "release")
    save_job(path, job)
    assert load_job(path) == job
    assert list(path.parent.glob("*.tmp")) == []


def test_next_question_is_conditional_and_one_at_a_time(tmp_path: Path) -> None:
    job = new_job(tmp_path / "release")
    assert next_question(job).field == "source_root"
    source = tmp_path / "source"
    source.mkdir()
    job = set_job_field(job, "source_root", str(source))
    assert next_question(job).field == "source_series"
    job = set_job_field(job, "planning.mode", "target-duration")
    job["source_series"] = "Source"
    job["output_series"] = "Output"
    job["rights_status"] = "owned"
    assert next_question(job).field == "planning.target_duration_s"


def test_validation_rejects_invalid_duration_band(tmp_path: Path) -> None:
    job = new_job(tmp_path / "release")
    job["planning"] = {
        "mode": "target-duration",
        "target_duration_s": 80.0,
        "min_duration_s": 45.0,
        "max_duration_s": 75.0,
    }
    assert "target duration must be between minimum and maximum" in validate_job(job)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m unittest tests.test_remaster_job_core -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'remaster_job_core'`.

- [ ] **Step 3: Implement the job schema, parsing, questions, and atomic persistence**

```python
SCHEMA_VERSION = 1
RIGHTS_STATUSES = {"owned", "licensed", "client-provided", "authorized"}
PLANNING_MODES = {"one-to-one", "target-duration", "mapping-csv"}


@dataclass(frozen=True)
class Question:
    field: str
    prompt: str
    default: str | None = None
    choices: tuple[str, ...] = ()


def new_job(output_root: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": uuid.uuid4().hex,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "output_root": str(output_root.expanduser().resolve()),
        "planning": {"mode": None},
        "profile": {
            "width": 1080,
            "height": 1920,
            "speed": 1.05,
            "video_bitrate": "6500k",
            "audio_bitrate": "192k",
        },
        "enhancements": {"covers": True, "subtitles": False, "metadata": True, "evidence": True},
        "episode_plan": [],
        "episodes": {},
        "last_error": None,
        "needs_input": None,
    }


def save_job(path: Path, job: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)
```

Implement dotted-field updates with explicit parsers for booleans, paths, integers, floats, bitrate strings, rights status, and planning mode. `next_question()` must return the first missing applicable field from the ordered intake table and must skip target-duration fields outside that mode and mapping path outside `mapping-csv` mode.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python3 -m unittest tests.test_remaster_job_core -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/remaster_job_core.py tests/test_remaster_job_core.py
git commit -m "Add durable remaster job schema"
```

### Task 2: Chronological Duration and Scene-Boundary Planner

**Files:**
- Create: `scripts/episode_planner.py`
- Create: `tests/test_episode_planner.py`

**Interfaces:**
- Produces: `SourceMedia(path: str, duration_s: float, scene_changes_s: tuple[float, ...])`, `SourceSegment(path: str, start_s: float, end_s: float)`, `TimelineItem(path: str, start_s: float, end_s: float)`, `Timeline(items: tuple[TimelineItem, ...], boundaries: tuple[float, ...], total_duration_s: float)`, `PlannedEpisode(output_episode: int, segments: tuple[SourceSegment, ...], estimated_duration_s: float, short_final: bool)`, `plan_one_to_one(...)`, `plan_target_duration(...)`, `probe_scene_changes(path: Path, threshold: float = 0.35) -> tuple[float, ...]`, and `write_episode_plan_csv(path: Path, episodes: Sequence[PlannedEpisode]) -> None`.
- Consumes: source duration inventory and configured speed/duration band.

- [ ] **Step 1: Write failing planner tests**

```python
from episode_planner import SourceMedia, plan_target_duration


def test_target_duration_groups_adjacent_sources_without_reordering() -> None:
    media = [
        SourceMedia("01.mp4", 25.0, ()),
        SourceMedia("02.mp4", 30.0, ()),
        SourceMedia("03.mp4", 60.0, ()),
    ]
    plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
    assert [segment.path for segment in plan[0].segments] == ["01.mp4", "02.mp4"]
    assert plan[0].estimated_duration_s == 55.0
    assert [segment.path for segment in plan[1].segments] == ["03.mp4"]


def test_target_duration_uses_nearest_scene_boundary() -> None:
    media = [SourceMedia("long.mp4", 140.0, (52.0, 63.0, 118.0))]
    plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
    assert plan[0].segments[0].end_s == 63.0
    assert plan[1].segments[0].start_s == 63.0


def test_target_duration_forces_max_cut_without_scene_boundary() -> None:
    media = [SourceMedia("long.mp4", 160.0, ())]
    plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=7)
    assert plan[0].output_episode == 7
    assert plan[0].segments[0].end_s == 75.0
    assert plan[1].segments[0].start_s == 75.0


def test_final_short_episode_is_preserved_and_marked() -> None:
    media = [SourceMedia("long.mp4", 95.0, (60.0,))]
    plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
    assert plan[-1].estimated_duration_s == 35.0
    assert plan[-1].short_final is True
```

- [ ] **Step 2: Run the planner tests and verify RED**

Run: `python3 -m unittest tests.test_episode_planner -v`

Expected: FAIL because `episode_planner` does not exist.

- [ ] **Step 3: Implement global-timeline planning and segment projection**

```python
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

    timeline = _build_timeline(media)
    total_source_s = timeline.total_duration_s
    cursor = 0.0
    output_episode = episode_start
    result: list[PlannedEpisode] = []
    while cursor < total_source_s - 1e-6:
        remaining_final_s = (total_source_s - cursor) / speed
        if remaining_final_s <= max_duration_s:
            cut = total_source_s
        else:
            lower = cursor + min_duration_s * speed
            desired = cursor + target_duration_s * speed
            upper = min(total_source_s, cursor + max_duration_s * speed)
            candidates = [boundary for boundary in timeline.boundaries if lower <= boundary <= upper]
            cut = min(candidates, key=lambda value: (abs(value - desired), value)) if candidates else upper
        segments = tuple(_segments_for_range(timeline, cursor, cut))
        final_duration = (cut - cursor) / speed
        result.append(PlannedEpisode(output_episode, segments, round(final_duration, 3), final_duration < min_duration_s))
        cursor = cut
        output_episode += 1
    return result
```

Use file ends and detected scene changes as candidate boundaries. Convert every global range back to contiguous per-file `SourceSegment` entries. `probe_scene_changes()` must run FFmpeg with `select=gt(scene\,0.35),showinfo`, parse `pts_time`, and return sorted unique timestamps inside the media duration.

- [ ] **Step 4: Add speed-adjustment and CSV serialization tests**

```python
def test_speed_changes_source_cut_distance() -> None:
    media = [SourceMedia("long.mp4", 126.0, (63.0,))]
    plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.05, episode_start=1)
    assert plan[0].segments[0].end_s == 63.0
    assert plan[0].estimated_duration_s == 60.0


def test_plan_csv_contains_segment_ranges(tmp_path: Path) -> None:
    plan = plan_target_duration([SourceMedia("a.mp4", 80.0, ())], 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
    path = tmp_path / "episode_plan.csv"
    write_episode_plan_csv(path, plan)
    assert "a.mp4@0.000-75.000" in path.read_text(encoding="utf-8")
```

- [ ] **Step 5: Run all planner tests and commit Task 2**

Run: `python3 -m unittest tests.test_episode_planner -v`

Expected: all tests PASS.

```bash
git add scripts/episode_planner.py tests/test_episode_planner.py
git commit -m "Add duration aware episode planner"
```

### Task 3: Planned-Segment Encoding and Checkpoints

**Files:**
- Modify: `scripts/build_release_pack.py:47-840`
- Create: `tests/test_build_release_pack_plan.py`

**Interfaces:**
- Consumes: `SourceSegment`, persisted `episode_plan`, and job checkpoint helpers from Tasks 1-2.
- Produces: `EpisodeJob(output_episode: int, segments: list[SourceSegment])`, `parse_episode_plan(job: dict[str, Any]) -> list[EpisodeJob]`, `materialize_episode_input(job: EpisodeJob, temp_dir: Path, logger: BatchLogger, args: argparse.Namespace) -> Path`, and per-episode checkpoint updates in the job JSON.

- [ ] **Step 1: Write failing plan parsing and resume-skip tests**

```python
from build_release_pack import parse_episode_plan, should_skip_episode


def test_parse_episode_plan_keeps_segment_order(tmp_path: Path) -> None:
    job = {
        "episode_plan": [{
            "output_episode": 3,
            "segments": [
                {"path": str(tmp_path / "02.mp4"), "start_s": 10.0, "end_s": 30.0},
                {"path": str(tmp_path / "01.mp4"), "start_s": 0.0, "end_s": 20.0},
            ],
        }]
    }
    parsed = parse_episode_plan(job)
    assert parsed[0].output_episode == 3
    assert [item.path for item in parsed[0].segments] == [str(tmp_path / "02.mp4"), str(tmp_path / "01.mp4")]


def test_skip_requires_passed_qc_existing_path_and_matching_hash(tmp_path: Path) -> None:
    output = tmp_path / "episode-001.mp4"
    output.write_bytes(b"passed")
    state = {"status": "complete", "qc_status": "pass", "output_path": str(output), "output_sha256": sha256_file(output)}
    assert should_skip_episode(state) is True
    output.write_bytes(b"changed")
    assert should_skip_episode(state) is False
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_build_release_pack_plan -v`

Expected: FAIL because planned-segment interfaces do not exist.

- [ ] **Step 3: Replace path-only episode jobs with segment-aware jobs**

```python
@dataclass
class EpisodeJob:
    output_episode: int
    segments: list[SourceSegment]

    @property
    def source_paths(self) -> list[Path]:
        return list(dict.fromkeys(Path(segment.path) for segment in self.segments))


def parse_episode_plan(job: dict[str, Any]) -> list[EpisodeJob]:
    return [
        EpisodeJob(
            output_episode=int(item["output_episode"]),
            segments=[SourceSegment(**segment) for segment in item["segments"]],
        )
        for item in job.get("episode_plan", [])
    ]
```

Adapt the one-to-one and mapping-CSV routes to create full-file segments with `start_s=0.0` and `end_s=probe.duration_s`. Keep mapping order exact.

- [ ] **Step 4: Implement robust segment materialization**

For one complete source segment, keep the existing direct input route. For multiple or partial segments, re-encode each temporary segment to a common H.264/AAC intermediate (`args.width` x `args.height`, yuv420p, 30 fps, stereo 48 kHz), insert silent audio when the source has no audio, concatenate intermediates in plan order, then apply the existing final speed/style encode.

```python
def materialize_episode_input(job: EpisodeJob, temp_dir: Path, logger: BatchLogger, args: argparse.Namespace) -> Path:
    if len(job.segments) == 1 and _is_full_source_segment(job.segments[0]):
        return Path(job.segments[0].path)
    parts = []
    for index, segment in enumerate(job.segments, start=1):
        part = temp_dir / f"episode-{job.output_episode:03d}-part-{index:03d}.mp4"
        _encode_intermediate_segment(segment, part, args)
        parts.append(part)
    return make_concat_input(parts, temp_dir, logger, job.output_episode)
```

Add `--job-file`. When present, load planned episodes from the job, skip only hash-matching passed checkpoints, and atomically update the job after every episode result. Preserve existing positional/CSV behavior when `--job-file` is absent.

Change the existing positional `source_root` to `nargs="?"` and make `--output-root`, `--output-series`, and `--rights-status` conditionally required: they remain mandatory in legacy mode and are loaded from the JSON document in `--job-file` mode. `_is_full_source_segment()` probes the source duration and returns true only when `start_s <= 0.001` and `abs(end_s - source_duration_s) <= 0.05`.

- [ ] **Step 5: Run focused and regression tests**

Run: `python3 -m unittest tests.test_build_release_pack_plan -v`

Expected: all tests PASS.

Run: `python3 scripts/selftest.py`

Expected: `selftest ok`.

- [ ] **Step 6: Commit Task 3**

```bash
git add scripts/build_release_pack.py tests/test_build_release_pack_plan.py
git commit -m "Add planned segment encoding and checkpoints"
```

### Task 4: Interactive Controller, Execution, and Resume

**Files:**
- Create: `scripts/remaster_job.py`
- Create: `tests/test_remaster_job_cli.py`

**Interfaces:**
- Consumes: Task 1 job helpers, Task 2 planner, `ensure_tools.py`, and `build_release_pack.py --job-file`.
- Produces: subcommands `wizard`, `init`, `set`, `validate`, `plan`, `run`, `resume`, and `status` with machine-readable JSON on non-wizard commands.

- [ ] **Step 1: Write failing CLI lifecycle tests**

```python
def run_cli(*args: str, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "remaster_job.py"), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def test_init_set_and_status_persist_answers(tmp_path: Path) -> None:
    output = tmp_path / "release"
    init = run_cli("init", "--output-root", str(output))
    assert init.returncode == 0
    job_path = output / ".job" / "job.json"
    source = tmp_path / "source"
    source.mkdir()
    assert run_cli("set", "--job", str(job_path), "source_root", str(source)).returncode == 0
    payload = json.loads(run_cli("status", "--job", str(job_path), "--json").stdout)
    assert payload["next_question"]["field"] == "source_series"


def test_run_requires_confirmation(tmp_path: Path) -> None:
    job_path = make_ready_job(tmp_path)
    proc = run_cli("run", "--job", str(job_path))
    assert proc.returncode == 2
    assert "--confirm" in proc.stdout
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `python3 -m unittest tests.test_remaster_job_cli -v`

Expected: FAIL because `remaster_job.py` does not exist.

- [ ] **Step 3: Implement command parser and one-question wizard**

```python
def wizard(output_root: Path | None) -> int:
    if output_root is None:
        output_root = Path(input("Output root: ").strip()).expanduser()
    job_path = job_path_for_output(output_root)
    job = load_job(job_path) if job_path.exists() else new_job(output_root)
    save_job(job_path, job)
    while (question := next_question(job)) is not None:
        suffix = f" [{question.default}]" if question.default is not None else ""
        raw = input(f"{question.prompt}{suffix}: ").strip()
        if not raw and question.default is not None:
            raw = question.default
        try:
            job = set_job_field(job, question.field, raw)
            save_job(job_path, job)
        except ValueError as exc:
            print(f"Invalid value: {exc}")
    return show_summary_and_confirm(job_path)
```

Every non-wizard command emits a single JSON object and a stable exit code: `0` success, `1` failed, `2` invalid or confirmation missing, `3` needs input.

- [ ] **Step 4: Implement planning and execution orchestration**

`plan` probes duration and scene boundaries, writes the serialized plan to `job["episode_plan"]`, writes `<output-root>/manifests/episode_plan.csv`, and moves the job to `ready`. `run --confirm` invokes `ensure_tools.py --install --features core`, then `build_release_pack.py --job-file <path>`. `resume --confirm` performs the same route after checkpoint validation.

```python
def execute_job(job_path: Path, *, resume: bool, confirmed: bool) -> int:
    if not confirmed:
        raise CliUsageError("run and resume require --confirm")
    job = load_job(job_path)
    errors = validate_job(job, require_ready=True)
    if errors:
        return mark_needs_input(job_path, "; ".join(errors))
    set_status(job_path, "running")
    tools = subprocess.run([sys.executable, str(SCRIPTS / "ensure_tools.py"), "--install", "--features", "core", "--json"])
    if tools.returncode != 0:
        return mark_needs_input(job_path, "core dependencies are unavailable")
    command = [sys.executable, str(SCRIPTS / "build_release_pack.py"), "--job-file", str(job_path)]
    if resume:
        command.append("--resume")
    proc = subprocess.run(command)
    return finalize_from_builder(job_path, proc.returncode)
```

Do not pass an empty argument for non-resume runs; build the command list conditionally.

- [ ] **Step 5: Run CLI tests and commit Task 4**

Run: `python3 -m unittest tests.test_remaster_job_cli -v`

Expected: all tests PASS.

```bash
git add scripts/remaster_job.py tests/test_remaster_job_cli.py
git commit -m "Add interactive remaster job controller"
```

### Task 5: Codex, OpenCode, and WorkBuddy Installer

**Files:**
- Create: `scripts/install_skill.py`
- Create: `tests/test_install_skill.py`
- Modify: `scripts/ensure_tools.py:85-132`

**Interfaces:**
- Produces: `default_skill_root(host: str, home: Path, system: str) -> Path`, `install_skill(source: Path, target_root: Path, mode: str, force: bool) -> Path`, and CLI flags `--host`, `--target`, `--mode`, and `--force`.
- Consumes: canonical skill directory containing the installer.

- [ ] **Step 1: Write failing host-target and overwrite tests**

```python
from install_skill import default_skill_root, install_skill


def test_default_host_roots_are_platform_neutral(tmp_path: Path) -> None:
    assert default_skill_root("codex", tmp_path, "darwin") == tmp_path / ".codex" / "skills"
    assert default_skill_root("opencode", tmp_path, "darwin") == tmp_path / ".config" / "opencode" / "skills"
    assert default_skill_root("workbuddy", tmp_path, "windows") == tmp_path / ".workbuddy" / "skills"


def test_copy_install_refuses_existing_target_without_force(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    target_root = tmp_path / "host" / "skills"
    install_skill(source, target_root, mode="copy", force=False)
    case = unittest.TestCase()
    with case.assertRaises(FileExistsError):
        install_skill(source, target_root, mode="copy", force=False)
```

- [ ] **Step 2: Run installer tests and verify RED**

Run: `python3 -m unittest tests.test_install_skill -v`

Expected: FAIL because `install_skill.py` does not exist.

- [ ] **Step 3: Implement safe copy/link projection**

```python
HOST_ROOTS = {
    "codex": lambda home: home / ".codex" / "skills",
    "opencode": lambda home: home / ".config" / "opencode" / "skills",
    "workbuddy": lambda home: home / ".workbuddy" / "skills",
}


def install_skill(source: Path, target_root: Path, *, mode: str, force: bool) -> Path:
    source = source.resolve()
    target = target_root.expanduser().resolve() / source.name
    if target == source:
        return target
    if target.exists() or target.is_symlink():
        if not force:
            raise FileExistsError(f"skill already exists: {target}")
        backup = target.with_name(f"{target.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        target.replace(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        target.symlink_to(source, target_is_directory=True)
    else:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    return target
```

For `--host all`, install each host independently and return a JSON result per host. `--target` is allowed only with one host. On WorkBuddy, print the detected/default target and advise `--target` when that product version uses a different directory.

- [ ] **Step 4: Harden dependency-install reporting**

Add `requires_user_action: bool` to `CheckResult`. Mark non-interactive sudo failure, unsupported package manager, login/API requirements, and install failures as user-action blockers so `remaster_job.py` can set `needs_input` with the exact note.

```python
@dataclass
class CheckResult:
    kind: str
    name: str
    present: bool
    installed: bool = False
    requires_user_action: bool = False
    note: str = ""
```

- [ ] **Step 5: Run installer/tool tests and commit Task 5**

Run: `python3 -m unittest tests.test_install_skill -v`

Expected: all tests PASS.

Run: `python3 scripts/ensure_tools.py --features core --json`

Expected: exit `0` with `"ok": true` on the development machine.

```bash
git add scripts/install_skill.py scripts/ensure_tools.py tests/test_install_skill.py
git commit -m "Add cross-platform skill installer"
```

### Task 6: Skill Contract, Documentation, and End-to-End Resume Verification

**Files:**
- Modify: `SKILL.md`
- Create: `references/interactive-intake.md`
- Modify: `references/workflow.md`
- Modify: `scripts/selftest.py`
- Create: `tests/test_end_to_end_job.py`

**Interfaces:**
- Consumes: all previous task CLIs.
- Produces: discoverable host-neutral instructions, a realistic synthetic-media acceptance test, and updated package validation.

- [ ] **Step 1: Write failing package-contract and end-to-end tests**

```python
def test_skill_contract_routes_execution_through_job_controller() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "one question at a time" in text
    assert "scripts/remaster_job.py" in text
    assert "Codex" in text and "OpenCode" in text and "WorkBuddy" in text


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
def test_interrupted_job_resumes_without_reencoding_passed_episode(tmp_path: Path) -> None:
    source = make_synthetic_sources(tmp_path, durations=(2.0, 2.0, 2.0))
    job_path = make_ready_target_duration_job(tmp_path, source, target=4.0, minimum=2.0, maximum=5.0)
    first = run_job(job_path, stop_after=1)
    assert first.returncode != 0
    before = completed_episode_mtime(job_path, 1)
    resumed = resume_job(job_path)
    assert resumed.returncode == 0
    assert completed_episode_mtime(job_path, 1) == before
    assert load_job(job_path)["status"] == "complete"
```

Add a test-only `--stop-after N` controller option that is accepted only when environment variable `SHORT_DRAMA_TEST_MODE=1`; it exits after checkpointing N episodes and must never appear in normal skill instructions.

- [ ] **Step 2: Run package tests and verify RED**

Run: `python3 -m unittest tests.test_end_to_end_job -v`

Expected: FAIL because the skill contract and end-to-end fixture are not complete.

- [ ] **Step 3: Update the host-neutral skill contract**

Add an `Interactive Intake and Execution` section to `SKILL.md` with this required behavior:

```markdown
## Interactive Intake and Execution

For an execution request, use `scripts/remaster_job.py` as the durable controller.
Ask only the next missing question and ask one question at a time. Persist each
accepted answer with `remaster_job.py set`. After `validate` and `plan` succeed,
show the plan, obtain one execution confirmation, then call `run --confirm` or
`resume --confirm` and stay with the job until it is complete, failed, or needs input.

These instructions are host-neutral and apply in Codex, OpenCode, and Tencent
WorkBuddy. When chat-based tool execution is unavailable, run
`python3 scripts/remaster_job.py wizard` in a terminal.
```

Link `references/interactive-intake.md` for the exact field order, JSON status model, CLI examples, host installation commands, and recovery procedures.

- [ ] **Step 4: Update self-test and workflow reference**

Extend `scripts/selftest.py` required files and tokens:

```python
required.extend([
    ROOT / "references" / "interactive-intake.md",
    ROOT / "scripts" / "episode_planner.py",
    ROOT / "scripts" / "install_skill.py",
    ROOT / "scripts" / "remaster_job.py",
    ROOT / "scripts" / "remaster_job_core.py",
])
for token in ["one question at a time", "OpenCode", "WorkBuddy", "remaster_job.py"]:
    assert token in text
```

Document these primary examples in `references/workflow.md`:

```bash
python3 scripts/remaster_job.py wizard
python3 scripts/remaster_job.py status --job /path/to/release/.job/job.json --json
python3 scripts/remaster_job.py resume --job /path/to/release/.job/job.json --confirm
python3 scripts/install_skill.py --host all
```

- [ ] **Step 5: Run the complete verification suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests PASS; FFmpeg-only tests may be skipped only when FFmpeg is absent.

Run: `python3 -m py_compile scripts/*.py tests/*.py`

Expected: exit `0` with no output.

Run: `python3 scripts/selftest.py`

Expected: `selftest ok`.

Run: `python3 /Users/t/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/t/.codex/skills/short-drama-batch-remaster`

Expected: `Skill is valid!`.

Run: `git diff --check`

Expected: exit `0` with no output.

- [ ] **Step 6: Commit Task 6 and push**

```bash
git add SKILL.md references/interactive-intake.md references/workflow.md scripts/selftest.py tests/test_end_to_end_job.py
git commit -m "Complete cross-platform interactive remaster workflow"
git push origin main
```

After the push, verify the remote branch points to the final local commit and report the repository URL, commit ID, test summary, and invocation examples.
