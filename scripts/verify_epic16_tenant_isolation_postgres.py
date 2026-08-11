"""Verify EPIC 16 tenant identity and isolation against PostgreSQL."""

# ruff: noqa: E402, I001
from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC16_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.analytics.price_change import PriceChangeDetector
from app.config.settings import settings
from app.domain.market_events import (
    MarketEventCandidate,
    MarketEventType,
    SnapshotIdentity,
    build_event_identity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.tenancy import (
    LEGACY_TENANT_ID,
    LEGACY_TENANT_SLUG,
    Membership,
    Tenant,
    TenantRole,
    User,
)
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_postgres_provider
from app.services.price_drop_market_event_builder import PriceDropMarketEventBuilder

DATABASE_URL_ENV = "EPIC16_DATABASE_URL"
TENANT_A_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B_ID = UUID("10000000-0000-4000-8000-000000000002")
USER_A_ID = UUID("20000000-0000-4000-8000-000000000001")
USER_B_ID = UUID("20000000-0000-4000-8000-000000000002")
MEMBERSHIP_A_ID = UUID("30000000-0000-4000-8000-000000000001")
MEMBERSHIP_B_ID = UUID("30000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


class Verification:
    """Collect and print named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run EPIC 16 tenant-isolation verification on an isolated database."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url, "0009_admin_actions")
    await _seed_legacy_rows(database_url)
    await asyncio.to_thread(_apply_migrations, database_url, "head")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await _verify_schema(connection, verifier)
            await _verify_legacy_backfill(connection, verifier)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                await _seed_two_tenants(session)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                await _verify_repository_isolation(session, verifier)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            await _verify_fresh_session_persistence(session, verifier)
    finally:
        await engine.dispose()

    print(
        f"EPIC 16 tenant isolation verification: {len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_schema(
    connection: AsyncConnection,
    verifier: Verification,
) -> None:
    tables = (
        "users",
        "tenants",
        "tenant_memberships",
        "offers",
        "price_snapshots",
        "market_events",
        "generated_contents",
        "publications",
        "admin_actions",
    )
    for table_name in tables:
        exists = await connection.scalar(
            text("SELECT to_regclass(:table_name) IS NOT NULL"),
            {"table_name": table_name},
        )
        verifier.check(f"{table_name} table exists", exists is True)

    constraints = {
        "uq_offers_marketplace_external_id_not_null",
        "uq_price_snapshots_exact_identity",
        "uq_market_events_identity_key",
        "uq_generated_contents_idempotency_key",
        "uq_publications_idempotency_key",
        "uq_admin_actions_idempotency_key",
        "uq_tenant_memberships_user_tenant",
    }
    rows = await connection.execute(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conname = ANY(:constraint_names)
            UNION
            SELECT indexname
            FROM pg_indexes
            WHERE indexname = ANY(:constraint_names)
            """,
        ),
        {"constraint_names": list(constraints)},
    )
    found = {row[0] for row in rows}
    verifier.check("tenant-aware constraints and indexes exist", constraints <= found)


async def _verify_legacy_backfill(
    connection: AsyncConnection,
    verifier: Verification,
) -> None:
    legacy_slug = await connection.scalar(
        text("SELECT slug FROM tenants WHERE id = :tenant_id"),
        {"tenant_id": LEGACY_TENANT_ID},
    )
    verifier.check(
        "deterministic legacy tenant exists", legacy_slug == LEGACY_TENANT_SLUG
    )

    for table_name in (
        "products",
        "prices",
        "canonical_products",
        "offers",
        "price_snapshots",
        "market_events",
        "generated_contents",
        "publications",
        "admin_actions",
    ):
        count = await connection.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE tenant_id = :tenant_id"),
            {"tenant_id": LEGACY_TENANT_ID},
        )
        null_count = await connection.scalar(
            text(f"SELECT count(*) FROM {table_name} WHERE tenant_id IS NULL"),
        )
        verifier.check(f"{table_name} legacy rows backfilled", count == 1)
        verifier.check(f"{table_name} tenant_id not null", null_count == 0)


