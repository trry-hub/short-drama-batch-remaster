#!/usr/bin/env python3
"""Bounded episode execution with deterministic result ordering."""

from __future__ import annotations

import os
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from itertools import islice
from typing import Any, Callable, Iterable, TypeVar


JobT = TypeVar("JobT")
ResultT = TypeVar("ResultT")


class FatalConfigurationError(RuntimeError):
    """A shared configuration error that should stop scheduling new episodes."""


def resolve_worker_count(value: str | int, cpu_count: int | None = None) -> int:
    if value != "auto":
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("worker count must be greater than zero")
        return parsed
    available = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
    return max(1, min(4, available // 2 or 1))


def execute_episodes(
    jobs: Iterable[JobT],
    worker: Callable[[JobT], ResultT],
    workers: int,
) -> list[ResultT]:
    if workers <= 0:
        raise ValueError("worker count must be greater than zero")
    pending_jobs = iter(sorted(jobs, key=lambda job: getattr(job, "output_episode")))
    results: list[ResultT] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="episode") as pool:
        futures: dict[Future[ResultT], JobT] = {
            pool.submit(worker, job): job for job in islice(pending_jobs, workers)
        }
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                futures.pop(future)
                try:
                    results.append(future.result())
                except FatalConfigurationError:
                    for remaining in futures:
                        remaining.cancel()
                    raise
                next_job = next(pending_jobs, None)
                if next_job is not None:
                    futures[pool.submit(worker, next_job)] = next_job
    return sorted(results, key=lambda result: getattr(result, "episode_number"))
