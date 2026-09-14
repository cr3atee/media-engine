from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    get_public_category_read_service,
    get_public_comparison_read_service,
    get_public_offer_read_service,
    get_public_price_change_read_service,
    get_public_price_history_read_service,
    get_public_product_read_service,
)
from app.api.errors import ApiError
from app.api.public_mappers import (
    public_category,
    public_comparison_result,
    public_offer_summary,
    public_price_change,
    public_price_history_point,
    public_product_card,
    public_product_detail,
)
from app.api.routes.helpers import next_cursor, page_request
from app.api.schemas.common import PageResponse
from app.api.schemas.public import (
    PublicCategoriesQueryParams,
    PublicCategory,
    PublicComparisonResult,
    PublicOffersQueryParams,
    PublicOfferSummary,
    PublicPriceChange,
    PublicPriceChangesQueryParams,
    PublicPriceHistoryPoint,
    PublicPriceHistoryQueryParams,
    PublicProductCard,
    PublicProductDetail,
    PublicProductsQueryParams,
)
from app.repositories.public_queries.models import (
    PublicCategoryQuery,
    PublicOfferQuery,
    PublicPriceChangeQuery,
    PublicPriceHistoryQuery,
    PublicProductQuery,
)
from app.services.public_categories import PublicCategoryReadService
from app.services.public_comparisons import PublicComparisonReadService
from app.services.public_offers import PublicOfferReadService
from app.services.public_price_changes import PublicPriceChangeReadService
from app.services.public_price_history import PublicPriceHistoryReadService
from app.services.public_products import PublicProductReadService

router = APIRouter(prefix="/api/v1/public", tags=["Public"])


@router.get("/products", response_model=PageResponse[PublicProductCard])
async def list_public_products(
    request: Request,
    params: Annotated[PublicProductsQueryParams, Depends()],
    service: Annotated[
        PublicProductReadService,
        Depends(get_public_product_read_service),
    ],
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> PageResponse[PublicProductCard]:
    """List public product cards for Market Terminal browse and search."""
    page = page_request(request, resource="public_products", params=params)
    result = await service.list_products(
        PublicProductQuery(
            search=params.search or q,
            category=params.category,
            marketplace=params.marketplace,
            min_price=params.min_price,
            max_price=params.max_price,
        ),
        page,
    )
    return PageResponse(
        items=[public_product_card(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/products/{product_id}", response_model=PublicProductDetail)
async def get_public_product(
    product_id: UUID,
    service: Annotated[
        PublicProductReadService,
        Depends(get_public_product_read_service),
    ],
) -> PublicProductDetail:
    """Return one public product detail for Market Terminal."""
    product = await service.get_product(product_id)
    if product is None:
        raise ApiError(404, "not_found", "Product was not found.")
    return public_product_detail(product)


@router.get(
    "/products/{product_id}/offers",
    response_model=PageResponse[PublicOfferSummary],
)
async def list_public_product_offers(
    request: Request,
    product_id: UUID,
    params: Annotated[PublicOffersQueryParams, Depends()],
    service: Annotated[
        PublicOfferReadService,
        Depends(get_public_offer_read_service),
    ],
) -> PageResponse[PublicOfferSummary]:
    """List public marketplace offers for one canonical product."""
    page = page_request(
        request,
        resource="public_product_offers",
        params=params,
        extra_filters={"product_id": product_id},
    )
    result = await service.list_offers(
        PublicOfferQuery(
            product_id=product_id,
            marketplace=params.marketplace,
            min_price=params.min_price,
            max_price=params.max_price,
        ),
        page,
    )
    return PageResponse(
        items=[public_offer_summary(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get(
    "/products/{product_id}/comparison",
    response_model=PublicComparisonResult,
)
async def get_public_product_comparison(
    product_id: UUID,
    service: Annotated[
        PublicComparisonReadService,
        Depends(get_public_comparison_read_service),
    ],
) -> PublicComparisonResult:
    """Return a UI-safe comparison result for one canonical product."""
    comparison = await service.get_comparison(product_id)
    if comparison is None:
        raise ApiError(404, "not_found", "Product comparison was not found.")
    return public_comparison_result(comparison)


@router.get(
    "/products/{product_id}/price-history",
    response_model=PageResponse[PublicPriceHistoryPoint],
)
async def list_public_product_price_history(
    request: Request,
    product_id: UUID,
    params: Annotated[PublicPriceHistoryQueryParams, Depends()],
    service: Annotated[
        PublicPriceHistoryReadService,
        Depends(get_public_price_history_read_service),
    ],
) -> PageResponse[PublicPriceHistoryPoint]:
    """List public price-history points for a product chart."""
    collected_to = datetime.now(UTC)
    page = page_request(
        request,
        resource="public_product_price_history",
        params=params,
        extra_filters={"product_id": product_id},
    )
    result = await service.list_price_history(
        PublicPriceHistoryQuery(
            product_id=product_id,
            marketplace=params.marketplace,
            collected_from=_period_start(params.period, now=collected_to),
            collected_to=collected_to if params.period != "all" else None,
        ),
        page,
    )
    return PageResponse(
        items=[public_price_history_point(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/price-changes", response_model=PageResponse[PublicPriceChange])
async def list_public_price_changes(
    request: Request,
    params: Annotated[PublicPriceChangesQueryParams, Depends()],
    service: Annotated[
        PublicPriceChangeReadService,
        Depends(get_public_price_change_read_service),
    ],
) -> PageResponse[PublicPriceChange]:
    """List public latest price changes for feeds and product pages."""
    page = page_request(request, resource="public_price_changes", params=params)
    result = await service.list_price_changes(
        PublicPriceChangeQuery(
            product_id=params.product_id,
            marketplace=params.marketplace,
            changed_from=params.changed_from,
            changed_to=params.changed_to,
        ),
        page,
    )
    return PageResponse(
        items=[public_price_change(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


@router.get("/categories", response_model=PageResponse[PublicCategory])
async def list_public_categories(
    request: Request,
    params: Annotated[PublicCategoriesQueryParams, Depends()],
    service: Annotated[
        PublicCategoryReadService,
        Depends(get_public_category_read_service),
    ],
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> PageResponse[PublicCategory]:
    """List public product categories for browse and filter UIs."""
    page = page_request(request, resource="public_categories", params=params)
    result = await service.list_categories(
        PublicCategoryQuery(search=params.search or q),
        page,
    )
    return PageResponse(
        items=[public_category(item) for item in result.items],
        next_cursor=next_cursor(request, position=result.next_cursor),
        page_size=page.limit,
    )


def _period_start(period: str, *, now: datetime) -> datetime | None:
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "90d":
        return now - timedelta(days=90)
    if period == "1y":
        return now - timedelta(days=365)
    return None
