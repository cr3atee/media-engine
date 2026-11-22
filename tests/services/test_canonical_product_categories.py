from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.catalog.categories import category_by_code
from app.domain.admin_actions import AdminAction, AdminResourceType
from app.models.canonical_product import CanonicalProduct
from app.repositories.memory.memory_admin_actions import MemoryAdminActionRepository
from app.repositories.provider import create_memory_provider
from app.services.admin_mutations import AdminCommandContext
from app.services.canonical_product_categories import (
    CanonicalProductCategoryService,
    ChangeProductCategoryCommand,
    ProductCategoryChangeError,
)
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("78000000-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("78000000-0000-4000-8000-000000000002")


def _product() -> CanonicalProduct:
    return CanonicalProduct(
        id=PRODUCT_ID,
        tenant_id=TENANT_ID,
        name="ExitLag 1 month Key",
        category=category_by_code("keys").name,
        aliases=("ExitLag monthly key",),
    )


def _command() -> ChangeProductCategoryCommand:
    return ChangeProductCategoryCommand(
        tenant_id=TENANT_ID,
        product_id=PRODUCT_ID,
        expected_version=1,
        expected_category="keys",
        category="subscriptions",
        reason="Product category is independent of its delivery method.",
    )


def _context(key: str = "category-correction") -> AdminCommandContext:
    return AdminCommandContext(
        tenant_id=TENANT_ID,
        actor_id="test-operator",
        elevated=True,
        request_id=key,
        idempotency_key=key,
    )


def test_category_change_is_audited_replayable_and_preserves_identity() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = _product()
        await provider.canonical_products.save(product)
        service = CanonicalProductCategoryService(
            create_memory_repository_scope(provider)
        )
        action = await service.change(_command(), _context())
        replay = await service.change(_command(), _context())
        assert action == replay
        assert action.previous_state == "keys"
        assert action.resulting_state == "subscriptions"
        assert (action.expected_version, action.resulting_version) == (1, 2)
        assert await provider.canonical_products.get_by_id(PRODUCT_ID) == replace(
            product, category=category_by_code("subscriptions").name
        )
        assert (
            len(
                await provider.admin_actions.list_for_resource(
                    AdminResourceType.CANONICAL_PRODUCT, PRODUCT_ID
                )
            )
            == 1
        )
        with pytest.raises(ProductCategoryChangeError, match="idempotency_conflict"):
            await service.change(replace(_command(), category="accounts"), _context())
        with pytest.raises(
            ProductCategoryChangeError, match="category_version_conflict"
        ):
            await service.change(_command(), _context("other-command"))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case", ["permission", "tenant", "missing", "reason", "noop", "version"]
)
def test_invalid_category_changes_do_not_write(case: str) -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = _product()
        await provider.canonical_products.save(product)
        command = _command()
        context = _context()
        if case == "permission":
            context = replace(context, elevated=False)
        elif case == "tenant":
            command = replace(command, tenant_id=uuid4())
            context = replace(context, tenant_id=command.tenant_id)
        elif case == "missing":
            command = replace(command, product_id=uuid4())
        elif case == "reason":
            command = replace(command, reason="  ")
        elif case == "noop":
            command = replace(command, category="keys")
        else:
            command = replace(command, expected_version=0)
        with pytest.raises(ProductCategoryChangeError):
            await CanonicalProductCategoryService(
                create_memory_repository_scope(provider)
            ).change(command, context)
        assert await provider.canonical_products.get_by_id(PRODUCT_ID) == product
        assert not await provider.admin_actions.list_for_resource(
            AdminResourceType.CANONICAL_PRODUCT, PRODUCT_ID
        )

    asyncio.run(scenario())


class FailingAuditRepository(MemoryAdminActionRepository):
    """Exercise rollback after the category has been written."""

    async def append(self, action: AdminAction) -> AdminAction:
        raise RuntimeError("controlled audit failure")


def test_audit_failure_rolls_back_category() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        product = _product()
        await provider.canonical_products.save(product)
        provider.admin_actions = FailingAuditRepository()
        with pytest.raises(RuntimeError, match="controlled audit failure"):
            await CanonicalProductCategoryService(
                create_memory_repository_scope(provider)
            ).change(_command(), _context())
        assert await provider.canonical_products.get_by_id(PRODUCT_ID) == product

    asyncio.run(scenario())


def test_conflicting_commands_have_only_one_winner() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        await provider.canonical_products.save(_product())
        service = CanonicalProductCategoryService(
            create_memory_repository_scope(provider)
        )
        outcomes = await asyncio.gather(
            service.change(_command(), _context("first")),
            service.change(
                replace(_command(), category="accounts"), _context("second")
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, AdminAction) for result in outcomes) == 1
        assert (
            sum(isinstance(result, ProductCategoryChangeError) for result in outcomes)
            == 1
        )

    asyncio.run(scenario())
