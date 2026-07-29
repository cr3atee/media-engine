from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

from app.domain.price_snapshot import PriceSnapshot
from app.models.offer import Offer
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.parsers.models import ParsedOffer
from app.repositories.postgres import (
    PostgresOfferRepository,
    PostgresPriceHistoryRepository,
)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async repository calls without an external pytest plugin."""
    return asyncio.run(awaitable)


class RecordingSession:
    """Capture SQL statements without opening a database connection."""

    def __init__(self, scalar: int | None = 1) -> None:
        self.statements: list[ClauseElement] = []
        self._scalar = scalar

    async def execute(self, statement: ClauseElement) -> RecordingResult:
        """Record one executable SQL statement."""
        self.statements.append(statement)
        return RecordingResult(self._scalar)


class RecordingResult:
    """Minimal scalar result returned by the recording session."""

    def __init__(self, scalar: int | None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> int | None:
        """Return the configured insert identifier or no row."""
        return self._scalar


def compile_postgres(statement: ClauseElement) -> str:
    """Compile a statement with the PostgreSQL dialect for assertions."""
    dialect_factory = cast(Callable[[], Dialect], PGDialect)
    compiled = statement.compile(dialect=dialect_factory())
    return " ".join(str(compiled).split())


def make_offer(*, external_id: str | None = "offer-1") -> ParsedOffer:
    """Create a parsed offer for PostgreSQL statement tests."""
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft Premium",
        url="https://ggsel.net/item/offer-1",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
    )


def test_offer_metadata_defines_identity_and_canonical_integrity() -> None:
    table = cast(Table, Offer.__table__)
    indexes = {str(index.name): index for index in table.indexes}
    identity = indexes["uq_offers_marketplace_external_id_not_null"]
    canonical = indexes["ix_offers_canonical_product_id"]

    assert identity.unique is True
    assert tuple(column.name for column in identity.columns) == (
        "marketplace",
        "external_id",
    )
    assert identity.dialect_options["postgresql"]["where"] is not None
    assert tuple(column.name for column in canonical.columns) == (
        "canonical_product_id",
    )

    foreign_key = next(iter(Offer.__table__.c.canonical_product_id.foreign_keys))
    assert foreign_key.name == "fk_offers_canonical_product_id_canonical_products"
    assert foreign_key.target_fullname == "canonical_products.id"
    assert foreign_key.ondelete == "SET NULL"


def test_snapshot_metadata_defines_exact_identity_and_history_index() -> None:
    table = cast(Table, PriceSnapshotRecord.__table__)
    exact_identity = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_price_snapshots_exact_identity"
    )
    assert isinstance(exact_identity, UniqueConstraint)
    assert tuple(column.name for column in exact_identity.columns) == (
        "marketplace",
        "external_id",
        "collected_at",
        "price",
        "currency",
    )

    indexes = {str(index.name): index for index in table.indexes}
    history = indexes["ix_price_snapshots_history_order"]
    assert tuple(column.name for column in history.columns) == (
        "marketplace",
        "external_id",
        "collected_at",
        "id",
    )


def test_offer_save_compiles_partial_identity_upsert() -> None:
    session = RecordingSession()
    repository = PostgresOfferRepository(cast(AsyncSession, session))

    run_async(repository.save(make_offer()))

    sql = compile_postgres(session.statements[0])
    assert "ON CONFLICT (marketplace, external_id)" in sql
    assert "WHERE external_id IS NOT NULL" in sql
    assert "DO UPDATE SET" in sql
    assert "title = coalesce(excluded.title, offers.title)" in sql
    assert "price = coalesce(excluded.price, offers.price)" in sql
    assert "canonical_product_id = coalesce(" in sql


def test_offer_without_external_id_compiles_append_only_insert() -> None:
    session = RecordingSession()
    repository = PostgresOfferRepository(cast(AsyncSession, session))

    run_async(repository.save(make_offer(external_id=None)))

    assert "ON CONFLICT" not in compile_postgres(session.statements[0])


def test_snapshot_add_compiles_exact_conflict_suppression() -> None:
    session = RecordingSession()
    repository = PostgresPriceHistoryRepository(cast(AsyncSession, session))
    snapshot = PriceSnapshot(
        marketplace="ggsel",
        external_id="offer-1",
        price=Decimal("790.00"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )

    inserted = run_async(repository.add(snapshot))

    sql = compile_postgres(session.statements[0])
    assert inserted is True
    assert "ON CONFLICT ON CONSTRAINT uq_price_snapshots_exact_identity" in sql
    assert "DO NOTHING" in sql


def test_snapshot_add_reports_suppressed_conflict() -> None:
    session = RecordingSession(scalar=None)
    repository = PostgresPriceHistoryRepository(cast(AsyncSession, session))
    snapshot = PriceSnapshot(
        marketplace="ggsel",
        external_id="offer-1",
        price=Decimal("790.00"),
        currency="RUB",
        collected_at=datetime.now(UTC),
    )

    assert run_async(repository.add(snapshot)) is False
