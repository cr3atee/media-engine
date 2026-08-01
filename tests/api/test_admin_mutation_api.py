from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings
from app.domain.admin_actions import AdminResourceType
from app.domain.generated_content import calculate_content_checksum
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.processing import ProcessingError
from app.main import create_app
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.queries.provider import (
    ReadRepositoryProvider,
    create_memory_read_provider,
)
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import (
    NOW,
    make_content_command,
    make_publication_command,
    run_async,
    uuid_for,
)

ADMIN_KEY = "test-admin-secret"


def test_content_approval_endpoint_auth_idempotency_and_replay() -> None:
    provider = create_memory_provider()
    content_id, version = run_async(_seed_generated_content(provider, number=1))
    client = _client(provider)
    path = f"/api/v1/admin/content/{content_id}/approve"

    unauthenticated = client.post(path, json={"expected_version": version})
    missing_key = client.post(
        path,
        headers={"X-Admin-API-Key": ADMIN_KEY},
        json={"expected_version": version},
    )
    approved = client.post(
        path,
        headers={
            "X-Admin-API-Key": ADMIN_KEY,
            "Idempotency-Key": "api-content-approve-1",
            "X-Request-ID": "request-content-approve",
        },
        json={"expected_version": version},
    )
    replay = client.post(
        path,
        headers={
            "X-Admin-API-Key": ADMIN_KEY,
            "Idempotency-Key": "api-content-approve-1",
            "X-Request-ID": "request-content-approve",
        },
        json={"expected_version": version},
    )
    stored = run_async(provider.generated_contents.get_by_id(content_id))
    actions = run_async(
        provider.admin_actions.list_for_resource(AdminResourceType.CONTENT, content_id)
    )

    assert unauthenticated.status_code == 401
    assert missing_key.status_code == 422
    assert approved.status_code == 200
    assert approved.json()["action"] == "approve_content"
    assert approved.json()["request_id"] == "request-content-approve"
    assert replay.status_code == 200
    assert replay.json()["action_id"] == approved.json()["action_id"]
    assert replay.json()["replayed"] is True
    assert stored is not None
    assert stored.review_status is ContentReviewStatus.APPROVED
    assert len(actions) == 1
    assert ADMIN_KEY not in approved.text


def test_content_endpoint_reports_stale_version_and_key_mismatch_safely() -> None:
    provider = create_memory_provider()
    content_id, version = run_async(_seed_generated_content(provider, number=2))
    client = _client(provider)
    path = f"/api/v1/admin/content/{content_id}/approve"
    headers = {
        "X-Admin-API-Key": ADMIN_KEY,
        "Idempotency-Key": "api-content-approve-conflict",
    }

    stale = client.post(path, headers=headers, json={"expected_version": version - 1})
    accepted = client.post(path, headers=headers, json={"expected_version": version})
    mismatch = client.post(
        path,
        headers=headers,
        json={"expected_version": version, "reason": "different command"},
    )
    actions = run_async(
        provider.admin_actions.list_for_resource(AdminResourceType.CONTENT, content_id)
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "optimistic_concurrency_conflict"
    assert accepted.status_code == 200
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "idempotency_conflict"
    assert len(actions) == 1
    assert ADMIN_KEY not in stale.text


def test_publication_cancel_and_ambiguous_resolution_endpoints_are_guarded() -> None:
    provider = create_memory_provider()
    pending_id, pending_version = run_async(
        _seed_pending_publication(provider, number=1)
    )
    client = _client(provider)
    headers = {"X-Admin-API-Key": ADMIN_KEY}

    cancel = client.post(
        f"/api/v1/admin/publications/{pending_id}/cancel",
        headers={**headers, "Idempotency-Key": "api-cancel-1"},
        json={"expected_version": pending_version, "reason": "obsolete"},
    )
    ambiguous_id, ambiguous_version = run_async(
        _seed_ambiguous_publication(provider, number=2)
    )
    missing_message = client.post(
        f"/api/v1/admin/publications/{ambiguous_id}/resolve-ambiguous",
        headers={**headers, "Idempotency-Key": "api-resolve-invalid"},
        json={
            "expected_version": ambiguous_version,
            "resolution": "delivered",
            "reason": "operator checked provider",
        },
    )
    resolved = client.post(
        f"/api/v1/admin/publications/{ambiguous_id}/resolve-ambiguous",
        headers={**headers, "Idempotency-Key": "api-resolve-1"},
        json={
            "expected_version": ambiguous_version,
            "resolution": "not_delivered",
            "reason": "operator checked provider",
        },
    )
    cancelled = run_async(provider.publications.get_by_id(pending_id))
    resolved_publication = run_async(provider.publications.get_by_id(ambiguous_id))

    assert cancel.status_code == 200
    assert cancel.json()["action"] == "cancel_publication"
    assert missing_message.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["action"] == "resolve_publication_not_delivered"
    assert cancelled is not None
    assert cancelled.status is PublicationStatus.CANCELLED
    assert resolved_publication is not None
    assert resolved_publication.status is PublicationStatus.PENDING


def _client(provider: RepositoryProvider) -> TestClient:
    @asynccontextmanager
    async def read_scope() -> AsyncIterator[ReadRepositoryProvider]:
        yield create_memory_read_provider()

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        ),
        read_repository_scope_factory=read_scope,
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return TestClient(application, raise_server_exceptions=False)


async def _seed_generated_content(
    provider: RepositoryProvider,
    *,
    number: int,
) -> tuple[UUID, int]:
    command = make_content_command(number=number)
    await provider.generated_contents.create_attempt(command)
    claimed = (
        await provider.generated_contents.claim_pending(
            NOW + timedelta(minutes=10),
            "content-worker",
            NOW + timedelta(minutes=11),
            1,
        )
    )[0]
    text = f"Generated content {number}"
    await provider.generated_contents.complete_attempt(
        command.id,
        claimed.claim.token,
        claimed.content.version,
        text,
        calculate_content_checksum(text),
        NOW + timedelta(minutes=10, seconds=1),
    )
    stored = await provider.generated_contents.get_by_id(command.id)
    assert stored is not None
    return stored.id, stored.version


async def _seed_pending_publication(
    provider: RepositoryProvider,
    *,
    number: int,
) -> tuple[UUID, int]:
    command = make_publication_command(
        number=number,
        event_id=uuid_for(40_000 + number),
        content_id=uuid_for(50_000 + number),
        publication_id=uuid_for(60_000 + number),
        channel="telegram",
        destination_key=f"api-channel-{number}",
    )
    result = await provider.publications.create_idempotently(command)
    return result.publication.id, result.publication.version


async def _seed_ambiguous_publication(
    provider: RepositoryProvider,
    *,
    number: int,
) -> tuple[UUID, int]:
    publication_id, _ = await _seed_pending_publication(provider, number=number)
    claimed = (
        await provider.publications.claim_pending(
            NOW + timedelta(minutes=30),
            "publication-worker",
            NOW + timedelta(minutes=31),
            1,
        )
    )[0]
    assert claimed.publication.id == publication_id
    await provider.publications.mark_ambiguous(
        claimed.publication.id,
        claimed.claim.token,
        claimed.publication.version,
        ProcessingError(code="telegram_timeout", summary="unknown outcome"),
        NOW + timedelta(minutes=30, seconds=1),
    )
    stored = await provider.publications.get_by_id(publication_id)
    assert stored is not None
    return stored.id, stored.version
