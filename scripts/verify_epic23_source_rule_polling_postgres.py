"""Verify one live GGSEL source rule through polling and public catalog reads."""

# ruff: noqa: E402, I001

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC23_SOURCE_RULE_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.catalog.taxonomy import MVP_CATALOG_HUBS
from app.core.http_client import HttpClient
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.domain.marketplace import Marketplace
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.public_queries.models import PublicCatalogHubQuery
from app.repositories.public_queries.repository_backed import (
    create_repository_backed_public_read_provider,
)
from app.repositories.queries.models import PageRequest
from app.runtime.marketplaces import create_marketplace_runner_factories
from app.services.canonical_offer_review import (
    CanonicalOfferReviewContext,
    CanonicalOfferReviewService,
    ReviewCanonicalOfferCommand,
)
from app.services.catalog_classification import (
    CatalogClassificationService,
    CreateCatalogSourceRuleCommand,
)
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.repository_scope import RepositoryScopeFactory

TENANT_ID = UUID("53000000-0000-4000-8000-000000000001")
INTEGRATION_ID = UUID("53000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("53000000-0000-4000-8000-000000000003")
GGSEL_URL = "https://ggsel.net/en/catalog/minecraft-keys-pc"
SOURCE_CATEGORY_ID = "66568"
HUB_CODE = "minecraft"
SECTION_CODE = "keys"


class Verification:
    """Collect named checks and stop on the first false claim."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing condition or raise its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run the guarded live source-rule lifecycle against isolated PostgreSQL."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
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
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        integration = await _seed_tenant_and_integration(scope_factory)
        classification = CatalogClassificationService(
            scope_factory,
            MVP_CATALOG_HUBS,
        )
        async with HttpClient(timeout=45.0) as http_client:
            runner = create_marketplace_runner_factories(
                http_client=http_client,
                repository_scope_factory=scope_factory,
            )[Marketplace.GGSEL.value](integration)

            first = _require_run_result(await runner.run(GGSEL_URL))
            verifier.check(
                "first live GGSEL poll persists a complete nonempty snapshot",
                first.offers_received > 0
                and first.offers_persisted == first.offers_received
                and first.source_snapshot_complete,
            )
            first_offers = await _integration_offers(scope_factory)
            selected_before = _selected_category_offers(first_offers)
            verifier.check(
                "live GGSEL exposes source category 66568",
                len(selected_before) > 0,
            )
            verifier.check(
                "offers remain unclassified before an explicit rule",
                all(_has_no_catalog_classification(offer) for offer in first_offers),
            )

            evidence = await classification.list_source_categories(
                TENANT_ID,
                INTEGRATION_ID,
            )
            selected_evidence = tuple(
                item
                for item in evidence
                if item.source_category_id == SOURCE_CATEGORY_ID
            )
            verifier.check(
                "seller workflow reads exact integration source evidence",
                len(selected_evidence) == 1
                and selected_evidence[0].marketplace == Marketplace.GGSEL.value
                and selected_evidence[0].offer_count == len(selected_before),
            )

            rule = await classification.create_rule(
                CreateCatalogSourceRuleCommand(
                    tenant_id=TENANT_ID,
                    integration_id=INTEGRATION_ID,
                    marketplace=Marketplace.GGSEL.value,
                    source_category_id=SOURCE_CATEGORY_ID,
                    source_category_name=selected_evidence[0].source_category_name,
                    hub_code=HUB_CODE,
                    section_code=SECTION_CODE,
                )
            )
            verifier.check(
                "explicit rule maps 66568 to Minecraft keys",
                rule.source_category_id == SOURCE_CATEGORY_ID
                and rule.hub_code == HUB_CODE
                and rule.section_code == SECTION_CODE,
            )

            second = _require_run_result(await runner.run(GGSEL_URL))
            verifier.check(
                "second live poll commits after rule creation",
                second.offers_persisted > 0 and second.persistence_committed,
            )
            second_offers = await _integration_offers(scope_factory)
            selected_after = _selected_category_offers(second_offers)
            verifier.check(
                "every observed 66568 offer receives the persisted classification",
                len(selected_after) > 0
                and all(
                    offer.catalog_hub_code == HUB_CODE
                    and offer.catalog_section_code == SECTION_CODE
                    and offer.catalog_source_rule_id == rule.id
                    for offer in selected_after
                ),
            )
            verifier.check(
                "unmapped source categories receive no invented classification",
                all(
                    _has_no_catalog_classification(offer)
                    for offer in second_offers
                    if offer.source_category_id != SOURCE_CATEGORY_ID
                ),
            )

            reviewed_offer = selected_after[0]
            await _seed_canonical_product(scope_factory)
            review = await CanonicalOfferReviewService(scope_factory).review(
                ReviewCanonicalOfferCommand(
                    tenant_id=TENANT_ID,
                    marketplace=Marketplace.GGSEL.value,
                    external_id=_require_external_id(reviewed_offer),
                    canonical_product_id=PRODUCT_ID,
                    decision=CanonicalOfferDecisionType.CONFIRMED,
                    reason="Explicit EPIC 23 verification decision.",
                ),
                CanonicalOfferReviewContext(
                    actor_id="epic23-source-rule-verifier",
                    actor_type=AdminActorType.USER,
                    request_id="epic23-source-rule-request",
                    idempotency_key="epic23-source-rule-decision",
                ),
            )
            verifier.check(
                "explicit review persists one confirmed canonical link",
                review.decision.decision is CanonicalOfferDecisionType.CONFIRMED
                and not review.replayed,
            )
            await _verify_public_hub(scope_factory, verifier)

            third = _require_run_result(await runner.run(GGSEL_URL))
            verifier.check(
                "repeated live polling remains successful",
                third.offers_persisted > 0 and third.persistence_committed,
            )
            linked = await _get_offer(
                scope_factory,
                _require_external_id(reviewed_offer),
            )
            verifier.check(
                "repeated polling preserves the reviewed canonical link",
                linked is not None
                and linked.canonical_product_id == PRODUCT_ID
                and linked.catalog_source_rule_id == rule.id,
            )
            await _verify_public_hub(scope_factory, verifier)
    finally:
        await engine.dispose()

    await _verify_fresh_engine(
        database_url,
        rule_id=rule.id,
        external_id=_require_external_id(reviewed_offer),
        verifier=verifier,
    )
    print()
    print(
        "EPIC 23 live source-rule polling verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _seed_tenant_and_integration(
    scope_factory: RepositoryScopeFactory,
) -> MarketplaceIntegration:
    timestamp = datetime.now(UTC)
    integration = MarketplaceIntegration(
        id=INTEGRATION_ID,
        tenant_id=TENANT_ID,
        marketplace=Marketplace.GGSEL.value,
        display_name="GGSEL Minecraft Keys verification",
        source_url=GGSEL_URL,
        enabled=True,
        status=MarketplaceIntegrationStatus.ACTIVE,
        created_at=timestamp,
        updated_at=timestamp,
    )
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="EPIC 23 Source Rule Verification",
                slug="epic23-source-rule-verification",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        await repositories.marketplace_integrations.save(integration)
    return integration


async def _seed_canonical_product(scope_factory: RepositoryScopeFactory) -> None:
    async with scope_factory() as repositories:
        await repositories.canonical_products.save(
            CanonicalProduct(
                id=PRODUCT_ID,
                name="Minecraft Keys",
                category=SECTION_CODE,
                aliases=("minecraft key",),
                tenant_id=TENANT_ID,
            )
        )


async def _integration_offers(
    scope_factory: RepositoryScopeFactory,
) -> tuple[ParsedOffer, ...]:
    async with scope_factory() as repositories:
        return tuple(
            await repositories.offers.list_by_integration(
                TENANT_ID,
                INTEGRATION_ID,
            )
        )


async def _get_offer(
    scope_factory: RepositoryScopeFactory,
    external_id: str,
) -> ParsedOffer | None:
    async with scope_factory() as repositories:
        return await repositories.offers.get_by_identity(
            TENANT_ID,
            Marketplace.GGSEL.value,
            external_id,
        )


async def _verify_public_hub(
    scope_factory: RepositoryScopeFactory,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        public = create_repository_backed_public_read_provider(repositories)
        page = await public.catalog_hubs.list_catalog_hubs(
            PublicCatalogHubQuery(tenant_id=TENANT_ID),
            PageRequest(
                limit=20,
                sort="code",
                direction="asc",
                filter_hash="epic23-source-rule",
            ),
        )
    minecraft = tuple(item for item in page.items if item.code == HUB_CODE)
    verifier.check(
        "public catalog exposes reviewed Minecraft keys classification",
        len(minecraft) == 1
        and minecraft[0].product_count == 1
        and minecraft[0].offer_count == 1
        and minecraft[0].marketplaces == (Marketplace.GGSEL.value,)
        and len(minecraft[0].sections) == 1
        and minecraft[0].sections[0].code == SECTION_CODE,
    )


async def _verify_fresh_engine(
    database_url: str,
    *,
    rule_id: UUID,
    external_id: str,
    verifier: Verification,
) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(factory)
    try:
        async with scope_factory() as repositories:
            rule = await repositories.catalog_source_rules.get_by_source(
                TENANT_ID,
                INTEGRATION_ID,
                Marketplace.GGSEL.value,
                SOURCE_CATEGORY_ID,
            )
            offer = await repositories.offers.get_by_identity(
                TENANT_ID,
                Marketplace.GGSEL.value,
                external_id,
            )
        async with engine.connect() as connection:
            migration = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        verifier.check(
            "fresh engine reads the exact persisted source rule",
            rule is not None and rule.id == rule_id,
        )
        verifier.check(
            "fresh engine reads the linked classified offer",
            offer is not None
            and offer.canonical_product_id == PRODUCT_ID
            and offer.catalog_source_rule_id == rule_id,
        )
        verifier.check(
            "current Alembic head is applied",
            migration == _migration_head(),
        )
        await _verify_public_hub(scope_factory, verifier)
    finally:
        await engine.dispose()


def _selected_category_offers(
    offers: tuple[ParsedOffer, ...],
) -> tuple[ParsedOffer, ...]:
    return tuple(
        offer for offer in offers if offer.source_category_id == SOURCE_CATEGORY_ID
    )


def _has_no_catalog_classification(offer: ParsedOffer) -> bool:
    return (
        offer.catalog_hub_code is None
        and offer.catalog_section_code is None
        and offer.catalog_source_rule_id is None
    )


def _require_external_id(offer: ParsedOffer) -> str:
    if offer.external_id is None:
        raise RuntimeError("GGSEL offer has no external ID.")
    return offer.external_id


def _require_run_result(result: object) -> MarketplaceRunResult:
    if not isinstance(result, MarketplaceRunResult):
        raise RuntimeError("GGSEL runner returned an unexpected result type.")
    return result


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head revision.")
    return head


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "localhost"}
        or not database_name.startswith("epic23_source_rule_")
    ):
        msg = (
            f"{DATABASE_URL_ENV} must use postgresql+asyncpg and an isolated "
            "loopback epic23_source_rule_* database."
        )
        raise RuntimeError(msg)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
