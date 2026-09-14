from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import AdminApiSettings
from app.main import create_app
from app.repositories.public_queries.contracts import (
    PublicCategoryQueryRepository,
    PublicComparisonQueryRepository,
    PublicOfferQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicProductQueryRepository,
)
from app.repositories.public_queries.models import (
    CategoryRead,
    OfferSummaryRead,
    PriceChangeRead,
    PriceDifferenceRead,
    PriceHistoryPointRead,
    ProductComparisonRead,
    ProductDetailRead,
    ProductSummaryRead,
    PublicCategoryQuery,
    PublicOfferQuery,
    PublicPriceChangeQuery,
    PublicPriceHistoryQuery,
    PublicProductQuery,
)
from app.repositories.public_queries.provider import PublicReadRepositoryProvider
from app.repositories.queries.models import PageRequest, ReadPage

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


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


def _product_summary() -> ProductSummaryRead:
    return ProductSummaryRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        best_offer=_offer(),
        offer_count=2,
        marketplace_count=2,
        updated_at=NOW,
    )


def _product_detail() -> ProductDetailRead:
    return ProductDetailRead(
        id=UUID(int=1),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft", "mc"),
        best_offer=_offer(),
        offer_count=2,
        marketplace_count=2,
        updated_at=NOW,
    )


class PublicReadFixtureRepository(
    PublicProductQueryRepository,
    PublicOfferQueryRepository,
    PublicComparisonQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicCategoryQueryRepository,
):
    """Deterministic public read repository used by route tests."""

    def __init__(self) -> None:
        """Prepare recorded query slots for assertions."""
        self.product_query: PublicProductQuery | None = None
        self.offer_query: PublicOfferQuery | None = None
        self.history_query: PublicPriceHistoryQuery | None = None
        self.price_change_query: PublicPriceChangeQuery | None = None
        self.category_query: PublicCategoryQuery | None = None

    async def list_products(
        self,
        query: PublicProductQuery,
        page: PageRequest,
    ) -> ReadPage[ProductSummaryRead]:
        """Return one configured product summary."""
        del page
        self.product_query = query
        return ReadPage(items=(_product_summary(),), next_cursor=None)

    async def get_product(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductDetailRead | None:
        """Return one product detail when the identifier is known."""
        del tenant_id
        if product_id != UUID(int=1):
            return None
        return _product_detail()

    async def list_offers(
        self,
        query: PublicOfferQuery,
        page: PageRequest,
    ) -> ReadPage[OfferSummaryRead]:
        """Return configured offer summaries."""
        del page
        self.offer_query = query
        return ReadPage(items=(_offer(),), next_cursor=None)

    async def get_comparison(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductComparisonRead | None:
        """Return a configured comparison for the known product."""
        del tenant_id
        if product_id != UUID(int=1):
            return None
        other_offer = _offer(Decimal("990.00"))
        return ProductComparisonRead(
            product=_product_detail(),
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

    async def list_price_history(
        self,
        query: PublicPriceHistoryQuery,
        page: PageRequest,
    ) -> ReadPage[PriceHistoryPointRead]:
        """Return configured history points."""
        del page
        self.history_query = query
        return ReadPage(
            items=(
                PriceHistoryPointRead(
                    marketplace="playerok",
                    price=Decimal("990.00"),
                    currency="RUB",
                    collected_at=NOW,
                ),
            ),
            next_cursor=None,
        )

    async def list_price_changes(
        self,
        query: PublicPriceChangeQuery,
        page: PageRequest,
    ) -> ReadPage[PriceChangeRead]:
        """Return configured latest price changes."""
        del page
        self.price_change_query = query
        return ReadPage(
            items=(
                PriceChangeRead(
                    product_id=UUID(int=1),
                    product_name="Minecraft Premium",
                    marketplace="playerok",
                    old_price=Decimal("990.00"),
                    new_price=Decimal("790.00"),
                    currency="RUB",
                    discount_percent=Decimal("20.20"),
                    changed_at=NOW,
                    url="https://example.com/product",
                ),
            ),
            next_cursor=None,
        )

    async def list_categories(
        self,
        query: PublicCategoryQuery,
        page: PageRequest,
    ) -> ReadPage[CategoryRead]:
        """Return configured categories."""
        del page
        self.category_query = query
        return ReadPage(
            items=(CategoryRead(code="games", name="Games", product_count=1),),
            next_cursor=None,
        )


def _client() -> tuple[TestClient, PublicReadFixtureRepository]:
    repository = PublicReadFixtureRepository()

    @asynccontextmanager
    async def scope() -> AsyncIterator[PublicReadRepositoryProvider]:
        yield PublicReadRepositoryProvider(
            products=repository,
            offers=repository,
            comparisons=repository,
            price_history=repository,
            price_changes=repository,
            categories=repository,
        )

    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("test-secret"),
        ),
        public_read_repository_scope_factory=scope,
    )
    return TestClient(app), repository


def test_public_products_are_available_without_admin_authentication() -> None:
    client, repository = _client()

    response = client.get("/api/v1/public/products?q=minecraft&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["name"] == "Minecraft Premium"
    assert body["items"][0]["best_offer"]["price"] == "790.00"
    assert repository.product_query is not None
    assert repository.product_query.search == "minecraft"


def test_public_product_detail_offers_and_comparison_are_readable() -> None:
    client, repository = _client()

    detail = client.get(f"/api/v1/public/products/{UUID(int=1)}")
    offers = client.get(
        f"/api/v1/public/products/{UUID(int=1)}/offers?marketplace=playerok",
    )
    comparison = client.get(f"/api/v1/public/products/{UUID(int=1)}/comparison")

    assert detail.status_code == 200
    assert detail.json()["aliases"] == ["minecraft", "mc"]
    assert offers.status_code == 200
    assert offers.json()["items"][0]["marketplace"] == "playerok"
    assert repository.offer_query is not None
    assert repository.offer_query.product_id == UUID(int=1)
    assert comparison.status_code == 200
    assert comparison.json()["status"] == "complete"


def test_public_history_changes_and_categories_are_readable() -> None:
    client, repository = _client()

    history = client.get(
        f"/api/v1/public/products/{UUID(int=1)}/price-history?period=7d",
    )
    changes = client.get("/api/v1/public/price-changes?marketplace=playerok")
    categories = client.get("/api/v1/public/categories?q=game")

    assert history.status_code == 200
    assert history.json()["items"][0]["price"] == "990.00"
    assert repository.history_query is not None
    assert repository.history_query.collected_from is not None
    assert changes.status_code == 200
    assert changes.json()["items"][0]["discount_percent"] == "20.20"
    assert repository.price_change_query is not None
    assert repository.price_change_query.marketplace == "playerok"
    assert categories.status_code == 200
    assert categories.json()["items"][0]["code"] == "games"
    assert repository.category_query is not None
    assert repository.category_query.search == "game"


def test_public_routes_return_stable_errors() -> None:
    client, _ = _client()

    missing = client.get(f"/api/v1/public/products/{UUID(int=999)}")
    invalid_limit = client.get("/api/v1/public/products?limit=101")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["error"]["code"] == "validation_error"


def test_public_read_api_reports_unconfigured_provider_safely() -> None:
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("test-secret"),
        )
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/public/products")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "public_read_api_unavailable"
    assert "test-secret" not in response.text
