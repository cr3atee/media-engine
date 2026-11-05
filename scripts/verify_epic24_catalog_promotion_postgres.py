"""Verify deterministic catalog-promotion manifests on memory and PostgreSQL."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC24_CATALOG_PROMOTION_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.offer_availability import OfferAvailabilityStatus
from app.domain.processing import StateTransitionOutcome
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifest,
    CatalogPromotionManifestError,
    CatalogPromotionManifestService,
)
from app.services.catalog_promotion_preflight import (
    CatalogPromotionIssueCode,
    CatalogPromotionLinkActionType,
    CatalogPromotionPreflightService,
    CatalogPromotionPreflightStatus,
)
from app.services.repository_scope import (
    RepositoryScopeFactory,
    create_memory_repository_scope,
)

TENANT_ID = UUID("75000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("75000000-0000-4000-8000-000000000002")
INCOMPLETE_TENANT_ID = UUID("75000000-0000-4000-8000-000000000003")
TARGET_TENANT_ID = UUID("75000000-0000-4000-8000-000000000004")
MINECRAFT_ID = UUID("75000000-0000-4000-8000-000000000010")
FORTNITE_ID = UUID("75000000-0000-4000-8000-000000000011")
FOREIGN_PRODUCT_ID = UUID("75000000-0000-4000-8000-000000000012")
INCOMPLETE_PRODUCT_ID = UUID("75000000-0000-4000-8000-000000000013")
DECIDED_AT = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


@dataclass(slots=True, frozen=True)
class RepositorySnapshot:
    """Tenant state used to prove that manifest generation is read-only."""

    products: tuple[CanonicalProduct, ...]
    offers: tuple[ParsedOffer, ...]
    decisions: tuple[CanonicalOfferDecision, ...]
    availability: tuple[tuple[str, str, str, int], ...]


class Verification:
    """Collect named checks and stop at the first violated invariant."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one successful invariant or raise its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Verify parity, isolation, fail-closed behavior, and restart stability."""
    _configure_stdout()
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    verifier = Verification()
    memory_provider = create_memory_provider()
    memory_scope = create_memory_repository_scope(memory_provider)
    await _seed(memory_scope)
    memory_manifest = await CatalogPromotionManifestService(memory_scope).build(
        TENANT_ID
    )
    verifier.check(
        "memory manifest digest is valid", memory_manifest.has_valid_digest()
    )
    memory_preflight = await CatalogPromotionPreflightService(memory_scope).inspect(
        memory_manifest,
        target_tenant_id=TARGET_TENANT_ID,
    )
    verifier.check(
        "memory preflight blocks a source-owned product ID in the same database",
        memory_preflight.status is CatalogPromotionPreflightStatus.BLOCKED
        and memory_preflight.required_mutations == 2
        and {issue.code for issue in memory_preflight.issues}
        == {CatalogPromotionIssueCode.PRODUCT_OWNED_BY_OTHER_TENANT},
    )

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    postgres_scope = create_postgres_repository_scope(sessions)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        verifier.check("database is at the Alembic head", revision == _migration_head())

        await _seed(postgres_scope)
        before = await _snapshot(postgres_scope, TENANT_ID)
        service = CatalogPromotionManifestService(postgres_scope)
        manifest = await service.build(TENANT_ID)
        repeated = await service.build(TENANT_ID)
        after = await _snapshot(postgres_scope, TENANT_ID)

        _verify_manifest(verifier, manifest)
        verifier.check(
            "memory and PostgreSQL manifests are identical",
            manifest.to_json() == memory_manifest.to_json(),
        )
        verifier.check(
            "repeated PostgreSQL build is idempotent",
            repeated.to_json() == manifest.to_json(),
        )
        verifier.check(
            "manifest generation does not mutate repositories", after == before
        )

        target_before = await _snapshot(postgres_scope, TARGET_TENANT_ID)
        preflight_service = CatalogPromotionPreflightService(postgres_scope)
        preflight = await preflight_service.inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )
        repeated_preflight = await preflight_service.inspect(
            manifest,
            target_tenant_id=TARGET_TENANT_ID,
        )
        target_after = await _snapshot(postgres_scope, TARGET_TENANT_ID)
        verifier.check(
            "PostgreSQL preflight matches memory",
            preflight == memory_preflight,
        )
        verifier.check(
            "preflight reports ownership conflict and two otherwise ready links",
            preflight.status is CatalogPromotionPreflightStatus.BLOCKED
            and preflight.product_actions == ()
            and all(
                action.action is CatalogPromotionLinkActionType.LINK
                for action in preflight.link_actions
            )
            and preflight.required_mutations == 2
            and {issue.code for issue in preflight.issues}
            == {CatalogPromotionIssueCode.PRODUCT_OWNED_BY_OTHER_TENANT},
        )
        verifier.check(
            "repeated preflight is deterministic",
            repeated_preflight == preflight,
        )
        verifier.check(
            "preflight does not mutate target repositories",
            target_after == target_before,
        )

        foreign = await service.build(FOREIGN_TENANT_ID)
        verifier.check(
            "tenant isolation excludes foreign catalog state",
            len(foreign.products) == 1
            and foreign.products[0].id == FOREIGN_PRODUCT_ID
            and len(foreign.links) == 1
            and foreign.links[0].marketplace == "funpay",
        )
        verifier.check(
            "unconfirmed active links fail closed",
            await _fails_closed(service, INCOMPLETE_TENANT_ID),
        )
    finally:
        await engine.dispose()

    fresh_engine = create_async_engine(database_url)
    fresh_sessions = async_sessionmaker(fresh_engine, expire_on_commit=False)
    try:
        fresh_scope = create_postgres_repository_scope(fresh_sessions)
        fresh = await CatalogPromotionManifestService(fresh_scope).build(TENANT_ID)
        verifier.check(
            "fresh engine retains the exact manifest",
            fresh.to_json() == memory_manifest.to_json(),
        )
        fresh_preflight = await CatalogPromotionPreflightService(fresh_scope).inspect(
            fresh,
            target_tenant_id=TARGET_TENANT_ID,
        )
        verifier.check(
            "fresh engine retains the exact preflight plan",
            fresh_preflight == memory_preflight,
        )
    finally:
        await fresh_engine.dispose()
        await default_engine.dispose()

    print()
    print(
        "EPIC 24 catalog promotion verification passed: "
        f"{len(verifier.passed)}/{len(verifier.passed)} checks."
    )
    print(
        "Artifact: "
        f"products={memory_manifest.summary.promoted_products}, "
        f"links={memory_manifest.summary.promoted_links}, "
        f"digest={memory_manifest.digest}"
    )
    print("Mode: export verification only; no target import was performed.")
    return 0


