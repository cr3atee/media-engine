"""Verify atomic canonical-product proposal workflows on PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_URL_ENV = "EPIC19_CATALOG_PROPOSAL_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings, settings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.admin_actions import AdminActorType
from app.domain.auth import PasswordCredential
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
)
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.postgres import PostgresCanonicalOfferDecisionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.canonical_offer_linking import (
    MarketplaceOfferUnavailableError,
)
from app.services.canonical_offer_review import (
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
)
from app.services.canonical_offer_review_queue import canonical_product_proposal_id
from app.services.canonical_product_proposals import (
    CanonicalProductProposalConfirmationResult,
    CanonicalProductProposalConflictError,
    CanonicalProductProposalResolutionResult,
    CanonicalProductProposalService,
    ConfirmCanonicalProductProposalCommand,
    ResolveCanonicalProductProposalCommand,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory

TENANT_A_ID = UUID("3d000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("3d000000-0000-4000-8000-000000001002")
EXISTING_PRODUCT_ID = UUID("3d000000-0000-4000-8000-000000002001")
REVIEWER_ID = UUID("3d000000-0000-4000-8000-000000003001")
VIEWER_ID = UUID("3d000000-0000-4000-8000-000000003002")
NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class Verification:
    """Collect named PostgreSQL proposal checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or fail with its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class FailingDecisionRepository(PostgresCanonicalOfferDecisionRepository):
    """Fail after proposal product and offer-link writes."""

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        del decision
        raise RuntimeError("controlled proposal audit failure")


