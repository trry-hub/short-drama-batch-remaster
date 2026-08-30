from __future__ import annotations

import sys
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from batch_executor import FatalConfigurationError, execute_episodes, resolve_worker_count  # noqa: E402


@dataclass(frozen=True)
class Job:
    output_episode: int


@dataclass(frozen=True)
class Result:
    episode_number: int


class ConcurrencyTracker:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def worker(self, job: Job) -> Result:
        with self.lock:
            self.current += 1
            self.maximum = max(self.maximum, self.current)
        time.sleep(0.02)
        with self.lock:
            self.current -= 1
        return Result(job.output_episode)


class BatchExecutorTests(unittest.TestCase):
    def test_auto_worker_count_is_conservative(self) -> None:
        self.assertEqual(resolve_worker_count("auto", cpu_count=1), 1)
        self.assertEqual(resolve_worker_count("auto", cpu_count=16), 4)
        self.assertEqual(resolve_worker_count(3, cpu_count=16), 3)

    def test_executor_is_bounded_and_returns_episode_order(self) -> None:
        tracker = ConcurrencyTracker()
        jobs = [Job(number) for number in (3, 1, 2, 4)]
        results = execute_episodes(jobs, tracker.worker, workers=2)
        self.assertLessEqual(tracker.maximum, 2)
        self.assertEqual([item.episode_number for item in results], [1, 2, 3, 4])

    def test_fatal_configuration_error_is_not_converted_to_episode_failure(self) -> None:
        def worker(job: Job) -> Result:
            if job.output_episode == 1:
                raise FatalConfigurationError("bad profile")
            time.sleep(0.1)
            return Result(job.output_episode)

        with self.assertRaisesRegex(FatalConfigurationError, "bad profile"):
            execute_episodes([Job(1), Job(2), Job(3)], worker, workers=2)


if __name__ == "__main__":
    unittest.main()
