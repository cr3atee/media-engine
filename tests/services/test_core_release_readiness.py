from __future__ import annotations

import pytest

from scripts.verify_core_release_readiness import (
    OFFLINE_GATES,
    POSTGRES_GATES,
    validate_release_database_url,
)


def test_release_gate_reuses_offline_and_postgres_verifiers() -> None:
    assert tuple(gate.script for gate in OFFLINE_GATES) == (
        "scripts/verify_marketplace_payload_contracts.py",
        "scripts/verify_public_ui_readiness.py",
    )
    assert tuple(gate.script for gate in POSTGRES_GATES) == (
        "scripts/verify_epic19_public_ui_postgres.py",
        "scripts/verify_marketplace_polling_history_postgres.py",
    )


def test_release_gate_accepts_isolated_local_postgres() -> None:
    validate_release_database_url(
        "postgresql+asyncpg://user:secret@127.0.0.1:5432/epic19_history_release_verify"
    )


@pytest.mark.parametrize(
    "database_url",
    (
        "sqlite:///epic19_history_release_verify.db",
        "postgresql+asyncpg://user:secret@example.com/epic19_history_release_verify",
        "postgresql+asyncpg://user:secret@127.0.0.1/mediaengine",
    ),
)
def test_release_gate_rejects_unsafe_database(database_url: str) -> None:
    with pytest.raises(RuntimeError):
        validate_release_database_url(database_url)


def test_release_gate_excludes_live_network_verifiers() -> None:
    scripts = tuple(gate.script for gate in OFFLINE_GATES + POSTGRES_GATES)

    assert all("live_marketplace" not in script for script in scripts)
    assert all("telegram" not in script for script in scripts)