async def main() -> int:
    """Run isolated PostgreSQL proposal confirmation verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    settings.database.url = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    scope_factory = create_postgres_repository_scope(session_factory)
    verifier = Verification()
    try:
        await _seed_data(session_factory)
        await _verify_migration_head(session_factory, verifier)
        application = create_app(
            admin_api_settings=AdminApiSettings(
                api_enabled=True,
                api_key=SecretStr("catalog-proposal-admin-key"),
            ),
            auth_settings=AuthSettings(
                access_token_secret=SecretStr("catalog-proposal-auth-secret"),
                password_hash_iterations=100_000,
            ),
            repository_scope_factory=scope_factory,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://catalog-proposal.test",
        ) as client:
            api_proposal_id = await _verify_api(client, session_factory, verifier)
        concurrent_id = await _verify_concurrency(
            scope_factory, session_factory, verifier
        )
        await _verify_resolution_rollback(session_factory, verifier)
        await _verify_cross_command_concurrency(
            scope_factory,
            session_factory,
            verifier,
        )
        await _verify_rollback(session_factory, verifier)
        await _verify_tenant_isolation(scope_factory, session_factory, verifier)
        await engine.dispose()
        await _verify_fresh_engine(
            database_url,
            api_proposal_id,
            concurrent_id,
            verifier,
        )
    finally:
        await engine.dispose()
        await default_engine.dispose()

    print(
        "Canonical product proposal PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_migration_head(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    async with session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    verifier.check(
        "existing migration head remains 0016",
        revision == "0016_canonical_offer_decisions",
    )


async def _verify_api(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> UUID:
    reviewer = await _login(client, "reviewer@example.com")
    viewer = await _login(client, "viewer@example.com")
    proposals_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/product-proposals"

    forbidden = await client.get(proposals_url, headers=viewer)
    foreign = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/product-proposals",
        headers=reviewer,
    )
    proposals = await client.get(proposals_url, headers=reviewer)
    payloads = proposals.json()
    verifier.check(
        "proposal API enforces tenant catalog permission",
        forbidden.status_code == 403 and foreign.status_code == 404,
    )
    api_proposal = next(
        payload for payload in payloads if payload["external_id"] == "offer-api"
    )
    resolution_proposal = next(
        payload for payload in payloads if payload["external_id"] == "offer-resolve"
    )
    verifier.check(
        "proposal API exposes only current no-match offers",
        proposals.status_code == 200
        and {payload["external_id"] for payload in payloads}
        == {"offer-api", "offer-concurrent", "offer-resolve", "offer-rollback"}
        and api_proposal["proposed_name"] == "Stardew Valley Complete",
    )

    proposal_id = UUID(api_proposal["proposal_id"])
    confirm_url = f"{proposals_url}/{proposal_id}/confirm"
    command_payload = {
        "marketplace": "ggsel",
        "external_id": "offer-api",
        "reason": "Verified source product",
    }
    headers = {**reviewer, "Idempotency-Key": "proposal-api-confirm"}
    confirmed = await client.post(confirm_url, headers=headers, json=command_payload)
    replayed = await client.post(confirm_url, headers=headers, json=command_payload)
    fingerprint_conflict = await client.post(
        confirm_url,
        headers=headers,
        json={**command_payload, "reason": "Different semantics"},
    )
    verifier.check(
        "proposal confirmation returns created canonical identity",
        confirmed.status_code == 200
        and confirmed.json()["canonical_product_id"] == str(proposal_id)
        and confirmed.json()["canonical_product_name"] == "Stardew Valley Complete"
        and confirmed.json()["canonical_product_aliases"] == []
        and confirmed.json()["decision"] == "confirmed"
        and confirmed.json()["replayed"] is False,
    )
    verifier.check(
        "proposal confirmation replays idempotently",
        replayed.status_code == 200
        and replayed.json()["decision_id"] == confirmed.json()["decision_id"]
        and replayed.json()["replayed"] is True,
    )
    verifier.check(
        "proposal idempotency conflict is sanitized",
        fingerprint_conflict.status_code == 409
        and fingerprint_conflict.json()["error"]["code"] == "idempotency_conflict"
        and "fingerprint" not in fingerprint_conflict.text.lower(),
    )

    stale_id = UUID("3d000000-0000-4000-8000-000000009999")
    stale = await client.post(
        f"{proposals_url}/{stale_id}/confirm",
        headers={**reviewer, "Idempotency-Key": "proposal-stale"},
        json={
            "marketplace": "ggsel",
            "external_id": "offer-rollback",
        },
    )
    auto_offer = _offer("offer-auto", "Minecraft Java Bedrock Windows")
    auto_id = canonical_product_proposal_id(TENANT_A_ID, auto_offer)
    auto_match = await client.post(
        f"{proposals_url}/{auto_id}/confirm",
        headers={**reviewer, "Idempotency-Key": "proposal-auto-match"},
        json={"marketplace": "ggsel", "external_id": "offer-auto"},
    )
    verifier.check(
        "stale and non-no-match proposals fail without mutation",
        stale.status_code == 409
        and stale.json()["error"]["code"] == "canonical_product_proposal_stale"
        and auto_match.status_code == 409
        and auto_match.json()["error"]["code"] == "canonical_product_proposal_stale",
    )

    remaining = await client.get(proposals_url, headers=reviewer)
    verifier.check(
        "confirmed source leaves proposal queue",
        remaining.status_code == 200
        and {payload["external_id"] for payload in remaining.json()}
        == {"offer-concurrent", "offer-resolve", "offer-rollback"},
    )

    resolution_id = UUID(resolution_proposal["proposal_id"])
    resolution_url = f"{proposals_url}/{resolution_id}/resolve-existing"
    resolution_payload = {
        "marketplace": "ggsel",
        "external_id": "offer-resolve",
        "canonical_product_id": str(EXISTING_PRODUCT_ID),
        "reason": "Reviewer verified the existing catalog identity",
    }
    missing_evidence = await client.post(
        resolution_url,
        headers={**reviewer, "Idempotency-Key": "resolution-missing-evidence"},
        json={**resolution_payload, "reason": "  "},
    )
    wrong_target = await client.post(
        resolution_url,
        headers={**reviewer, "Idempotency-Key": "resolution-wrong-target"},
        json={**resolution_payload, "canonical_product_id": str(proposal_id)},
    )
    resolution_headers = {
        **reviewer,
        "Idempotency-Key": "proposal-resolve-existing",
    }
    resolved = await client.post(
        resolution_url,
        headers=resolution_headers,
        json=resolution_payload,
    )
    resolution_replay = await client.post(
        resolution_url,
        headers=resolution_headers,
        json=resolution_payload,
    )
    resolution_fingerprint_conflict = await client.post(
        resolution_url,
        headers=resolution_headers,
        json={**resolution_payload, "reason": "Different resolution evidence"},
    )
    verifier.check(
        "existing-product resolution requires evidence and current nearest target",
        missing_evidence.status_code == 422
        and wrong_target.status_code == 409
        and wrong_target.json()["error"]["code"] == "canonical_product_proposal_stale",
    )
    verifier.check(
        "existing-product resolution returns current canonical identity",
        resolved.status_code == 200
        and resolved.json()["proposal_id"] == str(resolution_id)
        and resolved.json()["canonical_product_id"] == str(EXISTING_PRODUCT_ID)
        and resolved.json()["decision"] == "confirmed"
        and resolved.json()["replayed"] is False,
    )
    verifier.check(
        "existing-product resolution replays and rejects fingerprint reuse",
        resolution_replay.status_code == 200
        and resolution_replay.json()["decision_id"] == resolved.json()["decision_id"]
        and resolution_replay.json()["replayed"] is True
        and resolution_fingerprint_conflict.status_code == 409
        and resolution_fingerprint_conflict.json()["error"]["code"]
        == "idempotency_conflict",
    )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        product = await repositories.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            proposal_id,
        )
        offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-api",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-api",
        )
        stale_product = await repositories.canonical_products.get_by_id(stale_id)
        auto_product = await repositories.canonical_products.get_by_id(auto_id)
        resolution_product = await repositories.canonical_products.get_by_id(
            resolution_id
        )
        resolution_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-resolve",
        )
        resolution_decisions = (
            await repositories.canonical_offer_decisions.list_for_offer(
                TENANT_A_ID,
                "ggsel",
                "offer-resolve",
            )
        )
    verifier.check(
        "confirmation atomically persists product link and audit",
        product is not None
        and product.name == "Stardew Valley Complete"
        and product.aliases == ()
        and offer is not None
        and offer.canonical_product_id == proposal_id
        and len(decisions) == 1
        and decisions[0].canonical_product_id == proposal_id,
    )
    verifier.check(
        "rejected proposal commands leave no product rows",
        stale_product is None and auto_product is None,
    )
    verifier.check(
        "existing-product resolution avoids duplicate catalog product",
        resolution_product is None
        and resolution_offer is not None
        and resolution_offer.canonical_product_id == EXISTING_PRODUCT_ID
        and len(resolution_decisions) == 1
        and resolution_decisions[0].canonical_product_id == EXISTING_PRODUCT_ID,
    )
    return proposal_id


async def _verify_concurrency(
    scope_factory: RepositoryScopeFactory,
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> UUID:
    offer = _offer("offer-concurrent", "Hades Complete")
    proposal_id = canonical_product_proposal_id(TENANT_A_ID, offer)
    command_value = ConfirmCanonicalProductProposalCommand(
        tenant_id=TENANT_A_ID,
        proposal_id=proposal_id,
        marketplace="ggsel",
        external_id="offer-concurrent",
    )
    results = await asyncio.gather(
        CanonicalProductProposalService(scope_factory).confirm(
            command_value,
            _context("concurrent-a"),
        ),
        CanonicalProductProposalService(scope_factory).confirm(
            command_value,
            _context("concurrent-b"),
        ),
        return_exceptions=True,
    )
    accepted = [
        result
        for result in results
        if isinstance(result, CanonicalProductProposalConfirmationResult)
    ]
    conflicts = [
        result
        for result in results
        if isinstance(result, CanonicalOfferDecisionConflictError)
    ]
    verifier.check(
        "concurrent proposal commands serialize",
        len(accepted) == 1 and len(conflicts) == 1,
    )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        product = await repositories.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            proposal_id,
        )
        stored_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-concurrent",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-concurrent",
        )
    verifier.check(
        "concurrency creates one product link and decision",
        product is not None
        and stored_offer is not None
        and stored_offer.canonical_product_id == proposal_id
        and len(decisions) == 1,
    )
    return proposal_id


async def _verify_rollback(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    offer = _offer("offer-rollback", "Terraria Complete")
    proposal_id = canonical_product_proposal_id(TENANT_A_ID, offer)
    try:
        await CanonicalProductProposalService(_failing_scope(session_factory)).confirm(
            ConfirmCanonicalProductProposalCommand(
                tenant_id=TENANT_A_ID,
                proposal_id=proposal_id,
                marketplace="ggsel",
                external_id="offer-rollback",
            ),
            _context("rollback"),
        )
    except RuntimeError as exc:
        verifier.check(
            "controlled proposal audit failure surfaces",
            "controlled proposal audit" in str(exc),
        )
    else:
        raise AssertionError("controlled proposal audit failure did not raise")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        product = await repositories.canonical_products.get_by_id(proposal_id)
        stored_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-rollback",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-rollback",
        )
    verifier.check(
        "failed audit rolls back product link and decision",
        product is None
        and stored_offer is not None
        and stored_offer.canonical_product_id is None
        and decisions == (),
    )


async def _verify_resolution_rollback(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    offer = _offer("offer-resolution-rollback", "Minecraft Dungeons Legacy")
    async with session_factory() as session, session.begin():
        await create_postgres_provider(session).offers.save(TENANT_A_ID, offer)
    proposal_id = canonical_product_proposal_id(TENANT_A_ID, offer)

    try:
        await CanonicalProductProposalService(
            _failing_scope(session_factory)
        ).resolve_existing(
            ResolveCanonicalProductProposalCommand(
                tenant_id=TENANT_A_ID,
                proposal_id=proposal_id,
                marketplace="ggsel",
                external_id="offer-resolution-rollback",
                canonical_product_id=EXISTING_PRODUCT_ID,
                reason="Controlled rollback evidence",
            ),
            _context("resolution-rollback"),
        )
    except RuntimeError as exc:
        verifier.check(
            "controlled existing-product resolution failure surfaces",
            "controlled proposal audit" in str(exc),
        )
    else:
        raise AssertionError("controlled proposal resolution failure did not raise")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stored_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-resolution-rollback",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-resolution-rollback",
        )
    verifier.check(
        "failed existing-product audit rolls back link and decision",
        stored_offer is not None
        and stored_offer.canonical_product_id is None
        and decisions == (),
    )


async def _verify_cross_command_concurrency(
    scope_factory: RepositoryScopeFactory,
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    offer = _offer("offer-cross-command", "Minecraft Story Mode Legacy")
    async with session_factory() as session, session.begin():
        await create_postgres_provider(session).offers.save(TENANT_A_ID, offer)
    proposal_id = canonical_product_proposal_id(TENANT_A_ID, offer)

    results = await asyncio.gather(
        CanonicalProductProposalService(scope_factory).confirm(
            ConfirmCanonicalProductProposalCommand(
                tenant_id=TENANT_A_ID,
                proposal_id=proposal_id,
                marketplace="ggsel",
                external_id="offer-cross-command",
            ),
            _context("cross-proposal"),
        ),
        CanonicalProductProposalService(scope_factory).resolve_existing(
            ResolveCanonicalProductProposalCommand(
                tenant_id=TENANT_A_ID,
                proposal_id=proposal_id,
                marketplace="ggsel",
                external_id="offer-cross-command",
                canonical_product_id=EXISTING_PRODUCT_ID,
                reason="Existing product selected",
            ),
            _context("cross-existing"),
        ),
        return_exceptions=True,
    )
    accepted = [
        result
        for result in results
        if isinstance(
            result,
            (
                CanonicalProductProposalConfirmationResult,
                CanonicalProductProposalResolutionResult,
            ),
        )
    ]
    conflicts = [
        result
        for result in results
        if isinstance(
            result,
            CanonicalProductProposalConflictError,
        )
    ]
    verifier.check(
        "create-new and resolve-existing commands share one offer lock",
        len(accepted) == 1 and len(conflicts) == 1,
    )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stored_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-cross-command",
        )
        proposal_product = await repositories.canonical_products.get_by_id(proposal_id)
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-cross-command",
        )
    verifier.check(
        "cross-command race leaves one link product and decision",
        stored_offer is not None
        and stored_offer.canonical_product_id in {EXISTING_PRODUCT_ID, proposal_id}
        and len(decisions) == 1
        and decisions[0].canonical_product_id == stored_offer.canonical_product_id
        and (
            proposal_product is not None
            if stored_offer.canonical_product_id == proposal_id
            else proposal_product is None
        ),
    )


async def _verify_tenant_isolation(
    scope_factory: RepositoryScopeFactory,
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    foreign_identity = canonical_product_proposal_id(
        TENANT_B_ID,
        _offer("offer-api", "Stardew Valley Complete", tenant_id=TENANT_B_ID),
    )
    try:
        await CanonicalProductProposalService(scope_factory).confirm(
            ConfirmCanonicalProductProposalCommand(
                tenant_id=TENANT_B_ID,
                proposal_id=foreign_identity,
                marketplace="ggsel",
                external_id="offer-api",
            ),
            _context("tenant-isolation"),
        )
    except MarketplaceOfferUnavailableError:
        verifier.check("proposal confirmation hides cross-tenant offer", True)
    else:
        raise AssertionError("proposal confirmation crossed tenant boundary")

    try:
        await CanonicalProductProposalService(scope_factory).resolve_existing(
            ResolveCanonicalProductProposalCommand(
                tenant_id=TENANT_B_ID,
                proposal_id=foreign_identity,
                marketplace="ggsel",
                external_id="offer-api",
                canonical_product_id=EXISTING_PRODUCT_ID,
                reason="Must remain tenant isolated",
            ),
            _context("resolution-tenant-isolation"),
        )
    except MarketplaceOfferUnavailableError:
        verifier.check("proposal resolution hides cross-tenant offer", True)
    else:
        raise AssertionError("proposal resolution crossed tenant boundary")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        product = await repositories.canonical_products.get_by_id(foreign_identity)
    verifier.check("tenant isolation leaves no foreign product", product is None)


async def _verify_fresh_engine(
    database_url: str,
    api_proposal_id: UUID,
    concurrent_proposal_id: UUID,
    verifier: Verification,
) -> None:
    fresh_engine = create_async_engine(database_url)
    fresh_factory = async_sessionmaker(fresh_engine, expire_on_commit=False)
    try:
        async with fresh_factory() as session:
            repositories = create_postgres_provider(session)
            api_product = await repositories.canonical_products.get_by_tenant_and_id(
                TENANT_A_ID,
                api_proposal_id,
            )
            concurrent_product = (
                await repositories.canonical_products.get_by_tenant_and_id(
                    TENANT_A_ID,
                    concurrent_proposal_id,
                )
            )
            api_offer = await repositories.offers.get_by_identity(
                TENANT_A_ID,
                "ggsel",
                "offer-api",
            )
            api_decisions = await repositories.canonical_offer_decisions.list_for_offer(
                TENANT_A_ID,
                "ggsel",
                "offer-api",
            )
            resolved_offer = await repositories.offers.get_by_identity(
                TENANT_A_ID,
                "ggsel",
                "offer-resolve",
            )
            resolved_decisions = (
                await repositories.canonical_offer_decisions.list_for_offer(
                    TENANT_A_ID,
                    "ggsel",
                    "offer-resolve",
                )
            )
        verifier.check(
            "fresh engine retains confirmed proposal lifecycle",
            api_product is not None
            and concurrent_product is not None
            and api_offer is not None
            and api_offer.canonical_product_id == api_proposal_id
            and len(api_decisions) == 1,
        )
        verifier.check(
            "fresh engine retains existing-product proposal resolution",
            resolved_offer is not None
            and resolved_offer.canonical_product_id == EXISTING_PRODUCT_ID
            and len(resolved_decisions) == 1
            and resolved_decisions[0].canonical_product_id == EXISTING_PRODUCT_ID,
        )
    finally:
        await fresh_engine.dispose()


async def _seed_data(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    hasher = PasswordHasher(iterations=100_000)
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.tenants.create(_tenant(TENANT_A_ID, "Tenant A", "tenant-a"))
        await repositories.tenants.create(_tenant(TENANT_B_ID, "Tenant B", "tenant-b"))
        for user_id, email, role in (
            (REVIEWER_ID, "reviewer@example.com", TenantRole.REVIEWER),
            (VIEWER_ID, "viewer@example.com", TenantRole.VIEWER),
        ):
            await repositories.users.create(
                User(id=user_id, email=email, created_at=NOW, updated_at=NOW)
            )
            await repositories.password_credentials.set_for_user(
                PasswordCredential(
                    user_id=user_id,
                    password_hash=hasher.hash_password(PASSWORD),
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await repositories.memberships.create(
                Membership(
                    id=uuid4(),
                    user_id=user_id,
                    tenant_id=TENANT_A_ID,
                    role=role,
                    joined_at=NOW,
                    updated_at=NOW,
                )
            )
        await repositories.canonical_products.save(
            CanonicalProduct(
                id=EXISTING_PRODUCT_ID,
                tenant_id=TENANT_A_ID,
                name="Minecraft Java Bedrock Windows",
                category="Games",
                aliases=(),
            )
        )
        for offer in (
            _offer("offer-api", "Stardew Valley Complete"),
            _offer("offer-concurrent", "Hades Complete"),
            _offer("offer-resolve", "Minecraft Dungeons Legacy"),
            _offer("offer-rollback", "Terraria Complete"),
            _offer("offer-auto", "Minecraft Java Bedrock Windows"),
        ):
            await repositories.offers.save(TENANT_A_ID, offer)


def _failing_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.canonical_offer_decisions = FailingDecisionRepository(session)
            yield provider

    return scope


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    if response.status_code != 200:
        raise AssertionError(f"login failed for {email}: {response.text}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _context(idempotency_key: str) -> CanonicalOfferReviewContext:
    return CanonicalOfferReviewContext(
        actor_id="postgres-reviewer",
        actor_type=AdminActorType.USER,
        request_id=f"request-{idempotency_key}",
        idempotency_key=idempotency_key,
    )


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _offer(
    external_id: str,
    title: str,
    *,
    tenant_id: UUID = TENANT_A_ID,
) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        title=title,
        url=f"https://ggsel.net/catalog/product/{external_id}",
        price=Decimal("499.00"),
        currency="RUB",
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
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if not database_name.startswith("epic19_catalog_proposal_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic19_catalog_proposal_* database; got {database_name!r}."
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
