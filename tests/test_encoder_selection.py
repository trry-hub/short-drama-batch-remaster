from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from encoder_selection import select_encoder  # noqa: E402
from media_analysis import CommandResult  # noqa: E402


class EncoderRunner:
    def __init__(self, available: set[str], probe_ok: bool) -> None:
        self.available = available
        self.probe_ok = probe_ok

    def __call__(self, command: list[str]) -> CommandResult:
        if "-encoders" in command:
            listing = "\n".join(f" V..... {name} fake encoder" for name in sorted(self.available))
            return CommandResult(0, listing, "")
        return CommandResult(0 if self.probe_ok else 1, "", "probe failed" if not self.probe_ok else "")


class EncoderSelectionTests(unittest.TestCase):
    def test_software_mode_always_returns_libx264(self) -> None:
        choice = select_encoder("software", runner=EncoderRunner(set(), False))
        self.assertEqual(choice.codec, "libx264")
        self.assertFalse(choice.hardware)

    def test_auto_selects_probed_hardware(self) -> None:
        choice = select_encoder("auto", runner=EncoderRunner({"h264_videotoolbox"}, True))
        self.assertEqual(choice.codec, "h264_videotoolbox")
        self.assertTrue(choice.hardware)

    def test_auto_falls_back_after_failed_probe(self) -> None:
        choice = select_encoder("auto", runner=EncoderRunner({"h264_videotoolbox"}, False))
        self.assertEqual(choice.codec, "libx264")
        self.assertIn("probe failed", choice.fallback_reason or "")

    def test_explicit_hardware_mode_fails_without_encoder(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "hardware encoder"):
            select_encoder("hardware", runner=EncoderRunner(set(), False))


if __name__ == "__main__":
    unittest.main()
