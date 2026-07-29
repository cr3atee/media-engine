from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.metadata import get_metadata
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    SnapshotIdentity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
)
from app.models.generated_content_record import GeneratedContentRecord
from app.models.market_event_record import MarketEventRecord
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.models.publication_record import PublicationRecord
from app.repositories import MarketEventRepository, RepositoryIdentityConflictError
from app.repositories.postgres import (
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
)
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_event,
    run_async,
    uuid_for,
)
from tests.repositories.contracts.persistent import MarketEventRepositoryContract

DATABASE_URL = os.getenv("EPIC13_DATABASE_URL")
_ISOLATED_DATABASE = DATABASE_URL is not None and (
    make_url(DATABASE_URL).database or ""
).startswith("epic13_")
_SKIP_REASON = (
    "EPIC13_DATABASE_URL must target an isolated epic13_* PostgreSQL database"
)
_ENGINE: AsyncEngine | None = (
    create_async_engine(DATABASE_URL)
    if DATABASE_URL is not None and _ISOLATED_DATABASE
    else None
)
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = (
    async_sessionmaker(_ENGINE, expire_on_commit=False) if _ENGINE is not None else None
)

pytestmark = pytest.mark.skipif(not _ISOLATED_DATABASE, reason=_SKIP_REASON)


class TestPostgresMarketEventRepository(MarketEventRepositoryContract):
    """Run the shared market-event contract against PostgreSQL."""

    _session: AsyncSession

    def setup_method(self) -> None:
        """Create clean tables and one caller-owned session per test."""
        run_async(_reset_database())
        self._session = _session_factory()()

    def teardown_method(self) -> None:
        """Rollback and close the caller-owned contract session."""
        run_async(self._session.rollback())
        run_async(self._session.close())

    def make_repository(self) -> PostgresMarketEventRepository:
        return PostgresMarketEventRepository(
            self._session,
            claim_token_factory=SequentialUuidFactory(70_000),
        )

    def prepare_event(
        self,
        repository: MarketEventRepository,
        event: PriceDropMarketEvent,
    ) -> None:
        """Persist exact source snapshots in the repository transaction."""
        del repository
        snapshot_repository = PostgresPriceHistoryRepository(self._session)
        run_async(snapshot_repository.add(_to_snapshot(event.previous_snapshot)))
        run_async(snapshot_repository.add(_to_snapshot(event.current_snapshot)))


def test_concurrent_compatible_creation_produces_one_logical_row() -> None:
    run_async(_reset_database())
    event = make_event()
    duplicate = replace(
        event,
        id=uuid_for(9_001),
        created_at=event.created_at + timedelta(minutes=1),
    )
    run_async(_seed_snapshots(event))

    async def create(candidate: PriceDropMarketEvent) -> IdempotentCreateStatus:
        async with _session_factory()() as session, session.begin():
            result = await PostgresMarketEventRepository(session).add_idempotently(
                MarketEventCandidate(event=candidate),
            )
            return result.status

    async def create_both() -> tuple[
        IdempotentCreateStatus,
        IdempotentCreateStatus,
    ]:
        first, second = await asyncio.gather(create(event), create(duplicate))
        return first, second

    statuses = run_async(create_both())

    assert sorted(statuses) == sorted(
        (IdempotentCreateStatus.CREATED, IdempotentCreateStatus.EXISTING),
    )
    assert run_async(_event_count()) == 1


def test_conflicting_creation_keeps_original_row_unchanged() -> None:
    run_async(_reset_database())
    event = make_event()
    conflicting = replace(
        event,
        id=uuid_for(9_002),
        payload=replace(event.payload, title="Conflicting title"),
    )
    run_async(_seed_snapshots(event))
    run_async(_create_committed(event))

    async def create_conflict() -> None:
        async with _session_factory()() as session, session.begin():
            repository = PostgresMarketEventRepository(session)
            await repository.add_idempotently(
                MarketEventCandidate(event=conflicting),
            )

    with pytest.raises(RepositoryIdentityConflictError):
        run_async(create_conflict())

    stored = run_async(_load_event(event.id))
    assert stored == event
    assert run_async(_event_count()) == 1


