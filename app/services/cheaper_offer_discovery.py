"""Find lower asking-price review candidates without approving or persisting them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.selector import BestOfferSelector
from app.core.http_client import HttpClient
from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.services.subscription_candidate_rules import (
    LAUNCH_PRODUCTS,
    LAUNCH_SOURCES,
    FunPayLaunchSpec,
    LaunchProductSpec,
    assess_candidate,
    find_exact_month_candidates,
    has_title_duration_conflict,
)

_REVIEW_ONLY_REASONS = frozenset(
    {
        "launch_delivery_method_unverified",
        "source_delivery_method_unverified",
        "launch_account_plan_unverified",
        "delivery_method_mismatch",
    }
)
_RECOGNIZED_METHODS = frozenset(
    {
        "цифровой код",
        "с заходом на аккаунт",
        "без захода на аккаунт",
        "%готовый аккаунт-account with purchased subscription",
    }
)


@dataclass(slots=True, frozen=True)
class CheaperOfferCandidate:
    """A lower listed price, never verified equivalence, resale profit or a link."""

    offer: ParsedOffer
    review_reasons: tuple[str, ...]
    source_parameters: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True, frozen=True)
class CheaperOfferSourceResult:
    """One bounded source response and its captured saved-price reference."""

    hub_code: str
    marketplace: str
    source_url: str
    observed_at: datetime
    reference_offer: ParsedOffer
    source_items: int | None
    monthly_items: int
    cheaper_items: int
    candidates: tuple[CheaperOfferCandidate, ...]
    error_code: str | None = None


class DiscoverySourceError(RuntimeError):
    """The returned source cannot safely provide candidate evidence."""


class CheaperOfferDiscoveryService:
    """Orchestrate existing parsers, source screening and deterministic selection."""

    def __init__(
        self,
        http_client: HttpClient,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._http = http_client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._selector = BestOfferSelector()

    async def scan(
        self,
        references: Mapping[str, Sequence[ParsedOffer]],
        *,
        limit_per_source: int = 1,
    ) -> tuple[CheaperOfferSourceResult, ...]:
        """Scan six known sources outside repository scopes; never write any state."""
        if set(references) != {spec.hub_code for spec in LAUNCH_PRODUCTS}:
            raise ValueError(
                "Exactly the three approved subscription hubs are required."
            )
        if not 1 <= limit_per_source <= 3:
            raise ValueError(
                "Candidate limit must be between one and three per source."
            )
        tenants = {
            offer.tenant_id for offers in references.values() for offer in offers
        }
        if len(tenants) != 1:
            raise ValueError("Discovery references must belong to one tenant.")
        baselines: dict[str, ParsedOffer] = {}
        for hub, offers in references.items():
            products = {offer.canonical_product_id for offer in offers}
            if (
                len(products) != 1
                or None in products
                or any(not _valid_quote(offer) for offer in offers)
                or any(
                    offer.catalog_hub_code != hub
                    or offer.catalog_section_code != "subscriptions"
                    for offer in offers
                )
            ):
                raise ValueError("References must be valid linked product quotes.")
            selection = self._select(offers)
            if selection is None:
                raise ValueError("Reference quotes must share a currency.")
            baselines[hub] = selection
        if len({offer.canonical_product_id for offer in baselines.values()}) != 3:
            raise ValueError("Each subscription hub needs its own approved product.")

        reports: list[CheaperOfferSourceResult] = []
        for ggsel in LAUNCH_PRODUCTS:
            funpay = next(
                spec for spec in LAUNCH_SOURCES if spec.hub_code == ggsel.hub_code
            )
            for marketplace, spec in (("ggsel", ggsel), ("funpay", funpay)):
                reference = baselines[ggsel.hub_code]
                source_items: int | None = None
                monthly: tuple[CheaperOfferCandidate, ...] = ()
                cheaper: tuple[CheaperOfferCandidate, ...] = ()
                error: str | None = None
                try:
                    if isinstance(spec, LaunchProductSpec):
                        source_items, monthly = await self._ggsel(spec, reference)
                    else:
                        source_items, monthly = await self._funpay(spec, reference)
                    approved_ids = {
                        (offer.marketplace, offer.external_id)
                        for offer in references[ggsel.hub_code]
                    }
                    counts = Counter(
                        (item.offer.marketplace, item.offer.external_id)
                        for item in monthly
                    )
                    assert reference.price is not None
                    cheaper = tuple(
                        item
                        for item in monthly
                        if _valid_quote(item.offer)
                        and item.offer.tenant_id == reference.tenant_id
                        and item.offer.marketplace == marketplace
                        and item.offer.canonical_product_id is None
                        and item.offer.currency == reference.currency
                        and (item.offer.marketplace, item.offer.external_id)
                        not in approved_ids
                        and counts[(item.offer.marketplace, item.offer.external_id)]
                        == 1
                        and item.offer.price is not None
                        and item.offer.price < reference.price
                    )
                except Exception as exc:
                    error = type(exc).__name__
                selected: list[CheaperOfferCandidate] = []
                remaining = list(cheaper)
                while remaining and len(selected) < limit_per_source:
                    best = self._select([item.offer for item in remaining])
                    if best is None:
                        break
                    candidate = next(item for item in remaining if item.offer is best)
                    selected.append(candidate)
                    remaining.remove(candidate)
                reports.append(
                    CheaperOfferSourceResult(
                        ggsel.hub_code,
                        marketplace,
                        spec.category_url,
                        self._clock(),
                        reference,
                        source_items,
                        len(monthly),
                        len(cheaper),
                        tuple(selected),
                        error,
                    )
                )
        return tuple(reports)

    def _select(self, offers: Sequence[ParsedOffer]) -> ParsedOffer | None:
        selected = self._selector.select(
            ProductComparisonInput(
                None, tuple(MarketplaceOffer(offer) for offer in offers)
            ),
            require_activation_conditions=False,
        ).selected_offer
        return selected.offer if selected else None

    async def _ggsel(
        self,
        spec: LaunchProductSpec,
        reference: ParsedOffer,
    ) -> tuple[int, tuple[CheaperOfferCandidate, ...]]:
        extracted = GGSelExtractor().extract_source_items(
            await GGSelFetcher(self._http, max_pages=10).fetch_complete_category(
                spec.category_url
            )
        )
        if not extracted.evidence.complete:
            raise DiscoverySourceError("Incomplete GGSEL source evidence.")
        normalizer = OfferNormalizer("ggsel")
        offers = tuple(normalizer.normalize(item) for item in extracted.items)
        return len(offers), tuple(
            CheaperOfferCandidate(
                replace(offer, tenant_id=reference.tenant_id),
                ("activation_conditions_unverified", "fulfillment_unverified"),
            )
            for offer in find_exact_month_candidates(spec, offers)
            if not has_title_duration_conflict(offer.title)
        )

    async def _funpay(
        self,
        spec: FunPayLaunchSpec,
        reference: ParsedOffer,
    ) -> tuple[int, tuple[CheaperOfferCandidate, ...]]:
        extracted = FunPayExtractor().extract_with_parameters(
            await FunPayFetcher(self._http).fetch(spec.category_url)
        )
        if not extracted.evidence.complete:
            raise DiscoverySourceError("Incomplete FunPay source evidence.")
        monthly: list[CheaperOfferCandidate] = []
        for item in extracted.items:
            fields = dict(item.parameters)
            normalized = FunPayNormalizer().normalize(
                [
                    replace(
                        item.offer,
                        tenant_id=reference.tenant_id,
                        source_category_id=str(spec.category_id),
                    )
                ]
            )[0]
            assessment = assess_candidate(spec, replace(item, offer=normalized))
            if set(assessment.blockers) - _REVIEW_ONLY_REASONS:
                continue
            method = fields.get("f-method", "")
            if method and method not in _RECOGNIZED_METHODS:
                continue
            monthly.append(
                CheaperOfferCandidate(
                    normalized,
                    ("activation_conditions_unverified", *assessment.blockers),
                    item.parameters,
                )
            )
        return len(extracted.items), tuple(monthly)


def _valid_quote(offer: ParsedOffer) -> bool:
    """Require usable priced source evidence before invoking the shared selector."""
    if (
        offer.marketplace not in {"ggsel", "funpay"}
        or not offer.external_id
        or not offer.external_id.isdigit()
        or not offer.title
        or not offer.title.strip()
        or not offer.seller_name
        or not offer.seller_name.strip()
        or not offer.source_category_id
        or not offer.source_category_id.strip()
        or offer.price is None
        or not offer.price.is_finite()
        or offer.price <= Decimal(0)
        or offer.currency != "RUB"
        or not offer.url
    ):
        return False
    try:
        url = urlsplit(offer.url)
        allowed = (
            {"ggsel.net", "www.ggsel.net"}
            if offer.marketplace == "ggsel"
            else {"funpay.com"}
        )
        return (
            url.scheme == "https"
            and url.hostname in allowed
            and url.username is None
            and url.password is None
            and url.port in {None, 443}
            and (
                offer.marketplace != "funpay"
                or offer.url == f"https://funpay.com/lots/offer?id={offer.external_id}"
            )
        )
    except ValueError:
        return False
