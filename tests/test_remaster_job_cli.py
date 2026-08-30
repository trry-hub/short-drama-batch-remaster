from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from remaster_job_core import job_path_for_output, new_job, save_job  # noqa: E402
from remaster_job import invalidate_changed_source_checkpoints  # noqa: E402
from stage_cache import StageCache  # noqa: E402


def run_cli(*args: str, input_text: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "remaster_job.py"), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=command_env,
    )


class RemasterJobCliTests(unittest.TestCase):
    def test_init_set_and_status_persist_answers(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "release"
            init = run_cli("init", "--output-root", str(output))
            self.assertEqual(init.returncode, 0, init.stdout)
            job_path = job_path_for_output(output)
            source = root / "source"
            source.mkdir()
            set_result = run_cli("set", "--job", str(job_path), "source_root", str(source))
            self.assertEqual(set_result.returncode, 0, set_result.stdout)
            status = run_cli("status", "--job", str(job_path), "--json")
            self.assertEqual(status.returncode, 0, status.stdout)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["next_question"]["field"], "source_series")
            self.assertEqual(payload["job"]["source_root"], str(source.resolve()))

    def test_status_reports_only_the_next_missing_question(self) -> None:
        with TemporaryDirectory() as raw:
            output = Path(raw) / "release"
            run_cli("init", "--output-root", str(output))
            payload = json.loads(run_cli("status", "--job", str(job_path_for_output(output)), "--json").stdout)
            self.assertEqual(payload["next_question"]["field"], "source_root")
            self.assertNotIn("questions", payload)

    def test_run_requires_explicit_confirmation(self) -> None:
        with TemporaryDirectory() as raw:
            output = Path(raw) / "release"
            job_path = job_path_for_output(output)
            job = new_job(output)
            job["status"] = "ready"
            job["episode_plan"] = [
                {
                    "output_episode": 1,
                    "segments": [{"path": str(Path(raw) / "source.mp4"), "start_s": 0.0, "end_s": 1.0}],
                    "estimated_duration_s": 1.0,
                    "short_final": True,
                }
            ]
            save_job(job_path, job)
            result = run_cli("run", "--job", str(job_path))
            self.assertEqual(result.returncode, 2)
            self.assertIn("--confirm", result.stdout)

    def test_invalid_set_value_returns_usage_error_without_changing_job(self) -> None:
        with TemporaryDirectory() as raw:
            output = Path(raw) / "release"
            run_cli("init", "--output-root", str(output))
            job_path = job_path_for_output(output)
            result = run_cli("set", "--job", str(job_path), "rights_status", "unknown")
            self.assertEqual(result.returncode, 2)
            payload = json.loads(run_cli("status", "--job", str(job_path), "--json").stdout)
            self.assertIsNone(payload["job"]["rights_status"])

    def test_changed_source_invalidates_only_affected_episode_checkpoints(self) -> None:
        job = new_job(Path("/tmp/release"))
        job["episode_plan"] = [
            {"output_episode": 1, "segments": [{"path": "/src/a.mp4", "start_s": 0.0, "end_s": 10.0}]},
            {"output_episode": 2, "segments": [{"path": "/src/b.mp4", "start_s": 0.0, "end_s": 10.0}]},
        ]
        job["episodes"] = {
            "1": {"status": "complete", "qc_status": "pass"},
            "2": {"status": "complete", "qc_status": "pass"},
        }
        updated, affected = invalidate_changed_source_checkpoints(job, {"/src/a.mp4"})
        self.assertEqual(affected, [1])
        self.assertNotIn("1", updated["episodes"])
        self.assertIn("2", updated["episodes"])

    def test_cache_prune_preserves_checkpoint_references(self) -> None:
        with TemporaryDirectory() as raw:
            output = Path(raw) / "release"
            job_path = job_path_for_output(output)
            job = new_job(output)
            job["episodes"] = {"1": {"cache_key": "keep"}}
            save_job(job_path, job)
            artifact = Path(raw) / "artifact.mp4"
            artifact.write_bytes(b"video")
            cache = StageCache(output / ".job" / "cache")
            cache.store("keep", artifact, validation_status="pass")
            cache.store("remove", artifact, validation_status="pass")
            result = run_cli("cache-prune", "--job", str(job_path))
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["entries_removed"], 1)
            self.assertIsNotNone(cache.lookup("keep"))
            self.assertIsNone(cache.lookup("remove"))


if __name__ == "__main__":
    unittest.main()
