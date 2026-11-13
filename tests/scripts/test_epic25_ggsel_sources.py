from __future__ import annotations

from decimal import Decimal

import pytest

from app.parsers.models import ParsedOffer
from scripts.verify_epic25_ggsel_sources import (
    LAUNCH_PRODUCTS,
    Epic25SourceVerificationError,
    find_exact_month_candidates,
    select_candidate,
    validate_snapshot_ready_offer,
)


@pytest.mark.parametrize(
    ("spec_index", "title"),
    [
        (0, "ExitLag Subscription 30 days Key Russia +157 more"),
        (1, "Duolingo Super 1 Month Key | Instant Auto-Delivery"),
        (2, "Spotify Premium Individual - 1 Month"),
    ],
)
def test_exact_month_candidates_accept_launch_titles(
    spec_index: int,
    title: str,
) -> None:
    """Each launch product accepts only explicit one-month source evidence."""
    offer = _offer(external_id="20", title=title)

    assert find_exact_month_candidates(
        LAUNCH_PRODUCTS[spec_index],
        (offer,),
    ) == (offer,)


@pytest.mark.parametrize(
    "title",
    [
        "Duolingo Super 1 / 12 Months",
        "Duolingo Super 3 Months",
        "Duolingo Super subscription",
    ],
)
def test_exact_month_candidates_reject_ambiguous_durations(title: str) -> None:
    """Mixed, longer, and unstated durations fail closed."""
    assert (
        find_exact_month_candidates(
            LAUNCH_PRODUCTS[1],
            (_offer(external_id="20", title=title),),
        )
        == ()
    )


def test_spotify_candidate_rejects_non_individual_plan() -> None:
    """A family plan cannot provide evidence for the Individual product."""
    offer = _offer(
        external_id="20",
        title="Spotify Premium Individual Family 1 Month",
    )

    assert find_exact_month_candidates(LAUNCH_PRODUCTS[2], (offer,)) == ()


def test_candidate_selection_is_deterministic_and_not_price_ranked() -> None:
    """Evidence selection uses stable identity rather than claiming a best price."""
    newer = _offer(
        external_id="20",
        title="ExitLag 1 Month",
        price=Decimal("1.00"),
    )
    older = _offer(
        external_id="10",
        title="ExitLag 1 Month",
        price=Decimal("9.00"),
    )

    assert select_candidate(LAUNCH_PRODUCTS[0], (newer, older)) is older


def test_candidate_selection_rejects_missing_evidence() -> None:
    """A launch product without an exact candidate cannot pass verification."""
    with pytest.raises(Epic25SourceVerificationError, match="no exact one-month"):
        select_candidate(LAUNCH_PRODUCTS[0], ())


def test_snapshot_ready_validation_rejects_missing_source_field() -> None:
    """Live evidence must contain every field needed by the snapshot path."""
    offer = _offer(external_id="20", title="ExitLag 1 Month")
    offer.price = None

    with pytest.raises(Epic25SourceVerificationError, match="price"):
        validate_snapshot_ready_offer(offer)


def test_snapshot_ready_validation_rejects_untrusted_url() -> None:
    """The verifier never accepts an outbound URL on another host."""
    offer = _offer(external_id="20", title="ExitLag 1 Month")
    offer.url = "https://example.com/product"

    with pytest.raises(Epic25SourceVerificationError, match="trusted HTTPS host"):
        validate_snapshot_ready_offer(offer)


def _offer(
    *,
    external_id: str,
    title: str,
    price: Decimal = Decimal("7.22"),
) -> ParsedOffer:
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title=title,
        url=f"https://ggsel.net/en/catalog/product/{external_id}",
        price=price,
        currency="USD",
        seller_name="Source seller",
        source_category_id="123",
    )