def _verify_manifest(
    verifier: Verification,
    manifest: CatalogPromotionManifest,
) -> None:
    verifier.check("PostgreSQL manifest digest is valid", manifest.has_valid_digest())
    verifier.check(
        "only referenced canonical products are promoted",
        tuple(product.id for product in manifest.products) == (MINECRAFT_ID,),
    )
    verifier.check(
        "only active confirmed links are promoted",
        tuple((link.marketplace, link.external_id) for link in manifest.links)
        == (("ggsel", "gg-active"), ("playerok", "pl-active")),
    )
    verifier.check(
        "retired confirmed and rejected pairs remain excluded",
        manifest.summary.confirmed_decisions == 3
        and manifest.summary.rejected_decisions == 1
        and manifest.summary.excluded_confirmed_decisions == 1,
    )
    verifier.check(
        "promotion summary matches the reviewed source state",
        manifest.summary.active_offers == 3
        and manifest.summary.canonical_products == 2
        and manifest.summary.terminal_decisions == 4
        and manifest.summary.promoted_products == 1
        and manifest.summary.promoted_links == 2,
    )
    verifier.check(
        "every promoted link carries immutable source and decision evidence",
        all(
            link.source_url.startswith("https://")
            and len(link.source_fingerprint) == 64
            and len(link.decision_fingerprint) == 64
            for link in manifest.links
        ),
    )