def test_skip_locked_claimers_receive_different_events() -> None:
    run_async(_reset_database())
    events = (make_event(number=1), make_event(number=2))
    for event in events:
        run_async(_seed_snapshots(event))
        run_async(_create_committed(event))

    async def claim_two_sessions() -> tuple[UUID, UUID]:
        factory = _session_factory()
        async with factory() as first_session, factory() as second_session:
            async with first_session.begin():
                first = await PostgresMarketEventRepository(
                    first_session,
                    claim_token_factory=SequentialUuidFactory(71_000),
                ).claim_pending(
                    NOW + timedelta(minutes=10),
                    "worker-one",
                    NOW + timedelta(minutes=11),
                    1,
                )
                async with second_session.begin():
                    second = await PostgresMarketEventRepository(
                        second_session,
                        claim_token_factory=SequentialUuidFactory(72_000),
                    ).claim_pending(
                        NOW + timedelta(minutes=10),
                        "worker-two",
                        NOW + timedelta(minutes=11),
                        1,
                    )
                return first[0].event.id, second[0].event.id

    claimed_ids = run_async(claim_two_sessions())

    assert len(set(claimed_ids)) == 2


def test_skip_locked_one_event_contention_has_one_winner() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_snapshots(event))
    run_async(_create_committed(event))

    async def contend() -> tuple[int, int]:
        factory = _session_factory()
        async with factory() as first_session, factory() as second_session:
            async with first_session.begin():
                first = await PostgresMarketEventRepository(
                    first_session,
                ).claim_pending(
                    NOW + timedelta(minutes=10),
                    "worker-one",
                    NOW + timedelta(minutes=11),
                    1,
                )
                async with second_session.begin():
                    second = await PostgresMarketEventRepository(
                        second_session,
                    ).claim_pending(
                        NOW + timedelta(minutes=10),
                        "worker-two",
                        NOW + timedelta(minutes=11),
                        1,
                    )
                return len(first), len(second)

    assert run_async(contend()) == (1, 0)


def test_expired_lease_requires_explicit_recovery_before_retry() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_snapshots(event))
    run_async(_create_committed(event))
    claimed_at = NOW + timedelta(minutes=10)
    lease_until = claimed_at + timedelta(minutes=1)

    async def claim(
        now: datetime,
        worker_id: str,
        lease: datetime,
        token: int,
    ) -> tuple[UUID, int]:
        async with _session_factory()() as session, session.begin():
            claimed = await PostgresMarketEventRepository(
                session,
                claim_token_factory=SequentialUuidFactory(token),
            ).claim_pending(now, worker_id, lease, 1)
            return claimed[0].claim.token, claimed[0].event.version

    first_token, first_version = run_async(
        claim(claimed_at, "worker-one", lease_until, 73_000),
    )

    async def recover() -> None:
        async with _session_factory()() as session, session.begin():
            repository = PostgresMarketEventRepository(session)
            expired = await repository.list_expired_scoring_claims(lease_until, 1)
            assert expired[0].claim.token == first_token
            result = await repository.mark_scoring_failed(
                event.id,
                expired[0].claim.token,
                expired[0].event.version,
                ProcessingError(code="lease_expired", summary="Lease expired"),
                lease_until,
                lease_until,
            )
            assert result.applied

    run_async(recover())
    second_token, second_version = run_async(
        claim(
            lease_until,
            "worker-two",
            lease_until + timedelta(minutes=1),
            74_000,
        ),
    )

    assert second_token != first_token
    assert first_version == 2
    assert second_version == 4


