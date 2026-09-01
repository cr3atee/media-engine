from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.admin_actions import AdminActorType, AdminResourceType
from app.domain.auth import PasswordCredential
from app.domain.generated_content import calculate_content_checksum
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.processing import ProcessingError
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.queries.models import (
    EventRead,
    PriceDropPayloadRead,
    RelatedSummary,
    SnapshotRead,
)
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    create_memory_read_provider,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import (
    NOW,
    make_content_command,
    make_publication_command,
    run_async,
    uuid_for,
)

TENANT_A_ID = UUID("22000000-0000-4000-8000-000000000101")
TENANT_B_ID = UUID("22000000-0000-4000-8000-000000000202")
ADMIN_USER_ID = UUID("12000000-0000-4000-8000-000000000101")
VIEWER_USER_ID = UUID("12000000-0000-4000-8000-000000000202")
PASSWORD = "correct horse battery staple"


def test_seller_event_reads_are_tenant_scoped() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    tenant_a_event = _event(1, TENANT_A_ID)
    tenant_b_event = _event(2, TENANT_B_ID)
    client = _client(
        provider,
        create_memory_read_provider(events=(tenant_a_event, tenant_b_event)),
    )
    headers = _login_headers(client, "admin@example.com")

    own = client.get(f"/api/v1/tenants/{TENANT_A_ID}/events", headers=headers)
    foreign_detail = client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/events/{tenant_b_event.id}",
        headers=headers,
    )
    foreign_list = client.get(f"/api/v1/tenants/{TENANT_B_ID}/events", headers=headers)

    assert own.status_code == 200
    assert [item["id"] for item in own.json()["items"]] == [str(tenant_a_event.id)]
    assert foreign_detail.status_code == 404
    assert foreign_list.status_code == 200
    assert [item["id"] for item in foreign_list.json()["items"]] == [
        str(tenant_b_event.id)
    ]


def test_seller_commands_are_tenant_scoped_and_audited() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    content_id = uuid_for(81_001)
    run_async(_seed_reviewable_content(provider, content_id=content_id))
    content = run_async(provider.generated_contents.get_by_id(content_id))
    assert content is not None
    client = _client(provider, create_memory_read_provider())
    headers = _login_headers(client, "admin@example.com")
    headers["Idempotency-Key"] = "seller-approve-content"

    approved = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{content_id}/approve",
        headers=headers,
        json={"expected_version": content.version, "reason": "ready"},
    )
    foreign = client.post(
        f"/api/v1/tenants/{TENANT_B_ID}/content/{content_id}/approve",
        headers={**headers, "Idempotency-Key": "seller-foreign-content"},
        json={"expected_version": content.version, "reason": "ready"},
    )
    stored = run_async(provider.generated_contents.get_by_id(content_id))
    actions = run_async(
        provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content_id,
        )
    )

    assert approved.status_code == 200
    assert approved.json()["resulting_state"] == "approved"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "resource_not_found"
    assert stored is not None
    assert stored.review_status is ContentReviewStatus.APPROVED
    assert len(actions) == 1
    assert actions[0].tenant_id == TENANT_A_ID
    assert actions[0].actor_id == str(ADMIN_USER_ID)
    assert actions[0].actor_type is AdminActorType.USER
    assert actions[0].elevated is False


def test_viewer_cannot_execute_seller_content_command() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    content_id = uuid_for(81_002)
    run_async(_seed_reviewable_content(provider, content_id=content_id))
    content = run_async(provider.generated_contents.get_by_id(content_id))
    assert content is not None
    client = _client(provider, create_memory_read_provider())
    headers = _login_headers(client, "viewer@example.com")
    headers["Idempotency-Key"] = "viewer-approve-denied"

    response = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{content_id}/approve",
        headers=headers,
        json={"expected_version": content.version},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_seller_publication_operation_is_tenant_scoped() -> None:
    provider = create_memory_provider()
    run_async(_seed_identity(provider))
    publication_id = uuid_for(82_001)
    run_async(_seed_retryable_publication(provider, publication_id=publication_id))
    publication = run_async(provider.publications.get_by_id(publication_id))
    assert publication is not None
    client = _client(provider, create_memory_read_provider())
    headers = _login_headers(client, "admin@example.com")
    headers["Idempotency-Key"] = "seller-retry-publication"

    retried = client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/publications/{publication_id}/retry",
        headers=headers,
        json={"expected_version": publication.version, "reason": "operator retry"},
    )
    stored = run_async(provider.publications.get_by_id(publication_id))
    actions = run_async(
        provider.admin_actions.list_for_resource(
            AdminResourceType.PUBLICATION,
            publication_id,
        )
    )

    assert retried.status_code == 200
    assert retried.json()["resulting_state"] == "pending"
    assert stored is not None
    assert stored.status is PublicationStatus.PENDING
    assert len(actions) == 1
    assert actions[0].tenant_id == TENANT_A_ID
    assert actions[0].actor_type is AdminActorType.USER


def _client(
    provider: RepositoryProvider,
    read_provider: ReadRepositoryProvider,
) -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield read_provider

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


