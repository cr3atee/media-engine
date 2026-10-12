from __future__ import annotations

import pytest

from scripts import verify_epic20_catalog_onboarding
from scripts.verify_epic20_catalog_onboarding import (
    LIVE_EVIDENCE_GATE,
    REQUIRED_GATES,
    VerificationGate,
)


def test_required_gate_reuses_existing_deterministic_verifiers() -> None:
    assert tuple((gate.script, gate.arguments) for gate in REQUIRED_GATES) == (
        ("scripts/verify_marketplace_payload_contracts.py", ()),
        (
            "scripts/run_catalog_review_preview.py",
            ("--saved-data", "--check"),
        ),
        ("scripts/verify_catalog_onboarding_end_to_end.py", ()),
        ("scripts/verify_public_ui_readiness.py", ()),
    )


def test_default_gate_does_not_use_live_marketplace_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[VerificationGate] = []

    def record_success(gate: VerificationGate) -> bool:
        executed.append(gate)
        return True

    monkeypatch.setattr(
        verify_epic20_catalog_onboarding,
        "_run_gate",
        record_success,
    )

    result = verify_epic20_catalog_onboarding.main([])

    assert result == 0
    assert tuple(executed) == REQUIRED_GATES


def test_live_evidence_is_explicitly_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[VerificationGate] = []

    def record_success(gate: VerificationGate) -> bool:
        executed.append(gate)
        return True

    monkeypatch.setattr(
        verify_epic20_catalog_onboarding,
        "_run_gate",
        record_success,
    )

    result = verify_epic20_catalog_onboarding.main(["--include-live-evidence"])

    assert result == 0
    assert tuple(executed) == REQUIRED_GATES + (LIVE_EVIDENCE_GATE,)


def test_gate_returns_failure_when_one_stage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_gate = REQUIRED_GATES[1]
    monkeypatch.setattr(
        verify_epic20_catalog_onboarding,
        "_run_gate",
        lambda gate: gate != failing_gate,
    )

    assert verify_epic20_catalog_onboarding.main([]) == 1
