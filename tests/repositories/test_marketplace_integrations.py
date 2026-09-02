from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, Table

from app.domain.marketplace_integrations import (
    MarketplaceAuthType,
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.models.marketplace_integration_record import MarketplaceIntegrationRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memory import MemoryMarketplaceIntegrationRepository
from app.repositories.provider import create_memory_provider

TENANT_A_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B_ID = UUID("10000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run repository async methods without requiring a pytest plugin."""
    return asyncio.run(awaitable)


def make_integration(
    *,
    number: int = 1,
    tenant_id: UUID = TENANT_A_ID,
    marketplace: str = "ggsel",
    display_name: str = "GGSEL main",
    enabled: bool = True,
    status: MarketplaceIntegrationStatus = MarketplaceIntegrationStatus.ACTIVE,
    external_account_id: str | None = None,
    source_url: str | None = "https://ggsel.net/catalog/minecraft",
    auth_type: MarketplaceAuthType = MarketplaceAuthType.NONE,
) -> MarketplaceIntegration:
    """Create deterministic marketplace integration test data."""
    return MarketplaceIntegration(
        id=UUID(int=17_000 + number),
        tenant_id=tenant_id,
        marketplace=marketplace,
        display_name=display_name,
        enabled=enabled,
        status=status,
        external_account_id=external_account_id,
        source_url=source_url,
        auth_type=auth_type,
        created_at=NOW + timedelta(minutes=number),
        updated_at=NOW + timedelta(minutes=number),
    )


def test_marketplace_integration_normalizes_text_and_enums() -> None:
    integration = make_integration(
        marketplace=" GGSEL ",
        display_name="  GGSEL   catalog ",
        source_url=" https://example.com/catalog ",
    )

    assert integration.marketplace == "ggsel"
    assert integration.display_name == "GGSEL catalog"
    assert integration.source_url == "https://example.com/catalog"
    assert integration.status is MarketplaceIntegrationStatus.ACTIVE
    assert integration.auth_type is MarketplaceAuthType.NONE


def test_memory_repository_saves_updates_and_lists_by_tenant() -> None:
    repository = MemoryMarketplaceIntegrationRepository()
    original = make_integration(display_name="GGSEL original")
    updated = make_integration(display_name="GGSEL updated", enabled=False)
    other = make_integration(
        number=2,
        tenant_id=TENANT_B_ID,
        display_name="Playerok",
        marketplace="playerok",
        source_url="https://playerok.com/catalog/minecraft",
    )

    run_async(repository.save(original))
    run_async(repository.save(other))
    run_async(repository.save(updated))

    assert run_async(repository.get_by_tenant_and_id(TENANT_A_ID, original.id)) == (
        updated
    )
    assert run_async(repository.get_by_tenant_and_id(TENANT_B_ID, original.id)) is None
    assert tuple(run_async(repository.list_by_tenant(TENANT_A_ID))) == (updated,)
    assert tuple(run_async(repository.list_by_tenant(TENANT_B_ID))) == (other,)


def test_memory_repository_lists_only_enabled_active_integrations() -> None:
    repository = MemoryMarketplaceIntegrationRepository()
    active = make_integration(number=1)
    disabled_flag = make_integration(
        number=2,
        enabled=False,
        source_url="https://ggsel.net/catalog/hidden",
    )
    disabled_status = make_integration(
        number=3,
        status=MarketplaceIntegrationStatus.DISABLED,
        source_url="https://ggsel.net/catalog/disabled",
    )
    tenant_b_active = make_integration(
        number=4,
        tenant_id=TENANT_B_ID,
        source_url="https://ggsel.net/catalog/tenant-b",
    )

    for integration in (active, disabled_flag, disabled_status, tenant_b_active):
        run_async(repository.save(integration))

    assert tuple(run_async(repository.list_enabled())) == (active, tenant_b_active)
    assert tuple(run_async(repository.list_enabled_by_tenant(TENANT_A_ID))) == (active,)


def test_memory_repository_scopes_external_account_identity_by_tenant() -> None:
    repository = MemoryMarketplaceIntegrationRepository()
    tenant_a = make_integration(
        external_account_id="seller-1",
        source_url=None,
    )
    tenant_b = make_integration(
        number=2,
        tenant_id=TENANT_B_ID,
        external_account_id="seller-1",
        source_url=None,
    )

    run_async(repository.save(tenant_a))
    run_async(repository.save(tenant_b))

    duplicate = make_integration(
        number=3,
        external_account_id="seller-1",
        source_url=None,
    )
    with pytest.raises(RepositoryIdentityConflictError):
        run_async(repository.save(duplicate))


def test_memory_repository_scopes_source_url_identity_by_tenant() -> None:
    repository = MemoryMarketplaceIntegrationRepository()
    tenant_a = make_integration(source_url="https://example.com/source")
    tenant_b = make_integration(
        number=2,
        tenant_id=TENANT_B_ID,
        source_url="https://example.com/source",
    )

    run_async(repository.save(tenant_a))
    run_async(repository.save(tenant_b))

    duplicate = make_integration(
        number=3,
        source_url="https://example.com/source",
    )
    with pytest.raises(RepositoryIdentityConflictError):
        run_async(repository.save(duplicate))


def test_provider_exposes_memory_marketplace_integrations() -> None:
    provider = create_memory_provider()

    assert isinstance(
        provider.marketplace_integrations,
        MemoryMarketplaceIntegrationRepository,
    )


def test_marketplace_integration_metadata_matches_task_contract() -> None:
    table = cast(Table, MarketplaceIntegrationRecord.__table__)
    constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_marketplace_integrations_marketplace_nonempty",
        "ck_marketplace_integrations_display_name_nonempty",
        "ck_marketplace_integrations_status",
        "ck_marketplace_integrations_auth_type",
        "ck_marketplace_integrations_version",
        "ck_marketplace_integrations_timestamp_order",
    } <= constraints

    indexes = {str(index.name): index for index in table.indexes}
    external_account = indexes[
        "uq_marketplace_integrations_tenant_marketplace_external_account"
    ]
    source_url = indexes["uq_marketplace_integrations_tenant_marketplace_source_url"]
    enabled_runs = indexes["ix_marketplace_integrations_enabled_runs"]

    assert external_account.unique is True
    assert tuple(column.name for column in external_account.columns) == (
        "tenant_id",
        "marketplace",
        "external_account_id",
    )
    assert external_account.dialect_options["postgresql"]["where"] is not None
    assert source_url.unique is True
    assert tuple(column.name for column in source_url.columns) == (
        "tenant_id",
        "marketplace",
        "source_url",
    )
    assert source_url.dialect_options["postgresql"]["where"] is not None
    assert tuple(column.name for column in enabled_runs.columns) == (
        "enabled",
        "status",
        "created_at",
        "id",
    )

    foreign_key = next(iter(table.c.tenant_id.foreign_keys))
    assert foreign_key.name == "fk_marketplace_integrations_tenant"
    assert foreign_key.target_fullname == "tenants.id"
    assert foreign_key.ondelete == "RESTRICT"
