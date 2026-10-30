from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

from app.domain.price_snapshot import PriceSnapshot
from app.models.canonical_offer_decision_record import CanonicalOfferDecisionRecord
from app.models.canonical_product_record import CanonicalProductRecord
from app.models.offer import Offer
from app.models.offer_source_observation_record import OfferSourceObservationRecord
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferObservationContext
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

    def scalar_one(self) -> int:
        """Return the configured insert identifier."""
        assert self._scalar is not None
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
        source_category_id="section-1",
        source_category_name="Digital keys",
    )


def test_offer_metadata_defines_identity_and_canonical_integrity() -> None:
    table = cast(Table, Offer.__table__)
    indexes = {str(index.name): index for index in table.indexes}
    identity = indexes["uq_offers_marketplace_external_id_not_null"]
    canonical = indexes["ix_offers_canonical_product_id"]
    tenant_canonical = indexes["ix_offers_tenant_canonical_product"]
    source_category = indexes["ix_offers_tenant_marketplace_source_category"]

    assert identity.unique is True
    assert tuple(column.name for column in identity.columns) == (
        "tenant_id",
        "marketplace",
        "external_id",
    )
    assert identity.dialect_options["postgresql"]["where"] is not None
    assert tuple(column.name for column in canonical.columns) == (
        "canonical_product_id",
    )
    assert tuple(column.name for column in tenant_canonical.columns) == (
        "tenant_id",
        "canonical_product_id",
    )
    assert tenant_canonical.dialect_options["postgresql"]["where"] is not None
    assert tuple(column.name for column in source_category.columns) == (
        "tenant_id",
        "marketplace",
        "source_category_id",
    )
    assert source_category.dialect_options["postgresql"]["where"] is not None

    foreign_key = next(
        foreign_key
        for foreign_key in Offer.__table__.c.canonical_product_id.foreign_keys
        if foreign_key.name == "fk_offers_canonical_product_id_canonical_products"
    )
    assert foreign_key.name == "fk_offers_canonical_product_id_canonical_products"
    assert foreign_key.target_fullname == "canonical_products.id"
    assert foreign_key.ondelete == "SET NULL"
    tenant_canonical_fk = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "fk_offers_tenant_canonical_product"
    )
    assert isinstance(tenant_canonical_fk, ForeignKeyConstraint)
    assert tuple(column.name for column in tenant_canonical_fk.columns) == (
        "tenant_id",
        "canonical_product_id",
    )
    assert tuple(
        element.target_fullname for element in tenant_canonical_fk.elements
    ) == (
        "canonical_products.tenant_id",
        "canonical_products.id",
    )
    tenant_foreign_key = next(
        foreign_key
        for foreign_key in Offer.__table__.c.tenant_id.foreign_keys
        if foreign_key.name == "fk_offers_tenant_id_tenants"
    )
    assert tenant_foreign_key.name == "fk_offers_tenant_id_tenants"
    assert tenant_foreign_key.target_fullname == "tenants.id"

    product_table = cast(Table, CanonicalProductRecord.__table__)
    tenant_identity = next(
        constraint
        for constraint in product_table.constraints
        if constraint.name == "uq_canonical_products_tenant_id_id"
    )
    assert isinstance(tenant_identity, UniqueConstraint)
    assert tuple(column.name for column in tenant_identity.columns) == (
        "tenant_id",
        "id",
    )


def test_offer_observation_metadata_is_source_scoped_and_ordered() -> None:
    offer_table = cast(Table, Offer.__table__)
    offer_identity = next(
        constraint
        for constraint in offer_table.constraints
        if constraint.name == "uq_offers_tenant_id_id"
    )
    assert isinstance(offer_identity, UniqueConstraint)
    assert tuple(column.name for column in offer_identity.columns) == (
        "tenant_id",
        "id",
    )

    table = cast(Table, OfferSourceObservationRecord.__table__)
    assert tuple(column.name for column in table.primary_key.columns) == (
        "tenant_id",
        "integration_id",
        "offer_id",
    )
    foreign_keys = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert tuple(
        element.target_fullname
        for element in foreign_keys["fk_offer_source_observations_integration"].elements
    ) == (
        "marketplace_integrations.tenant_id",
        "marketplace_integrations.id",
    )
    assert tuple(
        element.target_fullname
        for element in foreign_keys["fk_offer_source_observations_offer"].elements
    ) == ("offers.tenant_id", "offers.id")
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_offer_source_observations_state",
        "ck_offer_source_observations_time_order",
    }
    indexes = {str(index.name): index for index in table.indexes}
    assert set(indexes) == {
        "ix_offer_source_observations_active_offer",
        "ix_offer_source_observations_integration_state",
    }
    assert (
        indexes["ix_offer_source_observations_active_offer"].dialect_options[
            "postgresql"
        ]["where"]
        is not None
    )


