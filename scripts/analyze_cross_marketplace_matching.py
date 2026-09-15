"""Analyze real saved offers against the current deterministic matching rules."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    right_marketplace: str
    right_external_id: str | None
    right_title: str
    similarity: float
    decision: MatchDecision


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

    @property
    def automatic_grouping_ready(self) -> bool:
        """Return whether at least one automatic cross-marketplace match exists."""
        return self.auto_match_count > 0


def analyze_cross_marketplace_matching(
    offers_by_marketplace: Mapping[str, Sequence[ParsedOffer]],
    *,
    top_limit: int = 5,
) -> CrossMarketplaceMatchingReport:
    """Compare titled offers across sources with existing matching components."""
    if top_limit < 0:
        msg = "top_limit must not be negative"
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
                        right_marketplace=right_marketplace,
                        right_external_id=right_offer.external_id,
                        right_title=right_offer.title or "",
                        similarity=similarity,
                        decision=confidence_engine.classify(similarity),
                    )
                )

    candidates.sort(key=_candidate_sort_key)
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
        print(f"  {candidate.right_marketplace}: {candidate.right_title}")

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


if __name__ == "__main__":
    raise SystemExit(main())
