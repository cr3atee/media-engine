"""Bounded public ingestion and polite HTTP pacing for reviewed price refreshes."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from app.core.http_client import Headers, HttpClient, QueryParams
from app.parsers.funpay_extractor import FunPayExtractor
from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.funpay_normalizer import FunPayNormalizer
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.normalizers import OfferNormalizer
from app.parsers.source_snapshot import SourceSnapshotEvidence
from app.services.marketplace_ingestion import MarketplaceIngestionResult


class MarketplacePollingCooldownError(RuntimeError):
    """No network request was made because a source is still cooling down."""


class PollingHttpClient(HttpClient):
    """Reuse HTTP infrastructure with no retries, pacing and source cooldowns."""

    def __init__(
        self,
        *,
        cooldown_seconds: float = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not math.isfinite(cooldown_seconds) or cooldown_seconds < 1800:
            raise ValueError("Polling cooldown must be at least 1800 seconds.")
        super().__init__(timeout=30, max_retries=1)
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._blocked_until: dict[str, datetime] = {}
        self._last_request_at: datetime | None = None

    async def __aenter__(self) -> Self:
        """Retain the specialized client type within its async resource scope."""
        return self

    async def _request(
        self,
        method: str,
        url: str,
        *,
        content: Any = None,
        json: Any = None,
        params: QueryParams | None = None,
        headers: Headers | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> httpx.Response:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or host not in {"api.ggsel.com", "funpay.com", "www.funpay.com"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValueError("Polling request is outside the public source allowlist.")
        if host == "www.funpay.com":
            host = "funpay.com"
        now = self._clock()
        if now < self._blocked_until.get(host, datetime.min.replace(tzinfo=UTC)):
            raise MarketplacePollingCooldownError("Public source cooldown is active.")
        if self._last_request_at is not None:
            remaining = 1.0 - (now - self._last_request_at).total_seconds()
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_request_at = self._clock()
        response = await super()._request(
            method,
            url,
            content=content,
            json=json,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code in {403, 429}:
            now = self._clock()
            delay = self._cooldown_seconds
            value = response.headers.get("retry-after", "")
            if value:
                try:
                    seconds = float(value)
                except ValueError:
                    try:
                        deadline = parsedate_to_datetime(value)
                        seconds = (
                            deadline.replace(tzinfo=UTC)
                            if deadline.tzinfo is None
                            else deadline.astimezone(UTC)
                        ).timestamp() - now.timestamp()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                if math.isfinite(seconds):
                    delay = max(delay, seconds)
            try:
                self._blocked_until[host] = now + timedelta(seconds=delay)
            except OverflowError:
                self._blocked_until[host] = datetime.max.replace(tzinfo=UTC)
        return response


async def ingest_curated_category(
    http_client: HttpClient,
    marketplace: str,
    url: str,
) -> MarketplaceIngestionResult:
    """Reuse current parsers; a curated subset never authorizes deactivation."""
    if marketplace == "ggsel":
        extraction = GGSelExtractor().extract_source_items(
            await GGSelFetcher(http_client, max_pages=10).fetch_complete_category(url)
        )
        normalizer = OfferNormalizer("ggsel")
        offers = tuple(normalizer.normalize(item) for item in extraction.items)
        evidence = extraction.evidence
    elif marketplace == "funpay":
        raw = await FunPayFetcher(http_client).fetch(url)
        listing = FunPayExtractor().extract_with_parameters(raw)
        from app.services.funpay_pipeline import funpay_source_category_id

        category_id = funpay_source_category_id(url)
        if category_id is None:
            raise ValueError("Curated FunPay source must be a category listing.")
        offers = tuple(
            FunPayNormalizer().normalize(
                [
                    replace(item.offer, source_category_id=category_id)
                    for item in listing.items
                    if not item.disabled and item.available_amount != 0
                ]
            )
        )
        evidence = listing.evidence
    else:
        raise ValueError("Unsupported curated price source.")
    if not evidence.complete:
        raise ValueError("Source parsing coverage is incomplete; old prices retained.")
    return MarketplaceIngestionResult(
        offers=offers,
        evidence=SourceSnapshotEvidence(
            source_items=evidence.source_items,
            parsed_items=len(offers),
            expected_items=evidence.expected_items,
            complete=False,
            reason="Reviewed price refresh; missing-offer reconciliation disabled.",
        ),
    )
