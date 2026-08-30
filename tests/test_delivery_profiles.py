from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from delivery_profiles import load_delivery_profile  # noqa: E402


class DeliveryProfileTests(unittest.TestCase):
    def test_builtin_video_channels_profile_is_versioned(self) -> None:
        profile = load_delivery_profile("video-channels", 1)
        self.assertEqual(profile.name, "video-channels")
        self.assertEqual(profile.version, 1)
        self.assertEqual((profile.width, profile.height), (1080, 1920))
        self.assertEqual((profile.video_codec, profile.audio_codec), ("h264", "aac"))
        self.assertFalse(profile.platform_approval_guarantee)
        self.assertTrue(profile.require_ai_label_when_ai)
        self.assertIn("content_labels", profile.verified_fields)

    def test_profile_records_source_without_claiming_unverified_geometry(self) -> None:
        profile = load_delivery_profile("video-channels")
        self.assertIn("cac.gov.cn", profile.source_url or "")
        self.assertNotIn("geometry", profile.verified_fields)

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported delivery profile"):
            load_delivery_profile("unknown")


if __name__ == "__main__":
    unittest.main()
