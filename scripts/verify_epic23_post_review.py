"""Verify a durable human-reviewed catalog without mutating review state."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC23_CATALOG_REVIEW_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, AuthSettings
from app.database.public_read_scope import (
    create_postgres_public_read_repository_scope,
)
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import engine as default_engine
from app.domain.canonical_offer_decisions import CanonicalOfferDecisionType
from app.domain.offer_availability import OfferAvailabilityStatus
from app.main import create_app
from app.repositories.queries.provider import create_postgres_read_repository_scope
from app.services.repository_scope import RepositoryScopeFactory
from scripts.run_catalog_review_postgres import TENANT_ID

type OfferIdentity = tuple[str, str]
type OfferProductPair = tuple[str, str, UUID]


@dataclass(slots=True, frozen=True)
class CatalogSnapshot:
    """Stable reviewed-catalog facts expected to survive a fresh engine."""

    product_ids: frozenset[UUID]
    active_links: frozenset[OfferProductPair]
    retired_confirmed_links: frozenset[OfferProductPair]
    decision_ids: frozenset[UUID]


class Verification:
    """Collect named post-review checks and stop on the first violation."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one successful invariant or raise its diagnostic name."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")

    def status(self, response: Response, expected: int, name: str) -> None:
        """Require a public API status without hiding a safe body diagnostic."""
        if response.status_code != expected:
            raise AssertionError(
                f"{name}: HTTP {response.status_code}: {response.text[:500]}"
            )
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Verify repository decisions, public reads, and restart persistence."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    verifier = Verification()
    first = await _verify_engine(database_url, verifier, label="initial")
    second = await _verify_engine(database_url, verifier, label="fresh")
    verifier.check("fresh engine retains the reviewed catalog", second == first)
    await default_engine.dispose()

    print()
    print(
        "EPIC 23 post-review verification passed: "
        f"{len(verifier.passed)}/{len(verifier.passed)} checks."
    )
    print(
        "State: "
        f"products={len(first.product_ids)}, "
        f"active_links={len(first.active_links)}, "
        f"retired_links={len(first.retired_confirmed_links)}, "
        f"decisions={len(first.decision_ids)}"
    )
    print("Mode: read-only; no catalog decision or availability state was changed.")
    return 0


async def _verify_engine(
    database_url: str,
    verifier: Verification,
    *,
    label: str,
) -> CatalogSnapshot:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    scope = create_postgres_repository_scope(sessions)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        verifier.check(
            f"{label} engine uses the current Alembic head",
            revision == _migration_head(),
        )
        snapshot = await _verify_repositories(scope, verifier, label=label)
        await _verify_public_api(
            sessions,
            scope,
            snapshot,
            verifier,
            label=label,
        )
        return snapshot
    finally:
        await engine.dispose()


async def _verify_repositories(
    scope: RepositoryScopeFactory,
    verifier: Verification,
    *,
    label: str,
) -> CatalogSnapshot:
    async with scope() as repositories:
        products = tuple(
            await repositories.canonical_products.list_by_tenant(TENANT_ID)
        )
        visible_offers = tuple(await repositories.offers.list_by_tenant(TENANT_ID))
        decisions = tuple(
            await repositories.canonical_offer_decisions.list_by_tenant(TENANT_ID)
        )
        availability = {
            (decision.marketplace, decision.external_id): (
                await repositories.offers.get_availability_state(
                    TENANT_ID,
                    decision.marketplace,
                    decision.external_id,
                )
            )
            for decision in decisions
        }

    product_ids = frozenset(product.id for product in products)
    active_links = frozenset(
        (offer.marketplace, offer.external_id, offer.canonical_product_id)
        for offer in visible_offers
        if offer.external_id is not None and offer.canonical_product_id is not None
    )
    confirmed = frozenset(
        (
            decision.marketplace,
            decision.external_id,
            decision.canonical_product_id,
        )
        for decision in decisions
        if decision.decision is CanonicalOfferDecisionType.CONFIRMED
    )
    rejected = frozenset(
        (
            decision.marketplace,
            decision.external_id,
            decision.canonical_product_id,
        )
        for decision in decisions
        if decision.decision is CanonicalOfferDecisionType.REJECTED
    )
    retired_confirmed = frozenset(
        pair
        for pair in confirmed
        if (state := availability.get((pair[0], pair[1]))) is not None
        and state.status is OfferAvailabilityStatus.RETIRED
    )

    verifier.check(f"{label} catalog has canonical products", bool(product_ids))
    verifier.check(f"{label} catalog has immutable decisions", bool(decisions))
    verifier.check(
        f"{label} decisions reference existing products",
        all(decision.canonical_product_id in product_ids for decision in decisions),
    )
    verifier.check(
        f"{label} active links have confirmed decisions",
        active_links <= confirmed,
    )
    verifier.check(
        f"{label} rejected pairs are not active links",
        active_links.isdisjoint(rejected),
    )
    verifier.check(
        f"{label} every reviewed offer has availability state",
        all(state is not None for state in availability.values()),
    )
    verifier.check(
        f"{label} retired confirmed links are excluded from active reads",
        retired_confirmed.isdisjoint(active_links),
    )
    verifier.check(
        f"{label} decision identities are unique",
        len({decision.id for decision in decisions}) == len(decisions),
    )
    return CatalogSnapshot(
        product_ids=product_ids,
        active_links=active_links,
        retired_confirmed_links=retired_confirmed,
        decision_ids=frozenset(decision.id for decision in decisions),
    )


