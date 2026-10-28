"""Verify source-scoped offer availability against isolated PostgreSQL."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_DATABASE_ENV = "OFFER_AVAILABILITY_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.environ.get(_DATABASE_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.database.repository_scope import create_postgres_repository_scope
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.models.offer_source_observation_record import OfferSourceObservationRecord
from app.parsers.models import ParsedOffer
from app.repositories.offers import OfferObservationContext
from app.repositories.public_queries.models import PublicOfferQuery
from app.repositories.public_queries.repository_backed import (
    RepositoryBackedPublicReadRepository,
)
from app.repositories.queries.models import PageRequest
from app.services.repository_scope import RepositoryScopeFactory

_DATABASE_PREFIX = "mediaengine_offer_availability_verify_"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
TENANT_ID = UUID("24000000-0000-4000-8000-000000000001")
INTEGRATION_A_ID = UUID("24000000-0000-4000-8000-000000000101")
INTEGRATION_B_ID = UUID("24000000-0000-4000-8000-000000000102")
NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


class Verification:
    """Count named PostgreSQL availability checks."""

    def __init__(self) -> None:
        self.count = 0

    def check(self, condition: bool, name: str) -> None:
        """Record one successful invariant or fail with its stable name."""
        if not condition:
            raise AssertionError(name)
        self.count += 1
        print(f"PASS {self.count:02d}: {name}")


async def main() -> None:
    """Verify durable source observations against isolated PostgreSQL."""
    database_url = _safe_database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(sessions)
    verification = Verification()

    try:
        await _seed_source_boundaries(scope_factory)
        await _verify_source_isolation(scope_factory, verification)
        await _verify_empty_snapshot_guard(scope_factory, verification)
        await _verify_reactivation_and_ordering(scope_factory, verification)
        await _verify_rollback(scope_factory, verification)
        await _verify_storage_shape(sessions, verification)
    finally:
        await engine.dispose()

    await _verify_fresh_engine(database_url, verification)
    print(f"SUCCESS: {verification.count} PostgreSQL checks passed")


async def _seed_source_boundaries(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="Offer Availability Verification",
                slug="offer-availability-verification",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for integration in (
            _integration(INTEGRATION_A_ID, "Verification source A", 1),
            _integration(INTEGRATION_B_ID, "Verification source B", 2),
        ):
            await repositories.marketplace_integrations.save(integration)


async def _verify_source_isolation(
    scope_factory: RepositoryScopeFactory,
    verification: Verification,
) -> None:
    source_a = _context(INTEGRATION_A_ID, NOW + timedelta(minutes=3))
    source_b = _context(INTEGRATION_B_ID, NOW + timedelta(minutes=3))
    first = _offer("first")
    shared = _offer("shared")
    second = _offer("second")

    async with scope_factory() as repositories:
        await repositories.offers.save_observed(source_a, first)
        await repositories.offers.save_observed(source_a, shared)
        await repositories.offers.save_observed(source_b, shared)
        await repositories.offers.save_observed(source_b, second)

    async with scope_factory() as repositories:
        changed = await repositories.offers.reconcile_observations(
            _context(INTEGRATION_A_ID, NOW + timedelta(minutes=4)),
            {"first"},
        )
    verification.check(changed == 1, "source A deactivates one missing observation")
    verification.check(
        await _visible_ids(scope_factory) == ("first", "second", "shared"),
        "shared offer remains visible through source B",
    )

    async with scope_factory() as repositories:
        changed = await repositories.offers.reconcile_observations(
            _context(INTEGRATION_B_ID, NOW + timedelta(minutes=5)),
            {"second"},
        )
    verification.check(changed == 1, "source B deactivates its missing observation")
    verification.check(
        await _visible_ids(scope_factory) == ("first", "second"),
        "offer disappears only after every observing source is inactive",
    )


async def _verify_empty_snapshot_guard(
    scope_factory: RepositoryScopeFactory,
    verification: Verification,
) -> None:
    async with scope_factory() as repositories:
        changed = await repositories.offers.reconcile_observations(
            _context(INTEGRATION_A_ID, NOW + timedelta(minutes=6)),
            set(),
        )
    verification.check(changed == 0, "empty snapshot performs no deactivation")
    verification.check(
        await _visible_ids(scope_factory) == ("first", "second"),
        "empty snapshot preserves current public offers",
    )


async def _verify_reactivation_and_ordering(
    scope_factory: RepositoryScopeFactory,
    verification: Verification,
) -> None:
    reactivated_at = NOW + timedelta(minutes=10)
    async with scope_factory() as repositories:
        await repositories.offers.save_observed(
            _context(INTEGRATION_A_ID, reactivated_at),
            _offer("shared"),
        )
    verification.check(
        await _visible_ids(scope_factory) == ("first", "second", "shared"),
        "new observation reactivates a previously missing offer",
    )

    async with scope_factory() as repositories:
        changed = await repositories.offers.reconcile_observations(
            _context(INTEGRATION_A_ID, NOW + timedelta(minutes=8)),
            {"first"},
        )
    verification.check(changed == 0, "older run cannot overwrite newer source state")
    verification.check(
        await _visible_ids(scope_factory) == ("first", "second", "shared"),
        "out-of-order reconciliation preserves reactivated offer",
    )


async def _verify_rollback(
    scope_factory: RepositoryScopeFactory,
    verification: Verification,
) -> None:
    try:
        async with scope_factory() as repositories:
            changed = await repositories.offers.reconcile_observations(
                _context(INTEGRATION_A_ID, NOW + timedelta(minutes=20)),
                {"first"},
            )
            verification.check(changed == 1, "rollback scenario mutates transaction")
            raise RuntimeError("force availability rollback")
    except RuntimeError as exc:
        verification.check(
            str(exc) == "force availability rollback",
            "rollback scenario raises expected failure",
        )

    verification.check(
        await _visible_ids(scope_factory) == ("first", "second", "shared"),
        "failed transaction rolls observation state back",
    )


async def _verify_storage_shape(
    sessions: async_sessionmaker[AsyncSession],
    verification: Verification,
) -> None:
    async with sessions() as session:
        total = await session.scalar(
            select(func.count()).select_from(OfferSourceObservationRecord)
        )
        active = await session.scalar(
            select(func.count())
            .select_from(OfferSourceObservationRecord)
            .where(OfferSourceObservationRecord.is_active.is_(True))
        )
    verification.check(total == 4, "one durable row exists per source and offer")
    verification.check(active == 3, "inactive source observation remains auditable")


async def _verify_fresh_engine(database_url: str, verification: Verification) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(sessions)
    try:
        verification.check(
            await _visible_ids(scope_factory) == ("first", "second", "shared"),
            "fresh engine retains source availability state",
        )
        async with scope_factory() as repositories:
            public = RepositoryBackedPublicReadRepository(repositories)
            page = await public.list_offers(
                PublicOfferQuery(tenant_id=TENANT_ID),
                PageRequest(
                    limit=100,
                    sort="price",
                    direction="asc",
                    filter_hash="availability-verification",
                ),
            )
        verification.check(len(page.items) == 3, "public read excludes inactive offers")
    finally:
        await engine.dispose()


async def _visible_ids(scope_factory: RepositoryScopeFactory) -> tuple[str, ...]:
    async with scope_factory() as repositories:
        offers = await repositories.offers.list_by_tenant(TENANT_ID)
    return tuple(sorted(_external_ids(offers)))


def _external_ids(offers: Sequence[ParsedOffer]) -> list[str]:
    return [offer.external_id for offer in offers if offer.external_id is not None]


def _integration(
    integration_id: UUID,
    display_name: str,
    minute: int,
) -> MarketplaceIntegration:
    timestamp = NOW + timedelta(minutes=minute)
    return MarketplaceIntegration(
        id=integration_id,
        tenant_id=TENANT_ID,
        marketplace="ggsel",
        display_name=display_name,
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        source_url=f"https://example.com/source-{minute}",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _context(integration_id: UUID, observed_at: datetime) -> OfferObservationContext:
    return OfferObservationContext(
        tenant_id=TENANT_ID,
        integration_id=integration_id,
        marketplace="ggsel",
        observed_at=observed_at,
    )


def _offer(external_id: str) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT_ID,
        marketplace="ggsel",
        external_id=external_id,
        title=f"Verification offer {external_id}",
        url=f"https://example.com/offers/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
    )


def _safe_database_url() -> str:
    raw_url = os.environ.get(_DATABASE_ENV)
    if raw_url is None:
        raise RuntimeError(f"{_DATABASE_ENV} is required.")
    url: URL = make_url(raw_url)
    if url.host not in _LOOPBACK_HOSTS:
        raise RuntimeError("Verification PostgreSQL host must be loopback-only.")
    if url.database is None or not url.database.startswith(_DATABASE_PREFIX):
        raise RuntimeError(
            f"Verification database must start with {_DATABASE_PREFIX!r}."
        )
    return raw_url


if __name__ == "__main__":
    asyncio.run(main())
