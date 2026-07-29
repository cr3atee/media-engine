# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    create_price_drop_market_event,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import IdempotentCreateStatus, ProcessingError
from app.models.market_event_record import MarketEventRecord
from app.repositories.postgres import (
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
)

DATABASE_URL_ENV = "EPIC13_DATABASE_URL"
EXPECTED_REVISION = "0007_create_market_events"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class VerificationError(RuntimeError):
    """Raised when a live EPIC 13 verification assertion fails."""


class Verification:
    """Print and count focused live PostgreSQL checks."""

    def __init__(self) -> None:
        self.passed = 0

    def check(self, label: str, condition: bool) -> None:
        """Record one passing condition or stop the verification."""
        if not condition:
            raise VerificationError(label)
        self.passed += 1
        print(f"PASS: {label}")


class SequentialTokenFactory:
    """Issue deterministic UUID claim tokens for live verification."""

    def __init__(self, start: int) -> None:
        self._next = start

    def __call__(self) -> UUID:
        token = UUID(int=self._next)
        self._next += 1
        return token


def make_event(number: int = 1) -> PriceDropMarketEvent:
    """Build one deterministic persistent price-drop event."""
    occurred_at = NOW + timedelta(minutes=number)
    previous = SnapshotIdentity(
        marketplace="ggsel",
        external_id=f"verify-offer-{number}",
        collected_at=occurred_at - timedelta(minutes=1),
        price=Decimal("1000.00"),
        currency="RUB",
    )
    current = SnapshotIdentity(
        marketplace="ggsel",
        external_id=f"verify-offer-{number}",
        collected_at=occurred_at,
        price=Decimal("800.00"),
        currency="RUB",
    )
    return create_price_drop_market_event(
        payload=PriceDropPayload(
            title="Minecraft Premium",
            url=f"https://example.com/offers/{number}",
            old_price=previous.price,
            new_price=current.price,
            currency="RUB",
            absolute_difference=Decimal("200.00"),
            percentage=Decimal("20.000000"),
            previous_snapshot=previous,
            current_snapshot=current,
        ),
        detected_at=occurred_at + timedelta(seconds=1),
        event_id=UUID(int=100 + number),
        created_at=occurred_at + timedelta(seconds=2),
    )


async def reset_database(engine: AsyncEngine) -> None:
    """Clear only event verification data in the isolated database."""
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE market_events, price_snapshots RESTART IDENTITY")
        )


async def seed_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    event: PriceDropMarketEvent,
) -> None:
    """Persist both exact source snapshots before event creation."""
    async with session_factory() as session, session.begin():
        repository = PostgresPriceHistoryRepository(session)
        await repository.add(to_snapshot(event.previous_snapshot))
        await repository.add(to_snapshot(event.current_snapshot))


def to_snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    """Convert a persistence-neutral snapshot identity to a snapshot."""
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


async def event_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Count durable market-event rows."""
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(MarketEventRecord)
        )
        return int(result.scalar_one())


async def verify_schema(
    verification: Verification,
    engine: AsyncEngine,
) -> None:
    """Verify the migrated table, revision, constraints, and indexes."""
    async with engine.connect() as connection:
        database = (
            await connection.execute(text("SELECT current_database()"))
        ).scalar_one()
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one()
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'market_events'::regclass"
                    )
                )
            ).scalars()
        )
        indexes = set(
            (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'market_events'"
                    )
                )
            ).scalars()
        )

    print(f"Database: {database}")
    print(f"Alembic revision: {revision}")
    verification.check("isolated database", str(database).startswith("epic13_"))
    verification.check("expected migration revision", revision == EXPECTED_REVISION)
    for constraint in (
        "pk_market_events",
        "uq_market_events_identity_key",
        "fk_market_events_previous_snapshot",
        "fk_market_events_current_snapshot",
        "ck_market_events_claim_state",
    ):
        verification.check(f"constraint {constraint}", constraint in constraints)
    for index in (
        "uq_market_events_snapshot_transition",
        "ix_market_events_scoring_claim",
        "ix_market_events_lease_expiry",
    ):
        verification.check(f"index {index}", index in indexes)


async def verify_creation(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify idempotency, concurrent creation, and transaction rollback."""
    await reset_database(engine)
    event = make_event()
    duplicate = replace(
        event,
        id=UUID(int=999),
        created_at=event.created_at + timedelta(minutes=1),
    )
    await seed_snapshots(session_factory, event)

    async def create(candidate: PriceDropMarketEvent) -> IdempotentCreateStatus:
        async with session_factory() as session, session.begin():
            result = await PostgresMarketEventRepository(session).add_idempotently(
                MarketEventCandidate(event=candidate)
            )
            return result.status

    first, second = await asyncio.gather(create(event), create(duplicate))
    verification.check(
        "concurrent idempotent creation",
        {first, second}
        == {IdempotentCreateStatus.CREATED, IdempotentCreateStatus.EXISTING},
    )
    verification.check("one logical event row", await event_count(session_factory) == 1)

    rollback_event = make_event(2)
    await seed_snapshots(session_factory, rollback_event)
    try:
        async with session_factory() as session, session.begin():
            await PostgresMarketEventRepository(session).add_idempotently(
                MarketEventCandidate(event=rollback_event)
            )
            raise RuntimeError("controlled rollback")
    except RuntimeError:
        pass
    verification.check(
        "outer transaction owns rollback",
        await event_count(session_factory) == 1,
    )


