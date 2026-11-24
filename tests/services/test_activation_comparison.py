from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from app.comparator.difference import PriceDifferenceService
from app.comparator.grouping import OfferGroupingService
from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.result import ComparisonResultBuilder, ComparisonStatus
from app.comparator.selector import BestOfferSelection, BestOfferSelector
from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import create_memory_provider
from app.repositories.public_queries.repository_backed import (
    RepositoryBackedPublicReadRepository,
)

PRODUCT = CanonicalProduct(
    id=UUID(int=1), name="Subscription 1 month", category="subscriptions", aliases=()
)
TERMS = ActivationConditions(
    regions=("RU",),
    excluded_regions=(),
    device="pc",
    plan="individual",
    period="P1M",
    delivery_method=DeliveryMethod.KEY,
    account_requirement=AccountRequirement.ANY,
    vpn_required=False,
    activation_window_seconds=None,
)


def offer(
    identity: str, price: str, terms: ActivationConditions | None
) -> MarketplaceOffer:
    """Build an explicit offline offer fixture."""
    return MarketplaceOffer(
        offer=ParsedOffer(
            marketplace="funpay",
            external_id=identity,
            title=PRODUCT.name,
            url="https://example.com/offer",
            price=Decimal(price),
            currency="RUB",
            canonical_product_id=PRODUCT.id,
            activation_conditions=terms,
        )
    )


def comparison(*offers: MarketplaceOffer) -> ProductComparisonInput:
    return ProductComparisonInput(canonical_product_id=PRODUCT.id, offers=offers)


def test_equal_conditions_allow_lowest_price_and_decimal_difference() -> None:
    group = comparison(offer("1", "700", TERMS), offer("2", "500", TERMS))
    selected = BestOfferSelector().select(group)
    difference = PriceDifferenceService().compare(selected)
    assert selected.selected_offer is group.offers[1]
    assert difference.differences[0].absolute_difference == Decimal("200")
    assert difference.differences[0].percentage_difference == Decimal("40")


@pytest.mark.parametrize(
    "other",
    [
        None,
        replace(TERMS, regions=("BR",)),
        replace(TERMS, regions=("*",)),
        replace(TERMS, regions=("*",), excluded_regions=("RU",)),
        replace(TERMS, delivery_method=DeliveryMethod.NEW_ACCOUNT),
        replace(TERMS, account_requirement=AccountRequirement.NEW_ONLY),
        replace(TERMS, device="mobile"),
        replace(TERMS, plan="family"),
        replace(TERMS, period="P12M"),
        replace(TERMS, period="P30D"),
        replace(TERMS, vpn_required=True),
        replace(TERMS, activation_window_seconds=3600),
    ],
)
def test_different_or_unknown_conditions_never_create_savings(
    other: ActivationConditions | None,
) -> None:
    group = comparison(offer("1", "700", TERMS), offer("2", "200", other))
    selected = BestOfferSelector().select(group)
    difference = PriceDifferenceService().compare(selected)
    result = ComparisonResultBuilder().build(PRODUCT, selected, difference)
    assert selected.selected_offer is None
    assert difference.best_offer is None
    assert difference.differences == ()
    assert result.status in (
        ComparisonStatus.ACTIVATION_UNKNOWN,
        ComparisonStatus.ACTIVATION_MISMATCH,
    )


def test_two_unknown_offers_are_not_assumed_equivalent() -> None:
    selected = BestOfferSelector().select(
        comparison(offer("1", "700", None), offer("2", "200", None))
    )
    assert selected.selected_offer is None
    assert selected.reason == "activation conditions unknown"


def test_price_discovery_opt_out_cannot_bypass_difference_guard() -> None:
    group = comparison(offer("1", "700", None), offer("2", "200", None))
    selected = BestOfferSelector().select(group, require_activation_conditions=False)
    assert selected.selected_offer is group.offers[1]
    difference = PriceDifferenceService().compare(selected)
    assert difference.best_offer is None
    assert difference.differences == ()


def test_known_regions_form_separate_groups_and_unknown_is_not_a_wildcard() -> None:
    items = [
        offer("1", "700", TERMS),
        offer("2", "500", TERMS),
        offer("3", "200", replace(TERMS, regions=("BR",))),
        offer("4", "100", None),
    ]
    grouped = OfferGroupingService().group(items, [PRODUCT])
    assert [len(group.offers) for group in grouped] == [2, 1, 1]
    assert grouped[0].offers == tuple(items[:2])


def test_single_unknown_offer_keeps_its_source_price_without_savings() -> None:
    group = comparison(offer("1", "700", None))
    selected = BestOfferSelector().select(group)
    assert selected.selected_offer is group.offers[0]
    assert PriceDifferenceService().compare(selected).differences == ()


def test_public_repository_uses_the_same_activation_guard() -> None:
    asyncio.run(_assert_public_activation_guard())


