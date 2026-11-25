"""Shared existing source rules; screening is never canonical approval."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.comparator.models import MarketplaceOffer, ProductComparisonInput
from app.comparator.selector import BestOfferSelector
from app.parsers.funpay_extractor import FunPayOfferEvidence
from app.parsers.models import ParsedOffer

_GGSEL_DURATION = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:[-\N{EN DASH}\N{EM DASH}]\s*)?"
    r"(months?|days?|years?|weeks?)\b",
    re.IGNORECASE,
)
_WORD_SEPARATOR = re.compile(r"[\W_]+", re.UNICODE)
_DURATION = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:[-\N{EN DASH}\N{EM DASH}]\s*)?"
    r"(месяц(?:а|ев)?|мес\.?|дней|дня|день|год(?:а|ов)?|лет|"
    r"недел(?:я|и|ь)|months?|days?|years?|weeks?)(?!\w)",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class LaunchProductSpec:
    """Describe source evidence required for one launch product."""

    name: str
    hub_code: str
    category_url: str
    required_phrases: tuple[str, ...]
    section_code: str = "subscriptions"
    forbidden_phrases: tuple[str, ...] = ()


LAUNCH_PRODUCTS = (
    LaunchProductSpec(
        "ExitLag - 1 month",
        "exitlag",
        "https://ggsel.net/en/catalog/exitlag",
        ("exitlag",),
    ),
    LaunchProductSpec(
        "Duolingo Super - 1 month",
        "duolingo",
        "https://ggsel.net/en/catalog/duolingo-keys",
        ("duolingo", "super"),
    ),
    LaunchProductSpec(
        "Spotify Premium Individual - 1 month",
        "spotify",
        "https://ggsel.net/en/catalog/spotify-premium",
        ("spotify", "premium", "individual"),
        forbidden_phrases=("duo", "family", "student"),
    ),
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
        """Return the numeric URL previously discovered in the public catalog."""
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
        """Keep the original strict admission policy unchanged."""
        return not self.blockers


def has_title_duration_conflict(title: str | None) -> bool:
    """Reject explicit durations other than one month or thirty days."""
    normalized = unicodedata.normalize("NFKC", title or "").casefold()
    return any(
        not (
            (int(amount) == 1 and unit.startswith(("мес", "month")))
            or (int(amount) == 30 and unit.startswith(("дн", "день", "day")))
        )
        for amount, unit in _DURATION.findall(normalized)
    )


def assess_candidate(
    spec: FunPayLaunchSpec,
    evidence: FunPayOfferEvidence,
) -> FunPayCandidateAssessment:
    """Preserve the existing strict FunPay verifier's checks and reasons."""
    fields = dict(evidence.parameters)
    blockers: list[str] = []
    if evidence.disabled or evidence.available_amount == 0:
        blockers.append("source_offer_unavailable")
    if fields.get("f-time") != "1 месяц":
        blockers.append("duration_not_one_month")
    if any(fields.get(key) != value for key, value in spec.required_parameters):
        blockers.append("source_variant_mismatch")
    if has_title_duration_conflict(evidence.offer.title):
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
        offer, evidence.parameters, method, account_access, tuple(blockers)
    )


def select_review_candidate(
    candidates: Sequence[FunPayCandidateAssessment],
) -> FunPayCandidateAssessment | None:
    """Preserve strict selection for existing callers, using the price selector."""
    eligible = tuple(item for item in candidates if item.ready_for_review)
    selection = BestOfferSelector().select(
        ProductComparisonInput(
            None, tuple(MarketplaceOffer(offer=item.offer) for item in eligible)
        ),
        require_activation_conditions=False,
    )
    selected = selection.selected_offer
    if selected is None:
        return None
    return next(item for item in eligible if item.offer is selected.offer)


def find_exact_month_candidates(
    spec: LaunchProductSpec,
    offers: tuple[ParsedOffer, ...],
) -> tuple[ParsedOffer, ...]:
    """Preserve existing GGSEL title matching and identity-ordered evidence."""

    def matches(offer: ParsedOffer) -> bool:
        if offer.title is None:
            return False
        padded = (
            f" {' '.join(_WORD_SEPARATOR.sub(' ', offer.title.casefold()).split())} "
        )

        def phrase(value: str) -> str:
            return f" {' '.join(_WORD_SEPARATOR.sub(' ', value.casefold()).split())} "

        if any(phrase(term) not in padded for term in spec.required_phrases):
            return False
        if any(phrase(term) in padded for term in spec.forbidden_phrases):
            return False
        durations = _GGSEL_DURATION.findall(offer.title)
        return bool(durations) and all(
            (int(amount) == 1 and unit.casefold().startswith("month"))
            or (int(amount) == 30 and unit.casefold().startswith("day"))
            for amount, unit in durations
        )

    def identity(offer: ParsedOffer) -> tuple[int, str]:
        value = offer.external_id or ""
        return int(value) if value.isdigit() else sys.maxsize, value

    return tuple(sorted((offer for offer in offers if matches(offer)), key=identity))
