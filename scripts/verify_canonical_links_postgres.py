"""Verify tenant-safe canonical offer links against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_URL_ENV = "EPIC19_CANONICAL_LINK_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.comparator.grouping import OfferGroupingService
from app.comparator.models import MarketplaceOffer
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.models.canonical_product_record import CanonicalProductRecord
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_postgres_provider
from app.services.canonical_offer_linking import (
    CanonicalOfferLinkService,
    CanonicalProductUnavailableError,
    LinkCanonicalOfferCommand,
)

TENANT_A_ID = UUID("19000000-0000-4000-8000-000000000101")
TENANT_B_ID = UUID("19000000-0000-4000-8000-000000000102")
PRODUCT_ID = UUID("19000000-0000-4000-8000-000000000201")
NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


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
    """Run canonical-link persistence verification in an isolated database."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _verify_schema(session_factory, verifier)
        await _seed_data(session_factory)
        await _verify_link_service(session_factory, verifier)
        await _verify_cross_tenant_guards(session_factory, verifier)
        await _verify_delete_behavior(session_factory, verifier)
    finally:
        await engine.dispose()

    print(
        "Canonical offer links PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_schema(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    async with session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        constraints = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conname IN (
                            'uq_canonical_products_tenant_id_id',
                            'fk_offers_tenant_canonical_product',
                            'fk_offers_canonical_product_id_canonical_products'
                        )
                        """
                    )
                )
            ).scalars()
        )
        indexes = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                            AND indexname IN (
                                'ix_offers_tenant_canonical_product',
                                'ix_offers_canonical_product_id'
                            )
                        """
                    )
                )
            ).scalars()
        )

    verifier.check("migration head is 0015", revision == "0015_tenant_canonical_links")
    verifier.check(
        "tenant product identity constraint exists",
        "uq_canonical_products_tenant_id_id" in constraints,
    )
    verifier.check(
        "tenant canonical link foreign key exists",
        "fk_offers_tenant_canonical_product" in constraints,
    )
    verifier.check(
        "legacy canonical delete foreign key remains",
        "fk_offers_canonical_product_id_canonical_products" in constraints,
    )
    verifier.check(
        "canonical link indexes exist",
        indexes
        == {
            "ix_offers_tenant_canonical_product",
            "ix_offers_canonical_product_id",
        },
    )


async def _seed_data(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    product = _product()
    offer = _offer(tenant_id=TENANT_A_ID, external_id="offer-valid")
    foreign_offer = _offer(tenant_id=TENANT_B_ID, external_id="offer-foreign")
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.tenants.create(_tenant(TENANT_A_ID, "Tenant A", "tenant-a"))
        await repositories.tenants.create(_tenant(TENANT_B_ID, "Tenant B", "tenant-b"))
        await repositories.canonical_products.save(product)
        await repositories.offers.save(TENANT_A_ID, offer)
        await repositories.offers.save(TENANT_B_ID, foreign_offer)


async def _verify_link_service(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    service = CanonicalOfferLinkService(
        create_postgres_repository_scope(session_factory)
    )
    command_value = LinkCanonicalOfferCommand(
        tenant_id=TENANT_A_ID,
        canonical_product_id=PRODUCT_ID,
        marketplace="ggsel",
        external_id="offer-valid",
    )
    linked = await service.link(command_value)
    repeated = await service.link(command_value)

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        persisted = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-valid",
        )
        candidates = await repositories.canonical_products.list_by_tenant(TENANT_A_ID)

    groups = OfferGroupingService().group(
        [MarketplaceOffer(offer=linked)],
        candidates,
    )
    verifier.check("same-tenant canonical link persisted", persisted == linked)
    verifier.check("canonical link command is idempotent", repeated == linked)
    verifier.check(
        "fresh-session canonical link retained",
        persisted is not None and persisted.canonical_product_id == PRODUCT_ID,
    )
    verifier.check(
        "persisted link drives deterministic grouping",
        len(groups) == 1 and groups[0].canonical_product_id == PRODUCT_ID,
    )


async def _verify_cross_tenant_guards(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    service = CanonicalOfferLinkService(
        create_postgres_repository_scope(session_factory)
    )
    try:
        await service.link(
            LinkCanonicalOfferCommand(
                tenant_id=TENANT_B_ID,
                canonical_product_id=PRODUCT_ID,
                marketplace="ggsel",
                external_id="offer-foreign",
            )
        )
    except CanonicalProductUnavailableError:
        verifier.check("service rejects cross-tenant canonical product", True)
    else:
        raise AssertionError("service accepted a cross-tenant canonical product")

    invalid_offer = _offer(
        tenant_id=TENANT_B_ID,
        external_id="offer-direct-invalid",
        canonical_product_id=PRODUCT_ID,
    )
    try:
        async with session_factory() as session, session.begin():
            repositories = create_postgres_provider(session)
            await repositories.offers.save(TENANT_B_ID, invalid_offer)
    except IntegrityError:
        verifier.check("database rejects direct cross-tenant canonical link", True)
    else:
        raise AssertionError("database accepted a direct cross-tenant canonical link")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stored_invalid = await repositories.offers.get_by_identity(
            TENANT_B_ID,
            "ggsel",
            "offer-direct-invalid",
        )
        stored_foreign = await repositories.offers.get_by_identity(
            TENANT_B_ID,
            "ggsel",
            "offer-foreign",
        )

    verifier.check(
        "invalid direct link transaction rolled back", stored_invalid is None
    )
    verifier.check(
        "cross-tenant service failure left offer unchanged",
        stored_foreign is not None and stored_foreign.canonical_product_id is None,
    )


async def _verify_delete_behavior(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(CanonicalProductRecord).where(
                CanonicalProductRecord.id == PRODUCT_ID
            )
        )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stored = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-valid",
        )
        product = await repositories.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            PRODUCT_ID,
        )

    verifier.check("canonical product delete committed", product is None)
    verifier.check(
        "canonical product delete clears offer link",
        stored is not None and stored.canonical_product_id is None,
    )


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _product() -> CanonicalProduct:
    return CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=TENANT_A_ID,
        name="Minecraft: Java & Bedrock Edition for PC",
        category="Games",
        aliases=("minecraft java bedrock",),
    )


def _offer(
    *,
    tenant_id: UUID,
    external_id: str,
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        title="Noisy source title that cannot be guessed",
        url=f"https://ggsel.net/en/catalog/product/{external_id}",
        price=Decimal("1999.00"),
        currency="RUB",
        canonical_product_id=canonical_product_id,
    )


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        msg = f"{DATABASE_URL_ENV} must use PostgreSQL."
        raise RuntimeError(msg)
    if not database_name.startswith("epic19_canonical_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic19_canonical_* database; got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
