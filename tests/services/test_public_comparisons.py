from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.repositories.public_queries.contracts import PublicComparisonQueryRepository
from app.repositories.public_queries.models import (
    OfferSummaryRead,
    PriceDifferenceRead,
    ProductComparisonRead,
    ProductDetailRead,
)
from app.services.public_comparisons import PublicComparisonReadService


def _offer(price: Decimal = Decimal("790.00")) -> OfferSummaryRead:
    return OfferSummaryRead(
        marketplace="playerok",
        external_id="offer-1",
        title="Minecraft Premium",
        url="https://example.com/product",
        price=price,
        currency="RUB",
        seller_id="seller-1",
        seller_name="Seller",
        canonical_product_id=UUID(int=1),
    )


def _product() -> ProductDetailRead:
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


def _comparison() -> ProductComparisonRead:
    other_offer = _offer(Decimal("990.00"))
    return ProductComparisonRead(
        product=_product(),
        offers=(_offer(), other_offer),
        best_offer=_offer(),
        differences=(
            PriceDifferenceRead(
                offer=other_offer,
                absolute_difference=Decimal("200.00"),
                percentage_difference=Decimal("25.316455"),
                reason=None,
            ),
        ),
        status="complete",
    )


class RecordingComparisonRepository(PublicComparisonQueryRepository):
    """Small comparison query repository used by service tests."""

    def __init__(self, result: ProductComparisonRead | None) -> None:
        """Store a deterministic comparison result and recorded call."""
        self.result = result
        self.get_call: tuple[UUID, UUID | None] | None = None

    async def get_comparison(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductComparisonRead | None:
        """Return the configured comparison projection."""
        self.get_call = (product_id, tenant_id)
        return self.result


def test_public_comparison_service_gets_comparison() -> None:
    asyncio.run(_test_public_comparison_service_gets_comparison())


async def _test_public_comparison_service_gets_comparison() -> None:
    product_id = UUID(int=1)
    tenant_id = UUID(int=10)
    comparison = _comparison()
    repository = RecordingComparisonRepository(comparison)
    service = PublicComparisonReadService(repository)

    result = await service.get_comparison(product_id, tenant_id)

    assert result == comparison
    assert repository.get_call == (product_id, tenant_id)
    assert result is not None
    assert result.status == "complete"
    assert result.best_offer is not None
    assert result.best_offer.price == Decimal("790.00")


def test_public_comparison_service_returns_none_for_missing_comparison() -> None:
    asyncio.run(_test_public_comparison_service_returns_none_for_missing_comparison())


async def _test_public_comparison_service_returns_none_for_missing_comparison() -> None:
    product_id = UUID(int=999)
    repository = RecordingComparisonRepository(None)
    service = PublicComparisonReadService(repository)

    result = await service.get_comparison(product_id)

    assert result is None
    assert repository.get_call == (product_id, None)


def test_public_comparison_service_has_no_forbidden_dependencies() -> None:
    path = Path("app/services/public_comparisons.py")
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
        "app.matching",
        "app.comparator",
    )

    assert not any(
        module.startswith(prefix) for module in imports for prefix in forbidden
    )
