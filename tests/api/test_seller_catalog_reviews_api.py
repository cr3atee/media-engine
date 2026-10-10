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


def test_onboarding_summary_is_complete_and_permission_scoped() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    reviewer = _login_headers(client, "reviewer@example.com")
    viewer = _login_headers(client, "viewer@example.com")
    url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/onboarding-summary"

    own = client.get(url, headers=reviewer)
    workspace = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/catalog/onboarding-workspace?limit=100",
        headers=reviewer,
    )
    forbidden = client.get(url, headers=viewer)
    foreign = client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/onboarding-summary",
        headers=reviewer,
    )
    anonymous = client.get(url)

    assert own.status_code == 200
    assert own.json() == {
        "total_offers": 2,
        "linked_offers": 0,
        "unresolved_offers": 2,
        "review_candidates": 1,
        "product_proposals": 1,
        "unqueued_offers": 0,
        "canonical_products": 1,
        "terminal_decisions": 0,
        "marketplaces": [
            {
                "marketplace": "ggsel",
                "total_offers": 1,
                "linked_offers": 0,
                "unresolved_offers": 1,
                "review_candidates": 1,
                "product_proposals": 0,
                "unqueued_offers": 0,
            },
            {
                "marketplace": "playerok",
                "total_offers": 1,
                "linked_offers": 0,
                "unresolved_offers": 1,
                "review_candidates": 0,
                "product_proposals": 1,
                "unqueued_offers": 0,
            },
        ],
    }
    assert workspace.status_code == 200
    assert workspace.json()["summary"] == own.json()
    assert len(workspace.json()["review_candidates"]) == 1
    assert len(workspace.json()["product_proposals"]) == 1
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "tenant_not_found"
    assert anonymous.status_code == 401


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


def test_product_proposals_are_stable_and_permission_scoped() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    reviewer = _login_headers(client, "reviewer@example.com")
    viewer = _login_headers(client, "viewer@example.com")
    url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/product-proposals"

    first = client.get(url, headers=reviewer)
    repeated = client.get(url, headers=reviewer)
    limited = client.get(f"{url}?limit=1", headers=reviewer)
    invalid_limit = client.get(f"{url}?limit=0", headers=reviewer)
    forbidden = client.get(url, headers=viewer)
    foreign = client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/catalog/product-proposals",
        headers=reviewer,
    )

    assert first.status_code == 200
    assert first.json() == repeated.json()
    assert first.json() == limited.json()
    assert len(first.json()) == 1
    proposal = first.json()[0]
    assert proposal["marketplace"] == "playerok"
    assert proposal["external_id"] == "offer-proposal"
    assert proposal["offer_title"] == "Stardew Valley Complete"
    assert proposal["proposed_name"] == "Stardew Valley Complete"
    assert proposal["proposed_aliases"] == []
    assert proposal["nearest_canonical_product_id"] == str(PRODUCT_ID)
    assert proposal["nearest_similarity"] == 0.0
    assert proposal["match_decision"] == "no_match"
    assert invalid_limit.status_code == 422
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "tenant_not_found"


