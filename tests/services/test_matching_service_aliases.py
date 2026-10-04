from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer

TENANT_ID = UUID("3c000000-0000-4000-8000-000000001001")
PRODUCT_A_ID = UUID("3c000000-0000-4000-8000-000000002001")
PRODUCT_B_ID = UUID("3c000000-0000-4000-8000-000000002002")


def test_matching_uses_strongest_canonical_alias() -> None:
    offer = _offer("Minecraft Java Bedrock Windows Premium")
    product = _product(
        product_id=PRODUCT_A_ID,
        name="Minecraft Complete Collection",
        aliases=("Minecraft Java Bedrock Windows",),
    )

    result = MatchingService().match(offer, (product,))

    assert result.canonical_product == product
    assert result.similarity == 0.8
    assert result.decision is MatchDecision.REVIEW


def test_matching_keeps_name_score_when_aliases_are_weaker() -> None:
    offer = _offer("Minecraft Java Bedrock Windows")
    product = _product(
        product_id=PRODUCT_A_ID,
        name="Minecraft Java Bedrock Windows",
        aliases=("Minecraft", "Unrelated Product"),
    )

    result = MatchingService().match(offer, (product,))

    assert result.similarity == 1.0
    assert result.decision is MatchDecision.AUTO_MATCH


def test_blank_alias_cannot_turn_empty_offer_into_false_match() -> None:
    product = _product(
        product_id=PRODUCT_A_ID,
        name="Minecraft Java",
        aliases=("", "   "),
    )

    result = MatchingService().match(_offer(None), (product,))

    assert result.canonical_product == product
    assert result.similarity == 0.0
    assert result.decision is MatchDecision.NO_MATCH


def test_equal_alias_scores_preserve_candidate_order() -> None:
    offer = _offer("Minecraft Java Bedrock Windows Premium")
    first = _product(
        product_id=PRODUCT_A_ID,
        name="First Product",
        aliases=("Minecraft Java Bedrock Windows",),
    )
    second = _product(
        product_id=PRODUCT_B_ID,
        name="Second Product",
        aliases=("Minecraft Java Bedrock Premium",),
    )

    result = MatchingService().match(offer, (first, second))

    assert result.canonical_product == first
    assert result.similarity == 0.8


def _product(
    *,
    product_id: UUID,
    name: str,
    aliases: tuple[str, ...],
) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=TENANT_ID,
        name=name,
        category="Games",
        aliases=aliases,
    )


def _offer(title: str | None) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=TENANT_ID,
        marketplace="ggsel",
        external_id="offer-1",
        title=title,
        url="https://ggsel.net/catalog/product/offer-1",
        price=Decimal("790.00"),
        currency="RUB",
    )