def test_snapshot_metadata_defines_exact_identity_and_history_index() -> None:
    table = cast(Table, PriceSnapshotRecord.__table__)
    exact_identity = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_price_snapshots_exact_identity"
    )
    assert isinstance(exact_identity, UniqueConstraint)
    assert tuple(column.name for column in exact_identity.columns) == (
        "tenant_id",
        "marketplace",
        "external_id",
        "collected_at",
        "price",
        "currency",
    )

    indexes = {str(index.name): index for index in table.indexes}
    history = indexes["ix_price_snapshots_history_order"]
    assert tuple(column.name for column in history.columns) == (
        "tenant_id",
        "marketplace",
        "external_id",
        "collected_at",
        "id",
    )


def test_canonical_offer_decision_metadata_is_tenant_scoped_and_immutable() -> None:
    table = cast(Table, CanonicalOfferDecisionRecord.__table__)
    unique_constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert tuple(
        column.name
        for column in unique_constraints[
            "uq_canonical_offer_decisions_idempotency"
        ].columns
    ) == ("tenant_id", "idempotency_key")
    assert tuple(
        column.name
        for column in unique_constraints["uq_canonical_offer_decisions_pair"].columns
    ) == (
        "tenant_id",
        "marketplace",
        "external_id",
        "canonical_product_id",
    )

    product_foreign_key = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "fk_canonical_offer_decisions_product"
    )
    assert isinstance(product_foreign_key, ForeignKeyConstraint)
    assert tuple(column.name for column in product_foreign_key.columns) == (
        "tenant_id",
        "canonical_product_id",
    )
    assert tuple(
        element.target_fullname for element in product_foreign_key.elements
    ) == (
        "canonical_products.tenant_id",
        "canonical_products.id",
    )
    assert product_foreign_key.ondelete == "RESTRICT"

    index = next(
        index
        for index in table.indexes
        if index.name == "ix_canonical_offer_decisions_offer_created"
    )
    assert tuple(column.name for column in tuple(index.columns)[:3]) == (
        "tenant_id",
        "marketplace",
        "external_id",
    )
    assert cast(DateTime, table.c.created_at.type).timezone is True


def test_active_postgres_timestamps_are_timezone_aware() -> None:
    offer_created_at = cast(DateTime, Offer.__table__.c.created_at.type)
    product_created_at = cast(
        DateTime,
        CanonicalProductRecord.__table__.c.created_at.type,
    )
    snapshot_collected_at = cast(
        DateTime,
        PriceSnapshotRecord.__table__.c.collected_at.type,
    )

    assert offer_created_at.timezone is True
    assert product_created_at.timezone is True
    assert snapshot_collected_at.timezone is True


def test_offer_save_compiles_partial_identity_upsert() -> None:
    session = RecordingSession()
    repository = PostgresOfferRepository(cast(AsyncSession, session))

    run_async(repository.save(make_offer()))

    sql = compile_postgres(session.statements[0])
    assert "ON CONFLICT (tenant_id, marketplace, external_id)" in sql
    assert "WHERE external_id IS NOT NULL" in sql
    assert "DO UPDATE SET" in sql
    assert "title = coalesce(excluded.title, offers.title)" in sql
    assert "price = coalesce(excluded.price, offers.price)" in sql
    assert "source_category_id = coalesce(" in sql
    assert "source_category_name = coalesce(" in sql
    assert "canonical_product_id = coalesce(" in sql


def test_offer_without_external_id_compiles_append_only_insert() -> None:
    session = RecordingSession()
    repository = PostgresOfferRepository(cast(AsyncSession, session))

    run_async(repository.save(make_offer(external_id=None)))

    assert "ON CONFLICT" not in compile_postgres(session.statements[0])


def test_observed_offer_compiles_offer_and_source_upserts() -> None:
    session = RecordingSession()
    repository = PostgresOfferRepository(cast(AsyncSession, session))
    context = OfferObservationContext(
        tenant_id=make_offer().tenant_id,
        integration_id=UUID("10000000-0000-4000-8000-000000000104"),
        marketplace="ggsel",
        observed_at=datetime(2026, 10, 27, 10, 0, tzinfo=UTC),
    )

    run_async(repository.save_observed(context, make_offer()))

    assert len(session.statements) == 2
    offer_sql = compile_postgres(session.statements[0])
    observation_sql = compile_postgres(session.statements[1])
    assert "RETURNING offers.id" in offer_sql
    assert "ON CONFLICT (tenant_id, integration_id, offer_id)" in observation_sql
    assert "greatest(" in observation_sql
    assert "least(" in observation_sql


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
