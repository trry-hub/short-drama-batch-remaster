# Cross-Platform Interactive Workflow Design

Date: 2026-08-30
Status: approved architecture, pending implementation-plan approval

## Context

The current skill documents an intake stage, but its deterministic runner only accepts command-line arguments. It does not provide a durable question-and-answer workflow, duration-based episode planning, or checkpointed resume behavior. The updated skill must behave consistently in Codex, OpenCode, and Tencent WorkBuddy.

## Goals

- Ask for missing task parameters one question at a time before processing.
- Validate and persist each accepted answer in a portable JSON job file.
- Support agent-led chat intake and a terminal-based interactive wizard.
- Continue from confirmed intake through processing, QC, and packaging until the job reaches a terminal state.
- Resume interrupted jobs without re-encoding episodes that already passed QC.
- Plan output episodes by target duration while preserving source order by default.
- Keep one canonical implementation for Codex, OpenCode, and WorkBuddy.
- Preserve the current authorized-content and platform-review boundaries.

## Non-Goals

- Platform-specific implementations of the processing logic.
- Automatic random plot reordering.
- Watermark removal, source concealment, copyright-matching evasion, or review-bypass guarantees.
- Automatic publication without a separate, explicit publication confirmation.

## Chosen Approach

Use a platform-neutral Python job controller and keep each host integration thin. The same `SKILL.md`, scripts, references, and JSON schema are installed into each host's supported skill directory. Host-native chat questions are preferred when an agent is available; the terminal wizard is the fallback and direct-user entry point.

This approach is preferred over a prompt-only state machine because it survives conversation loss and process interruption. It is preferred over three separate host implementations because behavior and validation remain identical.

## Compatibility Model

The canonical package remains a standard skill directory:

