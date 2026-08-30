# Interactive Intake and Cross-Host Execution

Use this reference for execution, resume, status inspection, or installation in Codex, OpenCode, and Tencent WorkBuddy. The Python controller is canonical; host chat state is not.

## Agent Flow

If there is no job file, ask for the output root first and initialize it:

```bash
python3 scripts/remaster_job.py init --output-root /path/to/release-pack
```

Then repeat this loop:

1. Run `status --json`.
2. Ask only `next_question`.
3. Pass the accepted value to `set`.
4. Stop the loop when `next_question` is null.

```bash
python3 scripts/remaster_job.py status --job /path/to/release-pack/.job/job.json --json
python3 scripts/remaster_job.py set --job /path/to/release-pack/.job/job.json source_root /path/to/source
```

Run planning and show its output before requesting confirmation:

```bash
python3 scripts/remaster_job.py plan --job /path/to/release-pack/.job/job.json
```

After one explicit execution confirmation:

```bash
python3 scripts/remaster_job.py run --job /path/to/release-pack/.job/job.json --confirm
```

For an interrupted or partially failed job:

```bash
python3 scripts/remaster_job.py resume --job /path/to/release-pack/.job/job.json --confirm
```

## Terminal Flow

When the host cannot ask questions and run local commands, use the portable wizard:

```bash
python3 scripts/remaster_job.py wizard
```

The wizard asks the same conditional questions, writes the same job JSON, shows the same plan, and requires the same final confirmation.

## Question Order

The controller asks only applicable fields:

1. Output root before job initialization.
2. Authorized source folder.
3. Source series name.
4. Output series name.
5. Rights status: `owned`, `licensed`, `client-provided`, or `authorized`.
6. Planning mode: `target-duration`, `one-to-one`, or `mapping-csv`.
7. Target/minimum/maximum seconds for target-duration mode. Defaults: `60/45/75`.
8. Mapping CSV path for mapping mode.
9. Starting output episode and optional source limit.
10. Default or custom delivery profile.
11. Width, height, speed, and video/audio bitrates for a custom profile.
12. Cover, subtitle, release metadata, and evidence options.
13. Platform, account label, and publishing preparation.

The default profile is `1080x1920`, `1.050x`, H.264/AAC, `6500k` video, and `192k` audio.

## Planning Rules

- `mapping-csv` has highest precedence and preserves its listed order exactly.
- `target-duration` naturally sorts source files and preserves chronological order.
- File ends and detected scene changes are preferred near the target duration.
- If no boundary is available inside the duration band, the controller cuts at the maximum duration.
- A final short episode is preserved and marked instead of being silently pushed past the maximum.
- `one-to-one` maps every source file to one output episode.
- Planning accounts for the configured speed and writes `manifests/episode_plan.csv`.

Automatic random plot reordering is not part of this workflow. Use a mapping CSV only for an authorized editorial sequence approved by the user.

## Job States

| State | Meaning | Next action |
| --- | --- | --- |
| `draft` | Intake is incomplete or changed | Ask `next_question` |
| `ready` | Intake and episode plan are valid | Show plan and request confirmation |
| `running` | Builder is active | Continue reporting progress |
| `needs_input` | A path, dependency, permission, account, or key is missing | Ask only for the recorded requirement |
| `failed` | Processing ended with unresolved failures | Inspect logs, repair the cause, then resume |
| `complete` | Every planned output exists and passed QC | Return the release pack |

An episode checkpoint is reusable only when its output exists, its SHA-256 still matches, and QC status is `pass`.

## Host Installation

Install the same canonical package; do not fork its workflow logic:

```bash
python3 scripts/install_skill.py --host codex
python3 scripts/install_skill.py --host opencode
python3 scripts/install_skill.py --host workbuddy
python3 scripts/install_skill.py --host all
```

Default targets are:

- Codex: `~/.codex/skills/short-drama-batch-remaster`
- OpenCode: `~/.config/opencode/skills/short-drama-batch-remaster`
- WorkBuddy: `~/.workbuddy/skills/short-drama-batch-remaster`

Use `--target` when a WorkBuddy version is configured with a different skills directory. Set `WORKBUDDY_SKILLS_DIR` for a persistent override. Existing installations are rejected unless `--force` is provided; forced replacement keeps a timestamped backup.

## Completion Boundary

The controller may install missing tools when a supported package manager can do so non-interactively. Administrator approval, credentials, logins, API keys, and platform accounts move the job to `needs_input`.

Completion means all planned files passed local QC and release-pack validation. It does not guarantee Video Channels approval, copyright clearance, external fingerprint differences, or publication success.
