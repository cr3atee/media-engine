from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.repositories.public_queries.contracts import PublicPriceHistoryQueryRepository
from app.repositories.public_queries.models import (
    PriceHistoryPointRead,
    PublicPriceHistoryQuery,
)
from app.repositories.queries.models import PageRequest, ReadPage
from app.services.public_price_history import PublicPriceHistoryReadService


def _page_request() -> PageRequest:
    return PageRequest(
        limit=100,
        sort="collected_at",
        direction="asc",
        filter_hash="filters",
    )


def _history_point(
    *,
    price: Decimal,
    collected_at: datetime,
) -> PriceHistoryPointRead:
    return PriceHistoryPointRead(
        marketplace="playerok",
        price=price,
        currency="RUB",
        collected_at=collected_at,
    )


class RecordingPriceHistoryRepository(PublicPriceHistoryQueryRepository):
    """Small price-history query repository used by service tests."""

    def __init__(self, points: tuple[PriceHistoryPointRead, ...]) -> None:
        """Store deterministic fixture points and recorded calls."""
        self.points = points
        self.list_call: tuple[PublicPriceHistoryQuery, PageRequest] | None = None

    async def list_price_history(
        self,
        query: PublicPriceHistoryQuery,
        page: PageRequest,
    ) -> ReadPage[PriceHistoryPointRead]:
        """Return configured price-history points."""
        self.list_call = (query, page)
        return ReadPage(items=self.points, next_cursor=None)


def test_public_price_history_service_lists_chart_points() -> None:
    asyncio.run(_test_public_price_history_service_lists_chart_points())


async def _test_public_price_history_service_lists_chart_points() -> None:
    query = PublicPriceHistoryQuery(
        product_id=UUID(int=1),
        marketplace="playerok",
        collected_from=datetime(2026, 9, 13, 0, 0, tzinfo=UTC),
    )
    page = _page_request()
    points = (
        _history_point(
            price=Decimal("990.00"),
            collected_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        ),
        _history_point(
            price=Decimal("790.00"),
            collected_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        ),
    )
    repository = RecordingPriceHistoryRepository(points)
    service = PublicPriceHistoryReadService(repository)

    result = await service.list_price_history(query, page)

    assert result.items == points
    assert result.next_cursor is None
    assert repository.list_call == (query, page)
    assert result.items[0].price == Decimal("990.00")
    assert result.items[1].collected_at == datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def test_public_price_history_service_has_no_forbidden_dependencies() -> None:
    path = Path("app/services/public_price_history.py")
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
