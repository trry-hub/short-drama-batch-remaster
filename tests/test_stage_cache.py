from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage_cache import StageCache, build_cache_key  # noqa: E402


class StageCacheTests(unittest.TestCase):
    def test_validated_cache_entry_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "episode.mp4"
            source.write_bytes(b"encoded-video")
            cache = StageCache(root / "cache")
            key = build_cache_key([{"sha256": "source"}], [{"start": 0, "end": 2}], {"width": 1080}, {"speed": 1.05}, "cache-v1")
            cache.store(key, source, validation_status="pass", metadata={"episode": 1})
            hit = cache.lookup(key)
            self.assertIsNotNone(hit)
            self.assertEqual(hit.metadata["episode"], 1)
            self.assertEqual(hit.artifact.read_bytes(), b"encoded-video")

    def test_cache_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "episode.mp4"
            source.write_bytes(b"encoded-video")
            cache = StageCache(root / "cache")
            key = build_cache_key(["source"], [0, 2], {"width": 1080}, {}, "cache-v1")
            cache.store(key, source, validation_status="pass")
            hit = cache.lookup(key)
            self.assertIsNotNone(hit)
            hit.artifact.write_bytes(b"changed")
            self.assertIsNone(cache.lookup(key))

    def test_parameter_change_changes_cache_key(self) -> None:
        first = build_cache_key(["source"], [0, 2], {"width": 1080}, {"speed": 1.0}, "cache-v1")
        second = build_cache_key(["source"], [0, 2], {"width": 1080}, {"speed": 1.05}, "cache-v1")
        self.assertNotEqual(first, second)

    def test_prune_preserves_referenced_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "episode.mp4"
            source.write_bytes(b"video")
            cache = StageCache(root / "cache")
            cache.store("keep", source, validation_status="pass")
            cache.store("remove", source, validation_status="pass")
            result = cache.prune({"keep"})
            self.assertEqual(result.entries_removed, 1)
            self.assertIsNotNone(cache.lookup("keep"))
            self.assertIsNone(cache.lookup("remove"))


if __name__ == "__main__":
    unittest.main()
