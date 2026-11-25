"""Inspect real FunPay subscription candidates without linking or persisting them."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funpayparsers.parsers.categories_parser import CategoriesParser  # noqa: E402

from app.core.http_client import HttpClient  # noqa: E402
from app.parsers.funpay_extractor import (  # noqa: E402
    FunPayExtractor,
)
from app.parsers.funpay_fetcher import FunPayFetcher  # noqa: E402
from app.parsers.funpay_normalizer import FunPayNormalizer  # noqa: E402
from app.services.subscription_candidate_rules import (  # noqa: E402
    LAUNCH_SOURCES as LAUNCH_SOURCES,
)
from app.services.subscription_candidate_rules import (
    FunPayCandidateAssessment as FunPayCandidateAssessment,
)
from app.services.subscription_candidate_rules import (
    FunPayLaunchSpec as FunPayLaunchSpec,
)
from app.services.subscription_candidate_rules import (
    assess_candidate as assess_candidate,
)
from app.services.subscription_candidate_rules import (
    select_review_candidate as select_review_candidate,
)

LIVE_ENV = "EPIC25_FUNPAY_LIVE_VERIFY"
LIVE_GUARD = "I_UNDERSTAND_THIS_CONTACTS_FUNPAY"


@dataclass(slots=True, frozen=True)
class FunPaySourceVerification:
    """Describe one returned listing without claiming marketplace-wide coverage."""

    spec: FunPayLaunchSpec
    returned_items: int
    monthly_items: int
    review_candidates: int
    rejected_title_conflicts: int
    selected: FunPayCandidateAssessment | None
    url_status: int | None


async def fetch_funpay_launch_sources(
    http_client: HttpClient,
) -> tuple[FunPaySourceVerification, ...]:
    """Read the catalog and bounded source pages; never write or make decisions."""
    fetcher = FunPayFetcher(http_client)
    catalog = CategoriesParser(
        await fetcher.fetch(FunPayFetcher.CATALOG_URL), empty_raw_source=True
    ).parse()
    discovered = {
        (category.name.casefold(), section.id, section.name)
        for category in catalog
        for section in category.subcategories
    }
    extractor = FunPayExtractor()
    normalizer = FunPayNormalizer()
    results: list[FunPaySourceVerification] = []
    for spec in LAUNCH_SOURCES:
        if (
            spec.name.casefold(),
            spec.category_id,
            spec.category_name,
        ) not in discovered:
            raise RuntimeError(f"{spec.name}: expected public source category changed.")
        extraction = extractor.extract_with_parameters(
            await fetcher.fetch(spec.category_url)
        )
        if not extraction.evidence.complete:
            raise RuntimeError(f"{spec.name}: {extraction.evidence.reason}")
        monthly: list[FunPayCandidateAssessment] = []
        for item in extraction.items:
            fields = dict(item.parameters)
            if fields.get("f-time") != "1 месяц" or any(
                fields.get(key) != value for key, value in spec.required_parameters
            ):
                continue
            offer = normalizer.normalize([item.offer])[0]
            offer = replace(offer, source_category_id=str(spec.category_id))
            monthly.append(assess_candidate(spec, replace(item, offer=offer)))
        selected = select_review_candidate(monthly)
        status: int | None = None
        if selected is not None:
            assert selected.offer.url is not None
            await fetcher.fetch(selected.offer.url)
            status = fetcher.last_status_code
        results.append(
            FunPaySourceVerification(
                spec=spec,
                returned_items=len(extraction.items),
                monthly_items=len(monthly),
                review_candidates=sum(item.ready_for_review for item in monthly),
                selected=selected,
                url_status=status,
                rejected_title_conflicts=sum(
                    "title_duration_conflict" in item.blockers for item in monthly
                ),
            )
        )
        await asyncio.sleep(1)
    return tuple(results)


async def main() -> int:
    """Print actual source access separately from comparison eligibility."""
    if os.getenv(LIVE_ENV) != LIVE_GUARD:
        print(f"SKIP: set {LIVE_ENV}={LIVE_GUARD} for read-only verification.")
        return 2
    try:
        async with HttpClient(timeout=30, max_retries=1) as http:
            results = await fetch_funpay_launch_sources(http)
    except Exception as exc:
        print(f"FAIL: FunPay source verification failed ({type(exc).__name__}).")
        if isinstance(exc, RuntimeError):
            print(str(exc)[:400])
        return 1
    for result in results:
        print(f"\n{result.spec.name}: {result.spec.category_url}")
        print(
            f"Returned listing: {result.returned_items}; "
            f"monthly variants: {result.monthly_items}"
        )
        print(
            f"Ready for manual review: {result.review_candidates}; "
            f"title duration conflicts: {result.rejected_title_conflicts}"
        )
        if result.selected is not None:
            selected = result.selected
            print(f"Candidate: {selected.offer.external_id} | {selected.offer.title}")
            print(
                f"Price: {selected.offer.price} {selected.offer.currency}; "
                f"seller: {selected.offer.seller_name}"
            )
            print(f"Source fields: {dict(selected.parameters)}")
            print(f"URL: {selected.offer.url}; HTTP: {result.url_status}")
            print("Selection: lowest price among screened offers in this response.")
            print(
                "Still requires human platform, region and activation-condition review."
            )
            print("Not a resale-profit estimate or proof of resale permission.")
        else:
            print(
                "NOT COMPARABLE: launch method/plan is unverified "
                "or source delivery differs."
            )
    print(
        "\nSOURCE ACCESS: 3/3. "
        "No database writes, links, decisions or comparison claims."
    )
    print(
        "Returned listing coverage is not proof of all marketplace offers; "
        "no missing-offer reconciliation is authorized."
    )
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(main()))
