"""Verify the tenant catalog review API against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
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

DATABASE_URL_ENV = "EPIC19_CATALOG_REVIEW_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings, settings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.auth import PasswordCredential
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_postgres_provider
from app.services.canonical_offer_review_queue import CanonicalOfferReviewQueueService
from app.services.passwords import PasswordHasher

TENANT_A_ID = UUID("3b000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("3b000000-0000-4000-8000-000000001002")
PRODUCT_A_ID = UUID("3b000000-0000-4000-8000-000000002001")
PRODUCT_B_ID = UUID("3b000000-0000-4000-8000-000000002002")
REVIEWER_ID = UUID("3b000000-0000-4000-8000-000000003001")
VIEWER_ID = UUID("3b000000-0000-4000-8000-000000003002")
NOW = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class Verification:
    """Collect named PostgreSQL API checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or fail with its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run the isolated catalog review API verification."""
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
        application = create_app(
            admin_api_settings=AdminApiSettings(
                api_enabled=True,
                api_key=SecretStr("catalog-review-admin-key"),
            ),
            auth_settings=AuthSettings(
                access_token_secret=SecretStr("catalog-review-auth-secret"),
                password_hash_iterations=100_000,
            ),
            repository_scope_factory=scope_factory,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://catalog-review.test",
        ) as client:
            proposal_id = await _verify_api(client, verifier)
        await engine.dispose()
        await _verify_fresh_engine(database_url, proposal_id, verifier)
    finally:
        await engine.dispose()
        await default_engine.dispose()

    print(
        "Catalog review API PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_api(
    client: httpx.AsyncClient,
    verifier: Verification,
) -> UUID:
    reviewer = await _login(client, "reviewer@example.com")
    viewer = await _login(client, "viewer@example.com")
    queue_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates"

    anonymous = await client.get(queue_url)
    forbidden = await client.get(queue_url, headers=viewer)
    foreign = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/review-candidates",
        headers=reviewer,
    )
    initial = await client.get(queue_url, headers=reviewer)
    summary_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/onboarding-summary"
    initial_summary = await client.get(summary_url, headers=reviewer)
    initial_workspace = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/onboarding-workspace?limit=100",
        headers=reviewer,
    )
    verifier.check("seller authentication required", anonymous.status_code == 401)
    verifier.check(
        "catalog review permission enforced",
        forbidden.status_code == 403
        and forbidden.json()["error"]["code"] == "permission_denied",
    )
    verifier.check(
        "foreign tenant remains hidden",
        foreign.status_code == 404
        and foreign.json()["error"]["code"] == "tenant_not_found",
    )
    verifier.check(
        "review queue uses existing confidence range",
        initial.status_code == 200
        and len(initial.json()) == 1
        and initial.json()[0]["canonical_product_id"] == str(PRODUCT_A_ID)
        and initial.json()[0]["similarity"] == 0.8
        and initial.json()[0]["match_decision"] == "review",
    )
    summary_payload = initial_summary.json()
    verifier.check(
        "onboarding summary covers the complete tenant catalog",
        initial_summary.status_code == 200
        and summary_payload["total_offers"] == 3
        and summary_payload["linked_offers"] == 0
        and summary_payload["unresolved_offers"] == 3
        and summary_payload["review_candidates"] == 1
        and summary_payload["product_proposals"] == 1
        and summary_payload["canonical_products"] == 2
        and summary_payload["terminal_decisions"] == 0,
    )
    verifier.check(
        "onboarding summary exposes unresolved offers outside review queues",
        summary_payload["unqueued_offers"] == 1
        and [item["marketplace"] for item in summary_payload["marketplaces"]]
        == ["ggsel", "playerok"],
    )
    workspace_payload = initial_workspace.json()
    verifier.check(
        "workspace returns one consistent bounded catalog snapshot",
        initial_workspace.status_code == 200
        and workspace_payload["summary"] == summary_payload
        and len(workspace_payload["review_candidates"]) == 1
        and len(workspace_payload["product_proposals"]) == 1,
    )

    proposal_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/product-proposals"
    proposal_forbidden = await client.get(proposal_url, headers=viewer)
    proposal_foreign = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/product-proposals",
        headers=reviewer,
    )
    proposals = await client.get(proposal_url, headers=reviewer)
    repeated_proposals = await client.get(proposal_url, headers=reviewer)
    verifier.check(
        "product proposals enforce tenant catalog permission",
        proposal_forbidden.status_code == 403 and proposal_foreign.status_code == 404,
    )
    proposal_payload = proposals.json()
    verifier.check(
        "no-match offer produces source-backed product proposal",
        proposals.status_code == 200
        and len(proposal_payload) == 1
        and proposal_payload[0]["external_id"] == "offer-proposal"
        and proposal_payload[0]["proposed_name"] == "Stardew Valley Complete"
        and proposal_payload[0]["proposed_aliases"] == []
        and proposal_payload[0]["nearest_similarity"] == 0.0
        and proposal_payload[0]["match_decision"] == "no_match",
    )
    verifier.check(
        "product proposal identity is deterministic",
        repeated_proposals.status_code == 200
        and repeated_proposals.json() == proposal_payload,
    )
    proposal_id = UUID(proposal_payload[0]["proposal_id"])

    reject_headers = {**reviewer, "Idempotency-Key": "reject-product-a"}
    rejected = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/reject",
        headers=reject_headers,
        json=_payload(PRODUCT_A_ID, reason="Different package"),
    )
    fallback = await client.get(queue_url, headers=reviewer)
    verifier.check(
        "rejection persists terminal evidence",
        rejected.status_code == 200
        and rejected.json()["decision"] == "rejected"
        and rejected.json()["replayed"] is False,
    )
    verifier.check(
        "rejected pair is excluded before rematching",
        fallback.status_code == 200
        and len(fallback.json()) == 1
        and fallback.json()[0]["canonical_product_id"] == str(PRODUCT_B_ID),
    )

    idempotency_conflict = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=reject_headers,
        json=_payload(PRODUCT_B_ID),
    )
    verifier.check(
        "idempotency fingerprint conflict is sanitized",
        idempotency_conflict.status_code == 409
        and idempotency_conflict.json()["error"]["code"] == "idempotency_conflict"
        and "fingerprint" not in idempotency_conflict.text.lower(),
    )

    confirm_headers = {**reviewer, "Idempotency-Key": "confirm-product-b"}
    confirmed = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=confirm_headers,
        json=_payload(PRODUCT_B_ID),
    )
    replay = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=confirm_headers,
        json=_payload(PRODUCT_B_ID),
    )
    empty_queue = await client.get(queue_url, headers=reviewer)
    completed_summary = await client.get(summary_url, headers=reviewer)
    verifier.check(
        "confirmation persists reviewed link",
        confirmed.status_code == 200
        and confirmed.json()["decision"] == "confirmed"
        and confirmed.json()["actor_id"] == str(REVIEWER_ID),
    )
    verifier.check(
        "same command replays one decision",
        replay.status_code == 200
        and replay.json()["replayed"] is True
        and replay.json()["decision_id"] == confirmed.json()["decision_id"],
    )
    verifier.check(
        "linked offer leaves review queue",
        empty_queue.status_code == 200 and empty_queue.json() == [],
    )
    completed_payload = completed_summary.json()
    verifier.check(
        "onboarding summary advances after durable review decisions",
        completed_summary.status_code == 200
        and completed_payload["linked_offers"] == 1
        and completed_payload["unresolved_offers"] == 2
        and completed_payload["review_candidates"] == 0
        and completed_payload["product_proposals"] == 1
        and completed_payload["unqueued_offers"] == 1
        and completed_payload["terminal_decisions"] == 2,
    )
    return proposal_id


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
                User(
                    id=user_id,
                    email=email,
                    created_at=NOW,
                    updated_at=NOW,
                )
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
            _product(PRODUCT_A_ID, "Minecraft Java Bedrock Windows")
        )
        await repositories.canonical_products.save(
            _product(PRODUCT_B_ID, "Minecraft Java Bedrock Premium")
        )
        await repositories.offers.save(
            TENANT_A_ID,
            ParsedOffer(
                tenant_id=TENANT_A_ID,
                marketplace="ggsel",
                external_id="offer-review",
                title="Minecraft Java Bedrock Windows Premium",
                url="https://ggsel.net/catalog/product/offer-review",
                price=Decimal("790.00"),
                currency="RUB",
            ),
        )
        await repositories.offers.save(
            TENANT_A_ID,
            ParsedOffer(
                tenant_id=TENANT_A_ID,
                marketplace="playerok",
                external_id="offer-proposal",
                title="Stardew Valley Complete",
                url="https://playerok.com/products/offer-proposal",
                price=Decimal("499.00"),
                currency="RUB",
            ),
        )
        await repositories.offers.save(
            TENANT_A_ID,
            ParsedOffer(
                tenant_id=TENANT_A_ID,
                marketplace="playerok",
                external_id="offer-auto",
                title="Minecraft Java Bedrock Windows",
                url="https://playerok.com/products/offer-auto",
                price=Decimal("810.00"),
                currency="RUB",
            ),
        )


async def _verify_fresh_engine(
    database_url: str,
    expected_proposal_id: UUID,
    verifier: Verification,
) -> None:
    fresh_engine = create_async_engine(database_url)
    fresh_factory = async_sessionmaker(fresh_engine, expire_on_commit=False)
    try:
        async with fresh_factory() as session:
            repositories = create_postgres_provider(session)
            offer = await repositories.offers.get_by_identity(
                TENANT_A_ID,
                "ggsel",
                "offer-review",
            )
            decisions = await repositories.canonical_offer_decisions.list_for_offer(
                TENANT_A_ID,
                "ggsel",
                "offer-review",
            )
        verifier.check(
            "fresh engine retains canonical link",
            offer is not None and offer.canonical_product_id == PRODUCT_B_ID,
        )
        verifier.check(
            "fresh engine retains immutable decisions",
            len(decisions) == 2
            and {decision.decision for decision in decisions}
            == {
                CanonicalOfferDecisionType.CONFIRMED,
                CanonicalOfferDecisionType.REJECTED,
            },
        )
        queue_service = CanonicalOfferReviewQueueService(
            create_postgres_repository_scope(fresh_factory)
        )
        proposals = await queue_service.list_product_proposals(TENANT_A_ID)
        summary = await queue_service.get_onboarding_summary(TENANT_A_ID)
        verifier.check(
            "fresh engine reproduces stable product proposal",
            len(proposals) == 1
            and proposals[0].proposal_id == expected_proposal_id
            and proposals[0].offer.external_id == "offer-proposal",
        )
        verifier.check(
            "fresh engine reproduces onboarding progress",
            summary.total_offers == 3
            and summary.linked_offers == 1
            and summary.unresolved_offers == 2
            and summary.review_candidates == 0
            and summary.product_proposals == 1
            and summary.unqueued_offers == 1
            and summary.terminal_decisions == 2,
        )
    finally:
        await fresh_engine.dispose()


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    if response.status_code != 200:
        raise AssertionError(f"login failed for {email}: {response.text}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _payload(product_id: UUID, *, reason: str | None = None) -> dict[str, str]:
    payload = {
        "marketplace": "ggsel",
        "external_id": "offer-review",
        "canonical_product_id": str(product_id),
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _product(product_id: UUID, name: str) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=TENANT_A_ID,
        name=name,
        category="Games",
        aliases=(),
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
    if not database_name.startswith("epic19_catalog_review_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic19_catalog_review_* database; got {database_name!r}."
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