async def _seed_identity(provider: RepositoryProvider) -> None:
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    hasher = PasswordHasher(iterations=100_000)
    tenants = (
        Tenant(
            id=TENANT_A_ID,
            name="Tenant A",
            slug="tenant-a",
            created_at=now,
            updated_at=now,
        ),
        Tenant(
            id=TENANT_B_ID,
            name="Tenant B",
            slug="tenant-b",
            created_at=now,
            updated_at=now,
        ),
    )
    users = (
        User(
            id=ADMIN_USER_ID,
            email="admin@example.com",
            created_at=now,
            updated_at=now,
        ),
        User(
            id=VIEWER_USER_ID,
            email="viewer@example.com",
            created_at=now,
            updated_at=now,
        ),
    )
    for tenant in tenants:
        await provider.tenants.create(tenant)
    for user in users:
        await provider.users.create(user)
        await provider.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user.id,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=now,
                updated_at=now,
            )
        )
    await provider.memberships.create(
        Membership(
            id=uuid4(),
            user_id=ADMIN_USER_ID,
            tenant_id=TENANT_A_ID,
            role=TenantRole.ADMINISTRATOR,
            joined_at=now,
            updated_at=now,
        )
    )
    await provider.memberships.create(
        Membership(
            id=uuid4(),
            user_id=ADMIN_USER_ID,
            tenant_id=TENANT_B_ID,
            role=TenantRole.ADMINISTRATOR,
            joined_at=now,
            updated_at=now,
        )
    )
    await provider.memberships.create(
        Membership(
            id=uuid4(),
            user_id=VIEWER_USER_ID,
            tenant_id=TENANT_A_ID,
            role=TenantRole.VIEWER,
            joined_at=now,
            updated_at=now,
        )
    )


async def _seed_reviewable_content(
    provider: RepositoryProvider,
    *,
    content_id: UUID,
) -> None:
    command = replace(
        make_content_command(
            number=1,
            content_id=content_id,
            event_id=uuid_for(71_001),
        ),
        tenant_id=TENANT_A_ID,
    )
    await provider.generated_contents.create_attempt(command)
    claimed = (
        await provider.generated_contents.claim_pending(
            NOW + timedelta(minutes=10),
            "content-worker",
            NOW + timedelta(minutes=11),
            1,
        )
    )[0]
    text = "Generated seller content"
    await provider.generated_contents.complete_attempt(
        content_id,
        claimed.claim.token,
        claimed.content.version,
        text,
        calculate_content_checksum(text),
        NOW + timedelta(minutes=10, seconds=1),
    )


async def _seed_retryable_publication(
    provider: RepositoryProvider,
    *,
    publication_id: UUID,
) -> None:
    command = replace(
        make_publication_command(
            number=1,
            publication_id=publication_id,
            event_id=uuid_for(72_001),
            content_id=uuid_for(73_001),
            channel="telegram",
            destination_key="seller-channel",
        ),
        tenant_id=TENANT_A_ID,
    )
    await provider.publications.create_idempotently(command)
    claimed = (
        await provider.publications.claim_pending(
            NOW + timedelta(minutes=20),
            "publication-worker",
            NOW + timedelta(minutes=21),
            1,
        )
    )[0]
    await provider.publications.mark_failed(
        publication_id,
        claimed.claim.token,
        claimed.publication.version,
        ProcessingError(code="telegram_retryable", summary="Retry later"),
        NOW + timedelta(minutes=20, seconds=1),
        NOW + timedelta(minutes=22),
    )


def _event(number: int, tenant_id: UUID) -> EventRead:
    previous = SnapshotRead(
        marketplace="playerok",
        external_id=f"offer-{number}",
        collected_at=NOW - timedelta(hours=1),
        price=Decimal("990.00"),
        currency="RUB",
    )
    current = SnapshotRead(
        marketplace="playerok",
        external_id=f"offer-{number}",
        collected_at=NOW,
        price=Decimal("790.00"),
        currency="RUB",
    )
    return EventRead(
        id=uuid_for(70_000 + number),
        identity_key=f"{number:064x}",
        identity_version=2,
        event_type="price_drop",
        marketplace="playerok",
        external_id=f"offer-{number}",
        canonical_product_id=None,
        payload=PriceDropPayloadRead(
            payload_type="price_drop",
            version=2,
            title=f"Minecraft Premium {number}",
            url="https://example.com/item",
            old_price=Decimal("990.00"),
            new_price=Decimal("790.00"),
            currency="RUB",
            absolute_difference=Decimal("200.00"),
            percentage=Decimal("20.202020"),
            previous_snapshot=previous,
            current_snapshot=current,
        ),
        occurred_at=NOW,
        detected_at=NOW + timedelta(minutes=number),
        created_at=NOW + timedelta(minutes=number),
        disposition="active",
        scoring_status="succeeded",
        score=80,
        scoring_attempt_count=1,
        next_retry_at=None,
        error_code=None,
        error_summary=None,
        version=1,
        content_summary=RelatedSummary(count=0, statuses=()),
        publication_summary=RelatedSummary(count=0, statuses=()),
        tenant_id=tenant_id,
    )
