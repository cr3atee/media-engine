from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

import pytest

from app.core.http_client import HttpClient
from app.parsers.models import ParsedOffer
from scripts import verify_aligned_marketplace_categories as aligned


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one asynchronous verifier scenario."""
    return asyncio.run(awaitable)


def test_aligned_fetch_isolates_one_marketplace_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed source does not discard evidence from successful sources."""

    async def fetch_ggsel(client: HttpClient) -> aligned.MarketplaceCategoryBatch:
        del client
        return _batch("ggsel", "ggsel-offer")

    async def fetch_playerok(client: HttpClient) -> aligned.MarketplaceCategoryBatch:
        del client
        raise RuntimeError("upstream unavailable")

    async def fetch_funpay(client: HttpClient) -> aligned.MarketplaceCategoryBatch:
        del client
        return _batch("funpay", "funpay-offer")

    monkeypatch.setattr(aligned, "_fetch_ggsel", fetch_ggsel)
    monkeypatch.setattr(aligned, "_fetch_playerok", fetch_playerok)
    monkeypatch.setattr(aligned, "_fetch_funpay", fetch_funpay)

    results = run_async(aligned.fetch_aligned_marketplace_categories_isolated())

    assert [result.marketplace for result in results] == [
        "ggsel",
        "playerok",
        "funpay",
    ]
    assert results[0].succeeded is True
    assert results[1].succeeded is False
    assert results[1].batch is None
    assert results[1].error_code == "RuntimeError"
    assert results[1].error_summary == "upstream unavailable"
    assert results[2].succeeded is True


def test_strict_aligned_fetch_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers requiring all three sources still receive a hard failure."""
    results = (
        aligned.MarketplaceCategoryFetchResult(
            marketplace="ggsel",
            batch=_batch("ggsel", "ggsel-offer"),
        ),
        aligned.MarketplaceCategoryFetchResult(
            marketplace="playerok",
            error_code="PlayerokFetchError",
            error_summary="upstream unavailable",
        ),
        aligned.MarketplaceCategoryFetchResult(
            marketplace="funpay",
            batch=_batch("funpay", "funpay-offer"),
        ),
    )

    async def isolated() -> tuple[aligned.MarketplaceCategoryFetchResult, ...]:
        return results

    monkeypatch.setattr(
        aligned,
        "fetch_aligned_marketplace_categories_isolated",
        isolated,
    )

    with pytest.raises(
        RuntimeError,
        match="playerok:PlayerokFetchError",
    ):
        run_async(aligned.fetch_aligned_marketplace_categories())


def test_partial_main_reports_evidence_but_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Partial evidence is visible but cannot masquerade as a complete run."""
    results = (
        aligned.MarketplaceCategoryFetchResult(
            marketplace="ggsel",
            batch=_batch("ggsel", "ggsel-offer"),
        ),
        aligned.MarketplaceCategoryFetchResult(
            marketplace="playerok",
            error_code="PlayerokFetchError",
            error_summary="HTTP 502",
        ),
        aligned.MarketplaceCategoryFetchResult(
            marketplace="funpay",
            batch=_batch("funpay", "funpay-offer"),
        ),
    )

    async def isolated() -> tuple[aligned.MarketplaceCategoryFetchResult, ...]:
        return results

    monkeypatch.setattr(
        aligned,
        "fetch_aligned_marketplace_categories_isolated",
        isolated,
    )

    exit_code = run_async(aligned.main())
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "playerok: failed [PlayerokFetchError] HTTP 502" in output
    assert "Cross-marketplace pairs: 1" in output
    assert "Status: incomplete" in output


def test_error_summary_is_bounded_and_single_line() -> None:
    """External diagnostics remain concise and terminal-safe."""
    error = RuntimeError("first line\n" + ("x" * 400))

    summary = aligned._safe_error_summary(error)

    assert "\n" not in summary
    assert len(summary) == 240

    html_error = RuntimeError(
        "Playerok returned HTTP 502: <html><h1>Bad Gateway</h1></html>"
    )

    assert aligned._safe_error_summary(html_error) == "Playerok returned HTTP 502"


def test_source_category_diagnostic_is_deterministic_and_bounded() -> None:
    """Live diagnostics expose coverage and stable unique source identities."""
    offers = (
        _offer("first", source_category_id="28831", source_category_name=None),
        _offer(
            "second",
            source_category_id="28831",
            source_category_name="Digital keys",
        ),
        _offer("third", source_category_id=None, source_category_name=None),
    )
    batch = aligned.MarketplaceCategoryBatch(
        marketplace="ggsel",
        source_total=3,
        offers=offers,
        snapshot_ready_offers=offers,
    )

    assert aligned._source_category_diagnostic(batch) == (
        "source-categories: id=2/3, name=1/3, unique_ids=1 [28831]"
    )


def _batch(
    marketplace: str,
    external_id: str,
) -> aligned.MarketplaceCategoryBatch:
    offer = _offer(external_id, marketplace=marketplace)
    return aligned.MarketplaceCategoryBatch(
        marketplace=marketplace,
        source_total=1,
        offers=(offer,),
        snapshot_ready_offers=(offer,),
    )


def _offer(
    external_id: str,
    *,
    marketplace: str = "ggsel",
    source_category_id: str | None = None,
    source_category_name: str | None = None,
) -> ParsedOffer:
    return ParsedOffer(
        marketplace=marketplace,
        external_id=external_id,
        title="Minecraft Java Bedrock",
        url=f"https://example.com/{external_id}",
        price=Decimal("1000"),
        currency="RUB",
        source_category_id=source_category_id,
        source_category_name=source_category_name,
    )
