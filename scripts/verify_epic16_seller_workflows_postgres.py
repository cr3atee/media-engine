"""Verify EPIC 16 Task 3 tenant-scoped seller workflows against PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC16_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings, settings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import SessionLocal, engine
from app.domain.admin_actions import AdminAction, AdminActorType, AdminResourceType
from app.domain.auth import PasswordCredential
from app.domain.generated_content import (
    CreateContentAttempt,
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.market_events import (
    MarketEventCandidate,
    PriceDropMarketEvent,
    PriceDropPayload,
    SnapshotIdentity,
    create_price_drop_market_event,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import ProcessingError
from app.domain.publications import CreatePublication, Publication
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.main import create_app
from app.repositories.postgres import PostgresAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminMutationService,
    ContentReviewCommand,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import SequentialUuidFactory, uuid_for

DATABASE_URL_ENV = "EPIC16_DATABASE_URL"
ADMIN_KEY = "epic16-admin-workflows-key"
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

TENANT_A_ID = UUID("22000000-0000-4000-8000-000000000301")
TENANT_B_ID = UUID("22000000-0000-4000-8000-000000000302")
ADMIN_USER_ID = UUID("12000000-0000-4000-8000-000000000301")
VIEWER_USER_ID = UUID("12000000-0000-4000-8000-000000000302")
OPERATOR_USER_ID = UUID("12000000-0000-4000-8000-000000000303")


class Verification:
    """Collect named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class FailingPostgresAdminActionRepository(PostgresAdminActionRepository):
    """Fail audit insertion to prove command rollback preserves tenant state."""

    async def append(self, action: AdminAction) -> AdminAction:
        """Raise a controlled storage error after a state transition."""
        del action
        msg = "controlled tenant audit failure"
        raise RuntimeError(msg)


