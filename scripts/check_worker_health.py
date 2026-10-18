"""Check freshness and shape of a worker Prometheus textfile."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

SCHEDULER_STATE_METRIC = "mediaengine_scheduler_job_state"


def check_worker_health(
    metrics_file: Path,
    *,
    max_age_seconds: float,
    observed_at: float | None = None,
) -> None:
    """Raise a sanitized error unless worker metrics exist and are fresh."""
    if max_age_seconds <= 0:
        raise ValueError("Worker health maximum age must be greater than zero.")
    try:
        metadata = metrics_file.stat()
        payload = metrics_file.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(
            f"Worker health failed: metrics file {type(error).__name__}."
        ) from error
    current_time = time.time() if observed_at is None else observed_at
    age_seconds = current_time - metadata.st_mtime
    if age_seconds < 0 or age_seconds > max_age_seconds:
        raise RuntimeError("Worker health failed: metrics file is stale.")
    if SCHEDULER_STATE_METRIC not in payload:
        raise RuntimeError("Worker health failed: scheduler metrics are missing.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one bounded worker health check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-file", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=float, required=True)
    arguments = parser.parse_args(argv)
    try:
        check_worker_health(
            arguments.metrics_file,
            max_age_seconds=arguments.max_age_seconds,
        )
    except (RuntimeError, ValueError) as error:
        print(error)
        return 1
    print("MediaEngine worker is healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
