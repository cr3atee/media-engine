from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.domain.price_snapshot import PriceSnapshot
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.memory import (
    MemoryCanonicalProductRepository,
    MemoryOfferRepository,
    MemoryPriceHistoryRepository,
)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run repository async methods without requiring an external pytest plugin."""
    return asyncio.run(awaitable)


def make_product(
    *,
    id: UUID | None = None,
    name: str = "Minecraft Premium",
    category: str | None = "games",
    aliases: tuple[str, ...] = ("minecraft",),
) -> CanonicalProduct:
    """Create a canonical product for repository tests."""
    return CanonicalProduct(
        id=id or uuid4(),
        name=name,
        category=category,
        aliases=aliases,
    )


def make_offer(
    *,
    marketplace: str = "ggsel",
    external_id: str | None = "offer-1",
    title: str | None = "Minecraft Premium",
    price: Decimal | None = Decimal("790.00"),
    currency: str | None = "RUB",
    canonical_product_id: UUID | None = None,
) -> ParsedOffer:
    """Create a parsed offer for repository tests."""
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{marketplace}/{external_id or 'none'}",
        price=price,
        currency=currency,
        seller_id=f"{marketplace}-seller",
        seller_name=f"{marketplace} Seller",
        canonical_product_id=canonical_product_id,
    )


def make_snapshot(
    *,
    marketplace: str = "ggsel",
    external_id: str = "offer-1",
    price: Decimal = Decimal("790.00"),
    collected_at: datetime | None = None,
) -> PriceSnapshot:
    """Create a price snapshot for repository tests."""
    return PriceSnapshot(
        marketplace=marketplace,
        external_id=external_id,
        price=price,
        currency="RUB",
        collected_at=collected_at or datetime.now(UTC),
    )


def test_offer_repository_saves_retrieves_and_lists_deterministically() -> None:
    repository = MemoryOfferRepository()
    first = make_offer(external_id="one", title="Minecraft Premium")
    second = make_offer(
        marketplace="playerok",
        external_id="two",
        title="Minecraft Premium Playerok",
    )

    run_async(repository.save(first))
    run_async(repository.save(second))

    assert run_async(repository.get_by_identity("ggsel", "one")) == first
    assert tuple(run_async(repository.list_all())) == (first, second)


def test_offer_repository_updates_by_marketplace_and_external_id() -> None:
    repository = MemoryOfferRepository()
    original = make_offer(external_id="same", title="Old title")
    updated = make_offer(external_id="same", title="New title")

    run_async(repository.save(original))
    run_async(repository.save(updated))

    assert tuple(run_async(repository.list_all())) == (updated,)
    assert run_async(repository.get_by_identity("ggsel", "same")) == updated


def test_offer_repository_preserves_meaningful_optional_values() -> None:
    repository = MemoryOfferRepository()
    product_id = uuid4()
    original = make_offer(
        external_id="same",
        title="Old title",
        canonical_product_id=product_id,
    )
    incoming = ParsedOffer(
        marketplace="ggsel",
        external_id="same",
        title="New title",
        url=None,
        price=None,
        currency=None,
        seller_id=None,
        seller_name=None,
        canonical_product_id=None,
    )

    run_async(repository.save(original))
    run_async(repository.save(incoming))

    assert run_async(repository.get_by_identity("ggsel", "same")) == replace(
        original,
        title="New title",
    )


def test_offer_repository_isolates_same_external_id_by_marketplace() -> None:
    repository = MemoryOfferRepository()
    ggsel_offer = make_offer(marketplace="ggsel", external_id="shared")
    playerok_offer = make_offer(marketplace="playerok", external_id="shared")

    run_async(repository.save(ggsel_offer))
    run_async(repository.save(playerok_offer))

    assert tuple(run_async(repository.list_all())) == (ggsel_offer, playerok_offer)


def test_offer_repository_appends_offers_without_external_id() -> None:
    repository = MemoryOfferRepository()
    first = make_offer(external_id=None, title="First")
    second = make_offer(external_id=None, title="Second")

    run_async(repository.save(first))
    run_async(repository.save(second))

    assert tuple(run_async(repository.list_all())) == (first, second)


def test_offer_repository_filters_by_marketplace() -> None:
    repository = MemoryOfferRepository()
    ggsel_offer = make_offer(marketplace="ggsel", external_id="one")
    playerok_offer = make_offer(marketplace="playerok", external_id="two")

    run_async(repository.save(ggsel_offer))
    run_async(repository.save(playerok_offer))

    assert tuple(run_async(repository.list_by_marketplace("ggsel"))) == (ggsel_offer,)
    assert tuple(run_async(repository.list_by_marketplace("playerok"))) == (
        playerok_offer,
    )


def test_offer_repository_keeps_instances_isolated() -> None:
    first_repository = MemoryOfferRepository()
    second_repository = MemoryOfferRepository()
    offer = make_offer()

    run_async(first_repository.save(offer))

    assert tuple(run_async(first_repository.list_all())) == (offer,)
    assert tuple(run_async(second_repository.list_all())) == ()


def test_canonical_product_repository_saves_retrieves_and_updates() -> None:
    repository = MemoryCanonicalProductRepository()
    product_id = uuid4()
    original = make_product(id=product_id, name="Minecraft Premium")
    updated = make_product(
        id=product_id,
        name="Minecraft Java",
        aliases=("minecraft", "minecraft java"),
    )

    run_async(repository.save(original))
    run_async(repository.save(updated))

    assert run_async(repository.get_by_id(product_id)) == updated
    assert tuple(run_async(repository.list_all())) == (updated,)


def test_canonical_product_repository_lists_in_insertion_order() -> None:
    repository = MemoryCanonicalProductRepository()
    first = make_product(name="Minecraft Premium")
    second = make_product(name="Counter Strike 2")

    run_async(repository.save(first))
    run_async(repository.save(second))

    assert tuple(run_async(repository.list_all())) == (first, second)


def test_canonical_product_repository_keeps_instances_isolated() -> None:
    first_repository = MemoryCanonicalProductRepository()
    second_repository = MemoryCanonicalProductRepository()
    product = make_product()

    run_async(first_repository.save(product))

    assert tuple(run_async(first_repository.list_all())) == (product,)
    assert tuple(run_async(second_repository.list_all())) == ()


def test_price_history_repository_orders_latest_and_previous_snapshots() -> None:
    repository = MemoryPriceHistoryRepository()
    now = datetime.now(UTC)
    latest = make_snapshot(price=Decimal("790.00"), collected_at=now)
    earliest = make_snapshot(
        price=Decimal("990.00"),
        collected_at=now - timedelta(minutes=10),
    )
    middle = make_snapshot(
        price=Decimal("890.00"),
        collected_at=now - timedelta(minutes=5),
    )

    run_async(repository.add(latest))
    run_async(repository.add(earliest))
    run_async(repository.add(middle))

    assert run_async(repository.get_history("ggsel", "offer-1")) == [
        earliest,
        middle,
        latest,
    ]
    assert run_async(repository.get_last("ggsel", "offer-1")) == latest
    assert run_async(repository.get_previous("ggsel", "offer-1")) == middle


def test_price_history_repository_uses_insertion_order_for_equal_timestamps() -> None:
    repository = MemoryPriceHistoryRepository()
    collected_at = datetime.now(UTC)
    first = make_snapshot(price=Decimal("990.00"), collected_at=collected_at)
    second = make_snapshot(price=Decimal("790.00"), collected_at=collected_at)

    run_async(repository.add(first))
    run_async(repository.add(second))

    assert run_async(repository.get_history("ggsel", "offer-1")) == [first, second]
    assert run_async(repository.get_previous("ggsel", "offer-1")) == first
    assert run_async(repository.get_last("ggsel", "offer-1")) == second


def test_price_history_repository_keeps_same_price_at_new_timestamp() -> None:
    repository = MemoryPriceHistoryRepository()
    collected_at = datetime.now(UTC)
    first = make_snapshot(price=Decimal("790.00"), collected_at=collected_at)
    second = make_snapshot(
        price=Decimal("790.00"),
        collected_at=collected_at + timedelta(minutes=1),
    )

    run_async(repository.add(first))
    run_async(repository.add(second))

    assert run_async(repository.get_history("ggsel", "offer-1")) == [first, second]


def test_price_history_repository_returns_no_previous_for_one_snapshot() -> None:
    repository = MemoryPriceHistoryRepository()
    snapshot = make_snapshot()

    run_async(repository.add(snapshot))

    assert run_async(repository.get_last("ggsel", "offer-1")) == snapshot
    assert run_async(repository.get_previous("ggsel", "offer-1")) is None


def test_price_history_repository_isolates_marketplace_and_external_id() -> None:
    repository = MemoryPriceHistoryRepository()
    ggsel_snapshot = make_snapshot(marketplace="ggsel", external_id="one")
    playerok_snapshot = make_snapshot(marketplace="playerok", external_id="one")
    other_snapshot = make_snapshot(marketplace="ggsel", external_id="two")

    run_async(repository.add(ggsel_snapshot))
    run_async(repository.add(playerok_snapshot))
    run_async(repository.add(other_snapshot))

    assert run_async(repository.get_history("ggsel", "one")) == [ggsel_snapshot]
    assert run_async(repository.get_history("playerok", "one")) == [playerok_snapshot]
    assert run_async(repository.get_history("ggsel", "two")) == [other_snapshot]


def test_price_history_repository_ignores_exact_duplicate_snapshots() -> None:
    repository = MemoryPriceHistoryRepository()
    snapshot = make_snapshot()

    assert run_async(repository.add(snapshot)) is True
    assert run_async(repository.add(snapshot)) is False

    assert run_async(repository.get_history("ggsel", "offer-1")) == [snapshot]


def test_price_history_repository_keeps_instances_isolated() -> None:
    first_repository = MemoryPriceHistoryRepository()
    second_repository = MemoryPriceHistoryRepository()
    snapshot = make_snapshot()

    run_async(first_repository.add(snapshot))

    assert run_async(first_repository.get_history("ggsel", "offer-1")) == [snapshot]
    assert run_async(second_repository.get_history("ggsel", "offer-1")) == []
