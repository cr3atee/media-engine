"""Verify the guarded catalog release across isolated source and target databases."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.public_read_scope import create_postgres_public_read_repository_scope
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.admin_actions import AdminActorType, AdminResourceType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.services.catalog_promotion_import import catalog_promotion_resource_id
from app.services.catalog_promotion_preflight import CatalogPromotionPreflightStatus
from app.services.catalog_promotion_release import CatalogPromotionReleaseService
from app.services.public_products import PublicProductReadService
from app.services.repository_scope import RepositoryScopeFactory
from scripts.run_catalog_promotion_release import (
    ACTOR_ID_ENV,
    APPLY_ENABLED_ENV,
    APPROVAL_PHRASE_ENV,
    BACKUP_CONFIRMATION_ENV,
    EXPECTED_TARGET_DATABASE_ENV,
    IDEMPOTENCY_KEY_ENV,
    MONITORING_CONFIRMATION_ENV,
    REASON_ENV,
    REQUEST_ID_ENV,
    SOURCE_DATABASE_URL_ENV,
    SOURCE_TENANT_ID_ENV,
    TARGET_DATABASE_URL_ENV,
    TARGET_TENANT_ID_ENV,
    CatalogPromotionReleaseCliError,
    _run,
    release_guard_phrases,
)

SOURCE_URL_ENV = "EPIC24_RELEASE_SOURCE_DATABASE_URL"
TARGET_URL_ENV = "EPIC24_RELEASE_TARGET_DATABASE_URL"
SOURCE_TENANT_ID = UUID("7a000000-0000-4000-8000-000000000001")
TARGET_TENANT_ID = UUID("7a000000-0000-4000-8000-000000000002")
PRODUCT_ID = UUID("7a000000-0000-4000-8000-000000000010")
DECIDED_AT = datetime(2026, 11, 5, 14, 0, tzinfo=UTC)


@dataclass(slots=True, frozen=True)
class CatalogState:
    products: tuple[CanonicalProduct, ...]
    offers: tuple[ParsedOffer, ...]
    actions: int


class Verification:
    """Record named release checks and stop on the first failure."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run preview, apply, restart replay, and public-read verification."""
    _configure_stdout()
    source_url = os.getenv(SOURCE_URL_ENV, "").strip()
    target_url = os.getenv(TARGET_URL_ENV, "").strip()
    if not source_url or not target_url:
        print(f"SKIPPED: set {SOURCE_URL_ENV} and {TARGET_URL_ENV}.")
        return 0
    _require_isolated_database(source_url, prefix="epic24_release_source_")
    _require_isolated_database(target_url, prefix="epic24_release_target_")

    verifier = Verification()
    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)
    source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
    target_sessions = async_sessionmaker(target_engine, expire_on_commit=False)
    source_scope = create_postgres_repository_scope(source_sessions)
    target_scope = create_postgres_repository_scope(target_sessions)
    try:
        verifier.check(
            "source and target databases are at Alembic head",
            await _revision(source_engine) == _migration_head()
            and await _revision(target_engine) == _migration_head(),
        )
        await _seed(source_scope, target_scope)
        release = CatalogPromotionReleaseService(source_scope, target_scope)
        preview = await release.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
        verifier.check(
            "cross-database preflight is ready",
            preview.preflight.status is CatalogPromotionPreflightStatus.READY
            and preview.preflight.required_mutations == 2,
        )
        manifest_digest = preview.manifest.digest
        source_before = await _state(
            source_scope,
            SOURCE_TENANT_ID,
            manifest_digest,
        )
        target_before = await _state(
            target_scope,
            TARGET_TENANT_ID,
            manifest_digest,
        )
        environment = _preview_environment(source_url, target_url)
        preview_result = await _run(argparse.Namespace(apply=False), environment)
        verifier.check("operator preview succeeds", preview_result == 0)
        verifier.check(
            "operator preview mutates neither database",
            await _state(source_scope, SOURCE_TENANT_ID, manifest_digest)
            == source_before
            and await _state(target_scope, TARGET_TENANT_ID, manifest_digest)
            == target_before,
        )

        guard_blocked = False
        try:
            await _run(argparse.Namespace(apply=True), environment)
        except CatalogPromotionReleaseCliError as error:
            guard_blocked = error.code == "release_guard_failed"
        verifier.check(
            "incomplete apply guards fail before mutation",
            guard_blocked
            and await _state(target_scope, TARGET_TENANT_ID, manifest_digest)
            == target_before,
        )

        target_database = make_url(target_url).database or ""
        backup, monitoring = release_guard_phrases(
            target_database,
            TARGET_TENANT_ID,
        )
        apply_environment = {
            **environment,
            APPLY_ENABLED_ENV: "1",
            EXPECTED_TARGET_DATABASE_ENV: target_database,
            BACKUP_CONFIRMATION_ENV: backup,
            MONITORING_CONFIRMATION_ENV: monitoring,
            APPROVAL_PHRASE_ENV: preview.approval_phrase,
            ACTOR_ID_ENV: "epic24-release-verifier",
            REQUEST_ID_ENV: "epic24-release-request",
            IDEMPOTENCY_KEY_ENV: "epic24-release-1",
            REASON_ENV: "Verify guarded cross-database release",
        }
        apply_result = await _run(
            argparse.Namespace(apply=True),
            apply_environment,
        )
        verifier.check("guarded operator apply succeeds", apply_result == 0)

        postflight = await release.preview(
            source_tenant_id=SOURCE_TENANT_ID,
            target_tenant_id=TARGET_TENANT_ID,
        )
        verifier.check(
            "target converges to no changes",
            postflight.preflight.status is CatalogPromotionPreflightStatus.NO_CHANGES,
        )
        target_after = await _state(
            target_scope,
            TARGET_TENANT_ID,
            manifest_digest,
        )
        verifier.check(
            "target contains one linked product and one immutable audit",
            len(target_after.products) == 1
            and target_after.offers[0].canonical_product_id == PRODUCT_ID
            and target_after.actions == 1,
        )
        verifier.check(
            "source database remains unchanged",
            await _state(source_scope, SOURCE_TENANT_ID, manifest_digest)
            == source_before,
        )
        verifier.check(
            "repository-backed public read exposes the promoted product",
            await _public_product_visible(target_sessions),
        )

        replay_result = await _run(
            argparse.Namespace(apply=True),
            apply_environment,
        )
        verifier.check("fresh-engine operator replay succeeds", replay_result == 0)
        verifier.check(
            "replay creates no duplicate state or audit",
            await _state(target_scope, TARGET_TENANT_ID, manifest_digest)
            == target_after,
        )
    finally:
        await source_engine.dispose()
        await target_engine.dispose()

    print()
    print(
        "EPIC 24 catalog release verification passed: "
        f"{len(verifier.passed)}/{len(verifier.passed)} checks."
    )
    print("Mode: two isolated PostgreSQL databases; no production state was used.")
    return 0


