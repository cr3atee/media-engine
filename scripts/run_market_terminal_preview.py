"""Run a local Market Terminal preview from saved real marketplace payloads."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import AdminApiSettings
from app.repositories.provider import create_memory_provider
from app.repositories.public_queries.repository_backed import (
    create_repository_backed_public_read_scope_factory,
)
from app.services.repository_scope import create_memory_repository_scope
from scripts.verify_marketplace_data_readiness import MarketplaceReadiness
from scripts.verify_marketplace_payload_contracts import (
    collect_readiness,
    validate_readiness,
)
from scripts.verify_public_ui_readiness import (
    SeededProduct,
    build_seeded_products,
    save_seeded_data,
)


@dataclass(slots=True, frozen=True)
class PreviewArguments:
    """Validated command-line options for the local preview."""

    port: int
    check: bool


@dataclass(slots=True, frozen=True)
class MarketTerminalPreview:
    """Prepared local application and its real saved-payload evidence."""

    application: FastAPI
    readiness: tuple[MarketplaceReadiness, ...]
    products: tuple[SeededProduct, ...]
    notes: tuple[str, ...]


def parse_args() -> PreviewArguments:
    """Parse local preview command-line options."""
    parser = argparse.ArgumentParser(
        description="Run Market Terminal locally with saved marketplace data.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=8000,
        help="Loopback TCP port (default: 8000).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the prepared app without starting a server.",
    )
    namespace = parser.parse_args()
    return PreviewArguments(
        port=cast(int, namespace.port),
        check=cast(bool, namespace.check),
    )


async def build_preview() -> MarketTerminalPreview:
    """Build a memory-backed preview from saved real marketplace payloads."""
    readiness = collect_readiness()
    violations = validate_readiness(readiness)
    if violations:
        details = "\n".join(f"- {violation}" for violation in violations)
        raise RuntimeError(f"Saved marketplace data is not ready:\n{details}")

    provider = create_memory_provider()
    products, notes = build_seeded_products(readiness)
    await save_seeded_data(provider, products)
    if not products:
        raise RuntimeError("No snapshot-ready marketplace offers were found.")

    from app.main import create_app

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=False,
            api_docs_enabled=False,
        ),
        public_read_repository_scope_factory=(
            create_repository_backed_public_read_scope_factory(provider)
        ),
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return MarketTerminalPreview(
        application=application,
        readiness=readiness,
        products=products,
        notes=notes,
    )


async def verify_preview(preview: MarketTerminalPreview) -> int:
    """Verify that the prepared shell and product collection are readable."""
    async with AsyncClient(
        transport=ASGITransport(
            app=preview.application,
            raise_app_exceptions=False,
        ),
        base_url="http://preview.local",
    ) as client:
        document = await client.get("/terminal")
        products = await client.get("/api/v1/public/products?limit=10")

    if document.status_code != 200:
        raise RuntimeError(f"Terminal returned HTTP {document.status_code}.")
    if products.status_code != 200:
        raise RuntimeError(f"Products returned HTTP {products.status_code}.")
    product_count = len(products.json().get("items", []))
    if product_count != len(preview.products):
        raise RuntimeError(
            "Preview product count mismatch: "
            f"expected {len(preview.products)}, got {product_count}."
        )
    return product_count


def main() -> int:
    """Prepare and run the local loopback-only Market Terminal preview."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    try:
        preview = asyncio.run(build_preview())
        _print_readiness(preview)
        if arguments.check:
            product_count = asyncio.run(verify_preview(preview))
            print(f"Preview check passed with {product_count} products.")
            return 0

        url = f"http://127.0.0.1:{arguments.port}/terminal"
        print(f"Open Market Terminal: {url}")
        uvicorn.run(
            preview.application,
            host="127.0.0.1",
            port=arguments.port,
            log_level="info",
        )
        return 0
    except RuntimeError as error:
        print(f"Preview unavailable: {error}", file=sys.stderr)
        return 1


def _print_readiness(preview: MarketTerminalPreview) -> None:
    print("=== MARKET TERMINAL PREVIEW ===")
    for readiness in preview.readiness:
        print(
            f"{readiness.marketplace}: "
            f"raw={readiness.raw_items}, "
            f"parsed={readiness.parsed_offers}, "
            f"snapshot_ready={readiness.snapshot_ready_offers}"
        )
    for note in preview.notes:
        print(f"NOTE: {note}")


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Port must be an integer.") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535.")
    return port


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
