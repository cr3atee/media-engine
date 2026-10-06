from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.models.marketplace_integration_record import MarketplaceIntegrationRecord
from app.models.marketplace_polling_run_record import MarketplacePollingRunRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memory import MemoryMarketplacePollingRunRepository

TENANT_ID = UUID("25000000-0000-4000-8000-000000000001")
OTHER_TENANT_ID = UUID("25000000-0000-4000-8000-000000000002")
INTEGRATION_ID = UUID("26000000-0000-4000-8000-000000000001")
STARTED_AT = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async repository methods without a pytest plugin."""
    return asyncio.run(awaitable)


def make_run(
    *,
    number: int,
    tenant_id: UUID = TENANT_ID,
    status: MarketplacePollingRunStatus = MarketplacePollingRunStatus.SUCCEEDED,
) -> MarketplacePollingRun:
    """Create deterministic polling history test data."""
    started_at = STARTED_AT + timedelta(minutes=number)
    return MarketplacePollingRun(
        id=UUID(int=26_000 + number),
        tenant_id=tenant_id,
        integration_id=INTEGRATION_ID,
        marketplace=" GGSEL ",
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=2),
        offers_received=10 if status is MarketplacePollingRunStatus.SUCCEEDED else None,
        offers_persisted=10
        if status is MarketplacePollingRunStatus.SUCCEEDED
        else None,
        skipped_reason="missing_source_url"
        if status is MarketplacePollingRunStatus.SKIPPED
        else None,
        error_code="TimeoutError"
        if status is MarketplacePollingRunStatus.FAILED
        else None,
        error_summary="Marketplace polling failed."
        if status is MarketplacePollingRunStatus.FAILED
        else None,
    )


def test_polling_run_normalizes_and_validates_safe_outcome() -> None:
    run = make_run(number=1)

    assert run.marketplace == "ggsel"
    assert run.duration == timedelta(seconds=2)

    with pytest.raises(ValueError, match="safe error metadata"):
        MarketplacePollingRun(
            id=UUID(int=1),
            tenant_id=TENANT_ID,
            integration_id=INTEGRATION_ID,
            marketplace="ggsel",
            status=MarketplacePollingRunStatus.FAILED,
            started_at=STARTED_AT,
            finished_at=STARTED_AT,
        )


def test_memory_polling_repository_is_tenant_scoped_and_newest_first() -> None:
    repository = MemoryMarketplacePollingRunRepository()
    first = make_run(number=1)
    second = make_run(number=2, status=MarketplacePollingRunStatus.FAILED)
    foreign = make_run(number=3, tenant_id=OTHER_TENANT_ID)

    run_async(repository.save(first))
    run_async(repository.save(second))
    run_async(repository.save(foreign))

    assert tuple(
        run_async(
            repository.list_by_integration(
                TENANT_ID,
                INTEGRATION_ID,
                limit=1,
            )
        )
    ) == (second,)
    assert (
        tuple(
            run_async(
                repository.list_by_integration(
                    UUID(int=999),
                    INTEGRATION_ID,
                    limit=10,
                )
            )
        )
        == ()
    )
    with pytest.raises(ValueError, match="between 1 and 100"):
        run_async(
            repository.list_by_integration(
                TENANT_ID,
                INTEGRATION_ID,
                limit=101,
            )
        )


def test_memory_polling_repository_rejects_identity_redefinition() -> None:
    repository = MemoryMarketplacePollingRunRepository()
    run = make_run(number=1)
    conflicting = replace(run, marketplace="playerok")

    run_async(repository.save(run))
    with pytest.raises(RepositoryIdentityConflictError):
        run_async(repository.save(conflicting))


def test_polling_models_define_tenant_integrity_constraints() -> None:
    integration_table = cast(Table, MarketplaceIntegrationRecord.__table__)
    run_table = cast(Table, MarketplacePollingRunRecord.__table__)

    integration_uniques = {
        constraint.name
        for constraint in integration_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    run_foreign_keys = {
        constraint.name
        for constraint in run_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    run_checks = {
        constraint.name
        for constraint in run_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "uq_marketplace_integrations_tenant_id" in integration_uniques
    assert "fk_marketplace_polling_runs_integration" in run_foreign_keys
    assert "ck_marketplace_polling_runs_outcome" in run_checks
