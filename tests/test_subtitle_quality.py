from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subtitle_quality import inspect_subtitles, subtitle_rules  # noqa: E402


class SubtitleQualityTests(unittest.TestCase):
    def write_srt(self, text: str) -> Path:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        path = Path(self.tempdir.name) / "episode.srt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_overlapping_and_out_of_range_cues_are_reported(self) -> None:
        path = self.write_srt(
            "1\n00:00:01,000 --> 00:00:04,000\nFirst\n\n"
            "2\n00:00:03,500 --> 00:00:12,000\nSecond\n"
        )
        findings = inspect_subtitles(path, duration_s=10.0)
        self.assertIn("subtitle.overlap", {item.code for item in findings})
        self.assertIn("subtitle.out_of_range", {item.code for item in findings})

    def test_long_uncertain_text_and_review_terms_are_warnings(self) -> None:
        path = self.write_srt(
            "1\n00:00:01,000 --> 00:00:03,000\n"
            "这是一句非常非常非常非常非常非常非常长的字幕而且包含待核对词[?]\n"
        )
        findings = inspect_subtitles(path, duration_s=5.0, review_terms=("待核对词",))
        rules = {item.rule_id: item for item in subtitle_rules(findings)}
        self.assertEqual(rules["subtitle.line_length"].severity, "warning")
        self.assertEqual(rules["subtitle.uncertain"].status, "fail")
        self.assertEqual(rules["subtitle.review_term"].status, "fail")

    def test_malformed_srt_is_a_blocker(self) -> None:
        path = self.write_srt("not a subtitle")
        rules = {item.rule_id: item for item in subtitle_rules(inspect_subtitles(path, 5.0))}
        self.assertEqual((rules["subtitle.parse"].severity, rules["subtitle.parse"].status), ("blocker", "fail"))


if __name__ == "__main__":
    unittest.main()
