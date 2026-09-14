from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.comparator.difference import PriceDifferenceService
from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.result import ComparisonResultBuilder
from app.comparator.selector import BestOfferSelector
from app.domain.lifecycle import ScoringStatus
from app.domain.market_events import PriceDropMarketEvent
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider
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
from app.repositories.public_queries.provider import (
    PublicReadRepositoryProvider,
    PublicReadRepositoryScopeFactory,
)
from app.repositories.queries.models import PageRequest, ReadPage

_EVENT_READ_LIMIT = 1000


@dataclass(slots=True, frozen=True)
class _ProductContext:
    product: CanonicalProduct
    offers: tuple[ParsedOffer, ...]
    best_offer: OfferSummaryRead | None
    updated_at: datetime | None


class RepositoryBackedPublicReadRepository(
    PublicProductQueryRepository,
    PublicOfferQueryRepository,
    PublicComparisonQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicCategoryQueryRepository,
):
    """Public read adapter over the existing repository provider."""

    def __init__(self, provider: RepositoryProvider) -> None:
        """Bind public read projections to existing domain repositories."""
        self._provider = provider
        self._selector = BestOfferSelector()
        self._difference = PriceDifferenceService()
        self._result_builder = ComparisonResultBuilder()

    async def list_products(
        self,
        query: PublicProductQuery,
        page: PageRequest,
    ) -> ReadPage[ProductSummaryRead]:
        """Return public product cards from canonical products and offers."""
        products = await self._products(query.tenant_id)
        contexts = [await self._product_context(product) for product in products]
        filtered = [context for context in contexts if _product_matches(context, query)]
        ordered = _sort_product_contexts(filtered, page)
        return _read_page(
            [
                ProductSummaryRead(
                    id=context.product.id,
                    name=context.product.name,
                    category=context.product.category,
                    best_offer=context.best_offer,
                    offer_count=len(context.offers),
                    marketplace_count=len(
                        {offer.marketplace for offer in context.offers},
                    ),
                    updated_at=context.updated_at,
                )
                for context in ordered
            ],
            page,
        )

    async def get_product(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductDetailRead | None:
        """Return one public product detail projection by canonical ID."""
        product = await self._product_by_id(product_id, tenant_id)
        if product is None:
            return None
        context = await self._product_context(product)
        return _product_detail(context)

    async def list_offers(
        self,
        query: PublicOfferQuery,
        page: PageRequest,
    ) -> ReadPage[OfferSummaryRead]:
        """Return public offer summaries from parsed offer storage."""
        offers = await self._offers(query.tenant_id)
        filtered = [offer for offer in offers if _offer_matches(offer, query)]
        ordered = _sort_offers(filtered, page)
        return _read_page([_offer_summary(offer) for offer in ordered], page)

    async def get_comparison(
        self,
        product_id: UUID,
        tenant_id: UUID | None = None,
    ) -> ProductComparisonRead | None:
        """Return a public comparison projection built by existing comparator."""
        product = await self._product_by_id(product_id, tenant_id)
        if product is None:
            return None

        context = await self._product_context(product)
        comparison_input = _comparison_input(product.id, context.offers)
        selection = self._selector.select(comparison_input)
        difference = self._difference.compare(selection)
        result = self._result_builder.build(product, selection, difference)

        return ProductComparisonRead(
            product=_product_detail(context),
            offers=tuple(_offer_summary(item.offer) for item in result.grouped_offers),
            best_offer=(
                _offer_summary(result.best_offer.offer)
                if result.best_offer is not None
                else None
            ),
            differences=tuple(
                PriceDifferenceRead(
                    offer=_offer_summary(entry.offer.offer),
                    absolute_difference=entry.absolute_difference,
                    percentage_difference=entry.percentage_difference,
                    reason=entry.reason,
                )
                for entry in result.comparison_entries
            ),
            status=result.status.value,
        )

    async def list_price_history(
        self,
        query: PublicPriceHistoryQuery,
        page: PageRequest,
    ) -> ReadPage[PriceHistoryPointRead]:
        """Return public chart points for offers attached to a product."""
        if query.product_id is None:
            return ReadPage(items=(), next_cursor=None)

        offers = await self._offers(query.tenant_id)
        points: list[PriceHistoryPointRead] = []
        for offer in offers:
            if offer.canonical_product_id != query.product_id:
                continue
            if query.marketplace is not None and offer.marketplace != query.marketplace:
                continue
            if offer.external_id is None:
                continue
            history = await self._provider.price_history.get_history(
                offer.tenant_id,
                offer.marketplace,
                offer.external_id,
            )
            points.extend(
                PriceHistoryPointRead(
                    marketplace=snapshot.marketplace,
                    price=snapshot.price,
                    currency=snapshot.currency,
                    collected_at=snapshot.collected_at,
                )
                for snapshot in history
                if _history_point_matches(snapshot.collected_at, query)
            )

        points.sort(
            key=lambda point: (
                point.collected_at,
                point.marketplace,
                point.currency,
                point.price,
            ),
            reverse=page.direction == "desc",
        )
        return _read_page(points, page)

    async def list_price_changes(
        self,
        query: PublicPriceChangeQuery,
        page: PageRequest,
    ) -> ReadPage[PriceChangeRead]:
        """Return public price changes from durable price-drop events."""
        events = await self._provider.events.list_content_eligible(
            limit=_EVENT_READ_LIMIT,
        )
        changes: list[PriceChangeRead] = []
        for event in events:
            if not _price_change_event_matches(event, query):
                continue
            product_name = await self._product_name(event)
            if product_name is None:
                continue
            changes.append(
                PriceChangeRead(
                    product_id=event.canonical_product_id,
                    product_name=product_name,
                    marketplace=event.marketplace,
                    old_price=event.payload.old_price,
                    new_price=event.payload.new_price,
                    currency=event.payload.currency,
                    discount_percent=event.payload.percentage,
                    changed_at=event.occurred_at,
                    url=event.payload.url,
                )
            )

        changes.sort(
            key=lambda change: (
                change.changed_at,
                change.marketplace,
                change.product_name,
            ),
            reverse=page.direction == "desc",
        )
        return _read_page(changes, page)

    async def list_categories(
        self,
        query: PublicCategoryQuery,
        page: PageRequest,
    ) -> ReadPage[CategoryRead]:
        """Return categories derived from tenant-visible canonical products."""
        products = await self._products(query.tenant_id)
        counts: dict[str, tuple[str, int]] = {}
        for product in products:
            category = product.category.strip() if product.category else None
            if not category:
                continue
            code = _category_code(category)
            _, count = counts.get(code, (category, 0))
            counts[code] = (category, count + 1)

        categories = [
            CategoryRead(code=code, name=name, product_count=count)
            for code, (name, count) in counts.items()
            if _category_matches(name, query)
        ]
        categories.sort(
            key=(
                (lambda item: (item.product_count, item.name.casefold(), item.code))
                if page.sort == "product_count"
                else (lambda item: (item.name.casefold(), item.code))
            ),
            reverse=page.direction == "desc",
        )
        return _read_page(categories, page)

    async def _products(
        self,
        tenant_id: UUID | None,
    ) -> Sequence[CanonicalProduct]:
        if tenant_id is not None:
            return await self._provider.canonical_products.list_by_tenant(tenant_id)
        return await self._provider.canonical_products.list_all()

    async def _product_by_id(
        self,
        product_id: UUID,
        tenant_id: UUID | None,
    ) -> CanonicalProduct | None:
        if tenant_id is not None:
            return await self._provider.canonical_products.get_by_tenant_and_id(
                tenant_id,
                product_id,
            )
        return await self._provider.canonical_products.get_by_id(product_id)

    async def _offers(self, tenant_id: UUID | None) -> Sequence[ParsedOffer]:
        if tenant_id is not None:
            return await self._provider.offers.list_by_tenant(tenant_id)
        return await self._provider.offers.list_all()

    async def _product_context(self, product: CanonicalProduct) -> _ProductContext:
        offers = tuple(
            offer
            for offer in await self._provider.offers.list_by_tenant(product.tenant_id)
            if offer.canonical_product_id == product.id
        )
        return _ProductContext(
            product=product,
            offers=offers,
            best_offer=_best_offer(offers, self._selector),
            updated_at=await self._updated_at(offers),
        )

    async def _updated_at(
        self,
        offers: Sequence[ParsedOffer],
    ) -> datetime | None:
        latest: datetime | None = None
        for offer in offers:
            if offer.external_id is None:
                continue
            snapshot = await self._provider.price_history.get_last(
                offer.tenant_id,
                offer.marketplace,
                offer.external_id,
            )
            if snapshot is not None and (
                latest is None or snapshot.collected_at > latest
            ):
                latest = snapshot.collected_at
        return latest

    async def _product_name(self, event: PriceDropMarketEvent) -> str | None:
        if event.payload.title is not None:
            return event.payload.title
        if event.canonical_product_id is None:
            return None
        product = await self._provider.canonical_products.get_by_tenant_and_id(
            event.tenant_id,
            event.canonical_product_id,
        )
        return product.name if product is not None else None


def create_repository_backed_public_read_provider(
    provider: RepositoryProvider,
) -> PublicReadRepositoryProvider:
    """Create a public read provider backed by an existing repository provider."""
    repository = RepositoryBackedPublicReadRepository(provider)
    return PublicReadRepositoryProvider(
        products=repository,
        offers=repository,
        comparisons=repository,
        price_history=repository,
        price_changes=repository,
        categories=repository,
    )


def create_repository_backed_public_read_scope_factory(
    provider: RepositoryProvider,
) -> PublicReadRepositoryScopeFactory:
    """Create an async scope factory for FastAPI public read dependencies."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[PublicReadRepositoryProvider]:
        yield create_repository_backed_public_read_provider(provider)

    return cast(PublicReadRepositoryScopeFactory, scope)


def _read_page[TRead](
    items: Sequence[TRead],
    page: PageRequest,
) -> ReadPage[TRead]:
    return ReadPage(items=tuple(items[: page.limit]), next_cursor=None)


def _offer_summary(offer: ParsedOffer) -> OfferSummaryRead:
    return OfferSummaryRead(
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        title=offer.title,
        url=offer.url,
        price=offer.price,
        currency=offer.currency,
        seller_id=offer.seller_id,
        seller_name=offer.seller_name,
        canonical_product_id=offer.canonical_product_id,
    )


def _comparison_input(
    product_id: UUID | None,
    offers: Sequence[ParsedOffer],
) -> ProductComparisonInput:
    return ProductComparisonInput(
        canonical_product_id=product_id,
        offers=tuple(MarketplaceOffer(offer=offer) for offer in offers),
    )


def _best_offer(
    offers: Sequence[ParsedOffer],
    selector: BestOfferSelector,
) -> OfferSummaryRead | None:
    selection = selector.select(_comparison_input(None, offers))
    if selection.selected_offer is None:
        return None
    return _offer_summary(selection.selected_offer.offer)


def _product_detail(context: _ProductContext) -> ProductDetailRead:
    return ProductDetailRead(
        id=context.product.id,
        name=context.product.name,
        category=context.product.category,
        aliases=context.product.aliases,
        best_offer=context.best_offer,
        offer_count=len(context.offers),
        marketplace_count=len({offer.marketplace for offer in context.offers}),
        updated_at=context.updated_at,
    )


def _product_matches(context: _ProductContext, query: PublicProductQuery) -> bool:
    product = context.product
    if query.search is not None:
        needle = query.search.casefold()
        haystack = (product.name, *(product.aliases or ()))
        if not any(needle in value.casefold() for value in haystack):
            return False
    if query.category is not None and product.category != query.category:
        return False
    if query.marketplace is not None and not any(
        offer.marketplace == query.marketplace for offer in context.offers
    ):
        return False
    if query.min_price is not None or query.max_price is not None:
        return any(
            _price_in_range(offer.price, query.min_price, query.max_price)
            for offer in context.offers
        )
    return True


def _offer_matches(offer: ParsedOffer, query: PublicOfferQuery) -> bool:
    if query.tenant_id is not None and offer.tenant_id != query.tenant_id:
        return False
    if query.product_id is not None and offer.canonical_product_id != query.product_id:
        return False
    if query.marketplace is not None and offer.marketplace != query.marketplace:
        return False
    return _price_in_range(offer.price, query.min_price, query.max_price)


def _price_in_range(
    price: Decimal | None,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    if minimum is None and maximum is None:
        return True
    if price is None:
        return False
    if minimum is not None and price < minimum:
        return False
    return maximum is None or price <= maximum


def _history_point_matches(
    collected_at: datetime,
    query: PublicPriceHistoryQuery,
) -> bool:
    if query.collected_from is not None and collected_at < query.collected_from:
        return False
    return query.collected_to is None or collected_at <= query.collected_to


def _price_change_event_matches(
    event: PriceDropMarketEvent,
    query: PublicPriceChangeQuery,
) -> bool:
    if query.tenant_id is not None and event.tenant_id != query.tenant_id:
        return False
    if query.product_id is not None and event.canonical_product_id != query.product_id:
        return False
    if query.marketplace is not None and event.marketplace != query.marketplace:
        return False
    if query.changed_from is not None and event.occurred_at < query.changed_from:
        return False
    if query.changed_to is not None and event.occurred_at > query.changed_to:
        return False
    return event.scoring_status is ScoringStatus.SUCCEEDED


def _category_matches(name: str, query: PublicCategoryQuery) -> bool:
    if query.search is None:
        return True
    return query.search.casefold() in name.casefold()


def _category_code(name: str) -> str:
    return "-".join(name.strip().casefold().split())


def _sort_product_contexts(
    contexts: list[_ProductContext],
    page: PageRequest,
) -> list[_ProductContext]:
    if page.sort == "price_asc":
        return sorted(contexts, key=_product_price_key)
    if page.sort == "price_desc":
        priced = sorted(
            [
                context
                for context in contexts
                if context.best_offer is not None
                and context.best_offer.price is not None
            ],
            key=_product_price_key,
            reverse=True,
        )
        missing = [context for context in contexts if context not in priced]
        return priced + missing
    if page.sort == "popular":
        return sorted(
            contexts,
            key=lambda context: (
                len(context.offers),
                context.product.name.casefold(),
                context.product.id.hex,
            ),
            reverse=page.direction == "desc",
        )
    if page.sort == "name":
        return sorted(
            contexts,
            key=lambda context: (
                context.product.name.casefold(),
                context.product.id.hex,
            ),
            reverse=page.direction == "desc",
        )
    return sorted(
        contexts,
        key=lambda context: (
            context.updated_at is not None,
            context.updated_at or datetime.min,
            context.product.name.casefold(),
            context.product.id.hex,
        ),
        reverse=page.direction == "desc",
    )


def _product_price_key(context: _ProductContext) -> tuple[bool, Decimal, str, str]:
    price = context.best_offer.price if context.best_offer is not None else None
    return (
        price is None,
        price or Decimal("0"),
        context.product.name,
        context.product.id.hex,
    )


def _sort_offers(
    offers: list[ParsedOffer],
    page: PageRequest,
) -> list[ParsedOffer]:
    if page.sort == "marketplace":
        return sorted(
            offers,
            key=lambda offer: (
                offer.marketplace,
                offer.external_id or "",
                offer.title or "",
            ),
            reverse=page.direction == "desc",
        )
    if page.sort == "title":
        return sorted(
            offers,
            key=lambda offer: (
                offer.title or "",
                offer.marketplace,
                offer.external_id or "",
            ),
            reverse=page.direction == "desc",
        )

    priced = sorted(
        [offer for offer in offers if offer.price is not None],
        key=lambda offer: (
            offer.price or Decimal("0"),
            offer.currency or "",
            offer.marketplace,
            offer.external_id or "",
        ),
        reverse=page.direction == "desc",
    )
    missing = [offer for offer in offers if offer.price is None]
    return priced + missing