async def _verify_public_api(
    sessions: async_sessionmaker[Any],
    scope: RepositoryScopeFactory,
    snapshot: CatalogSnapshot,
    verifier: Verification,
    *,
    label: str,
) -> None:
    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=False,
            api_docs_enabled=False,
        ),
        auth_settings=AuthSettings(
            access_token_secret=SecretStr("epic23-post-review-verification-secret")
        ),
        read_repository_scope_factory=create_postgres_read_repository_scope(sessions),
        public_read_repository_scope_factory=(
            create_postgres_public_read_repository_scope(sessions)
        ),
        repository_scope_factory=scope,
    )
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://epic23-post-review.local",
    ) as client:
        products_response = await client.get("/api/v1/public/products?limit=100")
        verifier.status(products_response, 200, f"{label} public product list")
        product_cards = _items(products_response)
        active_product_ids = {product_id for _, _, product_id in snapshot.active_links}
        verifier.check(
            f"{label} public products equal active reviewed products",
            {UUID(str(card["id"])) for card in product_cards} == active_product_ids,
        )

        for card in product_cards:
            product_id = UUID(str(card["id"]))
            expected_links = {
                (marketplace, external_id)
                for marketplace, external_id, linked_product_id in snapshot.active_links
                if linked_product_id == product_id
            }
            offers_response = await client.get(
                f"/api/v1/public/products/{product_id}/offers?limit=100"
            )
            comparison_response = await client.get(
                f"/api/v1/public/products/{product_id}/comparison"
            )
            verifier.status(
                offers_response,
                200,
                f"{label} public offers for {product_id}",
            )
            verifier.status(
                comparison_response,
                200,
                f"{label} public comparison for {product_id}",
            )
            public_offers = _items(offers_response)
            comparison = _body(comparison_response)
            public_identities = {
                (str(offer["marketplace"]), str(offer["external_id"]))
                for offer in public_offers
            }
            comparison_offers = cast(list[dict[str, Any]], comparison["offers"])
            comparison_identities = {
                (str(offer["marketplace"]), str(offer["external_id"]))
                for offer in comparison_offers
            }
            verifier.check(
                f"{label} public offers match active links for {product_id}",
                public_identities == expected_links,
            )
            verifier.check(
                f"{label} comparison uses the public offer set for {product_id}",
                comparison_identities == expected_links,
            )
            _verify_comparison_truth(
                comparison,
                public_offers,
                verifier,
                name=f"{label} comparison truth for {product_id}",
            )

        retired_identities: set[OfferIdentity] = {
            (marketplace, external_id)
            for marketplace, external_id, _ in snapshot.retired_confirmed_links
        }
        all_public_identities = {
            (str(offer["marketplace"]), str(offer["external_id"]))
            for card in product_cards
            for offer in _items(
                await client.get(
                    f"/api/v1/public/products/{card['id']}/offers?limit=100"
                )
            )
        }
        verifier.check(
            f"{label} retired reviewed offers are absent from public API",
            retired_identities.isdisjoint(all_public_identities),
        )


def _verify_comparison_truth(
    comparison: dict[str, Any],
    offers: list[dict[str, Any]],
    verifier: Verification,
    *,
    name: str,
) -> None:
    currencies = {str(offer["currency"]) for offer in offers}
    if len(currencies) > 1:
        verifier.check(
            name,
            comparison["status"] == "currency_mismatch"
            and comparison["best_offer"] is None,
        )
        return

    best_offer = cast(dict[str, Any] | None, comparison["best_offer"])
    expected_price = min(Decimal(str(offer["price"])) for offer in offers)
    verifier.check(
        name,
        comparison["status"] == "complete"
        and best_offer is not None
        and Decimal(str(best_offer["price"])) == expected_price,
    )


def _body(response: Response) -> dict[str, Any]:
    body = response.json()
    if not isinstance(body, dict):
        raise AssertionError("Public API returned a non-object response.")
    return cast(dict[str, Any], body)


def _items(response: Response) -> list[dict[str, Any]]:
    items = _body(response).get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise AssertionError("Public API returned an invalid item collection.")
    return cast(list[dict[str, Any]], items)


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    host = (url.host or "").lower()
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must target a loopback host.")
    if not database_name.startswith("epic23_catalog_review_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"epic23_catalog_review_* database; got {database_name!r}."
        )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
