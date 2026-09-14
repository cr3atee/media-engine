"""Verify the EPIC 19 public UI flow against isolated PostgreSQL."""

# ruff: noqa: E402, I001

from __future__ import annotations

import asyncio
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC19_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings
from app.database.session import SessionLocal, engine
from app.main import create_app
from app.repositories.provider import create_postgres_provider
from scripts.verify_marketplace_payload_contracts import (
    collect_readiness,
    validate_readiness,
)
from scripts.verify_public_ui_readiness import (
    SeededProduct,
    build_seeded_products,
    save_seeded_data,
)

DATABASE_URL_ENV = "EPIC19_DATABASE_URL"


class Verification:
    """Collect and print named PostgreSQL public UI checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(
        self,
        name: str,
        condition: bool,
        *,
        diagnostic: str | None = None,
    ) -> None:
        """Record one passing check or raise a focused diagnostic."""
        if not condition:
            suffix = f": {diagnostic}" if diagnostic else ""
            raise AssertionError(f"{name}{suffix}")
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run production-shaped public UI verification on isolated PostgreSQL."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    readiness = collect_readiness()
    readiness_violations = validate_readiness(readiness)
    if readiness_violations:
        details = "; ".join(readiness_violations)
        raise AssertionError(f"saved marketplace payload readiness failed: {details}")
    seeded_products, notes = build_seeded_products(readiness)

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)

    try:
        async with engine.begin() as connection:
            await _verify_schema(connection, verifier)

        async with SessionLocal() as session:
            async with session.begin():
                await save_seeded_data(
                    create_postgres_provider(session),
                    seeded_products,
                )

        async with engine.connect() as connection:
            await _verify_seed_persistence(connection, seeded_products, verifier)

        await _verify_application(seeded_products, verifier)
        await engine.dispose()
        await _verify_restart(seeded_products, verifier)
    finally:
        await engine.dispose()

    print()
    print("=== POSTGRESQL PUBLIC UI READINESS ===")
    for result in readiness:
        print(
            f"{result.marketplace}: "
            f"raw={result.raw_items}, "
            f"parsed={result.parsed_offers}, "
            f"snapshot_ready={result.snapshot_ready_offers}"
        )
    for note in notes:
        print(f"NOTE: {note}")
    print(
        "EPIC 19 PostgreSQL public UI verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_schema(
    connection: AsyncConnection,
    verifier: Verification,
) -> None:
    migration = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    repository_head = _migration_head()
    verifier.check(
        "current Alembic head is applied",
        migration == repository_head,
        diagnostic=f"database={migration!r}, repository={repository_head!r}",
    )

    rows = await connection.execute(
        text(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            """
        )
    )
    tables = {str(row[0]) for row in rows}
    expected = {"tenants", "canonical_products", "offers", "price_snapshots"}
    verifier.check(
        "public read persistence tables exist",
        expected <= tables,
        diagnostic=f"missing={sorted(expected - tables)}",
    )


async def _verify_seed_persistence(
    connection: AsyncConnection,
    seeded_products: tuple[SeededProduct, ...],
    verifier: Verification,
) -> None:
    expected = len(seeded_products)
    for table in ("canonical_products", "offers", "price_snapshots"):
        count = await connection.scalar(text(f"SELECT count(*) FROM {table}"))
        verifier.check(
            f"{table} fixtures committed",
            count == expected,
            diagnostic=f"expected={expected}, actual={count}",
        )


async def _verify_application(
    seeded_products: tuple[SeededProduct, ...],
    verifier: Verification,
) -> None:
    app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("epic19-public-ui-postgres-secret"),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        await _verify_terminal_shell(client, verifier)
        await _verify_public_routes(client, seeded_products, verifier)


async def _verify_terminal_shell(
    client: AsyncClient,
    verifier: Verification,
) -> None:
    document = await client.get("/terminal")
    styles = await client.get("/terminal/styles.css")
    script = await client.get("/terminal/app.js")
    _expect_status(document, "terminal", verifier)
    _expect_status(styles, "terminal stylesheet", verifier)
    _expect_status(script, "terminal script", verifier)

    verifier.check(
        "terminal shell references static assets",
        "/terminal/styles.css" in document.text and "/terminal/app.js" in document.text,
    )
    verifier.check(
        "terminal shell exposes product and detail regions",
        'id="productGrid"' in document.text and 'id="details"' in document.text,
    )
    verifier.check(
        "terminal script binds public API",
        'const api = "/api/v1/public";' in script.text,
    )
    content_security_policy = document.headers.get("content-security-policy", "")
    verifier.check(
        "terminal CSP remains strict",
        "default-src 'self'" in content_security_policy
        and "'unsafe-inline'" not in content_security_policy,
        diagnostic=content_security_policy,
    )


