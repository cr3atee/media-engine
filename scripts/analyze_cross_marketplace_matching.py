"""Analyze real saved offers against the current deterministic matching rules."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.matching.confidence import ConfidenceEngine, MatchDecision  # noqa: E402
from app.matching.preprocessor import MatchingPreprocessor  # noqa: E402
from app.matching.similarity import SimilarityEngine  # noqa: E402
from app.parsers.models import ParsedOffer  # noqa: E402
from scripts.verify_marketplace_data_readiness import (  # noqa: E402
    load_saved_marketplace_offers,
)


@dataclass(slots=True, frozen=True)
class CrossMarketplaceMatchCandidate:
    """One deterministic title comparison across two marketplaces."""

    left_marketplace: str
    left_external_id: str | None
    left_title: str
    left_url: str | None
    left_price: Decimal | None
    left_currency: str | None
    left_seller_name: str | None
    right_marketplace: str
    right_external_id: str | None
    right_title: str
    right_url: str | None
    right_price: Decimal | None
    right_currency: str | None
    right_seller_name: str | None
    similarity: float
    decision: MatchDecision


@dataclass(slots=True, frozen=True)
class MarketplacePairMatchCandidates:
    """Top deterministic candidates for one ordered marketplace pair."""

    left_marketplace: str
    right_marketplace: str
    candidates: tuple[CrossMarketplaceMatchCandidate, ...]


@dataclass(slots=True, frozen=True)
class CrossMarketplaceMatchingReport:
    """Readiness evidence for automatic cross-marketplace grouping."""

    marketplace_count: int
    offer_count: int
    comparable_offer_count: int
    pair_count: int
    auto_match_count: int
    review_count: int
    no_match_count: int
    highest_similarity: float
    top_candidates: tuple[CrossMarketplaceMatchCandidate, ...]
    top_candidates_by_marketplace_pair: tuple[MarketplacePairMatchCandidates, ...]

    @property
    def automatic_grouping_ready(self) -> bool:
        """Return whether at least one automatic cross-marketplace match exists."""
        return self.auto_match_count > 0


def analyze_cross_marketplace_matching(
    offers_by_marketplace: Mapping[str, Sequence[ParsedOffer]],
    *,
    top_limit: int = 5,
    pair_top_limit: int = 5,
) -> CrossMarketplaceMatchingReport:
    """Compare titled offers across sources with existing matching components."""
    if top_limit < 0:
        msg = "top_limit must not be negative"
        raise ValueError(msg)
    if pair_top_limit < 0:
        msg = "pair_top_limit must not be negative"
        raise ValueError(msg)

    preprocessor = MatchingPreprocessor()
    similarity_engine = SimilarityEngine()
    confidence_engine = ConfidenceEngine()
    prepared: dict[str, tuple[tuple[ParsedOffer, tuple[str, ...]], ...]] = {}
    offer_count = 0

    for marketplace in sorted(offers_by_marketplace):
        offers = offers_by_marketplace[marketplace]
        offer_count += len(offers)
        titled_offers = (
            (offer, preprocessor.process(offer.title))
            for offer in offers
            if offer.title is not None and offer.title.strip()
        )
        prepared[marketplace] = tuple(
            sorted(
                titled_offers,
                key=lambda item: (
                    item[0].external_id or "",
                    item[0].title or "",
                ),
            )
        )

    candidates: list[CrossMarketplaceMatchCandidate] = []
    for left_marketplace, right_marketplace in combinations(prepared, 2):
        for left_offer, left_tokens in prepared[left_marketplace]:
            for right_offer, right_tokens in prepared[right_marketplace]:
                similarity = similarity_engine.calculate(left_tokens, right_tokens)
                candidates.append(
                    CrossMarketplaceMatchCandidate(
                        left_marketplace=left_marketplace,
                        left_external_id=left_offer.external_id,
                        left_title=left_offer.title or "",
                        left_url=left_offer.url,
                        left_price=left_offer.price,
                        left_currency=left_offer.currency,
                        left_seller_name=left_offer.seller_name,
                        right_marketplace=right_marketplace,
                        right_external_id=right_offer.external_id,
                        right_title=right_offer.title or "",
                        right_url=right_offer.url,
                        right_price=right_offer.price,
                        right_currency=right_offer.currency,
                        right_seller_name=right_offer.seller_name,
                        similarity=similarity,
                        decision=confidence_engine.classify(similarity),
                    )
                )

    candidates.sort(key=_candidate_sort_key)
    candidates_by_pair: dict[tuple[str, str], list[CrossMarketplaceMatchCandidate]] = {}
    for candidate in candidates:
        marketplace_pair = (
            candidate.left_marketplace,
            candidate.right_marketplace,
        )
        pair_candidates = candidates_by_pair.setdefault(marketplace_pair, [])
        if len(pair_candidates) < pair_top_limit:
            pair_candidates.append(candidate)
    pair_reports = tuple(
        MarketplacePairMatchCandidates(
            left_marketplace=marketplace_pair[0],
            right_marketplace=marketplace_pair[1],
            candidates=tuple(pair_candidates),
        )
        for marketplace_pair, pair_candidates in sorted(candidates_by_pair.items())
    )
    return CrossMarketplaceMatchingReport(
        marketplace_count=sum(bool(items) for items in prepared.values()),
        offer_count=offer_count,
        comparable_offer_count=sum(len(items) for items in prepared.values()),
        pair_count=len(candidates),
        auto_match_count=sum(
            candidate.decision is MatchDecision.AUTO_MATCH for candidate in candidates
        ),
        review_count=sum(
            candidate.decision is MatchDecision.REVIEW for candidate in candidates
        ),
        no_match_count=sum(
            candidate.decision is MatchDecision.NO_MATCH for candidate in candidates
        ),
        highest_similarity=candidates[0].similarity if candidates else 0.0,
        top_candidates=tuple(candidates[:top_limit]),
        top_candidates_by_marketplace_pair=pair_reports,
    )


def main() -> int:
    """Print factual matching readiness for all saved marketplace payloads."""
    _configure_stdout()
    offers_by_marketplace = load_saved_marketplace_offers()
    report = analyze_cross_marketplace_matching(offers_by_marketplace)

    print("=== CROSS-MARKETPLACE MATCHING READINESS ===")
    for marketplace, offers in offers_by_marketplace.items():
        print(f"{marketplace}: {len(offers)} offers")
    print()
    print(f"Marketplaces with data: {report.marketplace_count}")
    print(f"Offers: {report.offer_count}")
    print(f"Offers with titles: {report.comparable_offer_count}")
    print(f"Cross-marketplace pairs: {report.pair_count}")
    print(f"AUTO_MATCH: {report.auto_match_count}")
    print(f"REVIEW: {report.review_count}")
    print(f"NO_MATCH: {report.no_match_count}")
    print(f"Highest similarity: {report.highest_similarity:.3f}")
    print()
    print("Highest-scoring candidates:")
    for candidate in report.top_candidates:
        print(
            f"- {candidate.similarity:.3f} [{candidate.decision.value}] "
            f"{candidate.left_marketplace}: {candidate.left_title}"
        )
        _print_offer_evidence(
            marketplace=candidate.left_marketplace,
            external_id=candidate.left_external_id,
            price=candidate.left_price,
            currency=candidate.left_currency,
            seller_name=candidate.left_seller_name,
            url=candidate.left_url,
        )
        print(f"  {candidate.right_marketplace}: {candidate.right_title}")
        _print_offer_evidence(
            marketplace=candidate.right_marketplace,
            external_id=candidate.right_external_id,
            price=candidate.right_price,
            currency=candidate.right_currency,
            seller_name=candidate.right_seller_name,
            url=candidate.right_url,
        )

    print()
    print("Top candidates per marketplace pair:")
    for pair in report.top_candidates_by_marketplace_pair:
        print(f"- {pair.left_marketplace}/{pair.right_marketplace}")
        for candidate in pair.candidates:
            print(
                f"  {candidate.similarity:.3f} [{candidate.decision.value}] "
                f"{candidate.left_title} <> {candidate.right_title}"
            )

    print()
    if report.automatic_grouping_ready:
        print("Status: automatic cross-marketplace match evidence exists.")
    else:
        print(
            "Status: canonical catalog/bootstrap work is required; the current "
            "saved payloads contain no automatic cross-marketplace match."
        )
    return 0


def _candidate_sort_key(
    candidate: CrossMarketplaceMatchCandidate,
) -> tuple[float, str, str, str, str, str, str]:
    return (
        -candidate.similarity,
        candidate.left_marketplace,
        candidate.left_external_id or "",
        candidate.left_title,
        candidate.right_marketplace,
        candidate.right_external_id or "",
        candidate.right_title,
    )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


def _print_offer_evidence(
    *,
    marketplace: str,
    external_id: str | None,
    price: Decimal | None,
    currency: str | None,
    seller_name: str | None,
    url: str | None,
) -> None:
    details = [
        f"source={marketplace}",
        f"id={external_id or 'unknown'}",
        f"price={price if price is not None else 'unknown'} {currency or ''}".rstrip(),
    ]
    if seller_name:
        details.append(f"seller={seller_name}")
    print(f"  {' | '.join(details)}")
    print(f"  url={url or 'unknown'}")


if __name__ == "__main__":
    raise SystemExit(main())
