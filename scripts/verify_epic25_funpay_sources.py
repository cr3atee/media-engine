"""Inspect real FunPay subscription candidates without linking or persisting them."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funpayparsers.parsers.categories_parser import CategoriesParser  # noqa: E402

from app.core.http_client import HttpClient  # noqa: E402
from app.parsers.funpay_extractor import (  # noqa: E402
    FunPayExtractor,
    FunPayOfferEvidence,
)
from app.parsers.funpay_fetcher import FunPayFetcher  # noqa: E402
from app.parsers.funpay_normalizer import FunPayNormalizer  # noqa: E402
from app.parsers.models import ParsedOffer  # noqa: E402

LIVE_ENV = "EPIC25_FUNPAY_LIVE_VERIFY"
LIVE_GUARD = "I_UNDERSTAND_THIS_CONTACTS_FUNPAY"
_DURATION = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:[-\N{EN DASH}\N{EM DASH}]\s*)?"
    r"(месяц(?:а|ев)?|мес\.?|дней|дня|день|год(?:а|ов)?|лет|"
    r"недел(?:я|и|ь)|months?|days?|years?|weeks?)(?!\w)",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class FunPayLaunchSpec:
    """An exact source category and the existing launch product it can inform."""

    name: str
    hub_code: str
    category_id: int
    category_name: str
    required_parameters: tuple[tuple[str, str], ...]
    expected_delivery_method: str | None

    @property
    def category_url(self) -> str:
        """Return the numeric listing URL discovered in FunPay's public catalog."""
        return f"https://funpay.com/lots/{self.category_id}/"


LAUNCH_SOURCES = (
    FunPayLaunchSpec(
        "ExitLag", "exitlag", 1568, "Подписка", (("f-type", "pc"),), "key"
    ),
    FunPayLaunchSpec(
        "Duolingo", "duolingo", 4522, "Подписка", (("f-type", "super"),), "key"
    ),
    FunPayLaunchSpec(
        "Spotify", "spotify", 1217, "Premium", (("f-type", "individual"),), None
    ),
)


@dataclass(slots=True, frozen=True)
class FunPayCandidateAssessment:
    """Conservative listing evidence, not a canonical equivalence decision."""

    offer: ParsedOffer
    parameters: tuple[tuple[str, str], ...]
    delivery_method: str | None
    requires_account_access: bool | None
    blockers: tuple[str, ...]

    @property
    def ready_for_review(self) -> bool:
        """Return whether evidence is sufficient to queue, never to auto-confirm."""
        return not self.blockers


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


def assess_candidate(
    spec: FunPayLaunchSpec,
    evidence: FunPayOfferEvidence,
) -> FunPayCandidateAssessment:
    """Reject unknown/different fulfillment and contradictory duration claims."""
    fields = dict(evidence.parameters)
    blockers: list[str] = []
    if evidence.disabled or evidence.available_amount == 0:
        blockers.append("source_offer_unavailable")
    if fields.get("f-time") != "1 месяц":
        blockers.append("duration_not_one_month")
    if any(fields.get(key) != value for key, value in spec.required_parameters):
        blockers.append("source_variant_mismatch")
    normalized = unicodedata.normalize("NFKC", evidence.offer.title or "").casefold()
    if any(
        not (
            (int(amount) == 1 and unit.startswith(("мес", "month")))
            or (int(amount) == 30 and unit.startswith(("дн", "день", "day")))
        )
        for amount, unit in _DURATION.findall(normalized)
    ):
        blockers.append("title_duration_conflict")
    raw_method = fields.get("f-method")
    method = {
        "цифровой код": "key",
        "с заходом на аккаунт": "own_account",
        "%готовый аккаунт-account with purchased subscription": "new_account",
    }.get(raw_method or "")
    account_access = (
        True
        if raw_method == "с заходом на аккаунт"
        else False
        if raw_method in {"цифровой код", "без захода на аккаунт"}
        else None
    )
    if spec.expected_delivery_method is None:
        blockers.append("launch_delivery_method_unverified")
    if method is None:
        blockers.append("source_delivery_method_unverified")
    elif (
        spec.expected_delivery_method is not None
        and method != spec.expected_delivery_method
    ):
        blockers.append("delivery_method_mismatch")
    if spec.hub_code == "duolingo":
        blockers.append("launch_account_plan_unverified")
    offer = evidence.offer
    if (
        offer.marketplace != "funpay"
        or offer.external_id is None
        or not offer.external_id.isdigit()
        or offer.url != f"https://funpay.com/lots/offer?id={offer.external_id}"
        or offer.price is None
        or not offer.price.is_finite()
        or offer.price <= 0
        or offer.currency != "RUB"
        or not offer.seller_name
    ):
        blockers.append("incomplete_offer")
    return FunPayCandidateAssessment(
        offer=offer,
        parameters=evidence.parameters,
        delivery_method=method,
        requires_account_access=account_access,
        blockers=tuple(blockers),
    )


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
        eligible = sorted(
            (item for item in monthly if item.ready_for_review),
            key=lambda item: int(item.offer.external_id or "0"),
        )
        selected = eligible[0] if eligible else None
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
                review_candidates=len(eligible),
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
            print(
                "Still requires human platform, region and activation-condition review."
            )
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
