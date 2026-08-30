from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_release_pack import (  # noqa: E402
    EpisodeResult,
    apply_job_document,
    encoder_output_args,
    hash_file,
    is_full_source_segment,
    parse_args,
    parse_episode_plan,
    should_skip_episode,
    update_episode_checkpoint,
)
from episode_planner import SourceSegment  # noqa: E402
from encoder_selection import EncoderChoice  # noqa: E402
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
        self.assertEqual(args.workers, "auto")
        self.assertEqual(args.encoder, "auto")
        self.assertTrue(args.cache)

    def test_job_document_maps_execution_options(self) -> None:
        document = new_job(Path("/tmp/output"))
        document["source_root"] = "/tmp/source"
        document["source_series"] = "Source"
        document["output_series"] = "Output"
        document["rights_status"] = "owned"
        document["execution"] = {"workers": 3, "enhancement_workers": 1, "encoder": "software", "cache": False}
        args = apply_job_document(parse_args(["--job-file", "/tmp/job.json"]), document)
        self.assertEqual(args.workers, 3)
        self.assertEqual(args.encoder, "software")
        self.assertFalse(args.cache)

    def test_hardware_encoder_args_do_not_include_software_preset(self) -> None:
        software = Namespace(
            preset="medium",
            encoder_choice=EncoderChoice("software", "libx264", ("-c:v", "libx264"), False),
        )
        hardware = Namespace(
            preset="medium",
            encoder_choice=EncoderChoice(
                "hardware",
                "h264_videotoolbox",
                ("-c:v", "h264_videotoolbox", "-allow_sw", "0"),
                True,
            ),
        )
        self.assertEqual(encoder_output_args(software), ["-c:v", "libx264", "-preset", "medium"])
        self.assertEqual(encoder_output_args(hardware), ["-c:v", "h264_videotoolbox", "-allow_sw", "0"])


if __name__ == "__main__":
    unittest.main()
