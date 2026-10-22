from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.services.repository_scope import create_memory_repository_scope
from scripts.run_catalog_review_postgres import (
    DATABASE_URL_ENV,
    TENANT_ID,
    _require_isolated_database,
    _safe_error_summary,
    _seed_database,
    parse_args,
)


def test_runner_defaults_to_captured_data_and_loopback_port() -> None:
    arguments = parse_args([])

    assert arguments.port == 8001
    assert arguments.check is False
    assert arguments.aligned_live_data is False


def test_runner_accepts_explicit_live_check() -> None:
    arguments = parse_args(["--aligned-live-data", "--check", "--port", "8101"])

    assert arguments.port == 8101
    assert arguments.check is True
    assert arguments.aligned_live_data is True


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_runner_accepts_only_isolated_loopback_postgres(host: str) -> None:
    url_host = f"[{host}]" if ":" in host else host
    _require_isolated_database(
        f"postgresql+asyncpg://user:password@{url_host}/epic23_catalog_review_test"
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///epic23_catalog_review_test.db",
        "postgresql+asyncpg://db.internal/epic23_catalog_review_test",
        "postgresql+asyncpg://localhost/mediaengine",
    ],
)
def test_runner_rejects_non_isolated_database(database_url: str) -> None:
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        _require_isolated_database(database_url)


def test_runner_redacts_database_and_review_credentials() -> None:
    database_url = (
        "postgresql+asyncpg://reviewer:database-secret@127.0.0.1:55433/"
        "epic23_catalog_review_test"
    )

    summary = _safe_error_summary(
        RuntimeError(f"failed {database_url} database-secret catalog review local"),
        database_url,
    )

    assert "database-secret" not in summary
    assert "catalog review local" not in summary
    assert "[REDACTED]" in summary


def test_runner_seed_is_idempotent_through_repository_scope() -> None:
    provider = create_memory_provider()
    repository_scope = create_memory_repository_scope(provider)
    offer = ParsedOffer(
        marketplace="ggsel",
        external_id="launch-offer",
        title="Minecraft Java & Bedrock",
        url="https://example.com/launch-offer",
        price=Decimal("790"),
        currency="RUB",
    )

    first = asyncio.run(
        _seed_database(repository_scope, (offer, offer), mode="test batch")
    )
    second = asyncio.run(_seed_database(repository_scope, (offer,), mode="test batch"))

    assert first.offer_count == 1
    assert second.offer_count == 1
    stored = asyncio.run(provider.offers.list_by_tenant(TENANT_ID))
    assert len(stored) == 1
    assert stored[0].external_id == "launch-offer"
