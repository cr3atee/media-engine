from __future__ import annotations

from typing import Any

import pytest

from scripts.verify_epic23_post_review import (
    DATABASE_URL_ENV,
    Verification,
    _require_isolated_database,
    _verify_comparison_truth,
)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_post_review_verifier_accepts_only_isolated_loopback_postgres(
    host: str,
) -> None:
    url_host = f"[{host}]" if ":" in host else host

    _require_isolated_database(
        f"postgresql+asyncpg://reviewer:secret@{url_host}/epic23_catalog_review_test"
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///epic23_catalog_review_test.db",
        "postgresql+asyncpg://db.internal/epic23_catalog_review_test",
        "postgresql+asyncpg://localhost/mediaengine",
    ],
)
def test_post_review_verifier_rejects_unsafe_database(database_url: str) -> None:
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        _require_isolated_database(database_url)


def test_comparison_truth_accepts_currency_mismatch_without_best_offer() -> None:
    verifier = Verification()
    offers = [
        _offer("ggsel", "one", "100", "RUB"),
        _offer("funpay", "two", "2", "EUR"),
    ]

    _verify_comparison_truth(
        {"status": "currency_mismatch", "best_offer": None},
        offers,
        verifier,
        name="currency mismatch",
    )

    assert verifier.passed == ["currency mismatch"]


def test_comparison_truth_requires_the_lowest_same_currency_offer() -> None:
    verifier = Verification()
    offers = [
        _offer("ggsel", "one", "1899", "RUB"),
        _offer("playerok", "two", "1745", "RUB"),
    ]

    _verify_comparison_truth(
        {"status": "complete", "best_offer": offers[1]},
        offers,
        verifier,
        name="lowest offer",
    )

    assert verifier.passed == ["lowest offer"]


def _offer(
    marketplace: str,
    external_id: str,
    price: str,
    currency: str,
) -> dict[str, Any]:
    return {
        "marketplace": marketplace,
        "external_id": external_id,
        "price": price,
        "currency": currency,
    }
