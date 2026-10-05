"""Verify saved real-offer catalog onboarding against isolated PostgreSQL."""

# ruff: noqa: E402, I001

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC19_CATALOG_ONBOARDING_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.auth import PasswordCredential
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.parsers.models import ParsedOffer
from app.services.canonical_offer_review_queue import (
    CanonicalOfferReviewQueueService,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory
from scripts.verify_marketplace_data_readiness import load_saved_marketplace_offers
from scripts.verify_marketplace_payload_contracts import (
    collect_readiness,
    validate_readiness,
)

TENANT_ID = UUID("44000000-0000-4000-8000-000000000001")
FOREIGN_TENANT_ID = UUID("44000000-0000-4000-8000-000000000002")
ROLLBACK_TENANT_ID = UUID("44000000-0000-4000-8000-000000000003")
USER_ID = UUID("44000000-0000-4000-8000-000000000004")
MEMBERSHIP_ID = UUID("44000000-0000-4000-8000-000000000005")
NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
EMAIL = "catalog-onboarding@example.com"
PASSWORD = "catalog onboarding verification"


@dataclass(slots=True, frozen=True)
class CatalogOnboardingDataset:
    """Tenant-scoped source offers prepared without catalog decisions."""

    offers: tuple[ParsedOffer, ...]
    counts: tuple[tuple[str, int], ...]


class Verification:
    """Collect named PostgreSQL onboarding checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or fail with its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class _ExpectedRollback(Exception):
    pass


async def main() -> int:
    """Run production-shaped onboarding verification on isolated PostgreSQL."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    readiness = collect_readiness()
    violations = validate_readiness(readiness)
    if violations:
        raise AssertionError("; ".join(violations))
    dataset = _load_dataset()
    verifier = Verification()
    verifier.check("saved marketplace payload contracts are ready", not violations)

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    try:
        async with engine.connect() as connection:
            migration = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        verifier.check(
            "current Alembic head is applied",
            migration == _migration_head(),
        )
        await _seed_identity_and_offers(scope_factory, dataset.offers)
        await _save_offers(scope_factory, dataset.offers)
        await _verify_repository_state(scope_factory, dataset, verifier)
        proposal_ids = await _verify_application(scope_factory, dataset, verifier)
        await _verify_rollback(scope_factory, dataset.offers[0], verifier)
        await engine.dispose()
        await _verify_fresh_engine(database_url, dataset, proposal_ids, verifier)
    finally:
        await engine.dispose()
        await default_engine.dispose()

    counts = ", ".join(
        f"{marketplace}={count}" for marketplace, count in dataset.counts
    )
    print()
    print(f"Saved offers: {counts}")
    print(
        "Catalog onboarding PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


def _load_dataset() -> CatalogOnboardingDataset:
    loaded = load_saved_marketplace_offers()
    seen: set[tuple[str, str]] = set()
    offers: list[ParsedOffer] = []
    counts: list[tuple[str, int]] = []
    for marketplace in ("ggsel", "playerok", "funpay"):
        marketplace_count = 0
        for offer in loaded.get(marketplace, ()):
            normalized_marketplace = offer.marketplace.strip().lower()
            external_id = (offer.external_id or "").strip()
            title = (offer.title or "").strip()
            if not normalized_marketplace or not external_id or not title:
                continue
            identity = (normalized_marketplace, external_id)
            if identity in seen:
                continue
            seen.add(identity)
            offers.append(
                replace(
                    offer,
                    tenant_id=TENANT_ID,
                    marketplace=normalized_marketplace,
                    external_id=external_id,
                    title=title,
                    canonical_product_id=None,
                )
            )
            marketplace_count += 1
        counts.append((marketplace, marketplace_count))
    if not offers or any(count == 0 for _, count in counts):
        raise RuntimeError("Every saved marketplace payload must provide offers.")
    return CatalogOnboardingDataset(offers=tuple(offers), counts=tuple(counts))


async def _seed_identity_and_offers(
    scope_factory: RepositoryScopeFactory,
    offers: tuple[ParsedOffer, ...],
) -> None:
    hasher = PasswordHasher(iterations=100_000)
    async with scope_factory() as repositories:
        await repositories.tenants.create(
            _tenant(TENANT_ID, "Catalog Onboarding", "catalog-onboarding")
        )
        await repositories.tenants.create(
            _tenant(FOREIGN_TENANT_ID, "Foreign Tenant", "foreign-onboarding")
        )
        await repositories.users.create(
            User(
                id=USER_ID,
                email=EMAIL,
                display_name="Catalog Reviewer",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.password_credentials.set_for_user(
            PasswordCredential(
                user_id=USER_ID,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.memberships.create(
            Membership(
                id=MEMBERSHIP_ID,
                user_id=USER_ID,
                tenant_id=TENANT_ID,
                role=TenantRole.REVIEWER,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
        for offer in offers:
            await repositories.offers.save(TENANT_ID, offer)


async def _save_offers(
    scope_factory: RepositoryScopeFactory,
    offers: tuple[ParsedOffer, ...],
) -> None:
    async with scope_factory() as repositories:
        for offer in offers:
            await repositories.offers.save(TENANT_ID, offer)


async def _verify_repository_state(
    scope_factory: RepositoryScopeFactory,
    dataset: CatalogOnboardingDataset,
    verifier: Verification,
) -> None:
    async with scope_factory() as repositories:
        offers = tuple(await repositories.offers.list_by_tenant(TENANT_ID))
        foreign_offers = await repositories.offers.list_by_tenant(FOREIGN_TENANT_ID)
        products = await repositories.canonical_products.list_by_tenant(TENANT_ID)
        decisions = await repositories.canonical_offer_decisions.list_by_tenant(
            TENANT_ID
        )
    identities = {(offer.marketplace, offer.external_id) for offer in offers}
    expected_counts = dict(dataset.counts)
    actual_counts = Counter(offer.marketplace for offer in offers)
    verifier.check(
        "all saved offers are committed once", len(offers) == len(dataset.offers)
    )
    verifier.check(
        "offer identities remain unique after replay", len(identities) == len(offers)
    )
    verifier.check(
        "marketplace source counts are preserved", actual_counts == expected_counts
    )
    verifier.check("foreign tenant receives no offers", not foreign_offers)
    verifier.check("onboarding creates no canonical products", not products)
    verifier.check(
        "onboarding creates no links or review decisions",
        not decisions and all(offer.canonical_product_id is None for offer in offers),
    )


async def _verify_application(
    scope_factory: RepositoryScopeFactory,
    dataset: CatalogOnboardingDataset,
    verifier: Verification,
) -> set[str]:
    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=False,
            api_docs_enabled=False,
        ),
        auth_settings=AuthSettings(
            access_token_secret=SecretStr("catalog-onboarding-auth-secret"),
            password_hash_iterations=100_000,
        ),
        public_read_repository_scope_factory=None,
        repository_scope_factory=scope_factory,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://catalog-onboarding.test",
    ) as client:
        document = await client.get("/terminal/review")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
        )
        verifier.check(
            "review workspace and seller login are available",
            document.status_code == 200 and login.status_code == 200,
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        context = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/context",
            headers=headers,
        )
        candidates = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/review-candidates?limit=200",
            headers=headers,
        )
        proposals = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/product-proposals?limit=200",
            headers=headers,
        )
        repeated = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/product-proposals?limit=200",
            headers=headers,
        )
        foreign = await client.get(
            f"/api/v1/tenants/{FOREIGN_TENANT_ID}/catalog/product-proposals",
            headers=headers,
        )

    proposal_payload = proposals.json()
    verifier.check(
        "reviewer resolves explicit tenant context",
        context.status_code == 200
        and "catalog_review" in context.json()["permissions"],
    )
    verifier.check(
        "saved offers do not fabricate review candidates",
        candidates.status_code == 200 and candidates.json() == [],
    )
    verifier.check(
        "every saved offer becomes one source-backed proposal",
        proposals.status_code == 200 and len(proposal_payload) == len(dataset.offers),
    )
    verifier.check(
        "proposal payloads remain unresolved and source-backed",
        all(
            item["match_decision"] == "no_match"
            and item["nearest_canonical_product_id"] is None
            and item["external_id"]
            and item["offer_title"]
            for item in proposal_payload
        ),
    )
    verifier.check(
        "proposal projection is deterministic",
        repeated.status_code == 200 and repeated.json() == proposal_payload,
    )
    verifier.check(
        "seller cannot read a foreign tenant queue",
        foreign.status_code == 404
        and foreign.json()["error"]["code"] == "tenant_not_found",
    )
    proposal_ids = {item["proposal_id"] for item in proposal_payload}
    verifier.check(
        "proposal identities are unique",
        len(proposal_ids) == len(dataset.offers),
    )
    return proposal_ids


async def _verify_rollback(
    scope_factory: RepositoryScopeFactory,
    sample: ParsedOffer,
    verifier: Verification,
) -> None:
    try:
        async with scope_factory() as repositories:
            await repositories.tenants.create(
                _tenant(
                    ROLLBACK_TENANT_ID,
                    "Rollback Tenant",
                    "rollback-onboarding",
                )
            )
            await repositories.offers.save(
                ROLLBACK_TENANT_ID,
                replace(
                    sample,
                    tenant_id=ROLLBACK_TENANT_ID,
                    external_id="rollback-offer",
                ),
            )
            raise _ExpectedRollback
    except _ExpectedRollback:
        pass

    async with scope_factory() as repositories:
        tenant = await repositories.tenants.get_by_id(ROLLBACK_TENANT_ID)
        offers = await repositories.offers.list_by_tenant(ROLLBACK_TENANT_ID)
    verifier.check(
        "failed onboarding transaction rolls back atomically",
        tenant is None and not offers,
    )


async def _verify_fresh_engine(
    database_url: str,
    dataset: CatalogOnboardingDataset,
    expected_proposal_ids: set[str],
    verifier: Verification,
) -> None:
    fresh_engine = create_async_engine(database_url)
    fresh_factory = async_sessionmaker(fresh_engine, expire_on_commit=False)
    fresh_scope = create_postgres_repository_scope(fresh_factory)
    try:
        async with fresh_scope() as repositories:
            offers = await repositories.offers.list_by_tenant(TENANT_ID)
            products = await repositories.canonical_products.list_by_tenant(TENANT_ID)
            decisions = await repositories.canonical_offer_decisions.list_by_tenant(
                TENANT_ID
            )
        proposals = await CanonicalOfferReviewQueueService(
            fresh_scope
        ).list_product_proposals(TENANT_ID)
        verifier.check(
            "fresh engine retains all tenant offers",
            len(offers) == len(dataset.offers),
        )
        verifier.check(
            "fresh engine retains an unmodified catalog boundary",
            not products and not decisions,
        )
        verifier.check(
            "fresh engine reproduces stable proposal identities",
            {str(proposal.proposal_id) for proposal in proposals}
            == expected_proposal_ids,
        )
    finally:
        await fresh_engine.dispose()


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
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
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if not database_name.startswith("epic19_catalog_onboarding_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic19_catalog_onboarding_* database; got {database_name!r}."
        )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
