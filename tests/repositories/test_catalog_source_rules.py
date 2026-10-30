from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from app.catalog.hierarchy import CatalogSourceRule
from app.models.catalog_source_rule_record import CatalogSourceRuleRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memory import MemoryCatalogSourceRuleRepository
from app.repositories.provider import create_memory_provider

TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("10000000-0000-4000-8000-000000000002")
INTEGRATION_A = UUID("20000000-0000-4000-8000-000000000001")
INTEGRATION_B = UUID("20000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run repository coroutines without an async pytest plugin."""
    return asyncio.run(awaitable)


def make_rule(
    *,
    number: int = 1,
    tenant_id: UUID = TENANT_A,
    integration_id: UUID = INTEGRATION_A,
    marketplace: str = "playerok",
    source_category_id: str = "fortnite-vbucks",
    section_code: str = "v-bucks",
) -> CatalogSourceRule:
    """Build deterministic rule data for repository contract tests."""
    created_at = NOW + timedelta(minutes=number)
    return CatalogSourceRule(
        id=UUID(int=30_000 + number),
        tenant_id=tenant_id,
        integration_id=integration_id,
        marketplace=marketplace,
        source_category_id=source_category_id,
        source_category_name="Fortnite V-Bucks",
        hub_code="fortnite",
        section_code=section_code,
        created_at=created_at,
        updated_at=created_at,
    )


def test_memory_repository_roundtrip_update_and_deterministic_lists() -> None:
    repository = MemoryCatalogSourceRuleRepository()
    first = make_rule(number=1)
    second = make_rule(
        number=2,
        integration_id=INTEGRATION_B,
        source_category_id="fortnite-accounts",
        section_code="accounts",
    )
    other_tenant = make_rule(
        number=3,
        tenant_id=TENANT_B,
        source_category_id="fortnite-vbucks",
    )
    updated = replace(
        first,
        source_category_name="V-Bucks",
        updated_at=first.updated_at + timedelta(minutes=5),
        version=2,
    )

    for rule in (first, second, other_tenant, updated):
        run_async(repository.save(rule))

    assert (
        run_async(
            repository.get_by_source(
                TENANT_A,
                INTEGRATION_A,
                " PLAYEROK ",
                " fortnite-vbucks ",
            )
        )
        == updated
    )
    assert (
        run_async(
            repository.get_by_source(
                TENANT_B,
                INTEGRATION_A,
                "playerok",
                "fortnite-vbucks",
            )
        )
        == other_tenant
    )
    assert tuple(run_async(repository.list_by_tenant(TENANT_A))) == (updated, second)
    assert tuple(
        run_async(repository.list_by_integration(TENANT_A, INTEGRATION_B))
    ) == (second,)


def test_memory_repository_rejects_cross_tenant_id_and_duplicate_source() -> None:
    repository = MemoryCatalogSourceRuleRepository()
    original = make_rule()
    run_async(repository.save(original))

    with pytest.raises(RepositoryIdentityConflictError):
        run_async(repository.save(replace(original, tenant_id=TENANT_B)))

    with pytest.raises(RepositoryIdentityConflictError):
        run_async(repository.save(make_rule(number=2)))


def test_provider_exposes_isolated_memory_catalog_source_rules() -> None:
    left = create_memory_provider()
    right = create_memory_provider()
    rule = make_rule()

    run_async(left.catalog_source_rules.save(rule))

    assert tuple(run_async(left.catalog_source_rules.list_by_tenant(TENANT_A))) == (
        rule,
    )
    assert tuple(run_async(right.catalog_source_rules.list_by_tenant(TENANT_A))) == ()


def test_catalog_source_rule_metadata_has_required_integrity_constraints() -> None:
    table = cast(Table, CatalogSourceRuleRecord.__table__)
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    unique = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_catalog_source_rules_source_identity"
    )

    assert {
        "ck_catalog_source_rules_marketplace_nonempty",
        "ck_catalog_source_rules_source_id_nonempty",
        "ck_catalog_source_rules_source_name_nonempty",
        "ck_catalog_source_rules_hub_code_nonempty",
        "ck_catalog_source_rules_section_code_nonempty",
        "ck_catalog_source_rules_timestamp_order",
        "ck_catalog_source_rules_version",
    } <= checks
    assert tuple(column.name for column in unique.columns) == (
        "tenant_id",
        "integration_id",
        "marketplace",
        "source_category_id",
    )
    assert {index.name for index in table.indexes} == {
        "ix_catalog_source_rules_tenant_hub_section",
        "ix_catalog_source_rules_tenant_integration",
    }
