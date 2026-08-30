from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from remaster_job_core import (  # noqa: E402
    job_path_for_output,
    load_job,
    new_job,
    save_job,
    set_job_field,
)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def make_source(path: Path, color: str, frequency: int) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=160x284:d=1.2:r=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:duration=1.2",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def make_ready_intake(output_root: Path, source_root: Path) -> Path:
    job = new_job(output_root)
    answers = (
        ("source_root", str(source_root)),
        ("source_series", "Synthetic Source"),
        ("output_series", "Synthetic Output"),
        ("rights_status", "owned"),
        ("planning.mode", "target-duration"),
        ("planning.target_duration_s", "2.4"),
        ("planning.min_duration_s", "1.0"),
        ("planning.max_duration_s", "3.0"),
        ("episode_start", "1"),
        ("source_limit", "all"),
        ("profile.mode", "custom"),
        ("profile.width", "160"),
        ("profile.height", "284"),
        ("profile.speed", "1.0"),
        ("profile.video_bitrate", "600k"),
        ("profile.audio_bitrate", "96k"),
        ("enhancements.covers", "no"),
        ("enhancements.subtitles", "no"),
        ("enhancements.metadata", "yes"),
        ("enhancements.evidence", "yes"),
        ("platform", "WeChat Channels"),
        ("account", ""),
        ("publishing.prepare", "no"),
    )
    for field, value in answers:
        job = set_job_field(job, field, value)
    job["profile"]["maxrate"] = "800k"
    job["profile"]["bufsize"] = "1200k"
    job_path = job_path_for_output(output_root)
    save_job(job_path, job)
    return job_path


class EndToEndJobTests(unittest.TestCase):
    def test_skill_contract_routes_execution_through_job_controller(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("one question at a time", text)
        self.assertIn("scripts/remaster_job.py", text)
        self.assertIn("Codex", text)
        self.assertIn("OpenCode", text)
        self.assertIn("WorkBuddy", text)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_missing_episode_resumes_without_reencoding_passed_episode(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            source_root = root / "source"
            source_root.mkdir()
            for index, (color, frequency) in enumerate((("red", 440), ("green", 550), ("blue", 660)), start=1):
                make_source(source_root / f"episode-{index:03d}.mp4", color, frequency)

            output_root = root / "release"
            job_path = make_ready_intake(output_root, source_root)
            plan = run_command([sys.executable, str(SCRIPTS / "remaster_job.py"), "plan", "--job", str(job_path)])
            self.assertEqual(plan.returncode, 0, plan.stdout)
            planned = load_job(job_path)
            self.assertEqual(len(planned["episode_plan"]), 2)

            first_run = run_command(
                [sys.executable, str(SCRIPTS / "remaster_job.py"), "run", "--job", str(job_path), "--confirm"]
            )
            self.assertEqual(first_run.returncode, 0, first_run.stdout)
            complete = load_job(job_path)
            first_path = Path(complete["episodes"]["1"]["output_path"])
            second_path = Path(complete["episodes"]["2"]["output_path"])
            first_mtime = first_path.stat().st_mtime_ns

            second_path.unlink()
            complete["episodes"]["2"]["status"] = "failed"
            complete["episodes"]["2"]["qc_status"] = "fail"
            complete["status"] = "failed"
            save_job(job_path, complete)

            resumed = run_command(
                [sys.executable, str(SCRIPTS / "remaster_job.py"), "resume", "--job", str(job_path), "--confirm"]
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout)
            self.assertEqual(first_path.stat().st_mtime_ns, first_mtime)
            self.assertTrue(second_path.is_file())
            self.assertEqual(load_job(job_path)["status"], "complete")

            manifest = json.loads((output_root / "manifests" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["episodes"]), 2)


if __name__ == "__main__":
    unittest.main()
