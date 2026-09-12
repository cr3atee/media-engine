from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.repositories.public_queries.contracts import PublicProductQueryRepository
from app.repositories.public_queries.models import (
    OfferSummaryRead,
    ProductDetailRead,
    ProductSummaryRead,
    PublicProductQuery,
)
from app.repositories.queries.models import PageRequest, ReadPage
from app.services.public_products import PublicProductReadService


def _page_request() -> PageRequest:
    return PageRequest(
        limit=20,
        sort="recently_updated",
        direction="desc",
        filter_hash="filters",
    )


def _offer() -> OfferSummaryRead:
    return OfferSummaryRead(
        marketplace="playerok",
        external_id="offer-1",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=Decimal("790.00"),
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
        canonical_product_id=UUID(int=1),
    )


def _summary() -> ProductSummaryRead:
    return ProductSummaryRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        best_offer=_offer(),
        offer_count=2,
        marketplace_count=2,
        updated_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )


def _detail() -> ProductDetailRead:
    return ProductDetailRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft", "mc"),
        best_offer=_offer(),
        offer_count=2,
        marketplace_count=2,
        updated_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )


class RecordingProductRepository(PublicProductQueryRepository):
    """Small public product query repository used by service tests."""

    def __init__(
        self,
        *,
        products: tuple[ProductSummaryRead, ...],
        detail: ProductDetailRead | None,
    ) -> None:
        """Store deterministic fixture results and recorded calls."""
        self.products = products
        self.detail = detail
        self.list_call: tuple[PublicProductQuery, PageRequest] | None = None
        self.get_call: tuple[UUID, UUID | None] | None = None

    async def list_products(
        self,
        query: PublicProductQuery,
        page: PageRequest,
    ) -> ReadPage[ProductSummaryRead]:
        """Return configured product summaries."""
        self.list_call = (query, page)
        return ReadPage(items=self.products, next_cursor=None)

    async def get_product(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductDetailRead | None:
        """Return the configured product detail projection."""
        self.get_call = (product_id, tenant_id)
        return self.detail


def test_public_product_service_lists_product_cards() -> None:
    asyncio.run(_test_public_product_service_lists_product_cards())


async def _test_public_product_service_lists_product_cards() -> None:
    query = PublicProductQuery(search="minecraft", marketplace="playerok")
    page = _page_request()
    repository = RecordingProductRepository(products=(_summary(),), detail=None)
    service = PublicProductReadService(repository)

    result = await service.list_products(query, page)

    assert result.items == repository.products
    assert result.next_cursor is None
    assert repository.list_call == (query, page)
    assert result.items[0].best_offer is not None
    assert result.items[0].best_offer.price == Decimal("790.00")


def test_public_product_service_gets_product_detail() -> None:
    asyncio.run(_test_public_product_service_gets_product_detail())


async def _test_public_product_service_gets_product_detail() -> None:
    tenant_id = UUID(int=10)
    detail = _detail()
    repository = RecordingProductRepository(products=(), detail=detail)
    service = PublicProductReadService(repository)

    result = await service.get_product(detail.id, tenant_id)

    assert result == detail
    assert repository.get_call == (detail.id, tenant_id)
    assert result is not None
    assert result.aliases == ("minecraft", "mc")


def test_public_product_service_returns_none_for_missing_detail() -> None:
    asyncio.run(_test_public_product_service_returns_none_for_missing_detail())


async def _test_public_product_service_returns_none_for_missing_detail() -> None:
    repository = RecordingProductRepository(products=(), detail=None)
    service = PublicProductReadService(repository)

    result = await service.get_product(UUID(int=999))

    assert result is None
    assert repository.get_call == (UUID(int=999), None)


def test_public_product_service_has_no_transport_or_orm_dependencies() -> None:
    path = Path("app/services/public_products.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "sqlalchemy",
        "app.api",
        "app.database",
        "app.telegram",
        "app.adapters.telegram",
    )

    assert not any(
        module.startswith(prefix) for module in imports for prefix in forbidden
    )
