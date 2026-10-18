"""Check the MediaEngine API readiness endpoint for container orchestration."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import httpx


def check_api_health(url: str, *, timeout_seconds: float) -> None:
    """Raise a sanitized error unless the API reports ready status."""
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError(f"API readiness failed: {type(error).__name__}.") from error
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError("API readiness failed: service is not ready.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one bounded readiness check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    arguments = parser.parse_args(argv)
    if arguments.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    try:
        check_api_health(
            arguments.url,
            timeout_seconds=arguments.timeout_seconds,
        )
    except RuntimeError as error:
        print(error)
        return 1
    print("MediaEngine API is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
