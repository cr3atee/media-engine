"""Run the deterministic EPIC 20 catalog-onboarding acceptance gate."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True, frozen=True)
class VerificationGate:
    """One existing verifier and its fixed command-line arguments."""

    name: str
    script: str
    arguments: tuple[str, ...] = ()


REQUIRED_GATES = (
    VerificationGate(
        name="saved marketplace payload contracts",
        script="scripts/verify_marketplace_payload_contracts.py",
    ),
    VerificationGate(
        name="saved-data catalog review workspace",
        script="scripts/run_catalog_review_preview.py",
        arguments=("--saved-data", "--check"),
    ),
    VerificationGate(
        name="operator decision to public catalog",
        script="scripts/verify_catalog_onboarding_end_to_end.py",
    ),
    VerificationGate(
        name="repository-backed public catalog and terminal",
        script="scripts/verify_public_ui_readiness.py",
    ),
)

LIVE_EVIDENCE_GATE = VerificationGate(
    name="bounded aligned live review evidence",
    script="scripts/run_catalog_review_preview.py",
    arguments=("--aligned-live-data", "--check"),
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic gates and optionally refresh live review evidence."""
    _configure_stdout()
    arguments = _parse_arguments(argv)
    gates = REQUIRED_GATES + (
        (LIVE_EVIDENCE_GATE,) if arguments.include_live_evidence else ()
    )
    failures: list[str] = []

    print("=== EPIC 20 CATALOG ONBOARDING GATE ===")
    print(
        "Mode: "
        + (
            "offline plus live evidence"
            if arguments.include_live_evidence
            else "offline"
        )
    )
    print("Catalog mutations: isolated memory only")
    print("Automatic marketplace links: forbidden")

    for gate in gates:
        print()
        print(f"--- {gate.name} ---")
        if not _run_gate(gate):
            failures.append(gate.name)

    print()
    print(
        "Boundary: saved real offers remain unreviewed until an operator "
        "explicitly confirms or rejects them."
    )
    if failures:
        print("EPIC 20 catalog-onboarding gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"EPIC 20 catalog-onboarding gate passed: {len(gates)}/{len(gates)} gates.")
    return 0


def _run_gate(gate: VerificationGate) -> bool:
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / gate.script),
            *gate.arguments,
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    outcome = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{outcome}: {gate.name}")
    return completed.returncode == 0


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the guarded EPIC 20 catalog-onboarding boundary.",
    )
    parser.add_argument(
        "--include-live-evidence",
        action="store_true",
        help=(
            "Also fetch a bounded aligned review batch. External source "
            "availability may make this optional stage fail."
        ),
    )
    return parser.parse_args(argv)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