def test_product_proposal_confirmation_is_atomic_audited_and_idempotent() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    reviewer = _login_headers(client, "reviewer@example.com")
    viewer = _login_headers(client, "viewer@example.com")
    proposals_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/product-proposals"
    proposal = client.get(proposals_url, headers=reviewer).json()[0]
    confirm_url = f"{proposals_url}/{proposal['proposal_id']}/confirm"
    payload = {
        "marketplace": "playerok",
        "external_id": "offer-proposal",
        "reason": "Verified source product",
    }

    forbidden = client.post(
        confirm_url,
        headers={**viewer, "Idempotency-Key": "forbidden-confirm"},
        json=payload,
    )
    foreign = client.post(
        confirm_url.replace(str(TENANT_A_ID), str(TENANT_B_ID)),
        headers={**reviewer, "Idempotency-Key": "foreign-confirm"},
        json=payload,
    )
    headers = {**reviewer, "Idempotency-Key": "confirm-product-proposal"}
    confirmed = client.post(confirm_url, headers=headers, json=payload)
    replayed = client.post(confirm_url, headers=headers, json=payload)
    conflict = client.post(
        confirm_url,
        headers=headers,
        json={**payload, "reason": "Different semantics"},
    )
    empty_queue = client.get(proposals_url, headers=reviewer)

    result = confirmed.json()
    stored_product = run_async(
        provider.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            UUID(proposal["proposal_id"]),
        )
    )
    stored_offer = run_async(
        provider.offers.get_by_identity(
            TENANT_A_ID,
            "playerok",
            "offer-proposal",
        )
    )
    decisions = run_async(
        provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "playerok",
            "offer-proposal",
        )
    )

    assert forbidden.status_code == 403
    assert foreign.status_code == 404
    assert confirmed.status_code == 200
    assert result["proposal_id"] == proposal["proposal_id"]
    assert result["canonical_product_id"] == proposal["proposal_id"]
    assert result["canonical_product_name"] == "Stardew Valley Complete"
    assert result["canonical_product_category"] is None
    assert result["canonical_product_aliases"] == []
    assert result["decision"] == "confirmed"
    assert result["replayed"] is False
    assert replayed.status_code == 200
    assert replayed.json()["decision_id"] == result["decision_id"]
    assert replayed.json()["replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert "fingerprint" not in conflict.text.lower()
    assert empty_queue.status_code == 200
    assert empty_queue.json() == []
    assert stored_product is not None
    assert stored_product.id == UUID(proposal["proposal_id"])
    assert stored_offer is not None
    assert stored_offer.canonical_product_id == stored_product.id
    assert len(decisions) == 1


def test_product_proposal_can_resolve_to_displayed_existing_product() -> None:
    provider = _seeded_provider()
    client = _client(provider)
    reviewer = _login_headers(client, "reviewer@example.com")
    viewer = _login_headers(client, "viewer@example.com")
    proposals_url = f"/api/v1/tenants/{TENANT_A_ID}/catalog/product-proposals"
    proposal = client.get(proposals_url, headers=reviewer).json()[0]
    resolve_url = f"{proposals_url}/{proposal['proposal_id']}/resolve-existing"
    payload = {
        "marketplace": "playerok",
        "external_id": "offer-proposal",
        "canonical_product_id": str(PRODUCT_ID),
        "reason": "Verified as the same product by reviewer",
    }

    forbidden = client.post(
        resolve_url,
        headers={**viewer, "Idempotency-Key": "forbidden-resolution"},
        json=payload,
    )
    missing_evidence = client.post(
        resolve_url,
        headers={**reviewer, "Idempotency-Key": "missing-evidence"},
        json={**payload, "reason": "  "},
    )
    wrong_target = client.post(
        resolve_url,
        headers={**reviewer, "Idempotency-Key": "wrong-target"},
        json={
            **payload,
            "canonical_product_id": "3a000000-0000-4000-8000-000000009999",
        },
    )
    headers = {**reviewer, "Idempotency-Key": "resolve-product-proposal"}
    resolved = client.post(resolve_url, headers=headers, json=payload)
    replayed = client.post(resolve_url, headers=headers, json=payload)
    conflict = client.post(
        resolve_url,
        headers=headers,
        json={**payload, "reason": "Different evidence"},
    )

    stored_offer = run_async(
        provider.offers.get_by_identity(
            TENANT_A_ID,
            "playerok",
            "offer-proposal",
        )
    )
    products = run_async(provider.canonical_products.list_by_tenant(TENANT_A_ID))
    decisions = run_async(
        provider.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "playerok",
            "offer-proposal",
        )
    )

    assert forbidden.status_code == 403
    assert missing_evidence.status_code == 422
    assert wrong_target.status_code == 409
    assert wrong_target.json()["error"]["code"] == "canonical_product_proposal_stale"
    assert resolved.status_code == 200
    assert resolved.json()["proposal_id"] == proposal["proposal_id"]
    assert resolved.json()["canonical_product_id"] == str(PRODUCT_ID)
    assert resolved.json()["decision"] == "confirmed"
    assert resolved.json()["replayed"] is False
    assert replayed.status_code == 200
    assert replayed.json()["decision_id"] == resolved.json()["decision_id"]
    assert replayed.json()["replayed"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert stored_offer is not None
    assert stored_offer.canonical_product_id == PRODUCT_ID
    assert products == (
        CanonicalProduct(
            id=PRODUCT_ID,
            tenant_id=TENANT_A_ID,
            name="Minecraft Java Bedrock Windows",
            category="Games",
            aliases=(),
        ),
    )
    assert len(decisions) == 1


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
    await provider.offers.save(
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
