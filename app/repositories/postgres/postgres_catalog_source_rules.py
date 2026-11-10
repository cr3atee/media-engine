from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.hierarchy import CatalogSourceRule
from app.models.catalog_source_rule_record import CatalogSourceRuleRecord
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.catalog_source_rules import CatalogSourceRuleRepository


class PostgresCatalogSourceRuleRepository(CatalogSourceRuleRepository):
    """PostgreSQL storage for tenant- and integration-scoped catalog rules."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a caller-owned session and transaction."""
        self._session = session

    async def save(self, rule: CatalogSourceRule) -> CatalogSourceRule:
        """Persist one rule while enforcing its exact source identity."""
        existing = await self._session.get(CatalogSourceRuleRecord, rule.id)
        if existing is not None and existing.tenant_id != rule.tenant_id:
            msg = f"Catalog source rule ID already exists: {rule.id}."
            raise RepositoryIdentityConflictError(msg)
        conflict = await self._find_source_conflict(rule)
        if conflict is not None:
            msg = (
                "Catalog source rule identity already exists: "
                f"{rule.marketplace}:{rule.source_category_id}."
            )
            raise RepositoryIdentityConflictError(msg)

        if existing is None:
            self._session.add(_to_record(rule))
        else:
            _update_record(existing, rule)
        await self._session.flush()
        return rule

    async def get_by_source(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        marketplace: str,
        source_category_id: str,
    ) -> CatalogSourceRule | None:
        """Return one rule only for the requested tenant integration source."""
        result = await self._session.execute(
            select(CatalogSourceRuleRecord).where(
                CatalogSourceRuleRecord.tenant_id == tenant_id,
                CatalogSourceRuleRecord.integration_id == integration_id,
                CatalogSourceRuleRecord.marketplace == marketplace.strip().casefold(),
                CatalogSourceRuleRecord.source_category_id
                == source_category_id.strip(),
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record is not None else None

    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> Sequence[CatalogSourceRule]:
        """Return rules for one integration in deterministic order."""
        result = await self._session.execute(
            select(CatalogSourceRuleRecord)
            .where(
                CatalogSourceRuleRecord.tenant_id == tenant_id,
                CatalogSourceRuleRecord.integration_id == integration_id,
            )
            .order_by(
                CatalogSourceRuleRecord.created_at,
                CatalogSourceRuleRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[CatalogSourceRule]:
        """Return tenant-owned rules in deterministic order."""
        result = await self._session.execute(
            select(CatalogSourceRuleRecord)
            .where(CatalogSourceRuleRecord.tenant_id == tenant_id)
            .order_by(
                CatalogSourceRuleRecord.created_at,
                CatalogSourceRuleRecord.id,
            )
        )
        return tuple(_to_domain(record) for record in result.scalars())

    async def _find_source_conflict(self, rule: CatalogSourceRule) -> UUID | None:
        result = await self._session.execute(
            select(CatalogSourceRuleRecord.id)
            .where(
                CatalogSourceRuleRecord.tenant_id == rule.tenant_id,
                CatalogSourceRuleRecord.integration_id == rule.integration_id,
                CatalogSourceRuleRecord.marketplace == rule.marketplace,
                CatalogSourceRuleRecord.source_category_id == rule.source_category_id,
                CatalogSourceRuleRecord.id != rule.id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def _to_record(rule: CatalogSourceRule) -> CatalogSourceRuleRecord:
    return CatalogSourceRuleRecord(
        id=rule.id,
        tenant_id=rule.tenant_id,
        integration_id=rule.integration_id,
        marketplace=rule.marketplace,
        source_category_id=rule.source_category_id,
        source_category_name=rule.source_category_name,
        hub_code=rule.hub_code,
        section_code=rule.section_code,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        version=rule.version,
    )


def _update_record(
    record: CatalogSourceRuleRecord,
    rule: CatalogSourceRule,
) -> None:
    record.integration_id = rule.integration_id
    record.marketplace = rule.marketplace
    record.source_category_id = rule.source_category_id
    record.source_category_name = rule.source_category_name
    record.hub_code = rule.hub_code
    record.section_code = rule.section_code
    record.updated_at = rule.updated_at
    record.version = rule.version


def _to_domain(record: CatalogSourceRuleRecord) -> CatalogSourceRule:
    return CatalogSourceRule(
        id=record.id,
        tenant_id=record.tenant_id,
        integration_id=record.integration_id,
        marketplace=record.marketplace,
        source_category_id=record.source_category_id,
        source_category_name=record.source_category_name,
        hub_code=record.hub_code,
        section_code=record.section_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
        version=record.version,
    )
