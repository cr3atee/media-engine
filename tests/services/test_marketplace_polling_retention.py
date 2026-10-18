from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.repositories.marketplace_polling_runs import (
    MarketplacePollingRunPruneRequest,
    MarketplacePollingRunRepository,
)
from app.repositories.memory import MemoryMarketplacePollingRunRepository
from app.repositories.provider import create_memory_provider
from app.services.marketplace_polling_retention import (
    MarketplacePollingRetentionPolicy,
    MarketplacePollingRetentionService,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("54000000-0000-4000-8000-000000000001")
OTHER_TENANT_ID = UUID("54000000-0000-4000-8000-000000000002")
FIRST_INTEGRATION_ID = UUID("54000000-0000-4000-8000-000000000011")
SECOND_INTEGRATION_ID = UUID("54000000-0000-4000-8000-000000000012")
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_retention_policy_and_request_reject_unsafe_bounds() -> None:
    with pytest.raises(ValueError, match="period must be positive"):
        MarketplacePollingRetentionPolicy(retain_for=timedelta(0))
    with pytest.raises(ValueError, match="keep at least one"):
        MarketplacePollingRetentionPolicy(
            retain_for=timedelta(days=30),
            keep_latest_per_integration=0,
        )
    with pytest.raises(ValueError, match="between 1 and 1000"):
        MarketplacePollingRunPruneRequest(
            tenant_id=TENANT_ID,
            cutoff=NOW,
            keep_latest_per_integration=1,
            limit=1_001,
        )


def test_memory_pruning_is_bounded_deterministic_and_tenant_scoped() -> None:
    repository = MemoryMarketplacePollingRunRepository()
    tenant_runs = _tenant_runs()
    foreign = _run(
        number=9,
        tenant_id=OTHER_TENANT_ID,
        integration_id=FIRST_INTEGRATION_ID,
        days_ago=200,
    )
    run_async(_save_all(repository, (*tenant_runs, foreign)))
    request = MarketplacePollingRunPruneRequest(
        tenant_id=TENANT_ID,
        cutoff=NOW - timedelta(days=30),
        keep_latest_per_integration=2,
        limit=3,
    )

    first_deleted = tuple(run_async(repository.prune_by_tenant(request)))
    second_deleted = tuple(run_async(repository.prune_by_tenant(request)))

    assert first_deleted == (tenant_runs[4].id, tenant_runs[0].id, tenant_runs[1].id)
    assert second_deleted == (tenant_runs[5].id,)
    assert tuple(run_async(repository.prune_by_tenant(request))) == ()
    assert tuple(
        run_async(
            repository.list_by_integration(
                TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == (tenant_runs[3], tenant_runs[2])
    assert tuple(
        run_async(
            repository.list_by_integration(
                TENANT_ID,
                SECOND_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == (tenant_runs[7], tenant_runs[6])
    assert tuple(
        run_async(
            repository.list_by_integration(
                OTHER_TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == (foreign,)


def test_pruning_uses_a_strict_cutoff() -> None:
    repository = MemoryMarketplacePollingRunRepository()
    old = _run(number=10, integration_id=FIRST_INTEGRATION_ID, days_ago=31)
    at_cutoff = _run(number=11, integration_id=FIRST_INTEGRATION_ID, days_ago=30)
    newest = _run(number=12, integration_id=FIRST_INTEGRATION_ID, days_ago=1)
    run_async(_save_all(repository, (old, at_cutoff, newest)))

    deleted = run_async(
        repository.prune_by_tenant(
            MarketplacePollingRunPruneRequest(
                tenant_id=TENANT_ID,
                cutoff=NOW - timedelta(days=30),
                keep_latest_per_integration=1,
                limit=10,
            )
        )
    )

    assert tuple(deleted) == (old.id,)
    assert tuple(
        run_async(
            repository.list_by_integration(
                TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == (newest, at_cutoff)


def test_retention_service_commits_one_explicit_batch() -> None:
    provider = create_memory_provider()
    scope_factory = create_memory_repository_scope(provider)
    runs = tuple(
        _run(
            number=number,
            integration_id=FIRST_INTEGRATION_ID,
            days_ago=100 - number,
        )
        for number in range(1, 4)
    )
    run_async(_save_all(provider.marketplace_polling_runs, runs))
    service = MarketplacePollingRetentionService(
        repository_scope_factory=scope_factory,
        policy=MarketplacePollingRetentionPolicy(
            retain_for=timedelta(days=30),
            keep_latest_per_integration=1,
            batch_size=1,
        ),
    )

    result = run_async(service.prune(TENANT_ID, now=NOW))

    assert result.cutoff == NOW - timedelta(days=30)
    assert result.deleted_run_ids == (runs[0].id,)
    assert result.deleted_count == 1
    assert result.batch_limit_reached is True
    assert tuple(
        run_async(
            provider.marketplace_polling_runs.list_by_integration(
                TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == (runs[2], runs[1])


def test_memory_repository_scope_rolls_back_pruning() -> None:
    provider = create_memory_provider()
    scope_factory = create_memory_repository_scope(provider)
    runs = tuple(
        _run(
            number=number,
            integration_id=FIRST_INTEGRATION_ID,
            days_ago=100 - number,
        )
        for number in range(1, 4)
    )
    run_async(_save_all(provider.marketplace_polling_runs, runs))

    async def prune_then_fail() -> None:
        with pytest.raises(RuntimeError, match="controlled rollback"):
            async with scope_factory() as repositories:
                await repositories.marketplace_polling_runs.prune_by_tenant(
                    MarketplacePollingRunPruneRequest(
                        tenant_id=TENANT_ID,
                        cutoff=NOW - timedelta(days=30),
                        keep_latest_per_integration=1,
                        limit=10,
                    )
                )
                raise RuntimeError("controlled rollback")

    run_async(prune_then_fail())

    assert tuple(
        run_async(
            provider.marketplace_polling_runs.list_by_integration(
                TENANT_ID,
                FIRST_INTEGRATION_ID,
                limit=100,
            )
        )
    ) == tuple(reversed(runs))


async def _save_all(
    repository: MarketplacePollingRunRepository,
    runs: Sequence[MarketplacePollingRun],
) -> None:
    for run in runs:
        await repository.save(run)


def _tenant_runs() -> tuple[MarketplacePollingRun, ...]:
    return (
        _run(number=1, integration_id=FIRST_INTEGRATION_ID, days_ago=100),
        _run(number=2, integration_id=FIRST_INTEGRATION_ID, days_ago=80),
        _run(number=3, integration_id=FIRST_INTEGRATION_ID, days_ago=20),
        _run(number=4, integration_id=FIRST_INTEGRATION_ID, days_ago=1),
        _run(number=5, integration_id=SECOND_INTEGRATION_ID, days_ago=120),
        _run(number=6, integration_id=SECOND_INTEGRATION_ID, days_ago=70),
        _run(number=7, integration_id=SECOND_INTEGRATION_ID, days_ago=15),
        _run(number=8, integration_id=SECOND_INTEGRATION_ID, days_ago=2),
    )


def _run(
    *,
    number: int,
    integration_id: UUID,
    days_ago: int,
    tenant_id: UUID = TENANT_ID,
) -> MarketplacePollingRun:
    finished_at = NOW - timedelta(days=days_ago)
    return MarketplacePollingRun(
        id=UUID(int=54_000 + number),
        tenant_id=tenant_id,
        integration_id=integration_id,
        marketplace="ggsel",
        status=MarketplacePollingRunStatus.SUCCEEDED,
        started_at=finished_at - timedelta(seconds=2),
        finished_at=finished_at,
        offers_received=10,
        offers_persisted=10,
    )
