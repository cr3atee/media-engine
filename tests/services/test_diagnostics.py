"""Diagnostics retain only bounded metadata and survive storage failures."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.config.settings import DiagnosticSettings
from app.domain.auth import ActorType, AuthenticatedPrincipal
from app.domain.product_access import ProductRole
from app.domain.tenancy import User
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.diagnostics import DiagnosticService
from app.services.product_roles import ProductRoleService
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import run_async


def _principal(user_id: UUID) -> AuthenticatedPrincipal:
    now = datetime.now(UTC)
    return AuthenticatedPrincipal(
        actor_type=ActorType.USER,
        user_id=user_id,
        session_id=uuid4(),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def test_memory_deduplication_admin_access_and_retention(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        scope = create_memory_repository_scope(provider)
        user_id = uuid4()
        now = datetime.now(UTC)
        await provider.users.create(
            User(
                id=user_id,
                email="admin@example.test",
                created_at=now,
                updated_at=now,
            )
        )
        roles = ProductRoleService(scope)
        await roles.bootstrap(
            user_id=user_id,
            expected_version=1,
            reason="Test administrator",
            idempotency_key="bootstrap",
        )
        service = DiagnosticService(
            scope,
            DiagnosticSettings(fallback_path=tmp_path / "fallback.jsonl"),
        )
        first = await service.record_frontend(
            _principal(user_id),
            kind="error",
            page="review",
            component="shell",
            action="render",
            request_id="request-1",
        )
        repeated = await service.record_frontend(
            _principal(user_id),
            kind="error",
            page="review",
            component="shell",
            action="render",
            request_id="request-2",
        )
        assert repeated.id == first.id
        assert repeated.occurrence_count == 2
        assert repeated.first_request_id == "request-1"
        assert repeated.last_request_id == "request-2"
        incidents, total = await service.list_for_admin(
            _principal(user_id),
            source=None,
            severity=None,
            component="shell",
            environment="development",
            limit=20,
            offset=0,
        )
        assert total == 1 and incidents == (repeated,)
        stored_user = await provider.users.get_by_id(user_id)
        assert stored_user is not None
        assert stored_user.product_role is ProductRole.ADMIN

    run_async(scenario())


def test_database_failure_uses_redacted_bounded_fallback(tmp_path: Path) -> None:
    @asynccontextmanager
    async def failing_scope() -> AsyncIterator[RepositoryProvider]:
        raise RuntimeError("database password=top-secret")
        yield create_memory_provider()  # pragma: no cover

    async def scenario() -> None:
        fallback = tmp_path / "diagnostics" / "incidents.jsonl"
        service = DiagnosticService(
            failing_scope,
            DiagnosticSettings(
                fallback_path=fallback,
                fallback_max_bytes=1024,
                fallback_backups=2,
            ),
        )
        try:
            raise RuntimeError("bearer secret-token password=do-not-store")
        except RuntimeError as error:
            incident = await service.record_backend(
                request_id="safe-request",
                route="/api/v1/example/{item_id}",
                method="GET",
                error=error,
            )
        payload = json.loads(fallback.read_text(encoding="utf-8"))
        serialized = fallback.read_text(encoding="utf-8")
        assert payload["incident_id"] == str(incident.id)
        assert payload["error_type"] == "RuntimeError"
        assert payload["route"] == "/api/v1/example/{item_id}"
        assert "top-secret" not in serialized
        assert "secret-token" not in serialized
        assert "do-not-store" not in serialized

        for number in range(6):
            try:
                raise RuntimeError(f"different-secret-{number}")
            except RuntimeError as error:
                await service.record_backend(
                    request_id=f"rotation-{number}",
                    route=f"/api/v1/fallback/{number}",
                    method="POST",
                    error=error,
                )
        assert fallback.with_suffix(".jsonl.1").exists()
        assert fallback.stat().st_size <= 1024
        assert fallback.with_suffix(".jsonl.1").stat().st_size <= 1024

    run_async(scenario())


def test_slow_database_does_not_block_error_response(tmp_path: Path) -> None:
    @asynccontextmanager
    async def slow_scope() -> AsyncIterator[RepositoryProvider]:
        await asyncio.sleep(1)
        yield create_memory_provider()

    async def scenario() -> None:
        service = DiagnosticService(
            slow_scope,
            DiagnosticSettings(
                fallback_path=tmp_path / "timeout.jsonl",
                persistence_timeout_seconds=0.02,
                fallback_timeout_seconds=0.2,
            ),
        )
        started = time.monotonic()
        incident = await service.record_backend(
            request_id="timeout-request",
            route="/api/v1/slow",
            method="GET",
            error=RuntimeError("never store this message"),
        )
        assert time.monotonic() - started < 0.5
        assert incident.last_request_id == "timeout-request"
        assert (tmp_path / "timeout.jsonl").exists()

    run_async(scenario())
