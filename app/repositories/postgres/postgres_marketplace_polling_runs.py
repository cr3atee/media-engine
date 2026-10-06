from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.models.marketplace_polling_run_record import MarketplacePollingRunRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.marketplace_polling_runs import (
    MAX_POLLING_RUN_HISTORY,
    MarketplacePollingRunRepository,
)


class PostgresMarketplacePollingRunRepository(MarketplacePollingRunRepository):
    """PostgreSQL repository for immutable marketplace polling history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, run: MarketplacePollingRun) -> MarketplacePollingRun:
        """Persist an immutable run or replay the identical value."""
        existing = await self._session.get(MarketplacePollingRunRecord, run.id)
        if existing is not None:
            stored = _to_domain(existing)
            if stored != run:
                raise RepositoryIdentityConflictError(
                    f"Marketplace polling run ID already exists: {run.id}."
                )
            return stored
        self._session.add(_to_record(run))
        await self._session.flush()
        return run

    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        *,
        limit: int,
    ) -> Sequence[MarketplacePollingRun]:
        """Return newest tenant-scoped runs with deterministic tie-breaking."""
        if not 1 <= limit <= MAX_POLLING_RUN_HISTORY:
            raise ValueError(
                f"Polling run limit must be between 1 and {MAX_POLLING_RUN_HISTORY}."
            )
        result = await self._session.execute(
            select(MarketplacePollingRunRecord)
            .where(
                MarketplacePollingRunRecord.tenant_id == tenant_id,
                MarketplacePollingRunRecord.integration_id == integration_id,
            )
            .order_by(
                MarketplacePollingRunRecord.finished_at.desc(),
                MarketplacePollingRunRecord.id.desc(),
            )
            .limit(limit)
        )
        return tuple(_to_domain(record) for record in result.scalars())


def _to_record(run: MarketplacePollingRun) -> MarketplacePollingRunRecord:
    return MarketplacePollingRunRecord(
        id=run.id,
        tenant_id=run.tenant_id,
        integration_id=run.integration_id,
        marketplace=run.marketplace,
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        offers_received=run.offers_received,
        offers_persisted=run.offers_persisted,
        snapshots_created=run.snapshots_created,
        snapshots_persisted=run.snapshots_persisted,
        price_changes_detected=run.price_changes_detected,
        events_created=run.events_created,
        processing_error_count=run.processing_error_count,
        skipped_reason=run.skipped_reason,
        error_code=run.error_code,
        error_summary=run.error_summary,
    )


def _to_domain(record: MarketplacePollingRunRecord) -> MarketplacePollingRun:
    return MarketplacePollingRun(
        id=record.id,
        tenant_id=record.tenant_id,
        integration_id=record.integration_id,
        marketplace=record.marketplace,
        status=MarketplacePollingRunStatus(record.status),
        started_at=record.started_at,
        finished_at=record.finished_at,
        offers_received=record.offers_received,
        offers_persisted=record.offers_persisted,
        snapshots_created=record.snapshots_created,
        snapshots_persisted=record.snapshots_persisted,
        price_changes_detected=record.price_changes_detected,
        events_created=record.events_created,
        processing_error_count=record.processing_error_count,
        skipped_reason=record.skipped_reason,
        error_code=record.error_code,
        error_summary=record.error_summary,
    )