def _preview_environment(source_url: str, target_url: str) -> dict[str, str]:
    return {
        SOURCE_DATABASE_URL_ENV: source_url,
        TARGET_DATABASE_URL_ENV: target_url,
        SOURCE_TENANT_ID_ENV: str(SOURCE_TENANT_ID),
        TARGET_TENANT_ID_ENV: str(TARGET_TENANT_ID),
    }


async def _seed(
    source_scope: RepositoryScopeFactory,
    target_scope: RepositoryScopeFactory,
) -> None:
    async with source_scope() as repositories:
        await repositories.tenants.create(
            _tenant(SOURCE_TENANT_ID, "Release source", "release-source")
        )
        await repositories.canonical_products.save(
            CanonicalProduct(
                id=PRODUCT_ID,
                tenant_id=SOURCE_TENANT_ID,
                name="Minecraft",
                category="Games",
                aliases=("minecraft java",),
            )
        )
        await repositories.offers.save(
            SOURCE_TENANT_ID,
            _offer(SOURCE_TENANT_ID, PRODUCT_ID),
        )
        identity = f"{SOURCE_TENANT_ID}:ggsel:release-offer:{PRODUCT_ID}"
        await repositories.canonical_offer_decisions.append(
            CanonicalOfferDecision(
                id=uuid5(NAMESPACE_URL, identity),
                tenant_id=SOURCE_TENANT_ID,
                marketplace="ggsel",
                external_id="release-offer",
                canonical_product_id=PRODUCT_ID,
                decision=CanonicalOfferDecisionType.CONFIRMED,
                actor_id="reviewer",
                actor_type=AdminActorType.USER,
                request_id="release-review-request",
                idempotency_key="release-review-decision",
                request_fingerprint=sha256(identity.encode("utf-8")).hexdigest(),
                created_at=DECIDED_AT,
                reason="Reviewed",
            )
        )
    async with target_scope() as repositories:
        await repositories.tenants.create(
            _tenant(TARGET_TENANT_ID, "Release target", "release-target")
        )
        await repositories.offers.save(
            TARGET_TENANT_ID,
            _offer(TARGET_TENANT_ID, None),
        )


async def _state(
    scope: RepositoryScopeFactory,
    tenant_id: UUID,
    manifest_digest: str,
) -> CatalogState:
    async with scope() as repositories:
        products = tuple(
            await repositories.canonical_products.list_by_tenant(tenant_id)
        )
        offers = tuple(await repositories.offers.list_by_tenant(tenant_id))
        actions = await repositories.admin_actions.list_for_resource(
            AdminResourceType.CATALOG_PROMOTION,
            catalog_promotion_resource_id(
                TARGET_TENANT_ID,
                manifest_digest,
            ),
        )
    return CatalogState(products=products, offers=offers, actions=len(actions))


async def _public_product_visible(
    target_sessions: async_sessionmaker[AsyncSession],
) -> bool:
    scope = create_postgres_public_read_repository_scope(target_sessions)
    async with scope() as repositories:
        detail = await PublicProductReadService(repositories.products).get_product(
            PRODUCT_ID,
            TARGET_TENANT_ID,
        )
    return detail is not None


async def _revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    return str(revision) if revision is not None else None


def _offer(tenant_id: UUID, product_id: UUID | None) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="release-offer",
        title="Minecraft Java",
        url="https://example.test/ggsel/release-offer",
        price=Decimal("790.00"),
        currency="RUB",
        source_category_id="66568",
        source_category_name="Minecraft",
        canonical_product_id=product_id,
    )


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=DECIDED_AT,
        updated_at=DECIDED_AT,
    )


def _require_isolated_database(database_url: str, *, prefix: str) -> None:
    url = make_url(database_url)
    database = url.database or ""
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError("EPIC 24 release verifier requires PostgreSQL.")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("EPIC 24 release verifier requires loopback PostgreSQL.")
    if not database.startswith(prefix):
        raise RuntimeError(f"Verification database must start with {prefix}.")


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
