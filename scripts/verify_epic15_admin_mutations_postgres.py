"""Verify EPIC 15 guarded admin mutations against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
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

_CONFIGURED_DATABASE_URL = os.getenv("EPIC15_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, settings
from app.database.session import SessionLocal, engine
from app.domain.admin_actions import AdminAction, AdminResourceType
from app.domain.generated_content import (
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.market_events import MarketEventCandidate, SnapshotIdentity
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import ProcessingError
from app.domain.publications import Publication
from app.main import create_app
from app.repositories.postgres import PostgresAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminMutationService,
    ContentReviewCommand,
)
from app.services.repository_scope import RepositoryScopeFactory
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_content_command,
    make_event,
    make_publication_command,
    uuid_for,
)

DATABASE_URL_ENV = "EPIC15_DATABASE_URL"
ADMIN_KEY = "epic15-admin-mutation-key"


class Verification:
    """Collect and print named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class FailingPostgresAdminActionRepository(PostgresAdminActionRepository):
    """Fail audit insertion to verify transaction rollback."""

    async def append(self, action: AdminAction) -> AdminAction:
        """Raise a controlled storage error after the state transition."""
        del action
        msg = "controlled admin action failure"
        raise RuntimeError(msg)


async def main() -> int:
    """Run the isolated PostgreSQL admin mutation verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)

    verifier = Verification()
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://epic15-admin.test",
    ) as client:
        await _verify_http(client, verifier)

    await _verify_rollback(verifier)
    await engine.dispose()
    print(f"EPIC 15 admin mutation verification: {len(verifier.passed)} checks passed.")
    return 0


async def _verify_http(client: httpx.AsyncClient, verifier: Verification) -> None:
    headers = {"X-Admin-API-Key": ADMIN_KEY}
    content_id, content_version = await _seed_generated_content(1)
    approve_headers = {
        **headers,
        "Idempotency-Key": "verify-approve-1",
        "X-Request-ID": "verify-request-approve",
    }

    missing_auth = await client.post(
        f"/api/v1/admin/content/{content_id}/approve",
        json={"expected_version": content_version},
    )
    verifier.check("missing authentication", missing_auth.status_code == 401)
    verifier.check("secret redaction", ADMIN_KEY not in missing_auth.text)

    approve = await client.post(
        f"/api/v1/admin/content/{content_id}/approve",
        headers=approve_headers,
        json={"expected_version": content_version},
    )
    replay = await client.post(
        f"/api/v1/admin/content/{content_id}/approve",
        headers=approve_headers,
        json={"expected_version": content_version},
    )
    mismatch = await client.post(
        f"/api/v1/admin/content/{content_id}/approve",
        headers=approve_headers,
        json={"expected_version": content_version, "reason": "different command"},
    )
    stored_content, actions = await _load_content_and_actions(content_id)
    verifier.check("content approval", approve.status_code == 200)
    verifier.check("idempotent replay", replay.json()["replayed"] is True)
    verifier.check(
        "idempotency conflict",
        mismatch.status_code == 409
        and mismatch.json()["error"]["code"] == "idempotency_conflict",
    )
    verifier.check(
        "approved content persisted",
        stored_content is not None
        and stored_content.review_status is ContentReviewStatus.APPROVED,
    )
    verifier.check("single admin action", len(actions) == 1)
    verifier.check(
        "request correlation persisted",
        actions[0].request_id == "verify-request-approve",
    )

    stale_id, stale_version = await _seed_generated_content(2)
    stale = await client.post(
        f"/api/v1/admin/content/{stale_id}/approve",
        headers={**headers, "Idempotency-Key": "verify-stale-1"},
        json={"expected_version": stale_version - 1},
    )
    stale_actions = await _load_actions(AdminResourceType.CONTENT, stale_id)
    verifier.check(
        "optimistic concurrency conflict",
        stale.status_code == 409
        and stale.json()["error"]["code"] == "optimistic_concurrency_conflict",
    )
    verifier.check("failed transition creates no audit", stale_actions == ())

    reject_id, reject_version = await _seed_generated_content(3)
    reject = await client.post(
        f"/api/v1/admin/content/{reject_id}/reject",
        headers={**headers, "Idempotency-Key": "verify-reject-1"},
        json={"expected_version": reject_version, "reason": "bad generated facts"},
    )
    verifier.check(
        "content rejection",
        reject.status_code == 200 and reject.json()["action"] == "reject_content",
    )

    failed_id, failed_version = await _seed_failed_publication(4, retryable=True)
    retry = await client.post(
        f"/api/v1/admin/publications/{failed_id}/retry",
        headers={**headers, "Idempotency-Key": "verify-retry-1"},
        json={"expected_version": failed_version, "reason": "retry manually"},
    )
    retry_publication = await _load_publication(failed_id)
    verifier.check(
        "retry publication",
        retry.status_code == 200
        and retry_publication is not None
        and retry_publication.status is PublicationStatus.PENDING,
    )

    pending_id, pending_version, _ = await _seed_pending_publication(5)
    cancel = await client.post(
        f"/api/v1/admin/publications/{pending_id}/cancel",
        headers={**headers, "Idempotency-Key": "verify-cancel-1"},
        json={"expected_version": pending_version, "reason": "not needed"},
    )
    cancelled = await _load_publication(pending_id)
    verifier.check(
        "cancel publication",
        cancel.status_code == 200
        and cancelled is not None
        and cancelled.status is PublicationStatus.CANCELLED,
    )

    ambiguous_id, ambiguous_version = await _seed_ambiguous_publication(6)
    missing_message = await client.post(
        f"/api/v1/admin/publications/{ambiguous_id}/resolve-ambiguous",
        headers={**headers, "Idempotency-Key": "verify-resolve-invalid"},
        json={
            "expected_version": ambiguous_version,
            "resolution": "delivered",
            "reason": "operator confirmed",
        },
    )
    verifier.check(
        "delivered resolution requires message id",
        missing_message.status_code == 422,
    )
    resolve = await client.post(
        f"/api/v1/admin/publications/{ambiguous_id}/resolve-ambiguous",
        headers={**headers, "Idempotency-Key": "verify-resolve-1"},
        json={
            "expected_version": ambiguous_version,
            "resolution": "delivered",
            "reason": "operator confirmed",
            "external_message_id": "telegram-message-42",
        },
    )
    resolved = await _load_publication(ambiguous_id)
    verifier.check(
        "resolve ambiguous delivered",
        resolve.status_code == 200
        and resolved is not None
        and resolved.status is PublicationStatus.PUBLISHED
        and resolved.external_message_id == "telegram-message-42",
    )

    concurrent_id, concurrent_version = await _seed_generated_content(7)
    concurrent_headers = {**headers, "Idempotency-Key": "verify-concurrent-1"}
    first, second = await asyncio.gather(
        client.post(
            f"/api/v1/admin/content/{concurrent_id}/approve",
            headers=concurrent_headers,
            json={"expected_version": concurrent_version},
        ),
        client.post(
            f"/api/v1/admin/content/{concurrent_id}/approve",
            headers=concurrent_headers,
            json={"expected_version": concurrent_version},
        ),
    )
    concurrent_actions = await _load_actions(AdminResourceType.CONTENT, concurrent_id)
    verifier.check(
        "concurrent duplicate idempotency",
        first.status_code == 200
        and second.status_code == 200
        and {first.json()["replayed"], second.json()["replayed"]} == {False, True}
        and len(concurrent_actions) == 1,
    )


async def _verify_rollback(verifier: Verification) -> None:
    content_id, version = await _seed_generated_content(8)
    service = AdminMutationService(
        _failing_scope_factory(),
        maximum_publication_attempts=5,
        clock=lambda: NOW + timedelta(hours=1),
        action_id_factory=SequentialUuidFactory(96_000),
    )
    try:
        await service.approve(
            ContentReviewCommand(content_id=content_id, expected_version=version),
            AdminCommandContext(
                actor_id="postgres-admin",
                request_id="verify-rollback",
                idempotency_key="verify-rollback-1",
            ),
        )
    except RuntimeError as exc:
        verifier.check(
            "controlled rollback raised",
            "controlled admin action" in str(exc),
        )
    else:
        raise AssertionError("controlled rollback did not raise")
    stored, actions = await _load_content_and_actions(content_id)
    verifier.check(
        "rollback preserved previous content state",
        stored is not None
        and stored.review_status is ContentReviewStatus.PENDING
        and stored.version == version,
    )
    verifier.check("rollback created no audit", actions == ())


async def _seed_generated_content(number: int) -> tuple[UUID, int]:
    event = make_event(number=number, event_id=uuid_for(120_000 + number))
    command = make_content_command(
        number=number,
        event_id=event.id,
        content_id=uuid_for(121_000 + number),
    )
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(_snapshot(event.previous_snapshot))
        await repositories.price_history.add(_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
        await repositories.generated_contents.create_attempt(command)
        claimed = (
            await repositories.generated_contents.claim_pending(
                NOW + timedelta(minutes=10),
                "content-worker",
                NOW + timedelta(minutes=11),
                1,
            )
        )[0]
        text_value = f"Generated content {number}"
        await repositories.generated_contents.complete_attempt(
            command.id,
            claimed.claim.token,
            claimed.content.version,
            text_value,
            calculate_content_checksum(text_value),
            NOW + timedelta(minutes=10, seconds=1),
        )
        content = await repositories.generated_contents.get_by_id(command.id)
        assert content is not None
        return content.id, content.version


async def _seed_pending_publication(number: int) -> tuple[UUID, int, str]:
    event = make_event(number=number, event_id=uuid_for(130_000 + number))
    content_command = make_content_command(
        number=100 + number,
        event_id=event.id,
        content_id=uuid_for(132_000 + number),
    )
    channel = f"telegram-{number}"
    publication_command = make_publication_command(
        number=number,
        event_id=event.id,
        content_id=content_command.id,
        publication_id=uuid_for(131_000 + number),
        channel=channel,
        destination_key=f"telegram-{number}",
    )
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(_snapshot(event.previous_snapshot))
        await repositories.price_history.add(_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
        await repositories.generated_contents.create_attempt(content_command)
        result = await repositories.publications.create_idempotently(
            publication_command
        )
        return result.publication.id, result.publication.version, channel


async def _seed_failed_publication(
    number: int,
    *,
    retryable: bool,
) -> tuple[UUID, int]:
    publication_id, _, channel = await _seed_pending_publication(number)
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        claimed = (
            await repositories.publications.claim_pending(
                NOW + timedelta(minutes=20),
                "publication-worker",
                NOW + timedelta(minutes=21),
                1,
                channel=channel,
            )
        )[0]
        assert claimed.publication.id == publication_id
        await repositories.publications.mark_failed(
            claimed.publication.id,
            claimed.claim.token,
            claimed.publication.version,
            ProcessingError(code="telegram_retryable", summary="retry later"),
            NOW + timedelta(minutes=20, seconds=1),
            NOW + timedelta(minutes=22) if retryable else None,
        )
        stored = await repositories.publications.get_by_id(publication_id)
        assert stored is not None
        return stored.id, stored.version


async def _seed_ambiguous_publication(number: int) -> tuple[UUID, int]:
    publication_id, _, channel = await _seed_pending_publication(number)
    async with SessionLocal() as session, session.begin():
        repositories = create_postgres_provider(session)
        claimed = (
            await repositories.publications.claim_pending(
                NOW + timedelta(minutes=30),
                "publication-worker",
                NOW + timedelta(minutes=31),
                1,
                channel=channel,
            )
        )[0]
        assert claimed.publication.id == publication_id
        await repositories.publications.mark_ambiguous(
            claimed.publication.id,
            claimed.claim.token,
            claimed.publication.version,
            ProcessingError(code="telegram_timeout", summary="unknown outcome"),
            NOW + timedelta(minutes=30, seconds=1),
        )
        stored = await repositories.publications.get_by_id(publication_id)
        assert stored is not None
        return stored.id, stored.version


async def _load_content_and_actions(
    content_id: UUID,
) -> tuple[GeneratedContentAttempt | None, tuple[AdminAction, ...]]:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        content = await repositories.generated_contents.get_by_id(content_id)
        actions = await repositories.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content_id,
        )
        return content, tuple(actions)


async def _load_actions(
    resource_type: AdminResourceType,
    resource_id: UUID,
) -> tuple[AdminAction, ...]:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        return tuple(
            await repositories.admin_actions.list_for_resource(
                resource_type,
                resource_id,
            )
        )


async def _load_publication(publication_id: UUID) -> Publication | None:
    async with SessionLocal() as session:
        repositories = create_postgres_provider(session)
        return await repositories.publications.get_by_id(publication_id)


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
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


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("epic15_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated epic15_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
