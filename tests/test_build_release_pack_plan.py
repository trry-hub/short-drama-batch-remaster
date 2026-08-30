from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_release_pack import (  # noqa: E402
    EpisodeResult,
    hash_file,
    is_full_source_segment,
    parse_args,
    parse_episode_plan,
    should_skip_episode,
    update_episode_checkpoint,
)
from episode_planner import SourceSegment  # noqa: E402
from remaster_job_core import load_job, new_job, save_job  # noqa: E402


class BuildReleasePackPlanTests(unittest.TestCase):
    def test_parse_episode_plan_keeps_segment_order(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            document = {
                "episode_plan": [
                    {
                        "output_episode": 3,
                        "segments": [
                            {"path": str(root / "02.mp4"), "start_s": 10.0, "end_s": 30.0},
                            {"path": str(root / "01.mp4"), "start_s": 0.0, "end_s": 20.0},
                        ],
                    }
                ]
            }
            parsed = parse_episode_plan(document)
            self.assertEqual(parsed[0].output_episode, 3)
            self.assertEqual([item.path for item in parsed[0].segments], [str(root / "02.mp4"), str(root / "01.mp4")])
            self.assertEqual(parsed[0].source_paths, [root / "02.mp4", root / "01.mp4"])

    def test_skip_requires_passed_qc_existing_path_and_matching_hash(self) -> None:
        with TemporaryDirectory() as raw:
            output = Path(raw) / "episode-001.mp4"
            output.write_bytes(b"passed")
            state = {
                "status": "complete",
                "qc_status": "pass",
                "output_path": str(output),
                "output_sha256": hash_file(output)["sha256"],
            }
            self.assertTrue(should_skip_episode(state))
            output.write_bytes(b"changed")
            self.assertFalse(should_skip_episode(state))

    def test_complete_segment_detection_uses_source_duration(self) -> None:
        self.assertTrue(is_full_source_segment(SourceSegment("a.mp4", 0.0, 10.0), 10.0))
        self.assertFalse(is_full_source_segment(SourceSegment("a.mp4", 1.0, 10.0), 10.0))
        self.assertFalse(is_full_source_segment(SourceSegment("a.mp4", 0.0, 9.0), 10.0))

    def test_episode_checkpoint_is_written_to_job_file(self) -> None:
        with TemporaryDirectory() as raw:
            output_root = Path(raw) / "release"
            job_path = output_root / ".job" / "job.json"
            document = new_job(output_root)
            save_job(job_path, document)
            result = EpisodeResult(
                episode_number=2,
                sources=["source.mp4"],
                output_path=str(output_root / "videos" / "episode-002.mp4"),
                status="complete",
                qc_status="pass",
                output_hashes={"md5": "abc", "sha256": "def"},
            )
            update_episode_checkpoint(job_path, result)
            checkpoint = load_job(job_path)["episodes"]["2"]
            self.assertEqual(checkpoint["status"], "complete")
            self.assertEqual(checkpoint["output_sha256"], "def")

    def test_job_file_mode_does_not_require_legacy_arguments(self) -> None:
        args = parse_args(["--job-file", "/tmp/job.json"])
        self.assertEqual(args.job_file, Path("/tmp/job.json"))
        self.assertIsNone(args.source_root)


if __name__ == "__main__":
    unittest.main()
