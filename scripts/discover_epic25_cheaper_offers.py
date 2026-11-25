"""Discover real cheaper monthly offers; optional intake never approves/publishes."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.parsers.models import ParsedOffer
from app.runtime.curated_prices import PollingHttpClient
from app.services.cheaper_offer_discovery import CheaperOfferDiscoveryService
from app.services.cheaper_offer_review_intake import (
    CandidateIntakeResult,
    CheaperOfferReviewIntakeService,
)
from scripts.run_catalog_review_postgres import TENANT_ID, _require_isolated_database
from scripts.run_epic25_price_refresh import (
    DATABASE_ENV,
    load_refresh_targets,
    require_local_catalog,
)

LIVE_ENV = "EPIC25_CANDIDATE_DISCOVERY_LIVE"
LIVE_GUARD = "I_UNDERSTAND_THIS_CONTACTS_GGSEL_AND_FUNPAY"
REVIEW_ENV = "EPIC25_CANDIDATE_REVIEW_DATABASE_URL"


def require_review_database(url: str) -> None:
    """Intake may use only the retained local review or a discovery test copy."""
    _require_isolated_database(url)
    name = make_url(url).database or ""
    if name != "epic23_catalog_review_epic25_manual" and not name.startswith(
        "epic23_catalog_review_epic25_discovery_verify_"
    ):
        raise ValueError("Only the separate local candidate-review DB is allowed.")


def offer_record(offer: ParsedOffer) -> dict[str, object]:
    """Serialize only source facts and product identity, never connection settings."""
    return {
        "marketplace": offer.marketplace,
        "external_id": offer.external_id,
        "title": offer.title,
        "url": offer.url,
        "price": str(offer.price) if offer.price is not None else None,
        "currency": offer.currency,
        "seller_name": offer.seller_name,
        "source_category_id": offer.source_category_id,
        "canonical_product_id": str(offer.canonical_product_id)
        if offer.canonical_product_id
        else None,
    }


async def run(arguments: argparse.Namespace) -> int:
    """Read saved baselines, fetch outside transactions, then optionally stage."""
    if os.getenv(LIVE_ENV) != LIVE_GUARD:
        raise ValueError("Explicit live source-discovery guard is required.")
    url = os.getenv(DATABASE_ENV, "")
    require_local_catalog(url)
    review_url = os.getenv(REVIEW_ENV, "")
    if arguments.stage_review:
        require_review_database(review_url)
        if make_url(url).database == make_url(review_url).database:
            raise ValueError("Public catalog and private review DB must be separate.")
    if arguments.output is not None and (
        arguments.output.exists() or not arguments.output.parent.is_dir()
    ):
        raise ValueError("Report needs an existing directory and a new output path.")
    engine = create_async_engine(url)
    review_engine = None
    try:
        scope = create_postgres_repository_scope(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        await load_refresh_targets(scope)
        async with scope() as repositories:
            references: dict[str, list[ParsedOffer]] = {}
            for offer in await repositories.offers.list_by_tenant(TENANT_ID):
                if offer.catalog_hub_code is None:
                    raise ValueError("Approved source lacks its existing hub mapping.")
                references.setdefault(offer.catalog_hub_code, []).append(offer)
        async with PollingHttpClient() as http:
            reports = await CheaperOfferDiscoveryService(http).scan(
                references, limit_per_source=arguments.limit_per_source
            )
        intake: tuple[CandidateIntakeResult, ...] = ()
        if arguments.stage_review:
            review_engine = create_async_engine(review_url)
            review_scope = create_postgres_repository_scope(
                async_sessionmaker(review_engine, expire_on_commit=False)
            )
            intake = await CheaperOfferReviewIntakeService(review_scope).stage(
                TENANT_ID, reports
            )
        payload = {
            "scope": "returned_source_prices_only_not_equivalence_or_resale_profit",
            "publications_created": 0,
            "sources": [
                {
                    "hub": result.hub_code,
                    "marketplace": result.marketplace,
                    "source_url": result.source_url,
                    "observed_at": result.observed_at.isoformat(),
                    "saved_reference": offer_record(result.reference_offer),
                    "source_items": result.source_items,
                    "screened_monthly_items": result.monthly_items,
                    "cheaper_items": result.cheaper_items,
                    "error_code": result.error_code,
                    "candidates": [
                        {
                            "offer": offer_record(item.offer),
                            "review_reasons": item.review_reasons,
                            "source_parameters": dict(item.source_parameters),
                        }
                        for item in result.candidates
                    ],
                }
                for result in reports
            ],
            "intake": [
                {
                    "marketplace": item.marketplace,
                    "external_id": item.external_id,
                    "status": item.status,
                }
                for item in intake
            ],
        }
        if arguments.output is not None:
            with arguments.output.open("x", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
        for result in reports:
            print(
                f"\n{result.hub_code} / {result.marketplace}: "
                f"source={result.source_items}; monthly={result.monthly_items}; "
                f"cheaper={result.cheaper_items}; error={result.error_code}"
            )
            print(
                f"Saved reference: {result.reference_offer.price} "
                f"{result.reference_offer.currency}"
            )
            for item in result.candidates:
                print(
                    f"{item.offer.external_id} | {item.offer.price} "
                    f"{item.offer.currency} | {item.offer.seller_name}"
                )
                print(item.offer.title)
                print(item.offer.url)
                print(f"Review required: {', '.join(item.review_reasons)}")
        for outcome in intake:
            print(
                f"Intake {outcome.marketplace}/{outcome.external_id}: {outcome.status}"
            )
        print(
            "No canonical approval, public offer/link change, event, "
            "AI or Telegram call."
        )
        return 1 if any(result.error_code for result in reports) else 0
    finally:
        if review_engine is not None:
            await review_engine.dispose()
        await engine.dispose()
        await default_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Require explicit source/DB guards; default to no persistence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-per-source", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--stage-review", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        return asyncio.run(run(arguments))
    except Exception as error:
        print(f"Discovery failed: {type(error).__name__}; no public release performed.")
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
