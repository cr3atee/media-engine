from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.comparator.result import ComparisonStatus
from app.insights.scoring import EventScorer
from app.models.canonical_product import CanonicalProduct
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer, RawMarketplaceOffer
from app.parsers.normalizers import OfferNormalizer
from app.parsers.playerok_extractor import PlayerokExtractor
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.parsers.playerok_normalizer import PlayerokNormalizer
from app.repositories.canonical_products import CanonicalProductRepository
from app.repositories.memory import MemoryPriceHistoryRepository
from app.repositories.offers import OfferRepository
from app.repositories.provider import RepositoryProvider
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.playerok_pipeline import PlayerokPipeline
from app.services.price_history import PriceHistoryService
from app.services.snapshot_builder import SnapshotBuilder


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async application callers without requiring an external pytest plugin."""
    return asyncio.run(awaitable)


@dataclass(slots=True)
class AsyncCallState:
    """Tracks whether repository methods were awaited by application callers."""

    offer_save_count: int = 0
    offer_list_count: int = 0
    canonical_list_count: int = 0


class RecordingOfferRepository(OfferRepository):
    """Offer repository double that exposes async call counters."""

    def __init__(
        self,
        state: AsyncCallState,
        *,
        fail_on_save: bool = False,
    ) -> None:
        self._state = state
        self._offers: list[ParsedOffer] = []
        self._fail_on_save = fail_on_save

    async def save(self, offer: ParsedOffer) -> None:
        """Store an offer and record an awaited save operation."""
        self._state.offer_save_count += 1
        if self._fail_on_save:
            msg = "offer repository failed"
            raise RuntimeError(msg)
        self._offers.append(offer)

    async def get_by_identity(
        self,
        marketplace: str,
        external_id: str,
    ) -> ParsedOffer | None:
        """Return an offer by marketplace and external identifier."""
        for offer in self._offers:
            if offer.marketplace == marketplace and offer.external_id == external_id:
                return offer
        return None

    async def list_by_marketplace(self, marketplace: str) -> Sequence[ParsedOffer]:
        """Return offers from one marketplace."""
        return tuple(
            offer for offer in self._offers if offer.marketplace == marketplace
        )

    async def list_all(self) -> Sequence[ParsedOffer]:
        """Return all offers and record an awaited list operation."""
        self._state.offer_list_count += 1
        return tuple(self._offers)


class RecordingCanonicalProductRepository(CanonicalProductRepository):
    """Canonical product repository double that exposes async list usage."""

    def __init__(
        self,
        state: AsyncCallState,
        products: Sequence[CanonicalProduct],
    ) -> None:
        self._state = state
        self._products = {product.id: product for product in products}

    async def save(self, product: CanonicalProduct) -> None:
        """Store a canonical product."""
        self._products[product.id] = product

    async def get_by_id(self, id: UUID) -> CanonicalProduct | None:
        """Return a canonical product by identifier."""
        return self._products.get(id)

    async def list_all(self) -> Sequence[CanonicalProduct]:
        """Return all products and record an awaited list operation."""
        self._state.canonical_list_count += 1
        return tuple(self._products.values())


class StaticGGSelFetcher:
    """Returns deterministic HTML for marketplace pipeline tests."""

    async def fetch_html(self, url: str) -> str:
        """Return raw source content."""
        return "<html>ok</html>"


class StaticGGSelExtractor:
    """Returns deterministic raw GGSEL offers for marketplace pipeline tests."""

    def extract(self, html: str) -> list[RawMarketplaceOffer]:
        """Return one raw marketplace offer."""
        return [
            RawMarketplaceOffer(
                id_goods=1001,
                name="Minecraft Premium",
                url="https://ggsel.net/item/1001",
                seller_name="GGSEL Seller",
                id_section=1,
                price=790.0,
                currency="RUB",
            ),
        ]


def make_product() -> CanonicalProduct:
    """Create a canonical product used by repository-backed comparison."""
    return CanonicalProduct(
        id=uuid4(),
        name="Minecraft Premium",
        category="games",
        aliases=("minecraft",),
    )


def make_offer(
    *,
    marketplace: str = "ggsel",
    external_id: str = "1001",
    price: Decimal = Decimal("790"),
) -> ParsedOffer:
    """Create a parsed offer used by application caller tests."""
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title="Minecraft Premium",
        url=f"https://example.com/{marketplace}/{external_id}",
        price=price,
        currency="RUB",
        seller_id=None,
        seller_name=f"{marketplace} seller",
    )


def make_pipeline(
    provider: RepositoryProvider,
) -> MarketplacePipeline:
    """Build the existing marketplace pipeline with deterministic test doubles."""
    return MarketplacePipeline(
        fetcher=cast(GGSelFetcher, StaticGGSelFetcher()),
        extractor=cast(GGSelExtractor, StaticGGSelExtractor()),
        normalizer=OfferNormalizer(marketplace="ggsel"),
        repository_provider=provider,
        snapshot_builder=SnapshotBuilder(),
        price_history=PriceHistoryService(),
        price_change_detector=PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=ContentGenerator(FakeAIProvider()),
    )


def make_provider(
    *,
    product: CanonicalProduct,
    fail_on_offer_save: bool = False,
) -> tuple[RepositoryProvider, AsyncCallState]:
    """Build a repository provider with async-aware repository doubles."""
    state = AsyncCallState()
    return (
        RepositoryProvider(
            canonical_products=RecordingCanonicalProductRepository(
                state,
                (product,),
            ),
            offers=RecordingOfferRepository(
                state,
                fail_on_save=fail_on_offer_save,
            ),
            price_history=MemoryPriceHistoryRepository(),
        ),
        state,
    )


def test_marketplace_pipeline_awaits_repository_save_and_comparison_reads() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    pipeline = make_pipeline(provider)

    result = run_async(pipeline.run("demo://ggsel"))
    stored_offers = run_async(provider.offers.list_all())

    assert state.offer_save_count == 1
    assert state.offer_list_count >= 2
    assert state.canonical_list_count == 1
    assert len(stored_offers) == 1
    assert len(result) == 1
    assert result[0].canonical_product == product
    assert result[0].status is ComparisonStatus.COMPLETE


def test_repository_backed_comparison_loads_data_before_pure_comparator() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    run_async(
        provider.offers.save(
            make_offer(marketplace="ggsel", price=Decimal("990")),
        ),
    )
    run_async(
        provider.offers.save(
            make_offer(
                marketplace="playerok",
                external_id="2001",
                price=Decimal("790"),
            ),
        ),
    )
    pipeline = make_pipeline(provider)

    result = run_async(pipeline.compare_repository_offers())

    assert state.offer_list_count == 1
    assert state.canonical_list_count == 1
    assert len(result) == 1
    assert result[0].best_offer is not None
    assert result[0].best_offer.offer.marketplace == "playerok"


def test_playerok_comparison_helpers_await_repository_backed_pipeline() -> None:
    product = make_product()
    provider, state = make_provider(product=product)
    ggsel_pipeline = make_pipeline(provider)
    playerok_pipeline = PlayerokPipeline(
        fetcher=cast(PlayerokFetcher, object()),
        extractor=PlayerokExtractor(),
        normalizer=PlayerokNormalizer(),
        comparison_pipeline=ggsel_pipeline,
    )
    run_async(
        provider.offers.save(
            make_offer(marketplace="ggsel", price=Decimal("990")),
        ),
    )
    run_async(
        provider.offers.save(
            make_offer(
                marketplace="playerok",
                external_id="2001",
                price=Decimal("790"),
            ),
        ),
    )

    result = run_async(playerok_pipeline.compare_repository_offers())

    assert state.offer_list_count == 1
    assert state.canonical_list_count == 1
    assert len(result) == 1
    assert result[0].status is ComparisonStatus.COMPLETE


def test_repository_save_errors_propagate_from_marketplace_pipeline() -> None:
    product = make_product()
    provider, state = make_provider(product=product, fail_on_offer_save=True)
    pipeline = make_pipeline(provider)

    with pytest.raises(RuntimeError, match="offer repository failed"):
        run_async(pipeline.run("demo://ggsel"))

    assert state.offer_save_count == 1
    assert state.offer_list_count == 0
    assert state.canonical_list_count == 0
