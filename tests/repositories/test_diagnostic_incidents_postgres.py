"""PostgreSQL verification for concurrent durable diagnostic aggregation."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import DiagnosticSettings
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.diagnostics import DiagnosticIncident
from app.services.diagnostics import DiagnosticService
from app.services.product_roles import ProductRoleService
from tests.repositories.contracts.factories import run_async
from tests.services.test_product_roles import principal, seed


def test_postgres_diagnostics_concurrency_restart_and_admin_access() -> None:
    raw_url = os.environ.get("DIAGNOSTICS_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Requires a disposable DIAGNOSTICS_TEST_DATABASE_URL")
    url = make_url(raw_url)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.database == "mediaengine_diagnostics_test"

    async def scenario() -> None:
        environment = f"diagnostics-test-{uuid4().hex}"
        settings = DiagnosticSettings(environment=environment)
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        scope = create_postgres_repository_scope(factory)
        service = DiagnosticService(scope, settings)
        try:
            async with scope() as repositories:
                existing_admins = await repositories.users.list_product_admins()
                if existing_admins:
                    admin = existing_admins[0].id
                else:
                    admin, _ = await seed(repositories)
            if not existing_admins:
                await ProductRoleService(scope).bootstrap(
                    user_id=admin,
                    expected_version=1,
                    reason="Diagnostic verifier",
                    idempotency_key=f"diagnostic-bootstrap-{admin}",
                )

            async def record(number: int) -> DiagnosticIncident:
                try:
                    raise RuntimeError(f"untrusted-message-{number}")
                except RuntimeError as error:
                    return await service.record_backend(
                        request_id=f"request-{number}",
                        route="/api/v1/items/{item_id}",
                        method="GET",
                        error=error,
                    )

            occurrences = await asyncio.gather(*(record(index) for index in range(8)))
            assert len({item.id for item in occurrences}) == 1
            incidents, total = await service.list_for_admin(
                principal(admin),
                source=None,
                severity=None,
                component="api",
                environment=environment,
                limit=20,
                offset=0,
            )
            assert total == 1
            assert incidents[0].occurrence_count == 8
            assert incidents[0].error_type == "RuntimeError"
            assert all(
                "untrusted-message" not in frame for frame in incidents[0].stack_frames
            )

            await engine.dispose()
            fresh_engine = create_async_engine(url)
            fresh_scope = create_postgres_repository_scope(
                async_sessionmaker(fresh_engine, expire_on_commit=False)
            )
            try:
                fresh_service = DiagnosticService(fresh_scope, settings)
                persisted = await fresh_service.get_for_admin(
                    principal(admin), incidents[0].id
                )
                assert persisted == incidents[0]
                async with fresh_engine.connect() as connection:
                    indexes = await connection.run_sync(
                        lambda sync_connection: {
                            item["name"]
                            for item in inspect(sync_connection).get_indexes(
                                "diagnostic_incidents"
                            )
                        }
                    )
                    constraints = await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conrelid = 'diagnostic_incidents'::regclass"
                        )
                    )
                assert {
                    "uq_diagnostic_incidents_fingerprint",
                    "ix_diagnostic_incidents_last_seen",
                    "ix_diagnostic_incidents_severity_time",
                    "ix_diagnostic_incidents_component_time",
                    "ix_diagnostic_incidents_tenant_time",
                } <= indexes
                assert int(constraints or 0) >= 6
            finally:
                await fresh_engine.dispose()
        finally:
            await engine.dispose()

    run_async(scenario())