async def _seed_two_tenants(session: AsyncSession) -> None:
    repositories = create_postgres_provider(session)
    await repositories.tenants.create(
        Tenant(
            id=TENANT_A_ID,
            name="Tenant A",
            slug="tenant-a",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await repositories.tenants.create(
        Tenant(
            id=TENANT_B_ID,
            name="Tenant B",
            slug="tenant-b",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await repositories.users.create(
        User(id=USER_A_ID, email="seller-a@example.com", created_at=NOW, updated_at=NOW)
    )
    await repositories.users.create(
        User(id=USER_B_ID, email="seller-b@example.com", created_at=NOW, updated_at=NOW)
    )
    await repositories.memberships.create(
        Membership(
            id=MEMBERSHIP_A_ID,
            user_id=USER_A_ID,
            tenant_id=TENANT_A_ID,
            role=TenantRole.OWNER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )
    await repositories.memberships.create(
        Membership(
            id=MEMBERSHIP_B_ID,
            user_id=USER_B_ID,
            tenant_id=TENANT_B_ID,
            role=TenantRole.VIEWER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )


async def _verify_repository_isolation(
    session: AsyncSession,
    verifier: Verification,
) -> None:
    repositories = create_postgres_provider(session)
    offer_a = _offer(TENANT_A_ID, "Tenant A Minecraft")
    offer_b = _offer(TENANT_B_ID, "Tenant B Minecraft")
    await repositories.offers.save(TENANT_A_ID, offer_a)
    await repositories.offers.save(TENANT_B_ID, offer_b)
    verifier.check(
        "same external offer can exist in two tenants",
        await repositories.offers.get_by_identity(TENANT_A_ID, "ggsel", "shared")
        == offer_a
        and await repositories.offers.get_by_identity(TENANT_B_ID, "ggsel", "shared")
        == offer_b,
    )
    verifier.check(
        "offer list is tenant isolated",
        tuple(await repositories.offers.list_by_tenant(TENANT_A_ID)) == (offer_a,)
        and tuple(await repositories.offers.list_by_tenant(TENANT_B_ID)) == (offer_b,),
    )

    previous_a = _snapshot(TENANT_A_ID, Decimal("990.00"), NOW)
    current_a = _snapshot(TENANT_A_ID, Decimal("790.00"), NOW + timedelta(minutes=1))
    previous_b = _snapshot(TENANT_B_ID, Decimal("990.00"), NOW)
    current_b = _snapshot(TENANT_B_ID, Decimal("790.00"), NOW + timedelta(minutes=1))
    for snapshot in (previous_a, current_a, previous_b, current_b):
        await repositories.price_history.add(snapshot.tenant_id, snapshot)
    verifier.check(
        "price history is tenant isolated",
        await repositories.price_history.get_last(TENANT_A_ID, "ggsel", "shared")
        == current_a
        and await repositories.price_history.get_last(TENANT_B_ID, "ggsel", "shared")
        == current_b,
    )

    change_a = PriceChangeDetector().detect(previous_a, current_a)
    change_b = PriceChangeDetector().detect(previous_b, current_b)
    assert change_a is not None
    assert change_b is not None
    event_a = PriceDropMarketEventBuilder().build(
        offer=offer_a,
        previous_snapshot=previous_a,
        current_snapshot=current_a,
        change=change_a,
        detected_at=current_a.collected_at,
    )
    event_b = PriceDropMarketEventBuilder().build(
        offer=offer_b,
        previous_snapshot=previous_b,
        current_snapshot=current_b,
        change=change_b,
        detected_at=current_b.collected_at,
    )
    added_a = await repositories.events.add_idempotently(MarketEventCandidate(event_a))
    added_b = await repositories.events.add_idempotently(MarketEventCandidate(event_b))
    verifier.check(
        "event identity v2 includes tenant",
        event_a.identity_key != event_b.identity_key,
    )
    verifier.check(
        "equivalent tenant events can both persist", added_a.created and added_b.created
    )


async def _verify_fresh_session_persistence(
    session: AsyncSession,
    verifier: Verification,
) -> None:
    repositories = create_postgres_provider(session)
    tenant_a_memberships = await repositories.memberships.list_for_tenant(TENANT_A_ID)
    tenant_b_offers = await repositories.offers.list_by_tenant(TENANT_B_ID)
    tenant_a_history = await repositories.price_history.get_history(
        TENANT_A_ID,
        "ggsel",
        "shared",
    )
    verifier.check(
        "fresh-session membership persistence", len(tenant_a_memberships) == 1
    )
    verifier.check("fresh-session offer persistence", len(tenant_b_offers) == 1)
    verifier.check(
        "fresh-session price history persistence", len(tenant_a_history) == 2
    )


async def _seed_legacy_rows(database_url: str) -> None:
    engine = create_async_engine(database_url)
    legacy_event_identity = _legacy_event_identity()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO marketplaces (id, code, name, enabled, created_at)
                    VALUES (
                        '40000000-0000-4000-8000-000000000001',
                        'legacy-marketplace',
                        'Legacy Marketplace',
                        true,
                        :now
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO products (
                        id,
                        external_id,
                        title,
                        marketplace_id,
                        created_at
                    )
                    VALUES (
                        '41000000-0000-4000-8000-000000000001',
                        'legacy-product',
                        'Legacy Product',
                        '40000000-0000-4000-8000-000000000001',
                        :now
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO prices (
                        id,
                        product_id,
                        price,
                        currency,
                        seller,
                        collected_at
                    )
                    VALUES (
                        '42000000-0000-4000-8000-000000000001',
                        '41000000-0000-4000-8000-000000000001',
                        990.00,
                        'RUB',
                        'Legacy Seller',
                        :now
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO canonical_products (
                        id,
                        name,
                        category,
                        aliases,
                        created_at
                    )
                    VALUES (
                        '43000000-0000-4000-8000-000000000001',
                        'Legacy Canonical',
                        'games',
                        '[]',
                        :now
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO offers (
                        id,
                        marketplace,
                        external_id,
                        title,
                        url,
                        price,
                        currency,
                        canonical_product_id,
                        created_at
                    )
                    VALUES (
                        '44000000-0000-4000-8000-000000000001',
                        'ggsel',
                        'legacy-offer',
                        'Legacy Offer',
                        'https://example.com/legacy',
                        790.00,
                        'RUB',
                        '43000000-0000-4000-8000-000000000001',
                        :now
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO price_snapshots (
                        id,
                        marketplace,
                        external_id,
                        price,
                        currency,
                        collected_at
                    )
                    VALUES
                        (1, 'ggsel', 'legacy-offer', 990.00, 'RUB', :previous_at),
                        (2, 'ggsel', 'legacy-offer', 790.00, 'RUB', :current_at)
                    """,
                ),
                {
                    "previous_at": NOW,
                    "current_at": NOW + timedelta(minutes=1),
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO market_events (
                        id,
                        identity_key,
                        identity_version,
                        identity_source,
                        event_type,
                        marketplace,
                        external_id,
                        canonical_product_id,
                        previous_snapshot_id,
                        current_snapshot_id,
                        title,
                        url,
                        old_price,
                        new_price,
                        currency,
                        percentage,
                        score,
                        disposition,
                        scoring_status,
                        scoring_attempt_count,
                        occurred_at,
                        detected_at,
                        created_at,
                        updated_at,
                        version
                    )
                    VALUES (
                        '45000000-0000-4000-8000-000000000001',
                        :identity_key,
                        1,
                        'snapshot_ids',
                        'price_drop',
                        'ggsel',
                        'legacy-offer',
                        '43000000-0000-4000-8000-000000000001',
                        1,
                        2,
                        'Legacy Offer',
                        'https://example.com/legacy',
                        990.00,
                        790.00,
                        'RUB',
                        20.202020,
                        NULL,
                        'active',
                        'pending',
                        0,
                        :current_at,
                        :current_at,
                        :current_at,
                        :current_at,
                        1
                    )
                    """,
                ),
                {
                    "current_at": NOW + timedelta(minutes=1),
                    "identity_key": legacy_event_identity,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO generated_contents (
                        id,
                        event_id,
                        content_type,
                        language,
                        origin,
                        prompt_version,
                        generation_status,
                        review_status,
                        attempt_number,
                        idempotency_key,
                        created_at,
                        updated_at,
                        version
                    )
                    VALUES (
                        '46000000-0000-4000-8000-000000000001',
                        '45000000-0000-4000-8000-000000000001',
                        'telegram_post',
                        'ru',
                        'ai',
                        'price_drop_v1',
                        'pending',
                        'pending',
                        1,
                        repeat('b', 64),
                        :now,
                        :now,
                        1
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO publications (
                        id,
                        event_id,
                        content_id,
                        channel,
                        destination_key,
                        publication_status,
                        attempt_count,
                        idempotency_key,
                        created_at,
                        updated_at,
                        version
                    )
                    VALUES (
                        '47000000-0000-4000-8000-000000000001',
                        '45000000-0000-4000-8000-000000000001',
                        '46000000-0000-4000-8000-000000000001',
                        'telegram',
                        'legacy-destination',
                        'pending',
                        0,
                        repeat('c', 64),
                        :now,
                        :now,
                        1
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO admin_actions (
                        id,
                        action,
                        resource_type,
                        resource_id,
                        previous_state,
                        resulting_state,
                        actor_id,
                        request_id,
                        idempotency_key,
                        request_fingerprint,
                        expected_version,
                        resulting_version,
                        created_at,
                        metadata
                    )
                    VALUES (
                        '48000000-0000-4000-8000-000000000001',
                        'approve_content',
                        'content',
                        '46000000-0000-4000-8000-000000000001',
                        'pending',
                        'approved',
                        'legacy-admin',
                        'legacy-request',
                        'legacy-action-key',
                        repeat('d', 64),
                        1,
                        2,
                        :now,
                        '{}'
                    )
                    """,
                ),
                {"now": NOW},
            )
            await connection.execute(
                text(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('price_snapshots', 'id'),
                        (SELECT max(id) FROM price_snapshots)
                    )
                    """,
                ),
            )
    finally:
        await engine.dispose()


def _offer(tenant_id: UUID, title: str) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="shared",
        title=title,
        url="https://example.com/shared",
        price=Decimal("790.00"),
        currency="RUB",
    )


def _snapshot(tenant_id: UUID, price: Decimal, collected_at: datetime) -> PriceSnapshot:
    return PriceSnapshot(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="shared",
        price=price,
        currency="RUB",
        collected_at=collected_at,
    )


def _legacy_event_identity() -> str:
    previous = SnapshotIdentity(
        marketplace="ggsel",
        external_id="legacy-offer",
        collected_at=NOW,
        price=Decimal("990.00"),
        currency="RUB",
    )
    current = SnapshotIdentity(
        marketplace="ggsel",
        external_id="legacy-offer",
        collected_at=NOW + timedelta(minutes=1),
        price=Decimal("790.00"),
        currency="RUB",
    )
    return build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="legacy-offer",
        previous_snapshot=previous,
        current_snapshot=current,
        identity_version=1,
    ).key


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str, revision: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), revision)


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic16_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated epic16_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
