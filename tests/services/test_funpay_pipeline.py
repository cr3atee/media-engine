from __future__ import annotations

import asyncio

from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.services.funpay_pipeline import FunPayPipeline, funpay_source_category_id

_LISTING = """
<html><body>
  <div class="tc showcase-table">
    <a href="/lots/offer?id=1" class="tc-item" data-offer="1">
      <div class="tc-desc-text">Minecraft Premium</div>
      <div class="tc-price" data-s="790"><div>790 RUB</div></div>
    </a>
  </div>
</body></html>
"""


def test_funpay_pipeline_preserves_category_from_trusted_listing_url() -> None:
    """A FunPay listing path becomes exact source evidence for every offer."""
    result = asyncio.run(_pipeline().ingest("https://funpay.com/lots/4176/"))

    assert result.evidence.complete is True
    assert len(result.offers) == 1
    assert result.offers[0].source_category_id == "4176"
    assert result.offers[0].source_category_name is None


def test_funpay_pipeline_does_not_invent_category_for_untrusted_url() -> None:
    """A lookalike host cannot inject marketplace source evidence."""
    result = asyncio.run(_pipeline().ingest("https://example.com/lots/4176/"))

    assert result.offers[0].source_category_id is None


def test_funpay_pipeline_uses_final_redirect_url_as_source_evidence() -> None:
    """Only the final fetched listing URL supplies its category identity."""
    pipeline = FunPayPipeline(
        fetcher=_StaticFunPayFetcher(
            _LISTING,
            last_url="https://funpay.com/en/lots/1015/",
        ),
        extractor=FunPayExtractor(),
        normalizer=FunPayNormalizer(),
    )

    result = asyncio.run(pipeline.ingest("https://funpay.com/redirect"))

    assert result.offers[0].source_category_id == "1015"


def test_funpay_source_category_requires_numeric_listing_identity() -> None:
    """Offer pages and malformed listing paths remain unclassified."""
    assert funpay_source_category_id("https://funpay.com/en/lots/1015/") == "1015"
    assert funpay_source_category_id("https://www.funpay.com/lots/3486/") == "3486"
    assert funpay_source_category_id("https://funpay.com/lots/offer?id=1") is None
    assert funpay_source_category_id("https://funpay.com/users/4176/") is None
    assert funpay_source_category_id("https://funpay.com/fake/lots/4176/") is None
    assert funpay_source_category_id("file:///lots/4176/") is None


def _pipeline() -> FunPayPipeline:
    return FunPayPipeline(
        fetcher=_StaticFunPayFetcher(_LISTING),
        extractor=FunPayExtractor(),
        normalizer=FunPayNormalizer(),
    )


class _StaticFunPayFetcher(FunPayFetcher):
    def __init__(self, response: str, *, last_url: str | None = None) -> None:
        self._response = response
        self.last_url = last_url

    async def fetch(self, url: str = FunPayFetcher.DEFAULT_URL) -> str:
        del url
        return self._response