def test_stale_optimistic_version_is_explicit() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_snapshots(event))
    run_async(_create_committed(event))

    async def exercise() -> StateTransitionOutcome:
        async with _session_factory()() as session, session.begin():
            repository = PostgresMarketEventRepository(session)
            claimed = (
                await repository.claim_pending(
                    NOW + timedelta(minutes=10),
                    "worker",
                    NOW + timedelta(minutes=11),
                    1,
                )
            )[0]
            result = await repository.mark_scored(
                event.id,
                claimed.claim.token,
                1,
                90,
                NOW + timedelta(minutes=10, seconds=30),
            )
            return result.outcome

    assert run_async(exercise()) is StateTransitionOutcome.VERSION_CONFLICT


def test_outer_transaction_rolls_back_insert_and_claim() -> None:
    run_async(_reset_database())
    event = make_event()
    run_async(_seed_snapshots(event))

    async def rollback_insert() -> None:
        try:
            async with _session_factory()() as session, session.begin():
                await PostgresMarketEventRepository(session).add_idempotently(
                    MarketEventCandidate(event=event),
                )
                raise RuntimeError("rollback insert")
        except RuntimeError:
            pass

    run_async(rollback_insert())
    assert run_async(_event_count()) == 0
    run_async(_create_committed(event))

    async def rollback_claim() -> None:
        try:
            async with _session_factory()() as session, session.begin():
                await PostgresMarketEventRepository(session).claim_pending(
                    NOW + timedelta(minutes=10),
                    "worker",
                    NOW + timedelta(minutes=11),
                    1,
                )
                raise RuntimeError("rollback claim")
        except RuntimeError:
            pass

    run_async(rollback_claim())
    stored = run_async(_load_event(event.id))
    assert stored is not None
    assert stored.version == 1
    assert stored.claim is None


def test_decimal_and_utc_values_round_trip_exactly() -> None:
    run_async(_reset_database())
    event = make_event()
    precise = replace(
        event,
        payload=replace(event.payload, percentage=Decimal("20.123456")),
    )
    run_async(_seed_snapshots(precise))
    run_async(_create_committed(precise))

    stored = run_async(_load_event(precise.id))

    assert stored is not None
    assert stored.payload.old_price == Decimal("1000.00")
    assert stored.payload.new_price == Decimal("800.00")
    assert stored.payload.absolute_difference == Decimal("200.00")
    assert stored.payload.percentage == Decimal("20.123456")
    assert stored.occurred_at == precise.occurred_at
    assert stored.occurred_at.tzinfo is not None


async def _reset_database() -> None:
    engine = _engine()
    async with engine.begin() as connection:
        await connection.run_sync(get_metadata().create_all)
        await connection.execute(delete(PublicationRecord))
        await connection.execute(delete(GeneratedContentRecord))
        await connection.execute(delete(MarketEventRecord))
        await connection.execute(delete(PriceSnapshotRecord))


async def _seed_snapshots(event: PriceDropMarketEvent) -> None:
    async with _session_factory()() as session, session.begin():
        repository = PostgresPriceHistoryRepository(session)
        await repository.add(_to_snapshot(event.previous_snapshot))
        await repository.add(_to_snapshot(event.current_snapshot))


async def _create_committed(event: PriceDropMarketEvent) -> None:
    async with _session_factory()() as session, session.begin():
        await PostgresMarketEventRepository(session).add_idempotently(
            MarketEventCandidate(event=event),
        )


async def _load_event(event_id: UUID) -> PriceDropMarketEvent | None:
    async with _session_factory()() as session:
        return await PostgresMarketEventRepository(session).get_by_id(event_id)


async def _event_count() -> int:
    async with _session_factory()() as session:
        result = await session.execute(
            select(func.count()).select_from(MarketEventRecord),
        )
        return int(result.scalar_one())


def _to_snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


def _engine() -> AsyncEngine:
    if _ENGINE is None:
        raise RuntimeError(_SKIP_REASON)
    return _ENGINE


def _session_factory() -> async_sessionmaker[AsyncSession]:
    if _SESSION_FACTORY is None:
        raise RuntimeError(_SKIP_REASON)
    return _SESSION_FACTORY


def teardown_module() -> None:
    """Dispose the optional live test engine after the module completes."""
    if _ENGINE is not None:
        run_async(_ENGINE.dispose())
