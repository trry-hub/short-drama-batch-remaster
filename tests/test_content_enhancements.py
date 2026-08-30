from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_enhancements import (  # noqa: E402
    AdapterBundle,
    EnhancementRequest,
    NeedsInput,
    TranscriptSegment,
    enhance_episode,
)


def fake_adapters() -> AdapterBundle:
    def transcribe(_path: Path) -> list[TranscriptSegment]:
        return [TranscriptSegment(0.0, 1.5, "第一句"), TranscriptSegment(1.5, 3.0, "第二句")]

    def covers(_video: Path, output_dir: Path, episode: int) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(1, 4):
            path = output_dir / f"episode-{episode:03d}-{index}.jpg"
            path.write_bytes(b"image")
            paths.append(path)
        return paths

    def narrate(_text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"audio")
        return output_path

    return AdapterBundle(
        transcribe=transcribe,
        extract_covers=covers,
        narrate=narrate,
        scene_boundaries=lambda _path: [0.0, 1.4, 3.0],
        names={"transcribe": "fake-whisper", "covers": "fake-covers", "narrate": "fake-tts", "scenes": "fake-scenes"},
    )


class ContentEnhancementTests(unittest.TestCase):
    def request(self, root: Path, **overrides: object) -> EnhancementRequest:
        video = root / "episode.mp4"
        video.write_bytes(b"video")
        values = {
            "episode": 1,
            "video_path": video,
            "output_root": root / "release",
            "subtitles": False,
            "covers": False,
            "copy": False,
            "narration": False,
            "editorial_recommendations": False,
        }
        values.update(overrides)
        return EnhancementRequest(**values)

    def test_features_are_independently_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            request = self.request(Path(raw), subtitles=True, copy=True)
            artifacts = enhance_episode(request, adapters=fake_adapters())
            self.assertEqual({item.kind for item in artifacts}, {"srt", "vtt", "transcript", "copy"})
            self.assertTrue(all(item.review_status == "needs_review" for item in artifacts))

    def test_narration_requires_an_approved_script(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            request = self.request(Path(raw), narration=True, narration_script=None)
            with self.assertRaisesRegex(NeedsInput, "approved narration script"):
                enhance_episode(request, adapters=fake_adapters())

    def test_selected_narration_and_editorial_assets_have_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "narration.txt"
            script.write_text("经过确认的旁白", encoding="utf-8")
            request = self.request(
                root,
                narration=True,
                narration_script=script,
                narration_script_approved=True,
                editorial_recommendations=True,
            )
            artifacts = enhance_episode(request, adapters=fake_adapters())
            by_kind = {item.kind: item for item in artifacts}
            self.assertEqual({"narration", "editorial_recommendations"}, set(by_kind))
            self.assertEqual(by_kind["narration"].tool, "fake-tts")
            self.assertEqual(by_kind["editorial_recommendations"].source_episode, 1)
            recommendations = json.loads(Path(by_kind["editorial_recommendations"].path).read_text(encoding="utf-8"))
            self.assertEqual(recommendations["scene_boundaries_s"], [0.0, 1.4, 3.0])
            self.assertFalse(recommendations["scene_order_changed"])

    def test_unselected_provider_is_never_called(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            adapters = fake_adapters()

            def forbidden(_text: str, _path: Path) -> Path:
                raise AssertionError("narration provider should not be called")

            adapters.narrate = forbidden
            self.assertEqual(enhance_episode(self.request(Path(raw)), adapters=adapters), [])


if __name__ == "__main__":
    unittest.main()
