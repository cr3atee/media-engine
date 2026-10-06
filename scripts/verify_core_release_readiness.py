"""Run the repeatable MediaEngine backend core release gate."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL_ENV = "MEDIAENGINE_CORE_RELEASE_DATABASE_URL"


@dataclass(slots=True, frozen=True)
class VerificationGate:
    """One existing verifier executed by the release coordinator."""

    name: str
    script: str
    database_url_env: str | None = None


OFFLINE_GATES = (
    VerificationGate(
        name="saved marketplace payload contracts",
        script="scripts/verify_marketplace_payload_contracts.py",
    ),
    VerificationGate(
        name="repository-backed public UI readiness",
        script="scripts/verify_public_ui_readiness.py",
    ),
)

POSTGRES_GATES = (
    VerificationGate(
        name="PostgreSQL public UI and fresh-session reads",
        script="scripts/verify_epic19_public_ui_postgres.py",
        database_url_env="EPIC19_DATABASE_URL",
    ),
    VerificationGate(
        name="durable polling history and atomic outcomes",
        script="scripts/verify_marketplace_polling_history_postgres.py",
        database_url_env="EPIC19_POLLING_HISTORY_DATABASE_URL",
    ),
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run offline checks and, unless requested otherwise, PostgreSQL checks."""
    _configure_stdout()
    arguments = _parse_arguments(argv)
    database_url = os.getenv(DATABASE_URL_ENV, "").strip()
    if not arguments.offline:
        if not database_url:
            print(
                f"FAILED: set {DATABASE_URL_ENV} to an isolated local "
                "PostgreSQL database."
            )
            return 2
        validate_release_database_url(database_url)

    gates = OFFLINE_GATES if arguments.offline else OFFLINE_GATES + POSTGRES_GATES
    failures: list[str] = []
    print("=== MEDIAENGINE CORE RELEASE GATE ===")
    print(f"Mode: {'offline' if arguments.offline else 'full'}")
    print("Live marketplace, Telegram, and AI calls: disabled")

    for gate in gates:
        print()
        print(f"--- {gate.name} ---")
        if not _run_gate(gate, database_url=database_url):
            failures.append(gate.name)

    print()
    print("Catalog boundary: no cross-marketplace product identity was inferred.")
    if failures:
        print("Core release gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Core release gate passed: {len(gates)}/{len(gates)} gates.")
    return 0


def validate_release_database_url(database_url: str) -> None:
    """Reject non-local or ambiguously named databases before destructive checks."""
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must target local PostgreSQL.")
    if not database_name.startswith("epic19_history_release_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            "epic19_history_release_* database."
        )


def _run_gate(gate: VerificationGate, *, database_url: str) -> bool:
    environment = os.environ.copy()
    if gate.database_url_env is not None:
        environment[gate.database_url_env] = database_url
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / gate.script)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
    )
    outcome = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{outcome}: {gate.name}")
    return completed.returncode == 0


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the MediaEngine backend core release candidate.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run saved-payload and memory-backed public UI checks only.",
    )
    return parser.parse_args(argv)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