async def _verify_public_routes(
    client: AsyncClient,
    seeded_products: tuple[SeededProduct, ...],
    verifier: Verification,
) -> None:
    products_response = await client.get("/api/v1/public/products?limit=10")
    _expect_status(products_response, "public products", verifier)
    products = _items(products_response)
    verifier.check(
        "public products load from PostgreSQL",
        len(products) == len(seeded_products),
        diagnostic=f"expected={len(seeded_products)}, actual={len(products)}",
    )

    for seeded in seeded_products:
        await _verify_product_routes(client, seeded, verifier)

        filtered_response = await client.get(
            "/api/v1/public/products",
            params={"marketplace": seeded.offer.marketplace, "limit": 10},
        )
        _expect_status(
            filtered_response,
            f"{seeded.offer.marketplace} product filter",
            verifier,
        )
        filtered = _items(filtered_response)
        verifier.check(
            f"{seeded.offer.marketplace} product filter is isolated",
            len(filtered) == 1
            and _nested_marketplace(filtered[0]) == seeded.offer.marketplace,
        )

    price_changes = await client.get("/api/v1/public/price-changes?limit=10")
    categories = await client.get("/api/v1/public/categories?limit=10")
    _expect_status(price_changes, "public price changes", verifier)
    _expect_status(categories, "public categories", verifier)
    verifier.check(
        "saved current offers do not fabricate price changes",
        _items(price_changes) == [],
    )
    verifier.check(
        "missing saved categories are represented honestly",
        _items(categories) == [],
    )


async def _verify_product_routes(
    client: AsyncClient,
    seeded: SeededProduct,
    verifier: Verification,
) -> None:
    marketplace = seeded.offer.marketplace
    product_id = str(seeded.product.id)
    detail = await client.get(f"/api/v1/public/products/{product_id}")
    offers = await client.get(f"/api/v1/public/products/{product_id}/offers")
    comparison = await client.get(f"/api/v1/public/products/{product_id}/comparison")
    history = await client.get(
        f"/api/v1/public/products/{product_id}/price-history?period=all"
    )
    _expect_status(detail, f"{marketplace} product detail", verifier)
    _expect_status(offers, f"{marketplace} offers", verifier)
    _expect_status(comparison, f"{marketplace} comparison", verifier)
    _expect_status(history, f"{marketplace} price history", verifier)

    detail_body = _object(detail)
    verifier.check(
        f"{marketplace} detail identity is preserved",
        detail_body.get("id") == product_id
        and detail_body.get("name") == seeded.product.name,
    )

    offer_items = _items(offers)
    verifier.check(f"{marketplace} persisted offer is readable", len(offer_items) == 1)
    public_offer = offer_items[0]
    verifier.check(
        f"{marketplace} offer identity is preserved",
        public_offer.get("external_id") == seeded.offer.external_id
        and public_offer.get("marketplace") == marketplace,
    )
    verifier.check(
        f"{marketplace} offer price is preserved",
        Decimal(str(public_offer.get("price"))) == seeded.offer.price
        and public_offer.get("currency") == seeded.offer.currency,
    )

    comparison_body = _object(comparison)
    comparison_offers = cast(list[dict[str, Any]], comparison_body.get("offers", []))
    best_offer = cast(dict[str, Any] | None, comparison_body.get("best_offer"))
    verifier.check(
        f"{marketplace} comparison uses persisted offer",
        len(comparison_offers) == 1 and best_offer is not None,
    )
    verifier.check(
        f"{marketplace} comparison selects persisted price",
        best_offer is not None
        and Decimal(str(best_offer.get("price"))) == seeded.offer.price,
    )

    history_items = _items(history)
    verifier.check(
        f"{marketplace} snapshot history is readable",
        len(history_items) == 1,
    )
    history_point = history_items[0]
    verifier.check(
        f"{marketplace} snapshot price is preserved",
        Decimal(str(history_point.get("price"))) == seeded.offer.price
        and history_point.get("currency") == seeded.offer.currency,
    )


async def _verify_restart(
    seeded_products: tuple[SeededProduct, ...],
    verifier: Verification,
) -> None:
    restarted_app = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr("epic19-public-ui-restart-secret"),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=restarted_app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/public/products?limit=10")
        _expect_status(response, "fresh-session products", verifier)
        verifier.check(
            "fresh engine pool preserves PostgreSQL public data",
            len(_items(response)) == len(seeded_products),
        )
        detail = await client.get(
            f"/api/v1/public/products/{seeded_products[0].product.id}"
        )
        _expect_status(detail, "fresh-session product detail", verifier)


def _expect_status(
    response: Response,
    name: str,
    verifier: Verification,
) -> None:
    verifier.check(
        f"{name} returns HTTP 200",
        response.status_code == 200,
        diagnostic=f"HTTP {response.status_code}: {response.text[:300]}",
    )


def _items(response: Response) -> list[dict[str, Any]]:
    body = _object(response)
    return cast(list[dict[str, Any]], body["items"])


def _object(response: Response) -> dict[str, Any]:
    return cast(dict[str, Any], response.json())


def _nested_marketplace(product: dict[str, Any]) -> object:
    best_offer = cast(dict[str, Any] | None, product.get("best_offer"))
    return best_offer.get("marketplace") if best_offer is not None else None


async def _recreate_schema(database_url: str) -> None:
    isolated_engine = create_async_engine(database_url)
    try:
        async with isolated_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await isolated_engine.dispose()


def _apply_migrations(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(_alembic_config(database_url), "head")


def _migration_head() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("Alembic repository has no current head.")
    return head


def _alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def _require_isolated_database(database_url: str) -> None:
    parsed = make_url(database_url)
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if not database_name.startswith("epic19_"):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must point to an isolated epic19_* database; "
            f"got {database_name!r}."
        )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
