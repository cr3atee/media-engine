from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.catalog.hierarchy import CatalogSourceRule
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.catalog_source_rules import CatalogSourceRuleRepository


class MemoryCatalogSourceRuleRepository(CatalogSourceRuleRepository):
    """Deterministic in-memory storage for verified catalog source rules."""

    def __init__(self) -> None:
        """Initialize isolated rule storage preserving insertion order."""
        self._rules_by_id: dict[UUID, CatalogSourceRule] = {}
        self._order: list[UUID] = []

    async def save(self, rule: CatalogSourceRule) -> CatalogSourceRule:
        """Persist one rule while enforcing tenant-scoped source identity."""
        existing = self._rules_by_id.get(rule.id)
        if existing is not None and existing.tenant_id != rule.tenant_id:
            msg = f"Catalog source rule ID already exists: {rule.id}."
            raise RepositoryIdentityConflictError(msg)
        self._ensure_unique_source(rule)
        if existing is None:
            self._order.append(rule.id)
        self._rules_by_id[rule.id] = rule
        return rule

    async def get_by_source(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        marketplace: str,
        source_category_id: str,
    ) -> CatalogSourceRule | None:
        """Return the exact source rule without cross-tenant fallback."""
        identity = _source_identity(
            tenant_id,
            integration_id,
            marketplace,
            source_category_id,
        )
        return next(
            (rule for rule in self._iter_ordered() if _rule_identity(rule) == identity),
            None,
        )

    async def list_by_integration(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> Sequence[CatalogSourceRule]:
        """Return rules for one integration in insertion order."""
        return tuple(
            rule
            for rule in self._iter_ordered()
            if rule.tenant_id == tenant_id and rule.integration_id == integration_id
        )

    async def list_by_tenant(self, tenant_id: UUID) -> Sequence[CatalogSourceRule]:
        """Return tenant-owned rules in insertion order."""
        return tuple(
            rule for rule in self._iter_ordered() if rule.tenant_id == tenant_id
        )

    def _iter_ordered(self) -> tuple[CatalogSourceRule, ...]:
        return tuple(self._rules_by_id[rule_id] for rule_id in self._order)

    def _ensure_unique_source(self, incoming: CatalogSourceRule) -> None:
        identity = _rule_identity(incoming)
        for stored in self._rules_by_id.values():
            if stored.id != incoming.id and _rule_identity(stored) == identity:
                msg = (
                    "Catalog source rule identity already exists: "
                    f"{incoming.marketplace}:{incoming.source_category_id}."
                )
                raise RepositoryIdentityConflictError(msg)


def _rule_identity(rule: CatalogSourceRule) -> tuple[UUID, UUID, str, str]:
    return (
        rule.tenant_id,
        rule.integration_id,
        rule.marketplace,
        rule.source_category_id,
    )


def _source_identity(
    tenant_id: UUID,
    integration_id: UUID,
    marketplace: str,
    source_category_id: str,
) -> tuple[UUID, UUID, str, str]:
    return (
        tenant_id,
        integration_id,
        marketplace.strip().casefold(),
        source_category_id.strip(),
    )
