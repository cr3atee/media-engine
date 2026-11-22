"""Correct catalog categories without rewriting offer review history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from app.catalog.categories import CatalogCategoryCode, resolve_catalog_category
from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    build_admin_request_fingerprint,
    normalize_optional_reason,
    utc_now,
)
from app.services.admin_mutations import AdminCommandContext
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class ChangeProductCategoryCommand:
    """Compare-and-set category command; version counts category audit revisions."""

    tenant_id: UUID
    product_id: UUID
    expected_version: int
    expected_category: CatalogCategoryCode
    category: CatalogCategoryCode
    reason: str


class ProductCategoryChangeError(ValueError):
    """A safe category correction rejection with a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CanonicalProductCategoryService:
    """Persist a category and its immutable audit in one repository transaction."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        """Reuse the existing transaction and repository boundary."""
        self._scope = repository_scope_factory

    async def change(
        self,
        command: ChangeProductCategoryCommand,
        context: AdminCommandContext,
    ) -> AdminAction:
        """Apply an explicit operator correction or return its original audit."""
        if context.tenant_id != command.tenant_id or not context.elevated:
            raise ProductCategoryChangeError("permission_denied")
        old = resolve_catalog_category(command.expected_category)
        new = resolve_catalog_category(command.category)
        reason = normalize_optional_reason(command.reason)
        if old is None or new is None or old == new or command.expected_version < 1:
            raise ProductCategoryChangeError("invalid_category_change")
        if reason is None:
            raise ProductCategoryChangeError("reason_required")
        fingerprint = build_admin_request_fingerprint(
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            elevated=context.elevated,
            tenant_id=command.tenant_id,
            action=AdminActionType.CHANGE_PRODUCT_CATEGORY,
            resource_type=AdminResourceType.CANONICAL_PRODUCT,
            resource_id=command.product_id,
            expected_version=command.expected_version,
            reason=reason,
            metadata=(("previous_category", old.code), ("category", new.code)),
        )
        async with self._scope() as repositories:
            actions = repositories.admin_actions
            await actions.acquire_idempotency_lock(
                f"product-category:{command.product_id}", command.tenant_id
            )
            await actions.acquire_idempotency_lock(
                context.idempotency_key, command.tenant_id
            )
            existing = await actions.get_by_idempotency_key(
                context.idempotency_key, command.tenant_id
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ProductCategoryChangeError("idempotency_conflict")
                return existing
            product = await repositories.canonical_products.get_by_tenant_and_id(
                command.tenant_id, command.product_id
            )
            if product is None:
                raise ProductCategoryChangeError("product_not_found")
            trail = await actions.list_for_resource(
                AdminResourceType.CANONICAL_PRODUCT, product.id
            )
            version = max(
                (
                    item.resulting_version
                    for item in trail
                    if item.tenant_id == product.tenant_id
                ),
                default=1,
            )
            if (
                version != command.expected_version
                or resolve_catalog_category(product.category) != old
            ):
                raise ProductCategoryChangeError("category_version_conflict")
            await repositories.canonical_products.save(
                replace(product, category=new.name)
            )
            return await actions.append(
                AdminAction(
                    id=uuid4(),
                    tenant_id=command.tenant_id,
                    action=AdminActionType.CHANGE_PRODUCT_CATEGORY,
                    resource_type=AdminResourceType.CANONICAL_PRODUCT,
                    resource_id=product.id,
                    previous_state=old.code,
                    resulting_state=new.code,
                    actor_id=context.actor_id,
                    actor_type=context.actor_type,
                    elevated=context.elevated,
                    request_id=context.request_id,
                    idempotency_key=context.idempotency_key,
                    request_fingerprint=fingerprint,
                    expected_version=version,
                    resulting_version=version + 1,
                    reason=reason,
                    metadata=(("previous_category", old.code), ("category", new.code)),
                    created_at=utc_now(),
                )
            )
