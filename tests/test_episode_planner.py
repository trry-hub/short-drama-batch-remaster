from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from episode_planner import (  # noqa: E402
    SourceMedia,
    plan_one_to_one,
    plan_target_duration,
    write_episode_plan_csv,
)


class EpisodePlannerTests(unittest.TestCase):
    def test_one_to_one_preserves_files_and_applies_speed(self) -> None:
        media = [SourceMedia("01.mp4", 63.0, ()), SourceMedia("02.mp4", 31.5, ())]
        plan = plan_one_to_one(media, speed=1.05, episode_start=4)
        self.assertEqual([episode.output_episode for episode in plan], [4, 5])
        self.assertEqual(plan[0].segments[0].path, "01.mp4")
        self.assertEqual(plan[0].estimated_duration_s, 60.0)

    def test_target_duration_groups_adjacent_sources_without_reordering(self) -> None:
        media = [
            SourceMedia("01.mp4", 25.0, ()),
            SourceMedia("02.mp4", 30.0, ()),
            SourceMedia("03.mp4", 60.0, ()),
        ]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
        self.assertEqual([segment.path for segment in plan[0].segments], ["01.mp4", "02.mp4"])
        self.assertEqual(plan[0].estimated_duration_s, 55.0)
        self.assertEqual([segment.path for segment in plan[1].segments], ["03.mp4"])

    def test_target_duration_uses_nearest_scene_boundary(self) -> None:
        media = [SourceMedia("long.mp4", 140.0, (52.0, 63.0, 118.0))]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
        self.assertEqual(plan[0].segments[0].end_s, 63.0)
        self.assertEqual(plan[1].segments[0].start_s, 63.0)

    def test_target_duration_forces_max_cut_without_scene_boundary(self) -> None:
        media = [SourceMedia("long.mp4", 160.0, ())]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=7)
        self.assertEqual(plan[0].output_episode, 7)
        self.assertEqual(plan[0].segments[0].end_s, 75.0)
        self.assertEqual(plan[1].segments[0].start_s, 75.0)

    def test_final_short_episode_is_preserved_and_marked(self) -> None:
        media = [SourceMedia("long.mp4", 95.0, (60.0,))]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
        self.assertEqual(plan[-1].estimated_duration_s, 35.0)
        self.assertTrue(plan[-1].short_final)

    def test_speed_changes_source_cut_distance(self) -> None:
        media = [SourceMedia("long.mp4", 126.0, (63.0,))]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.05, episode_start=1)
        self.assertEqual(plan[0].segments[0].end_s, 63.0)
        self.assertEqual(plan[0].estimated_duration_s, 60.0)

    def test_plan_csv_contains_segment_ranges(self) -> None:
        media = [SourceMedia("a.mp4", 80.0, ())]
        plan = plan_target_duration(media, 60.0, 45.0, 75.0, speed=1.0, episode_start=1)
        with TemporaryDirectory() as raw:
            path = Path(raw) / "episode_plan.csv"
            write_episode_plan_csv(path, plan)
            text = path.read_text(encoding="utf-8")
            self.assertIn("a.mp4@0.000-75.000", text)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["output_episode"], "1")

    def test_planner_rejects_invalid_duration_band(self) -> None:
        with self.assertRaisesRegex(ValueError, "min <= target <= max"):
            plan_target_duration([], 80.0, 45.0, 75.0, speed=1.0, episode_start=1)


if __name__ == "__main__":
    unittest.main()
