from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from remaster_job_core import (  # noqa: E402
    job_path_for_output,
    load_job,
    new_job,
    next_question,
    normalize_job,
    save_job,
    set_job_field,
    validate_job,
)


class RemasterJobCoreTests(unittest.TestCase):
    def test_old_job_gets_backward_compatible_optimization_defaults(self) -> None:
        old = new_job(ROOT / "work" / "legacy")
        for field in ("delivery_profile", "execution", "disclosure", "release_readiness"):
            old.pop(field, None)
        old["enhancements"].pop("copy", None)
        old["enhancements"].pop("narration", None)

        normalized = normalize_job(old)

        self.assertEqual(normalized["delivery_profile"], {"name": "video-channels", "version": 1})
        self.assertEqual(normalized["execution"]["workers"], "auto")
        self.assertEqual(normalized["execution"]["enhancement_workers"], 1)
        self.assertEqual(normalized["execution"]["encoder"], "auto")
        self.assertTrue(normalized["execution"]["cache"])
        self.assertFalse(normalized["disclosure"]["ai_content"])
        self.assertEqual(normalized["release_readiness"]["status"], "pending")

    def test_new_job_requires_ai_content_decision(self) -> None:
        job = new_job(ROOT / "work" / "release")
        self.assertIsNone(job["disclosure"]["ai_content"])
        questions = [question.field for question in __import__("remaster_job_core")._question_table(job)]
        self.assertIn("disclosure.ai_content", questions)

    def test_worker_count_preserves_plan_but_encoder_change_invalidates_it(self) -> None:
        job = new_job(ROOT / "work" / "release")
        job["episode_plan"] = [{"output_episode": 1, "segments": []}]
        job["episodes"] = {"1": {"status": "complete", "qc_status": "pass"}}
        updated = set_job_field(job, "execution.workers", "3")
        self.assertEqual(updated["execution"]["workers"], 3)
        self.assertEqual(updated["episode_plan"], job["episode_plan"])
        changed_encoder = set_job_field(updated, "execution.encoder", "software")
        self.assertEqual(changed_encoder["execution"]["encoder"], "software")
        self.assertEqual(changed_encoder["episode_plan"], [])
        self.assertEqual(changed_encoder["episodes"], {})

    def test_new_job_is_draft_and_uses_output_job_folder(self) -> None:
        with self.subTest("new job defaults"):
            root = ROOT / "work" / "test-output"
            job = new_job(root)
            self.assertEqual(job["schema_version"], 1)
            self.assertEqual(job["status"], "draft")
            self.assertEqual(job["output_root"], str(root.resolve()))
            self.assertEqual(job_path_for_output(root), root / ".job" / "job.json")

    def test_save_job_round_trips_and_leaves_no_temp_file(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw:
            output_root = Path(raw) / "release"
            path = job_path_for_output(output_root)
            job = new_job(output_root)
            save_job(path, job)
            self.assertEqual(load_job(path), job)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_next_question_is_conditional_and_one_at_a_time(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw:
            output_root = Path(raw) / "release"
            source = Path(raw) / "source"
            source.mkdir()
            job = new_job(output_root)
            self.assertEqual(next_question(job).field, "source_root")
            job = set_job_field(job, "source_root", str(source))
            self.assertEqual(next_question(job).field, "source_series")
            job = set_job_field(job, "source_series", "Source")
            job = set_job_field(job, "output_series", "Output")
            job = set_job_field(job, "rights_status", "owned")
            job = set_job_field(job, "rights_evidence", "")
            job = set_job_field(job, "attribution.required", "no")
            job = set_job_field(job, "disclosure.ai_content", "no")
            job = set_job_field(job, "planning.mode", "target-duration")
            self.assertEqual(next_question(job).field, "planning.target_duration_s")

    def test_mapping_question_only_appears_in_mapping_mode(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw:
            source = Path(raw) / "source"
            source.mkdir()
            job = new_job(Path(raw) / "release")
            for field, value in (
                ("source_root", str(source)),
                ("source_series", "Source"),
                ("output_series", "Output"),
                ("rights_status", "owned"),
                ("rights_evidence", ""),
                ("attribution.required", "no"),
                ("disclosure.ai_content", "no"),
                ("planning.mode", "mapping-csv"),
            ):
                job = set_job_field(job, field, value)
            self.assertEqual(next_question(job).field, "planning.mapping_csv")

    def test_narration_questions_require_script_and_approval(self) -> None:
        job = new_job(ROOT / "work" / "release")
        job = set_job_field(job, "enhancements.narration", "yes")
        questions = [question.field for question in __import__("remaster_job_core")._question_table(job)]
        self.assertIn("enhancements.narration_script", questions)
        self.assertIn("enhancements.narration_script_approved", questions)
        self.assertIn("enhancements.mix_narration", questions)

    def test_validation_rejects_invalid_duration_band(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw:
            job = new_job(Path(raw) / "release")
            job["planning"] = {
                "mode": "target-duration",
                "target_duration_s": 80.0,
                "min_duration_s": 45.0,
                "max_duration_s": 75.0,
            }
            self.assertIn("target duration must be between minimum and maximum", validate_job(job))

    def test_set_field_rejects_unknown_rights_status(self) -> None:
        job = new_job(ROOT / "work" / "release")
        with self.assertRaisesRegex(ValueError, "rights status"):
            set_job_field(job, "rights_status", "unknown")

    def test_media_setting_change_invalidates_plan_and_episode_checkpoints(self) -> None:
        job = new_job(ROOT / "work" / "release")
        job["episode_plan"] = [{"output_episode": 1, "segments": []}]
        job["source_inventory"] = [{"path": "old.mp4"}]
        job["episodes"] = {"1": {"status": "complete", "qc_status": "pass"}}
        updated = set_job_field(job, "profile.speed", "1.1")
        self.assertEqual(updated["episode_plan"], [])
        self.assertEqual(updated["source_inventory"], [])
        self.assertEqual(updated["episodes"], {})

    def test_account_change_preserves_media_checkpoints(self) -> None:
        job = new_job(ROOT / "work" / "release")
        job["episode_plan"] = [{"output_episode": 1, "segments": []}]
        job["episodes"] = {"1": {"status": "complete", "qc_status": "pass"}}
        updated = set_job_field(job, "account", "channel-a")
        self.assertEqual(updated["episode_plan"], job["episode_plan"])
        self.assertEqual(updated["episodes"], job["episodes"])


if __name__ == "__main__":
    unittest.main()
