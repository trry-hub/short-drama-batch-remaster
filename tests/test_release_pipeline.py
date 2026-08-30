from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from media_analysis import MediaAnalysis  # noqa: E402
from release_pipeline import build_episode_report, run_readiness_pipeline  # noqa: E402


def passing_analysis(path: Path) -> MediaAnalysis:
    return MediaAnalysis(
        path=str(path),
        readable=True,
        duration_s=60.0,
        width=1080,
        height=1920,
        frame_rate=30.0,
        bitrate_mbps=6.5,
        size_mb=50.0,
        has_video=True,
        has_audio=True,
        video_codec="h264",
        audio_codec="aac",
        integrated_lufs=-16.0,
        true_peak_db=-1.5,
    )


class ReleasePipelineTests(unittest.TestCase):
    def context(self) -> dict:
        return {
            "rights_status": "owned",
            "rights_evidence": "ownership-record-1",
            "attribution": {"required": False, "text": "", "approved": False},
            "disclosure": {"ai_content": False, "ai_label": "not-applicable"},
            "enhancements": {"covers": False, "subtitles": False, "metadata": False, "copy": False, "narration": False},
            "publishing": {"prepare": False, "approved": False},
        }

    def test_episode_report_combines_media_and_rights_rules(self) -> None:
        episode = {"episode_number": 1, "output_path": "/tmp/episode.mp4", "status": "complete", "qc_status": "pass"}
        report = build_episode_report(episode, self.context(), [], analyzer=passing_analysis)
        self.assertEqual(report.status, "pass")
        rule_ids = {item.rule_id for item in report.rules}
        self.assertIn("media.readable", rule_ids)
        self.assertIn("rights.status", rule_ids)
        self.assertIn("subtitle.required", rule_ids)

    def test_requested_missing_subtitle_blocks_release(self) -> None:
        context = self.context()
        context["enhancements"]["subtitles"] = True
        episode = {"episode_number": 1, "output_path": "/tmp/episode.mp4", "status": "complete", "qc_status": "pass"}
        report = build_episode_report(episode, context, [], analyzer=passing_analysis)
        required = next(item for item in report.rules if item.rule_id == "subtitle.required")
        self.assertEqual((required.severity, required.status), ("blocker", "fail"))

    def test_pipeline_adds_batch_report_and_writes_three_formats(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            video = root / "episode.mp4"
            video.write_bytes(b"video")
            manifest = {
                "episodes": [{"episode_number": 1, "output_path": str(video), "status": "complete", "qc_status": "pass"}]
            }
            result = run_readiness_pipeline(manifest, self.context(), {}, root / "reports", analyzer=passing_analysis)
            self.assertEqual(result.status, "pass")
            self.assertEqual(len(result.reports), 2)
            self.assertTrue(result.paths.json.is_file())
            self.assertTrue(result.paths.csv.is_file())
            self.assertTrue(result.paths.markdown.is_file())
            payload = json.loads(result.paths.json.read_text(encoding="utf-8"))
            self.assertEqual(payload["reports"][-1]["subject"], "batch")


if __name__ == "__main__":
    unittest.main()
