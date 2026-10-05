"""Run a loopback-only preview of the seller catalog-review workspace."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import AdminApiSettings, AuthSettings
from app.domain.auth import PasswordCredential
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope

TENANT_ID = UUID("43000000-0000-4000-8000-000000000001")
USER_ID = UUID("43000000-0000-4000-8000-000000000002")
MEMBERSHIP_ID = UUID("43000000-0000-4000-8000-000000000003")
PRODUCT_ID = UUID("43000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
PREVIEW_EMAIL = "reviewer@preview.local"
PREVIEW_PASSWORD = "catalog review preview"


@dataclass(slots=True, frozen=True)
class PreviewArguments:
    """Validated command-line options for the local seller preview."""

    port: int
    check: bool


def parse_args() -> PreviewArguments:
    """Parse local preview command-line options."""
    parser = argparse.ArgumentParser(
        description="Run the Market Terminal catalog-review workspace locally.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=8001,
        help="Loopback TCP port (default: 8001).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify authentication and queues without starting a server.",
    )
    namespace = parser.parse_args()
    return PreviewArguments(
        port=cast(int, namespace.port),
        check=cast(bool, namespace.check),
    )


async def build_preview() -> FastAPI:
    """Build an isolated memory-backed seller review application."""
    provider = create_memory_provider()
    await _seed_preview(provider)

    from app.main import create_app

    return create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=False,
            api_docs_enabled=False,
        ),
        auth_settings=AuthSettings(
            access_token_secret=SecretStr("catalog-review-preview-secret"),
            password_hash_iterations=100_000,
        ),
        public_read_repository_scope_factory=None,
        repository_scope_factory=create_memory_repository_scope(provider),
    )


async def verify_preview(application: FastAPI) -> tuple[int, int]:
    """Verify the complete read path used by the browser workspace."""
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://catalog-review.local",
    ) as client:
        document = await client.get("/terminal/review")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD},
        )
        if login.status_code != 200:
            raise RuntimeError(f"Preview login returned HTTP {login.status_code}.")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        profile = await client.get("/api/v1/me", headers=headers)
        context = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/context",
            headers=headers,
        )
        candidates = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/review-candidates",
            headers=headers,
        )
        proposals = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/product-proposals",
            headers=headers,
        )

    responses = (document, profile, context, candidates, proposals)
    if any(response.status_code != 200 for response in responses):
        statuses = ", ".join(str(response.status_code) for response in responses)
        raise RuntimeError(f"Preview read path failed with statuses: {statuses}.")
    if "catalog_review" not in context.json()["permissions"]:
        raise RuntimeError("Preview reviewer does not have catalog_review permission.")
    candidate_count = len(candidates.json())
    proposal_count = len(proposals.json())
    if candidate_count != 1 or proposal_count != 1:
        raise RuntimeError(
            "Preview queue mismatch: "
            f"expected 1/1, got {candidate_count}/{proposal_count}."
        )
    return candidate_count, proposal_count


async def _seed_preview(provider: RepositoryProvider) -> None:
    hasher = PasswordHasher(iterations=100_000)
    await provider.tenants.create(
        Tenant(
            id=TENANT_ID,
            name="Demo Seller",
            slug="demo-seller",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.users.create(
        User(
            id=USER_ID,
            email=PREVIEW_EMAIL,
            display_name="Catalog Reviewer",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.password_credentials.set_for_user(
        PasswordCredential(
            user_id=USER_ID,
            password_hash=hasher.hash_password(PREVIEW_PASSWORD),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.memberships.create(
        Membership(
            id=MEMBERSHIP_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            role=TenantRole.REVIEWER,
            joined_at=NOW,
            updated_at=NOW,
        )
    )
    await provider.canonical_products.save(
        CanonicalProduct(
            id=PRODUCT_ID,
            tenant_id=TENANT_ID,
            name="Minecraft Java Bedrock Windows",
            category="Games",
            aliases=("Minecraft Premium",),
        )
    )
    for offer in (
        ParsedOffer(
            tenant_id=TENANT_ID,
            marketplace="ggsel",
            external_id="preview-review",
            title="Minecraft Java Bedrock Windows Premium",
            url="https://ggsel.net/catalog/product/preview-review",
            price=Decimal("790.00"),
            currency="RUB",
        ),
        ParsedOffer(
            tenant_id=TENANT_ID,
            marketplace="playerok",
            external_id="preview-proposal",
            title="Stardew Valley Complete",
            url="https://playerok.com/products/preview-proposal",
            price=Decimal("499.00"),
            currency="RUB",
        ),
    ):
        await provider.offers.save(TENANT_ID, offer)


def main() -> int:
    """Prepare and run the loopback-only catalog-review preview."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    try:
        application = asyncio.run(build_preview())
        if arguments.check:
            candidates, proposals = asyncio.run(verify_preview(application))
            print(
                "Catalog review preview passed: "
                f"candidates={candidates}, proposals={proposals}."
            )
            return 0

        url = f"http://127.0.0.1:{arguments.port}/terminal/review"
        print(f"Open catalog review workspace: {url}")
        print(f"Preview email: {PREVIEW_EMAIL}")
        print(f"Preview password: {PREVIEW_PASSWORD}")
        print("Data is memory-only and resets when the process stops.")
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=arguments.port,
            log_level="info",
        )
        return 0
    except RuntimeError as error:
        print(f"Catalog review preview unavailable: {error}", file=sys.stderr)
        return 1


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