async def _seed(scope: RepositoryScopeFactory) -> None:
    async with scope() as repositories:
        for tenant in (
            _tenant(TENANT_ID, "EPIC 24 catalog", "epic24-main"),
            _tenant(FOREIGN_TENANT_ID, "EPIC 24 foreign", "epic24-foreign"),
            _tenant(
                INCOMPLETE_TENANT_ID,
                "EPIC 24 incomplete",
                "epic24-incomplete",
            ),
            _tenant(TARGET_TENANT_ID, "EPIC 24 target", "epic24-target"),
        ):
            if await repositories.tenants.get_by_id(tenant.id) is None:
                await repositories.tenants.create(tenant)
        for product in (
            _product(TENANT_ID, MINECRAFT_ID, "Minecraft"),
            _product(TENANT_ID, FORTNITE_ID, "Fortnite"),
            _product(FOREIGN_TENANT_ID, FOREIGN_PRODUCT_ID, "Foreign product"),
            _product(INCOMPLETE_TENANT_ID, INCOMPLETE_PRODUCT_ID, "Unreviewed"),
        ):
            await repositories.canonical_products.save(product)

        offers = (
            _offer(TENANT_ID, "ggsel", "gg-active", MINECRAFT_ID),
            _offer(TENANT_ID, "playerok", "pl-active", MINECRAFT_ID),
            _offer(TENANT_ID, "funpay", "rejected-active", None),
            _offer(TENANT_ID, "ggsel", "retired-confirmed", FORTNITE_ID),
            _offer(
                FOREIGN_TENANT_ID,
                "funpay",
                "foreign-active",
                FOREIGN_PRODUCT_ID,
            ),
            _offer(
                INCOMPLETE_TENANT_ID,
                "ggsel",
                "unconfirmed-link",
                INCOMPLETE_PRODUCT_ID,
            ),
            _offer(TARGET_TENANT_ID, "ggsel", "gg-active", None),
            _offer(TARGET_TENANT_ID, "playerok", "pl-active", None),
        )
        for offer in offers:
            await repositories.offers.save(offer.tenant_id, offer)

        decisions = (
            _decision(TENANT_ID, "ggsel", "gg-active", MINECRAFT_ID, True, 1),
            _decision(TENANT_ID, "playerok", "pl-active", MINECRAFT_ID, True, 2),
            _decision(TENANT_ID, "funpay", "rejected-active", FORTNITE_ID, False, 3),
            _decision(
                TENANT_ID,
                "ggsel",
                "retired-confirmed",
                FORTNITE_ID,
                True,
                4,
            ),
            _decision(
                FOREIGN_TENANT_ID,
                "funpay",
                "foreign-active",
                FOREIGN_PRODUCT_ID,
                True,
                5,
            ),
        )
        for decision in decisions:
            await repositories.canonical_offer_decisions.append(decision)

        state = await repositories.offers.get_availability_state(
            TENANT_ID,
            "ggsel",
            "retired-confirmed",
        )
        if state is not None and state.status is not OfferAvailabilityStatus.RETIRED:
            result = await repositories.offers.set_availability_status(
                TENANT_ID,
                "ggsel",
                "retired-confirmed",
                OfferAvailabilityStatus.RETIRED,
                DECIDED_AT,
                state.version,
            )
            if result.outcome is not StateTransitionOutcome.APPLIED:
                raise AssertionError("Retired promotion fixture was not applied.")


async def _snapshot(
    scope: RepositoryScopeFactory,
    tenant_id: UUID,
) -> RepositorySnapshot:
    async with scope() as repositories:
        products = tuple(
            await repositories.canonical_products.list_by_tenant(tenant_id)
        )
        offers = tuple(await repositories.offers.list_by_tenant(tenant_id))
        decisions = tuple(
            await repositories.canonical_offer_decisions.list_by_tenant(tenant_id)
        )
        availability: list[tuple[str, str, str, int]] = []
        for marketplace, external_id in (
            ("ggsel", "gg-active"),
            ("playerok", "pl-active"),
            ("funpay", "rejected-active"),
            ("ggsel", "retired-confirmed"),
        ):
            state = await repositories.offers.get_availability_state(
                tenant_id,
                marketplace,
                external_id,
            )
            if state is not None:
                availability.append(
                    (marketplace, external_id, state.status.value, state.version)
                )
    return RepositorySnapshot(products, offers, decisions, tuple(availability))


async def _fails_closed(
    service: CatalogPromotionManifestService,
    tenant_id: UUID,
) -> bool:
    try:
        await service.build(tenant_id)
    except CatalogPromotionManifestError:
        return True
    return False


def _product(tenant_id: UUID, product_id: UUID, name: str) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=tenant_id,
        name=name,
        category="Games",
        aliases=(name.lower(),),
    )


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=DECIDED_AT,
        updated_at=DECIDED_AT,
    )


def _offer(
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
    product_id: UUID | None,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        title=f"{marketplace} {external_id}",
        url=f"https://example.test/{marketplace}/{external_id}",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Verified seller",
        source_category_id="games",
        source_category_name="Games",
        canonical_product_id=product_id,
    )


def _decision(
    tenant_id: UUID,
    marketplace: str,
    external_id: str,
    product_id: UUID,
    confirmed: bool,
    ordinal: int,
) -> CanonicalOfferDecision:
    outcome = (
        CanonicalOfferDecisionType.CONFIRMED
        if confirmed
        else CanonicalOfferDecisionType.REJECTED
    )
    identity = f"{tenant_id}:{marketplace}:{external_id}:{product_id}:{outcome}"
    return CanonicalOfferDecision(
        id=uuid5(NAMESPACE_URL, identity),
        tenant_id=tenant_id,
        marketplace=marketplace,
        external_id=external_id,
        canonical_product_id=product_id,
        decision=outcome,
        actor_id="catalog-reviewer",
        actor_type=AdminActorType.USER,
        request_id=f"request-{ordinal}",
        idempotency_key=f"promotion-{ordinal}-{external_id}",
        request_fingerprint=sha256(identity.encode("utf-8")).hexdigest(),
        created_at=DECIDED_AT.replace(minute=ordinal),
        reason="Reviewed for bounded catalog launch",
    )


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    host = (url.host or "").lower()
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must target a loopback host.")
    if not database_name.startswith("epic24_catalog_promotion_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic24_catalog_promotion_* database; got {database_name!r}."
        )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
