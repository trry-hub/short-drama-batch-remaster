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
    save_job,
    set_job_field,
    validate_job,
)


class RemasterJobCoreTests(unittest.TestCase):
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
                ("planning.mode", "mapping-csv"),
            ):
                job = set_job_field(job, field, value)
            self.assertEqual(next_question(job).field, "planning.mapping_csv")

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


if __name__ == "__main__":
    unittest.main()