async def verify_claims(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify SKIP LOCKED exclusivity and expired-lease recovery."""
    await reset_database(engine)
    events = (make_event(1), make_event(2))
    for event in events:
        await seed_snapshots(session_factory, event)
        async with session_factory() as session, session.begin():
            await PostgresMarketEventRepository(session).add_idempotently(
                MarketEventCandidate(event=event)
            )

    claimed_at = NOW + timedelta(minutes=10)
    lease_until = claimed_at + timedelta(minutes=1)
    async with session_factory() as first_session, session_factory() as second_session:
        async with first_session.begin():
            first = await PostgresMarketEventRepository(
                first_session,
                claim_token_factory=SequentialTokenFactory(10_000),
            ).claim_pending(
                claimed_at,
                "worker-one",
                lease_until,
                1,
            )
            async with second_session.begin():
                second = await PostgresMarketEventRepository(
                    second_session,
                    claim_token_factory=SequentialTokenFactory(20_000),
                ).claim_pending(
                    claimed_at,
                    "worker-two",
                    lease_until,
                    1,
                )
        verification.check(
            "SKIP LOCKED gives workers different rows",
            len(first) == len(second) == 1 and first[0].event.id != second[0].event.id,
        )

    first_token = first[0].claim.token
    async with session_factory() as session, session.begin():
        repository = PostgresMarketEventRepository(session)
        expired = await repository.list_expired_scoring_claims(lease_until, 1)
        recovered = await repository.mark_scoring_failed(
            expired[0].event.id,
            expired[0].claim.token,
            expired[0].event.version,
            ProcessingError(code="lease_expired", summary="Lease expired"),
            lease_until,
            lease_until,
        )
    async with session_factory() as session, session.begin():
        reclaimed = await PostgresMarketEventRepository(
            session,
            claim_token_factory=SequentialTokenFactory(30_000),
        ).claim_pending(
            lease_until,
            "worker-three",
            lease_until + timedelta(minutes=1),
            1,
        )
    verification.check(
        "expired lease is explicitly recovered before retry",
        recovered.applied
        and len(reclaimed) == 1
        and reclaimed[0].claim.token != first_token,
    )


async def run_verification(database_url: str) -> None:
    """Run focused live EPIC 13 market-event verification."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_schema(verification, engine)
        await verify_creation(verification, engine, session_factory)
        await verify_claims(verification, engine, session_factory)
        await reset_database(engine)
        print(f"Checks passed: {verification.passed}")
        print("SUCCESS")
    finally:
        await engine.dispose()


def apply_migrations(database_url: str) -> None:
    """Apply project migrations to the isolated verification database."""
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def main() -> None:
    """Guard the database, migrate it, and run live verification."""
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(
            f"Set {DATABASE_URL_ENV} to an isolated PostgreSQL test database."
        )
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql" or not database_name.startswith(
        "epic13_"
    ):
        raise SystemExit(
            f"{DATABASE_URL_ENV} must target an isolated epic13_* PostgreSQL database."
        )
    apply_migrations(database_url)
    asyncio.run(run_verification(database_url))


if __name__ == "__main__":
    main()
