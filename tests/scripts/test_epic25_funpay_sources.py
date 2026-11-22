from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from app.parsers.funpay_extractor import FunPayOfferEvidence
from app.parsers.models import ParsedOffer
from scripts.verify_epic25_funpay_sources import (
    LAUNCH_SOURCES,
    LIVE_ENV,
    assess_candidate,
    main,
)


def _evidence(
    *,
    title: str = "ExitLag 1 месяц",
    method: str = "цифровой код",
    duration: str = "1 месяц",
    platform: str = "pc",
) -> FunPayOfferEvidence:
    """Build an offline unit fixture, never a claimed live marketplace response."""
    return FunPayOfferEvidence(
        offer=ParsedOffer(
            marketplace="funpay",
            external_id="1",
            title=title,
            url="https://funpay.com/lots/offer?id=1",
            price=Decimal("790"),
            currency="RUB",
            seller_name="Unit fixture seller",
        ),
        parameters=tuple(
            sorted(
                {
                    "f-time": duration,
                    "f-method": method,
                    "f-type": platform,
                }.items()
            )
        ),
    )


def test_explicit_monthly_pc_key_can_be_queued_not_auto_linked() -> None:
    assessment = assess_candidate(LAUNCH_SOURCES[0], _evidence())
    assert assessment.ready_for_review
    assert assessment.delivery_method == "key"
    assert assessment.requires_account_access is False
    assert assessment.offer.canonical_product_id is None


@pytest.mark.parametrize(
    "title",
    [
        "ExitLag 12 мес",
        "ExitLag 1 год",
        "ExitLag 1 неделя",
        "ExitLag 27 дней",
        "ExitLag 3 months",
        "ExitLag 7 days",
        "ExitLag １２ месяцев",
    ],
)
def test_conflicting_title_cannot_hide_behind_month_filter(title: str) -> None:
    assessment = assess_candidate(LAUNCH_SOURCES[0], _evidence(title=title))
    assert "title_duration_conflict" in assessment.blockers
    assert not assessment.ready_for_review


@pytest.mark.parametrize(
    "title", ["ExitLag 30 дней", "ExitLag 1 month", "ExitLag 1 месяц"]
)
def test_known_one_month_duration_forms_remain_reviewable(title: str) -> None:
    assert assess_candidate(LAUNCH_SOURCES[0], _evidence(title=title)).ready_for_review


@pytest.mark.parametrize(
    ("method", "mapped", "access"),
    [
        ("с заходом на аккаунт", "own_account", True),
        ("%готовый аккаунт-account with purchased subscription", "new_account", None),
        ("без захода на аккаунт", None, False),
        ("акционный код (discord)", None, None),
        ("", None, None),
    ],
)
def test_unknown_and_different_methods_never_become_key_equivalents(
    method: str,
    mapped: str | None,
    access: bool | None,
) -> None:
    assessment = assess_candidate(LAUNCH_SOURCES[0], _evidence(method=method))
    assert not assessment.ready_for_review
    assert assessment.delivery_method == mapped
    assert assessment.requires_account_access is access


def test_source_duration_and_platform_are_required() -> None:
    assert not assess_candidate(
        LAUNCH_SOURCES[0], _evidence(duration="3 месяца")
    ).ready_for_review
    assert not assess_candidate(
        LAUNCH_SOURCES[0], _evidence(platform="mobile")
    ).ready_for_review


@pytest.mark.parametrize(
    "price", [Decimal("NaN"), Decimal("Infinity"), Decimal("0"), Decimal("-1")]
)
def test_invalid_price_cannot_enter_review_selection(price: Decimal) -> None:
    evidence = _evidence()
    evidence = replace(evidence, offer=replace(evidence.offer, price=price))
    assert "incomplete_offer" in assess_candidate(LAUNCH_SOURCES[0], evidence).blockers


def test_title_does_not_supply_missing_source_method() -> None:
    evidence = _evidence(title="ExitLag KEY CODE 1 month", method="")
    assert not assess_candidate(LAUNCH_SOURCES[0], evidence).ready_for_review


@pytest.mark.parametrize("disabled,amount", [(True, None), (False, 0)])
def test_unavailable_listing_is_never_queued(
    disabled: bool, amount: int | None
) -> None:
    evidence = replace(_evidence(), disabled=disabled, available_amount=amount)
    assert (
        "source_offer_unavailable"
        in assess_candidate(LAUNCH_SOURCES[0], evidence).blockers
    )


def test_unknown_duolingo_plan_and_spotify_fulfillment_fail_closed() -> None:
    assert not assess_candidate(
        LAUNCH_SOURCES[1], _evidence(platform="super")
    ).ready_for_review
    assert not assess_candidate(
        LAUNCH_SOURCES[2], _evidence(platform="individual")
    ).ready_for_review


def test_live_guard_performs_no_request_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LIVE_ENV, raising=False)
    assert asyncio.run(main()) == 2
