from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.auth import PasswordCredential
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.queries.provider import ReadRepositoryProvider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
TENANT_A_ID = UUID("3a000000-0000-4000-8000-000000001001")
TENANT_B_ID = UUID("3a000000-0000-4000-8000-000000001002")
PRODUCT_ID = UUID("3a000000-0000-4000-8000-000000002001")
REVIEWER_ID = UUID("3a000000-0000-4000-8000-000000003001")
VIEWER_ID = UUID("3a000000-0000-4000-8000-000000003002")
PASSWORD = "correct horse battery staple"


def test_review_queue_requires_catalog_permission_and_scopes_tenant() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    reviewer = _login_headers(client, "reviewer@example.com")
    viewer = _login_headers(client, "viewer@example.com")

    own = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates",
        headers=reviewer,
    )
    forbidden = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates",
        headers=viewer,
    )
    foreign = client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/review-candidates",
        headers=reviewer,
    )
    anonymous = client.get(f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates")

    assert own.status_code == 200
    assert own.json() == [
        {
            "marketplace": "ggsel",
            "external_id": "offer-1",
            "offer_title": "Minecraft Java Bedrock Windows Premium",
            "offer_url": "https://ggsel.net/catalog/product/offer-1",
            "offer_price": "790.00",
            "currency": "RUB",
            "canonical_product_id": str(PRODUCT_ID),
            "canonical_product_name": "Minecraft Java Bedrock Windows",
            "canonical_product_category": "Games",
            "similarity": 0.8,
            "match_decision": "review",
        }
    ]
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "tenant_not_found"
    assert anonymous.status_code == 401


def test_confirm_links_offer_and_replays_without_duplicate_decision() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    headers = _login_headers(client, "reviewer@example.com")
    headers["Idempotency-Key"] = "confirm-offer-1"
    payload = _review_payload()

    confirmed = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=headers,
        json=payload,
    )
    replay = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=headers,
        json=payload,
    )
    queue = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates",
        headers=headers,
    )
    stored = run_async(provider.offers.get_by_identity(TENANT_A_ID, "ggsel", "offer-1"))
    decisions = run_async(
        provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-1",
        )
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["decision"] == "confirmed"
    assert confirmed.json()["replayed"] is False
    assert confirmed.json()["actor_id"] == str(REVIEWER_ID)
    assert replay.status_code == 200
    assert replay.json()["decision_id"] == confirmed.json()["decision_id"]
    assert replay.json()["replayed"] is True
    assert queue.status_code == 200
    assert queue.json() == []
    assert stored is not None
    assert stored.canonical_product_id == PRODUCT_ID
    assert len(decisions) == 1


def test_reject_filters_pair_and_maps_idempotency_conflict_safely() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    headers = _login_headers(client, "reviewer@example.com")
    headers["Idempotency-Key"] = "reject-offer-1"
    payload = {**_review_payload(), "reason": "Different regional package"}

    rejected = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/reject",
        headers=headers,
        json=payload,
    )
    conflict = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/reviews/confirm",
        headers=headers,
        json=_review_payload(),
    )
    queue = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/review-candidates",
        headers=headers,
    )
    stored = run_async(provider.offers.get_by_identity(TENANT_A_ID, "ggsel", "offer-1"))

    assert rejected.status_code == 200
    assert rejected.json()["decision"] == "rejected"
    assert rejected.json()["reason"] == "Different regional package"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert "fingerprint" not in conflict.text.lower()
    assert queue.status_code == 200
    assert queue.json() == []
    assert stored is not None
    assert stored.canonical_product_id is None


def _seeded_provider() -> RepositoryProvider:
    provider = create_memory_provider()
    run_async(_seed(provider))
    return provider


async def _seed(provider: RepositoryProvider) -> None:
    hasher = PasswordHasher(iterations=100_000)
    for tenant_id, name in (
        (TENANT_A_ID, "Tenant A"),
        (TENANT_B_ID, "Tenant B"),
    ):
        await provider.tenants.create(
            Tenant(
                id=tenant_id,
                name=name,
                slug=name.lower().replace(" ", "-"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    for user_id, email, role in (
        (REVIEWER_ID, "reviewer@example.com", TenantRole.REVIEWER),
        (VIEWER_ID, "viewer@example.com", TenantRole.VIEWER),
    ):
        await provider.users.create(
            User(
                id=user_id,
                email=email,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await provider.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user_id,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await provider.memberships.create(
            Membership(
                id=uuid4(),
                user_id=user_id,
                tenant_id=TENANT_A_ID,
                role=role,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
    await provider.canonical_products.save(
        CanonicalProduct(
            id=PRODUCT_ID,
            tenant_id=TENANT_A_ID,
            name="Minecraft Java Bedrock Windows",
            category="Games",
            aliases=(),
        )
    )
    await provider.offers.save(
        TENANT_A_ID,
        ParsedOffer(
            tenant_id=TENANT_A_ID,
            marketplace="ggsel",
            external_id="offer-1",
            title="Minecraft Java Bedrock Windows Premium",
            url="https://ggsel.net/catalog/product/offer-1",
            price=Decimal("790.00"),
            currency="RUB",
        ),
    )


def _client(provider: RepositoryProvider) -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        from app.repositories.queries.provider import create_memory_read_provider

        yield create_memory_read_provider()

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("admin-secret"),
        ),
        auth_settings=AuthSettings(access_token_secret=SecretStr("auth-secret")),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return TestClient(application, raise_server_exceptions=False)


def _login_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _review_payload() -> dict[str, str]:
    return {
        "marketplace": "ggsel",
        "external_id": "offer-1",
        "canonical_product_id": str(PRODUCT_ID),
    }