async def main() -> int:
    """Run the isolated PostgreSQL seller workflow verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    seed = await _seed_database()

    verifier = Verification()
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        ),
        auth_settings=_auth_settings(),
        repository_scope_factory=create_postgres_repository_scope(),
    )
    app.state.dashboard_clock = lambda: NOW + timedelta(hours=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://epic16-seller.test",
    ) as client:
        await _verify_seller_reads(client, seed, verifier)
        await _verify_seller_commands(client, seed, verifier)
        await _verify_permission_gates(client, seed, verifier)
        await _verify_internal_admin_compatibility(client, seed, verifier)

    await _verify_fresh_session_persistence(verifier, seed)
    await _verify_rollback(verifier)
    await engine.dispose()
    print(
        "EPIC 16 seller workflow PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_seller_reads(
    client: httpx.AsyncClient,
    seed: dict[str, UUID | int],
    verifier: Verification,
) -> None:
    admin_headers = await _login_headers(client, "admin@example.com")
    window_params = {
        "from": (NOW - timedelta(hours=2)).isoformat(),
        "to": (NOW + timedelta(hours=2)).isoformat(),
    }

    tenant_a_events = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/events",
        headers=admin_headers,
    )
    foreign_detail = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/events/{seed['tenant_b_event_id']}",
        headers=admin_headers,
    )
    tenant_b_events = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/events",
        headers=admin_headers,
    )
    verifier.check(
        "seller event list is tenant scoped",
        tenant_a_events.status_code == 200
        and [item["id"] for item in tenant_a_events.json()["items"]]
        == [str(seed["tenant_a_event_id"])],
    )
    verifier.check(
        "seller cross-tenant event detail is hidden",
        foreign_detail.status_code == 404
        and foreign_detail.json()["error"]["code"] == "not_found",
    )
    verifier.check(
        "same user can read second authorized tenant",
        tenant_b_events.status_code == 200
        and [item["id"] for item in tenant_b_events.json()["items"]]
        == [str(seed["tenant_b_event_id"])],
    )

    content = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/content",
        headers=admin_headers,
    )
    publications = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/publications",
        headers=admin_headers,
    )
    dashboard_a = await client.get(
        f"/api/v1/tenants/{TENANT_A_ID}/dashboard/summary",
        headers=admin_headers,
        params=window_params,
    )
    dashboard_b = await client.get(
        f"/api/v1/tenants/{TENANT_B_ID}/dashboard/summary",
        headers=admin_headers,
        params=window_params,
    )
    verifier.check(
        "seller content list is tenant scoped",
        content.status_code == 200
        and {item["id"] for item in content.json()["items"]}
        >= {str(seed["tenant_a_content_id"])},
    )
    verifier.check(
        "seller publication list is tenant scoped",
        publications.status_code == 200
        and {item["id"] for item in publications.json()["items"]}
        >= {str(seed["tenant_a_publication_id"])},
    )
    verifier.check(
        "seller dashboard counts are tenant scoped",
        dashboard_a.status_code == 200
        and dashboard_b.status_code == 200
        and dashboard_a.json()["total_new_market_events"] == 1
        and dashboard_b.json()["total_new_market_events"] == 1,
    )


async def _verify_seller_commands(
    client: httpx.AsyncClient,
    seed: dict[str, UUID | int],
    verifier: Verification,
) -> None:
    admin_headers = await _login_headers(client, "admin@example.com")
    shared_key = "seller-shared-idempotency-key"
    tenant_a_approval = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{seed['tenant_a_content_id']}/approve",
        headers={**admin_headers, "Idempotency-Key": shared_key},
        json={"expected_version": seed["tenant_a_content_version"], "reason": "ready"},
    )
    tenant_b_approval = await client.post(
        f"/api/v1/tenants/{TENANT_B_ID}/content/{seed['tenant_b_content_id']}/approve",
        headers={**admin_headers, "Idempotency-Key": shared_key},
        json={"expected_version": seed["tenant_b_content_version"], "reason": "ready"},
    )
    replay = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{seed['tenant_a_content_id']}/approve",
        headers={**admin_headers, "Idempotency-Key": shared_key},
        json={"expected_version": seed["tenant_a_content_version"], "reason": "ready"},
    )
    conflict = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{seed['tenant_a_content_id']}/approve",
        headers={**admin_headers, "Idempotency-Key": shared_key},
        json={
            "expected_version": seed["tenant_a_content_version"],
            "reason": "different",
        },
    )
    foreign = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/{seed['tenant_b_content_id']}/approve",
        headers={**admin_headers, "Idempotency-Key": "tenant-cross-command"},
        json={"expected_version": seed["tenant_b_content_version"], "reason": "ready"},
    )
    actions = await _load_actions(shared_key)
    verifier.check(
        "seller content approvals succeed across tenants",
        tenant_a_approval.status_code == 200
        and tenant_b_approval.status_code == 200
        and tenant_a_approval.json()["resulting_state"] == "approved"
        and tenant_b_approval.json()["resulting_state"] == "approved",
    )
    verifier.check(
        "seller idempotency replay is tenant scoped",
        replay.status_code == 200 and replay.json()["replayed"] is True,
    )
    verifier.check(
        "seller idempotency conflicts remain tenant scoped",
        conflict.status_code == 409
        and conflict.json()["error"]["code"] == "idempotency_conflict",
    )
    verifier.check(
        "seller cross-tenant content command is hidden",
        foreign.status_code == 404
        and foreign.json()["error"]["code"] == "resource_not_found",
    )
    verifier.check(
        "seller audit records include tenant and actor",
        len(actions) == 2
        and {action.tenant_id for action in actions} == {TENANT_A_ID, TENANT_B_ID}
        and {action.actor_type for action in actions} == {AdminActorType.USER}
        and {action.actor_id for action in actions} == {str(ADMIN_USER_ID)}
        and {action.elevated for action in actions} == {False},
    )

    operator_headers = await _login_headers(client, "operator@example.com")
    retry = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/publications/"
        f"{seed['tenant_a_publication_id']}/retry",
        headers={**operator_headers, "Idempotency-Key": "operator-retry-publication"},
        json={
            "expected_version": seed["tenant_a_publication_version"],
            "reason": "retry delivery",
        },
    )
    publication = await _load_publication(seed["tenant_a_publication_id"])
    publication_actions = await _load_resource_actions(
        AdminResourceType.PUBLICATION,
        seed["tenant_a_publication_id"],
    )
    verifier.check(
        "seller publication retry is tenant scoped",
        retry.status_code == 200
        and publication is not None
        and publication.tenant_id == TENANT_A_ID
        and publication.status is PublicationStatus.PENDING,
    )
    verifier.check(
        "seller publication audit uses tenant actor",
        len(publication_actions) == 1
        and publication_actions[0].tenant_id == TENANT_A_ID
        and publication_actions[0].actor_type is AdminActorType.USER
        and publication_actions[0].actor_id == str(OPERATOR_USER_ID),
    )


async def _verify_permission_gates(
    client: httpx.AsyncClient,
    seed: dict[str, UUID | int],
    verifier: Verification,
) -> None:
    viewer_headers = await _login_headers(client, "viewer@example.com")
    denied = await client.post(
        f"/api/v1/tenants/{TENANT_A_ID}/content/"
        f"{seed['viewer_denied_content_id']}/approve",
        headers={**viewer_headers, "Idempotency-Key": "viewer-command-denied"},
        json={
            "expected_version": seed["viewer_denied_content_version"],
            "reason": "not allowed",
        },
    )
    verifier.check(
        "seller command permission denial is stable",
        denied.status_code == 403
        and denied.json()["error"]["code"] == "permission_denied"
        and PASSWORD not in denied.text,
    )


async def _verify_internal_admin_compatibility(
    client: httpx.AsyncClient,
    seed: dict[str, UUID | int],
    verifier: Verification,
) -> None:
    headers = {
        "X-Admin-API-Key": ADMIN_KEY,
        "Idempotency-Key": "internal-admin-still-works",
    }
    approved = await client.post(
        f"/api/v1/admin/content/{seed['internal_admin_content_id']}/approve",
        headers=headers,
        json={
            "expected_version": seed["internal_admin_content_version"],
            "reason": "internal approval",
        },
    )
    actions = await _load_actions("internal-admin-still-works")
    verifier.check(
        "internal admin API behavior is preserved",
        approved.status_code == 200
        and approved.json()["resulting_state"] == "approved",
    )
    verifier.check(
        "internal admin audit keeps resource tenant",
        len(actions) == 1
        and actions[0].tenant_id == TENANT_B_ID
        and actions[0].actor_type is AdminActorType.API_KEY,
    )


async def _verify_fresh_session_persistence(
    verifier: Verification,
    seed: dict[str, UUID | int],
) -> None:
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        ),
        auth_settings=_auth_settings(),
        repository_scope_factory=create_postgres_repository_scope(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://epic16-fresh-session.test",
    ) as client:
        headers = await _login_headers(client, "admin@example.com")
        content = await client.get(
            f"/api/v1/tenants/{TENANT_A_ID}/content/{seed['tenant_a_content_id']}",
            headers=headers,
        )
    verifier.check(
        "fresh-session seller state persists",
        content.status_code == 200 and content.json()["review_status"] == "approved",
    )


async def _verify_rollback(verifier: Verification) -> None:
    content_id, version = await _seed_reviewable_content(
        tenant_id=TENANT_A_ID,
        number=60,
    )
    service = AdminMutationService(
        _failing_scope_factory(),
        maximum_publication_attempts=5,
        action_id_factory=SequentialUuidFactory(90_000),
        clock=lambda: NOW + timedelta(hours=2),
    )
    try:
        await service.approve(
            ContentReviewCommand(
                content_id=content_id,
                expected_version=version,
                reason="rollback",
            ),
            AdminCommandContext(
                actor_id=str(ADMIN_USER_ID),
                request_id="verify-task3-rollback",
                idempotency_key="verify-task3-rollback",
                tenant_id=TENANT_A_ID,
                actor_type=AdminActorType.USER,
            ),
        )
    except RuntimeError as exc:
        verifier.check(
            "tenant rollback raised controlled failure", "controlled" in str(exc)
        )
    else:
        raise AssertionError("tenant rollback did not raise")

    content = await _load_content(content_id)
    actions = await _load_resource_actions(AdminResourceType.CONTENT, content_id)
    verifier.check(
        "tenant rollback preserved content state",
        content is not None
        and content.tenant_id == TENANT_A_ID
        and content.review_status is ContentReviewStatus.PENDING
        and content.version == version,
    )
    verifier.check("tenant rollback created no audit", actions == ())


async def _login_headers(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_database() -> dict[str, UUID | int]:
    await _seed_identity()
    tenant_a_event_id = await _seed_event(tenant_id=TENANT_A_ID, number=1)
    tenant_b_event_id = await _seed_event(tenant_id=TENANT_B_ID, number=2)
    tenant_a_content_id, tenant_a_content_version = await _seed_reviewable_content(
        tenant_id=TENANT_A_ID,
        number=10,
        event_id=tenant_a_event_id,
    )
    tenant_b_content_id, tenant_b_content_version = await _seed_reviewable_content(
        tenant_id=TENANT_B_ID,
        number=11,
        event_id=tenant_b_event_id,
    )
    (
        internal_admin_content_id,
        internal_admin_content_version,
    ) = await _seed_reviewable_content(
        tenant_id=TENANT_B_ID,
        number=12,
        event_id=tenant_b_event_id,
    )
    (
        viewer_denied_content_id,
        viewer_denied_content_version,
    ) = await _seed_reviewable_content(
        tenant_id=TENANT_A_ID,
        number=13,
        event_id=tenant_a_event_id,
    )
    (
        tenant_a_publication_id,
        tenant_a_publication_version,
    ) = await _seed_retryable_publication(
        tenant_id=TENANT_A_ID,
        number=20,
        event_id=tenant_a_event_id,
    )
    return {
        "tenant_a_event_id": tenant_a_event_id,
        "tenant_b_event_id": tenant_b_event_id,
        "tenant_a_content_id": tenant_a_content_id,
        "tenant_a_content_version": tenant_a_content_version,
        "tenant_b_content_id": tenant_b_content_id,
        "tenant_b_content_version": tenant_b_content_version,
        "internal_admin_content_id": internal_admin_content_id,
        "internal_admin_content_version": internal_admin_content_version,
        "viewer_denied_content_id": viewer_denied_content_id,
        "viewer_denied_content_version": viewer_denied_content_version,
        "tenant_a_publication_id": tenant_a_publication_id,
        "tenant_a_publication_version": tenant_a_publication_version,
    }


async def _seed_identity() -> None:
    hasher = PasswordHasher(iterations=100_000)
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.tenants.create(
            Tenant(
                id=TENANT_A_ID,
                name="Tenant A",
                slug="tenant-a",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.tenants.create(
            Tenant(
                id=TENANT_B_ID,
                name="Tenant B",
                slug="tenant-b",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for user_id, email in (
            (ADMIN_USER_ID, "admin@example.com"),
            (VIEWER_USER_ID, "viewer@example.com"),
            (OPERATOR_USER_ID, "operator@example.com"),
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
                id=uuid_for(91_001),
                user_id=ADMIN_USER_ID,
                tenant_id=TENANT_A_ID,
                role=TenantRole.ADMINISTRATOR,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.memberships.create(
            Membership(
                id=uuid_for(91_002),
                user_id=ADMIN_USER_ID,
                tenant_id=TENANT_B_ID,
                role=TenantRole.ADMINISTRATOR,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.memberships.create(
            Membership(
                id=uuid_for(91_003),
                user_id=VIEWER_USER_ID,
                tenant_id=TENANT_A_ID,
                role=TenantRole.VIEWER,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.memberships.create(
            Membership(
                id=uuid_for(91_004),
                user_id=OPERATOR_USER_ID,
                tenant_id=TENANT_A_ID,
                role=TenantRole.OPERATOR,
                joined_at=NOW,
                updated_at=NOW,
            )
        )


async def _seed_event(*, tenant_id: UUID, number: int) -> UUID:
    event = _make_event(tenant_id=tenant_id, number=number)
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(_snapshot(event.previous_snapshot))
        await repositories.price_history.add(_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
    return event.id


async def _seed_reviewable_content(
    *,
    tenant_id: UUID,
    number: int,
    event_id: UUID | None = None,
) -> tuple[UUID, int]:
    command = CreateContentAttempt(
        id=uuid_for(92_000 + number),
        tenant_id=tenant_id,
        event_id=event_id or await _seed_event(tenant_id=tenant_id, number=number),
        content_type="telegram_post",
        language="ru",
        prompt_version="price_drop_v1",
        attempt_number=number,
        provider="fake",
        model="deterministic",
        created_at=NOW + timedelta(minutes=number),
    )
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.generated_contents.create_attempt(command)
        claimed = await repositories.generated_contents.claim_pending(
            NOW + timedelta(minutes=100 + number),
            "content-worker",
            NOW + timedelta(minutes=101 + number),
            10,
        )
        content_claim = next(item for item in claimed if item.content.id == command.id)
        content_text = f"Generated tenant content {number}"
        await repositories.generated_contents.complete_attempt(
            command.id,
            content_claim.claim.token,
            content_claim.content.version,
            content_text,
            calculate_content_checksum(content_text),
            NOW + timedelta(minutes=100 + number, seconds=1),
        )
        content = await repositories.generated_contents.get_by_id(command.id)
        assert content is not None
        return content.id, content.version


async def _seed_retryable_publication(
    *,
    tenant_id: UUID,
    number: int,
    event_id: UUID,
) -> tuple[UUID, int]:
    content_id, _ = await _seed_reviewable_content(
        tenant_id=tenant_id,
        number=30 + number,
        event_id=event_id,
    )
    command = CreatePublication(
        id=uuid_for(93_000 + number),
        tenant_id=tenant_id,
        event_id=event_id,
        content_id=content_id,
        channel="telegram",
        destination_key=f"tenant-destination-{number}",
        created_at=NOW + timedelta(minutes=number),
    )
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.publications.create_idempotently(command)
        claimed = await repositories.publications.claim_pending(
            NOW + timedelta(minutes=200 + number),
            "publication-worker",
            NOW + timedelta(minutes=201 + number),
            10,
        )
        publication_claim = next(
            item for item in claimed if item.publication.id == command.id
        )
        await repositories.publications.mark_failed(
            command.id,
            publication_claim.claim.token,
            publication_claim.publication.version,
            ProcessingError(code="telegram_retryable", summary="retry later"),
            NOW + timedelta(minutes=200 + number, seconds=1),
            NOW + timedelta(minutes=202 + number),
        )
        publication = await repositories.publications.get_by_id(command.id)
        assert publication is not None
        return publication.id, publication.version


def _make_event(*, tenant_id: UUID, number: int) -> PriceDropMarketEvent:
    previous = SnapshotIdentity(
        marketplace="ggsel",
        external_id=f"tenant-offer-{number}",
        collected_at=NOW + timedelta(minutes=number - 2),
        price=Decimal("990.00"),
        currency="RUB",
        tenant_id=tenant_id,
    )
    current = SnapshotIdentity(
        marketplace="ggsel",
        external_id=f"tenant-offer-{number}",
        collected_at=NOW + timedelta(minutes=number),
        price=Decimal("790.00"),
        currency="RUB",
        tenant_id=tenant_id,
    )
    payload = PriceDropPayload(
        title=f"Minecraft Premium {number}",
        url=f"https://example.com/offers/{number}",
        old_price=previous.price,
        new_price=current.price,
        currency="RUB",
        absolute_difference=Decimal("200.00"),
        percentage=Decimal("20.202020"),
        previous_snapshot=previous,
        current_snapshot=current,
    )
    return create_price_drop_market_event(
        payload=payload,
        tenant_id=tenant_id,
        event_id=uuid_for(94_000 + number),
        detected_at=NOW + timedelta(minutes=number, seconds=1),
        created_at=NOW + timedelta(minutes=number, seconds=2),
    )


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
        tenant_id=identity.tenant_id,
    )


async def _load_content(content_id: UUID | int) -> GeneratedContentAttempt | None:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        return await repositories.generated_contents.get_by_id(content_id)  # type: ignore[arg-type]


async def _load_publication(publication_id: UUID | int) -> Publication | None:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        return await repositories.publications.get_by_id(publication_id)  # type: ignore[arg-type]


async def _load_actions(idempotency_key: str) -> tuple[AdminAction, ...]:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        result = await session.execute(
            text(
                "SELECT id FROM admin_actions "
                "WHERE idempotency_key = :idempotency_key "
                "ORDER BY tenant_id, created_at"
            ),
            {"idempotency_key": idempotency_key},
        )
        actions: list[AdminAction] = []
        for action_id in result.scalars():
            action = await repositories.admin_actions.get_by_id(action_id)
            assert action is not None
            actions.append(action)
        return tuple(actions)


async def _load_resource_actions(
    resource_type: AdminResourceType,
    resource_id: UUID | int,
) -> tuple[AdminAction, ...]:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        return tuple(
            await repositories.admin_actions.list_for_resource(
                resource_type,
                resource_id,  # type: ignore[arg-type]
            )
        )


def _failing_scope_factory() -> RepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with SessionLocal() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.admin_actions = FailingPostgresAdminActionRepository(session)
            yield provider

    return scope


async def _recreate_schema(database_url: str) -> None:
    temporary_engine = create_async_engine(database_url)
    try:
        async with temporary_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await temporary_engine.dispose()


def _apply_migrations(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def _auth_settings() -> AuthSettings:
    return AuthSettings(
        access_token_secret=SecretStr("epic16-seller-workflows-secret"),
        password_hash_iterations=100_000,
    )


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic16_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated epic16_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
