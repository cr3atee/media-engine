# ruff: noqa: E402,I001

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID, uuid5

from fastapi.testclient import TestClient
from pydantic import SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import AdminApiSettings
from app.main import create_app
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.repositories.public_queries.repository_backed import (
    create_repository_backed_public_read_scope_factory,
)
from app.services.snapshot_builder import SnapshotBuilder
from scripts.verify_marketplace_payload_contracts import (
    collect_readiness,
    validate_readiness,
)
from scripts.verify_marketplace_data_readiness import MarketplaceReadiness

_PRODUCT_NAMESPACE = UUID("00000000-0000-0000-0000-000000000019")


@dataclass(slots=True, frozen=True)
class SeededProduct:
    """Product seeded from one real saved marketplace offer."""

    product: CanonicalProduct
    offer: ParsedOffer


@dataclass(slots=True, frozen=True)
class PublicUiReadiness:
    """Verification result for buyer-facing UI DTO readiness."""

    checks: int
    seeded_products: tuple[SeededProduct, ...]
    notes: tuple[str, ...]


def main() -> int:
    """Verify saved marketplace payloads through public API response DTOs."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    readiness = collect_readiness()
    violations = list(validate_readiness(readiness))
    provider = create_memory_provider()
    seeded_products, seed_notes = _seed_provider(provider, readiness)
    notes = list(seed_notes)

    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("public-ui-readiness-secret"),
        ),
        public_read_repository_scope_factory=(
            create_repository_backed_public_read_scope_factory(provider)
        ),
    )
    client = TestClient(app, raise_server_exceptions=False)
    check_count = 0

    print("=== PUBLIC UI READINESS ===")
    for result in readiness:
        print(
            f"{result.marketplace}: "
            f"status={result.status}, "
            f"raw={result.raw_items}, "
            f"parsed={result.parsed_offers}, "
            f"snapshot_ready={result.snapshot_ready_offers}"
        )

    products_response = client.get("/api/v1/public/products?limit=10")
    check_count += _expect_status(
        products_response.status_code,
        200,
        "products",
        violations,
    )
    products = products_response.json()["items"]
    if len(products) != len(seeded_products):
        violations.append(
            f"products: expected {len(seeded_products)} cards, got {len(products)}"
        )
    else:
        check_count += 1

    for seeded in seeded_products:
        product_id = str(seeded.product.id)
        detail = client.get(f"/api/v1/public/products/{product_id}")
        offers = client.get(f"/api/v1/public/products/{product_id}/offers")
        comparison = client.get(f"/api/v1/public/products/{product_id}/comparison")
        history = client.get(
            f"/api/v1/public/products/{product_id}/price-history?period=all"
        )

        check_count += _expect_status(
            detail.status_code,
            200,
            "product detail",
            violations,
        )
        check_count += _expect_status(
            offers.status_code,
            200,
            "product offers",
            violations,
        )
        check_count += _expect_status(
            comparison.status_code,
            200,
            "comparison",
            violations,
        )
        check_count += _expect_status(
            history.status_code,
            200,
            "price history",
            violations,
        )

        offer_items = offers.json()["items"]
        history_items = history.json()["items"]
        comparison_body = comparison.json()
        if not offer_items:
            violations.append(f"{seeded.offer.marketplace}: no public offer rows")
        else:
            check_count += 1
            _validate_public_offer(seeded.offer.marketplace, offer_items[0], violations)
        if not history_items:
            violations.append(f"{seeded.offer.marketplace}: no public history points")
        else:
            check_count += 1
        if not comparison_body["offers"]:
            violations.append(f"{seeded.offer.marketplace}: no comparison offers")
        else:
            check_count += 1

    price_changes = client.get("/api/v1/public/price-changes?limit=10")
    categories = client.get("/api/v1/public/categories?limit=10")
    check_count += _expect_status(
        price_changes.status_code,
        200,
        "price changes",
        violations,
    )
    check_count += _expect_status(
        categories.status_code,
        200,
        "categories",
        violations,
    )

    if not price_changes.json()["items"]:
        notes.append(
            "Latest price-change DTOs were route-verified as empty because saved "
            "marketplace payloads contain current offers, not historical previous "
            "snapshots or durable scored events."
        )
    if not categories.json()["items"]:
        notes.append(
            "Category DTOs were route-verified as empty because the current "
            "ParsedOffer contract does not retain marketplace category fields."
        )

    print()
    print(f"Seeded public products: {len(seeded_products)}")
    for seeded in seeded_products:
        print(
            "- "
            f"{seeded.offer.marketplace}: "
            f"{seeded.offer.title or 'untitled'} | "
            f"{seeded.offer.price} {seeded.offer.currency} | "
            f"{seeded.offer.url or 'no url'}"
        )

    print()
    print(f"Public UI checks: {check_count}")
    print("Notes:")
    for note in notes:
        print(f"- {note}")

    if violations:
        print()
        print("Violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print()
    print("Public UI readiness passed.")
    return 0


async def _save_seeded_data(
    provider: RepositoryProvider,
    products: Iterable[SeededProduct],
) -> None:
    builder = SnapshotBuilder()
    for seeded in products:
        await provider.canonical_products.save(seeded.product)
        await provider.offers.save(seeded.offer)
        await provider.price_history.add(builder.build(seeded.offer))


def _seed_provider(
    provider: RepositoryProvider,
    readiness: Iterable[MarketplaceReadiness],
) -> tuple[tuple[SeededProduct, ...], tuple[str, ...]]:
    seeded_products: list[SeededProduct] = []
    notes: list[str] = []
    for result in readiness:
        offer = next(
            (
                item
                for item in result.examples
                if item.external_id is not None
                and item.title is not None
                and item.price is not None
                and item.currency is not None
            ),
            None,
        )
        if offer is None:
            notes.append(f"{result.marketplace}: no snapshot-ready example to seed.")
            continue
        title = offer.title
        assert title is not None
        if offer.url is None:
            notes.append(f"{result.marketplace}: saved offer has no public URL.")

        product = CanonicalProduct(
            id=uuid5(_PRODUCT_NAMESPACE, f"{offer.marketplace}:{offer.external_id}"),
            name=title,
            category=None,
            aliases=(),
            tenant_id=offer.tenant_id,
        )
        seeded_products.append(
            SeededProduct(
                product=product,
                offer=replace(offer, canonical_product_id=product.id),
            )
        )

    asyncio.run(_save_seeded_data(provider, seeded_products))
    return tuple(seeded_products), tuple(notes)


def _validate_public_offer(
    marketplace: str,
    offer: dict[str, object],
    violations: list[str],
) -> None:
    required_fields = (
        "marketplace",
        "external_id",
        "title",
        "url",
        "price",
        "currency",
    )
    for field_name in required_fields:
        if offer.get(field_name) in (None, ""):
            violations.append(f"{marketplace}: missing public offer field {field_name}")


def _expect_status(
    actual: int,
    expected: int,
    label: str,
    violations: list[str],
) -> int:
    if actual == expected:
        return 1
    violations.append(f"{label}: expected HTTP {expected}, got {actual}")
    return 0


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