```text
short-drama-batch-remaster/
|-- SKILL.md
|-- agents/openai.yaml
|-- references/
|-- scripts/
|-- tests/
`-- docs/superpowers/specs/
```

Host projection is limited to installation and invocation:

| Host | Preferred installation target | Invocation behavior |
| --- | --- | --- |
| Codex | `~/.codex/skills/short-drama-batch-remaster` | Load `SKILL.md`, ask missing fields in chat, call the job controller |
| OpenCode | `~/.config/opencode/skills/short-drama-batch-remaster` or `.agents/skills/...` | Load the same `SKILL.md` and call the same job controller |
| WorkBuddy | detected WorkBuddy skills directory, with an explicit override | Load the same `SKILL.md` and call the same job controller |

An installer will support `--host codex`, `--host opencode`, `--host workbuddy`, and `--host all`. It will detect known locations, refuse ambiguous overwrites unless `--force` is supplied, and accept `--target` for host-version differences. Copy mode is the portable default; link mode is optional for development.

## Components

### 1. Host-Neutral Skill Contract

`SKILL.md` will define the following intake contract:

1. Detect whether the user is asking to plan, execute, resume, or inspect a job.
2. For execution, ask only missing required questions, exactly one at a time.
3. Do not silently choose a required value. Present a recommended default that the user can accept.
4. Persist every accepted answer through the job controller.
5. Show a concise source and output plan after validation.
6. Ask for one execution confirmation.
7. Run or resume the job and continue through QC and packaging.
8. Stop only at `complete`, `failed`, or `needs_input`.

If the host cannot run local scripts, the skill may collect answers and emit a valid job JSON file, but it must report that local execution is unavailable.

### 2. Job Controller

Add `scripts/remaster_job.py` as the canonical entry point. It will provide these modes:

```text
remaster_job.py wizard
remaster_job.py init --job <path>
remaster_job.py set --job <path> <field> <value>
remaster_job.py validate --job <path>
remaster_job.py plan --job <path>
remaster_job.py run --job <path>
remaster_job.py resume --job <path>
remaster_job.py status --job <path>
```

`wizard` performs terminal intake. Agent hosts use `init`, `set`, `validate`, `plan`, and `run` so answers collected in chat are persisted immediately.

The job controller delegates encoding and release-pack generation to `build_release_pack.py`; it does not duplicate FFmpeg logic.

### 3. Durable Job File

The first question is the output root. Once accepted, the controller creates `<output-root>/.job/job.json`. Every subsequent accepted answer is written atomically by replacing a temporary file with the final JSON file.

The job document contains:

- schema version and job ID;
- status and timestamps;
- source and output paths;
- source and output series names;
- rights status and publication intent;
- episode-planning mode and parameters;
- encoding profile;
- enhancement options;
- source inventory and source fingerprints used for change detection;
- planned output episodes;
- per-episode attempt, output, hash, and QC status;
- last error and any required user input.

Allowed job states are `draft`, `ready`, `running`, `needs_input`, `failed`, and `complete`.

### 4. Intake Questions

Questions are conditional and appear in this order:

1. Output root.
2. Authorized source folder.
3. Source series name.
4. Output series name.
5. Rights status: `owned`, `licensed`, `client-provided`, or `authorized`.
6. Episode-planning mode: `one-to-one`, `target-duration`, or `mapping-csv`.
7. Target, minimum, and maximum duration when `target-duration` is selected.
8. Mapping file when `mapping-csv` is selected.
9. Starting output episode and optional source limit.
10. Delivery profile: accept the Video Channels default or customize geometry, speed, and bitrate.
11. Optional covers, subtitles, metadata drafts, and evidence artifacts.
12. Platform/account metadata and whether publishing preparation is required.

Defaults remain `1080x1920`, `1.050x`, H.264/AAC, and `6500k`. The default target-duration profile is target `60s`, minimum `45s`, and maximum `75s`.

### 5. Episode Planning

Planning precedence is explicit:

1. `mapping-csv` uses the exact listed source order.
2. `target-duration` creates a chronological plan from naturally sorted source files.
3. `one-to-one` maps each source file to one output episode.

For target-duration planning:

- Probe source durations before encoding.
- Treat the naturally sorted sources as one chronological logical timeline.
- Prefer existing file boundaries near the target.
- When a source file must be split, prefer a scene-change boundary inside the minimum/maximum window.
- If no acceptable scene boundary exists, split at the maximum-duration boundary during re-encoding.
- Account for the configured speed when estimating final duration.
- Keep a source segment contiguous and never duplicate or omit frames intentionally.
- Allow a final short episode and mark it in the plan instead of silently merging it past the maximum.

The controller writes `manifests/episode_plan.csv` and displays a short preview before execution. Manual editorial reordering remains available through `mapping-csv`; automatic random reordering is excluded.

### 6. Execution and Resume

`run` performs these stages:

1. Validate the job and source inventory.
2. Install missing dependencies through `ensure_tools.py` when installation is possible without credentials or unsafe privilege escalation.
3. Generate and persist the episode plan.
4. Process each pending episode.
5. Run per-episode QC.
6. Persist the episode checkpoint immediately after QC.
7. Retry an encoding or QC failure at most twice.
8. Generate release-pack artifacts and final validation reports.
9. Set the job to `complete` only when every required output exists and passes QC.

`resume` revalidates the source inventory. Episodes whose outputs still exist, match the recorded output hash, and passed QC are skipped. Changed or missing outputs return to pending. A changed source invalidates only affected planned episodes.

The controller remains attached until a terminal state. Hosts may stream concise log updates, but they must not claim success before the final job validation passes.

### 7. Failure and Input Handling

- Invalid answers are rejected immediately with one corrective question.
- Missing tools are installed automatically when a supported package manager is available.
- Administrator approval, a login, a platform account, or an API key changes the job to `needs_input` with the exact missing requirement.
- Ambiguous source numbering changes the job to `needs_input` and requests a mapping file.
- Unsupported media is reported per file before encoding starts.
- Publishing remains a separate action and requires account, copy, cover, schedule, rights, and final user confirmation.
- Processing does not claim to guarantee Video Channels approval or external fingerprint differences.

## Changes to Existing Files

- Update `SKILL.md` with the cross-host intake contract and job-controller routing.
- Add `references/interactive-intake.md` with field definitions and host usage.
- Add `scripts/remaster_job.py` for intake, persistence, planning, execution, resume, and status.
- Extend `scripts/build_release_pack.py` with config-driven execution, target-duration plans, segment ranges, and checkpoint callbacks or compatible output reporting.
- Extend `scripts/ensure_tools.py` with host-aware package-manager detection where practical.
- Add `scripts/install_skill.py` for Codex, OpenCode, and WorkBuddy projection.
- Add focused tests under `tests/`.
- Update `scripts/selftest.py` and `references/workflow.md`.

## Testing Strategy

Implementation will follow test-first development.

- Schema tests: required fields, defaults, invalid values, and atomic writes.
- Intake tests: one missing field at a time and conditional question ordering.
- Planning tests: one-to-one, exact mapping, adjacent grouping, scene-boundary choice, forced split, final short episode, and speed-adjusted duration.
- Resume tests: passed output skip, missing output retry, changed-output retry, and affected-source invalidation.
- Installer tests: host target selection, override behavior, and overwrite refusal.
- CLI tests: `wizard`, `validate`, `plan`, `run`, `resume`, and `status` exit behavior.
- End-to-end test: generate short synthetic media, interrupt after one episode, resume, and verify a complete release pack.
- Skill validation: run the bundled `quick_validate.py` and the package self-test.

No test will require a live Codex, OpenCode, WorkBuddy, WeChat, or publishing account.

## Acceptance Criteria

- The same repository installs into all three supported hosts without forking the workflow logic.
- A task started through chat asks one missing parameter at a time and persists each answer.
- A terminal user can complete the same intake with `wizard`.
- The default duration planner produces chronological episodes near `60s` within the configured `45-75s` band when source boundaries allow it.
- The plan is visible before encoding and saved as CSV/JSON.
- An interrupted job resumes without reprocessing unchanged, passed episodes.
- A job reaches `complete` only after all required outputs pass QC and release-pack validation.
- Missing installable dependencies are handled automatically; credential or privilege blockers become `needs_input`.
- Existing one-to-one and mapping-CSV workflows remain compatible.
- Documentation makes no platform-review, copyright-matching, or publication guarantee.

