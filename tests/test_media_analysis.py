from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from delivery_profiles import load_delivery_profile  # noqa: E402
from media_analysis import CommandResult, MediaAnalysis, analyze_media, media_rules  # noqa: E402


PROBE = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1080,
            "height": 1920,
            "pix_fmt": "yuv420p",
            "avg_frame_rate": "30/1",
        },
        {"codec_type": "audio", "codec_name": "aac"},
    ],
    "format": {"duration": "20.0", "size": "10000000", "bit_rate": "4000000"},
}


class FakeRunner:
    def __call__(self, command: list[str]) -> CommandResult:
        joined = " ".join(command)
        if command[0] == "ffprobe":
            return CommandResult(0, json.dumps(PROBE), "")
        if "blackdetect" in joined:
            return CommandResult(0, "", "black_start:2 black_end:4 black_duration:2")
        if "freezedetect" in joined:
            return CommandResult(0, "", "freeze_start:8\nfreeze_end:11 | freeze_duration:3")
        if "silencedetect" in joined:
            return CommandResult(0, "", "silence_start:12\nsilence_end:17 | silence_duration:5")
        if "loudnorm" in joined:
            return CommandResult(0, "", '{"input_i":"-25.0","input_tp":"-3.2"}')
        return CommandResult(0, "", "")


class MediaAnalysisTests(unittest.TestCase):
    def test_analysis_parses_quality_events(self) -> None:
        result = analyze_media(Path("episode.mp4"), runner=FakeRunner())
        self.assertEqual(result.black_ranges, ((2.0, 4.0),))
        self.assertEqual(result.freeze_ranges, ((8.0, 11.0),))
        self.assertEqual(result.silence_ranges, ((12.0, 17.0),))
        self.assertEqual(result.integrated_lufs, -25.0)
        self.assertEqual(result.true_peak_db, -3.2)

    def test_missing_audio_is_a_blocker(self) -> None:
        analysis = MediaAnalysis(path="episode.mp4", readable=True, has_video=True, has_audio=False)
        rules = {item.rule_id: item for item in media_rules(analysis, load_delivery_profile("video-channels"))}
        self.assertEqual((rules["media.streams"].severity, rules["media.streams"].status), ("blocker", "fail"))

    def test_quality_ranges_and_loudness_are_warnings(self) -> None:
        rules = {
            item.rule_id: item
            for item in media_rules(analyze_media(Path("episode.mp4"), runner=FakeRunner()), load_delivery_profile("video-channels"))
        }
        self.assertEqual(rules["audio.loudness"].status, "fail")
        self.assertEqual(rules["video.black"].status, "fail")
        self.assertEqual(rules["video.freeze"].status, "fail")
        self.assertEqual(rules["audio.silence"].status, "fail")
        self.assertTrue(all(rules[key].severity == "warning" for key in ("audio.loudness", "video.black", "video.freeze", "audio.silence")))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_real_synthetic_media_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sample.mp4"
            command = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=160x284:r=30:d=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ]
            subprocess.run(command, check=True)
            result = analyze_media(path)
            self.assertTrue(result.readable)
            self.assertTrue(result.has_video)
            self.assertTrue(result.has_audio)
            self.assertIsNotNone(result.integrated_lufs)
            self.assertEqual(result.decode_errors, ())


if __name__ == "__main__":
    unittest.main()