async def _assert_public_activation_guard() -> None:
    provider = create_memory_provider()
    await provider.canonical_products.save(PRODUCT)
    first = offer("1", "700", TERMS).offer
    second = offer("2", "200", replace(TERMS, regions=("BR",))).offer
    await provider.offers.save(first)
    await provider.offers.save(second)
    repository = RepositoryBackedPublicReadRepository(provider)
    result = await repository.get_comparison(PRODUCT.id)
    assert result is not None
    assert result.status == "activation_conditions_mismatch"
    assert result.best_offer is None
    assert result.differences == ()
    await provider.offers.save(replace(second, activation_conditions=TERMS))
    result = await repository.get_comparison(PRODUCT.id)
    assert result is not None and result.best_offer is not None
    assert result.best_offer.price == Decimal("200")
    await provider.offers.save(replace(second, activation_conditions=None))
    result = await repository.get_comparison(PRODUCT.id)
    assert result is not None and result.status == "price_only"
    assert result.best_offer is not None and result.best_offer.price == Decimal("200")
    assert result.differences[0].absolute_difference == Decimal("500")


@pytest.mark.parametrize("first_terms", [None, TERMS])
def test_explicit_unknown_mode_returns_price_only_not_confirmed_equivalence(
    first_terms: ActivationConditions | None,
) -> None:
    group = comparison(offer("1", "700", first_terms), offer("2", "200", None))
    selected = BestOfferSelector().select(
        group, allow_unknown_activation_conditions=True
    )
    difference = PriceDifferenceService().compare(selected)
    result = ComparisonResultBuilder().build(PRODUCT, selected, difference)
    assert selected.activation_conditions_unverified
    assert result.status is ComparisonStatus.PRICE_ONLY
    assert result.best_offer is group.offers[1]
    assert result.comparison_entries[0].absolute_difference == Decimal("500")
    assert result.comparison_entries[0].percentage_difference == Decimal("250")
    assert all(item.offer.activation_conditions is None for item in group.offers[1:])


@pytest.mark.parametrize(
    "conflicting",
    [
        replace(TERMS, regions=("BR",)),
        replace(TERMS, period="P30D"),
        replace(TERMS, delivery_method=DeliveryMethod.OWN_ACCOUNT),
        replace(TERMS, plan="family"),
    ],
)
def test_price_only_does_not_mask_known_conflicts_with_an_unknown_offer(
    conflicting: ActivationConditions,
) -> None:
    group = comparison(
        offer("1", "700", TERMS),
        offer("2", "200", conflicting),
        offer("3", "100", None),
    )
    selected = BestOfferSelector().select(
        group, allow_unknown_activation_conditions=True
    )
    assert selected.selected_offer is None
    assert selected.reason == "activation conditions mismatch"
    # Difference independently checks known conflicts even with an explicit marker.
    forged = BestOfferSelection(
        comparison=group,
        selected_offer=group.offers[2],
        reason="lowest price",
        activation_conditions_unverified=True,
    )
    difference = PriceDifferenceService().compare(forged)
    assert difference.best_offer is None and difference.differences == ()
    assert difference.reason == "activation conditions mismatch"


def test_price_only_preserves_currency_guard_and_stable_ties() -> None:
    first, second = offer("2", "200", None), offer("1", "200", None)
    group = comparison(first, second)
    selector = BestOfferSelector()
    for ordering in ((first, second), (second, first)):
        selected = selector.select(
            comparison(*ordering), allow_unknown_activation_conditions=True
        )
        assert selected.selected_offer is second
        assert selected.activation_conditions_unverified
    foreign_currency = MarketplaceOffer(offer=replace(first.offer, currency="USD"))
    selected = selector.select(
        replace(group, offers=(second, foreign_currency)),
        allow_unknown_activation_conditions=True,
    )
    assert selected.currency_mismatch and selected.selected_offer is None


def test_price_only_with_one_missing_price_keeps_price_and_unavailable_entry() -> None:
    first, second = offer("1", "200", None), offer("2", "300", None)
    second = MarketplaceOffer(offer=replace(second.offer, price=None))
    selected = BestOfferSelector().select(
        comparison(first, second), allow_unknown_activation_conditions=True
    )
    difference = PriceDifferenceService().compare(selected)
    result = ComparisonResultBuilder().build(PRODUCT, selected, difference)
    assert result.best_offer is first and result.status is ComparisonStatus.PRICE_ONLY
    assert result.comparison_entries[0].reason == "price unavailable"


def test_fully_verified_and_single_offer_results_keep_their_previous_status() -> None:
    for group in (
        comparison(offer("1", "200", TERMS), offer("2", "300", TERMS)),
        comparison(offer("1", "200", None)),
    ):
        selected = BestOfferSelector().select(
            group, allow_unknown_activation_conditions=True
        )
        result = ComparisonResultBuilder().build(
            PRODUCT, selected, PriceDifferenceService().compare(selected)
        )
        assert not selected.activation_conditions_unverified
        assert result.status is ComparisonStatus.COMPLETE
