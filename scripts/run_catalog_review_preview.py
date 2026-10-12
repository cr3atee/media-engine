"""Run a loopback-only preview of the seller catalog-review workspace."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, replace
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
from app.repositories.public_queries.repository_backed import (
    create_repository_backed_public_read_scope_factory,
)
from app.services.passwords import PasswordHasher
from app.services.repository_scope import create_memory_repository_scope
from scripts.analyze_cross_marketplace_matching import (
    analyze_cross_marketplace_matching,
)
from scripts.verify_aligned_marketplace_categories import (
    MarketplaceCategoryBatch,
    fetch_aligned_marketplace_categories_isolated,
)

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
    saved_data: bool
    aligned_live_data: bool


@dataclass(slots=True, frozen=True)
class PreviewSeedSummary:
    """Expected review queues for one isolated preview dataset."""

    mode: str
    offers_by_marketplace: tuple[tuple[str, int], ...]
    expected_candidates: int
    expected_proposals: int
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class PreparedPreview:
    """Catalog-review application and its deterministic seed summary."""

    application: FastAPI
    seed: PreviewSeedSummary


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
    data_source = parser.add_mutually_exclusive_group()
    data_source.add_argument(
        "--saved-data",
        action="store_true",
        help="Load saved real GGSEL, Playerok, and FunPay offers into memory.",
    )
    data_source.add_argument(
        "--aligned-live-data",
        action="store_true",
        help=(
            "Fetch a bounded live review batch from aligned public categories "
            "without persisting decisions."
        ),
    )
    namespace = parser.parse_args()
    return PreviewArguments(
        port=cast(int, namespace.port),
        check=cast(bool, namespace.check),
        saved_data=cast(bool, namespace.saved_data),
        aligned_live_data=cast(bool, namespace.aligned_live_data),
    )


async def prepare_preview(
    *,
    saved_data: bool = False,
    aligned_live_data: bool = False,
) -> PreparedPreview:
    """Build an isolated memory-backed seller review application and seed."""
    if saved_data and aligned_live_data:
        raise ValueError("Preview data sources are mutually exclusive.")
    provider = create_memory_provider()
    seed = await _seed_preview(
        provider,
        saved_data=saved_data,
        aligned_live_data=aligned_live_data,
    )

    from app.main import create_app

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=False,
            api_docs_enabled=False,
        ),
        auth_settings=AuthSettings(
            access_token_secret=SecretStr("catalog-review-preview-secret"),
            password_hash_iterations=100_000,
        ),
        public_read_repository_scope_factory=(
            create_repository_backed_public_read_scope_factory(provider)
        ),
        repository_scope_factory=create_memory_repository_scope(provider),
    )
    return PreparedPreview(application=application, seed=seed)


async def build_preview(*, saved_data: bool = False) -> FastAPI:
    """Build the preview application while preserving the original helper API."""
    return (await prepare_preview(saved_data=saved_data)).application


async def verify_preview(
    application: FastAPI,
    *,
    expected_candidates: int = 1,
    expected_proposals: int = 1,
) -> tuple[int, int]:
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
        workspace = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/onboarding-workspace?limit=100",
            headers=headers,
        )
        public_document = await client.get("/terminal")
        public_products = await client.get("/api/v1/public/products?limit=10")

    responses = (
        document,
        profile,
        context,
        workspace,
        public_document,
        public_products,
    )
    if any(response.status_code != 200 for response in responses):
        statuses = ", ".join(str(response.status_code) for response in responses)
        raise RuntimeError(f"Preview read path failed with statuses: {statuses}.")
    if "catalog_review" not in context.json()["permissions"]:
        raise RuntimeError("Preview reviewer does not have catalog_review permission.")
    workspace_body = workspace.json()
    candidate_count = len(workspace_body["review_candidates"])
    proposal_count = len(workspace_body["product_proposals"])
    if candidate_count != expected_candidates or proposal_count != expected_proposals:
        raise RuntimeError(
            "Preview queue mismatch: "
            f"expected {expected_candidates}/{expected_proposals}, "
            f"got {candidate_count}/{proposal_count}."
        )
    summary_body = workspace_body["summary"]
    if summary_body["review_candidates"] != expected_candidates:
        raise RuntimeError("Preview summary candidate count does not match queue.")
    if summary_body["product_proposals"] != expected_proposals:
        raise RuntimeError("Preview summary proposal count does not match queue.")
    return candidate_count, proposal_count


async def _seed_preview(
    provider: RepositoryProvider,
    *,
    saved_data: bool,
    aligned_live_data: bool,
) -> PreviewSeedSummary:
    await _seed_identity(provider)
    if saved_data:
        return await _seed_saved_marketplace_offers(provider)
    if aligned_live_data:
        return await _seed_aligned_live_offers(provider)
    await _seed_synthetic_catalog(provider)
    return PreviewSeedSummary(
        mode="synthetic",
        offers_by_marketplace=(("ggsel", 1), ("playerok", 1)),
        expected_candidates=1,
        expected_proposals=1,
    )


async def _seed_identity(provider: RepositoryProvider) -> None:
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


async def _seed_synthetic_catalog(provider: RepositoryProvider) -> None:
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


async def _seed_saved_marketplace_offers(
    provider: RepositoryProvider,
) -> PreviewSeedSummary:
    from scripts.verify_marketplace_data_readiness import (
        load_saved_marketplace_offers,
    )

    offers_by_marketplace = load_saved_marketplace_offers()
    missing = tuple(
        marketplace
        for marketplace in ("ggsel", "playerok", "funpay")
        if not offers_by_marketplace.get(marketplace)
    )
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Saved marketplace payloads are missing: {names}.")

    seen: set[tuple[str, str]] = set()
    seeded_counts: list[tuple[str, int]] = []
    for marketplace, offers in offers_by_marketplace.items():
        seeded = 0
        for offer in offers:
            normalized_marketplace = offer.marketplace.strip().lower()
            external_id = (offer.external_id or "").strip()
            if (
                not normalized_marketplace
                or not external_id
                or not (offer.title or "").strip()
            ):
                continue
            identity = (normalized_marketplace, external_id)
            if identity in seen:
                continue
            seen.add(identity)
            await provider.offers.save(
                TENANT_ID,
                replace(
                    offer,
                    tenant_id=TENANT_ID,
                    marketplace=normalized_marketplace,
                    external_id=external_id,
                ),
            )
            seeded += 1
        seeded_counts.append((marketplace, seeded))

    if not seen:
        raise RuntimeError("Saved marketplace payloads contain no reviewable offers.")
    return PreviewSeedSummary(
        mode="saved real payloads",
        offers_by_marketplace=tuple(seeded_counts),
        expected_candidates=0,
        expected_proposals=len(seen),
    )


async def _seed_aligned_live_offers(
    provider: RepositoryProvider,
) -> PreviewSeedSummary:
    results = await fetch_aligned_marketplace_categories_isolated()
    batches = tuple(
        result.batch
        for result in results
        if result.succeeded and result.batch is not None
    )
    if len(batches) < 2:
        statuses = ", ".join(
            f"{result.marketplace}={result.error_code or 'unavailable'}"
            for result in results
            if not result.succeeded
        )
        raise RuntimeError(
            "Aligned live review requires at least two sources; "
            f"failures: {statuses or 'insufficient source data'}."
        )

    selected = _select_aligned_review_offers(batches)
    if not selected:
        raise RuntimeError("Aligned live sources produced no reviewable pair.")

    seeded_counts = await _save_review_offers(provider, selected)
    unavailable = tuple(
        f"{result.marketplace} unavailable: {result.error_code or 'UnknownError'}"
        for result in results
        if not result.succeeded
    )
    return PreviewSeedSummary(
        mode="bounded aligned live review batch",
        offers_by_marketplace=seeded_counts,
        expected_candidates=0,
        expected_proposals=len(selected),
        notes=(
            "Highest deterministic NO_MATCH pair per available source pairing; "
            "human confirmation is still required.",
            *unavailable,
        ),
    )


def _select_aligned_review_offers(
    batches: tuple[MarketplaceCategoryBatch, ...],
) -> tuple[ParsedOffer, ...]:
    report = analyze_cross_marketplace_matching(
        {batch.marketplace: batch.snapshot_ready_offers for batch in batches},
        top_limit=0,
        pair_top_limit=1,
    )
    offer_lookup = {
        (offer.marketplace.strip().lower(), (offer.external_id or "").strip()): offer
        for batch in batches
        for offer in batch.snapshot_ready_offers
        if offer.marketplace.strip() and (offer.external_id or "").strip()
    }
    selected: list[ParsedOffer] = []
    seen: set[tuple[str, str]] = set()
    for pair in report.top_candidates_by_marketplace_pair:
        if not pair.candidates:
            continue
        candidate = pair.candidates[0]
        identities = (
            (
                candidate.left_marketplace,
                candidate.left_external_id or "",
            ),
            (
                candidate.right_marketplace,
                candidate.right_external_id or "",
            ),
        )
        for marketplace, external_id in identities:
            identity = (marketplace.strip().lower(), external_id.strip())
            if identity in seen or identity not in offer_lookup:
                continue
            seen.add(identity)
            selected.append(offer_lookup[identity])
    return tuple(selected)


async def _save_review_offers(
    provider: RepositoryProvider,
    offers: tuple[ParsedOffer, ...],
) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for offer in offers:
        marketplace = offer.marketplace.strip().lower()
        external_id = (offer.external_id or "").strip()
        await provider.offers.save(
            TENANT_ID,
            replace(
                offer,
                tenant_id=TENANT_ID,
                marketplace=marketplace,
                external_id=external_id,
            ),
        )
        counts[marketplace] = counts.get(marketplace, 0) + 1
    return tuple(sorted(counts.items()))


def main() -> int:
    """Prepare and run the loopback-only catalog-review preview."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_args()
    try:
        preview = asyncio.run(
            prepare_preview(
                saved_data=arguments.saved_data,
                aligned_live_data=arguments.aligned_live_data,
            )
        )
        if arguments.check:
            candidates, proposals = asyncio.run(
                verify_preview(
                    preview.application,
                    expected_candidates=preview.seed.expected_candidates,
                    expected_proposals=preview.seed.expected_proposals,
                )
            )
            sources = ", ".join(
                f"{marketplace}={count}"
                for marketplace, count in preview.seed.offers_by_marketplace
            )
            print(
                "Catalog review preview passed: "
                f"mode={preview.seed.mode}, {sources}, "
                f"candidates={candidates}, proposals={proposals}."
            )
            return 0

        url = f"http://127.0.0.1:{arguments.port}/terminal/review"
        print(f"Open catalog review workspace: {url}")
        print(f"Preview email: {PREVIEW_EMAIL}")
        print(f"Preview password: {PREVIEW_PASSWORD}")
        print(f"Dataset: {preview.seed.mode}")
        for marketplace, count in preview.seed.offers_by_marketplace:
            print(f"{marketplace}: {count} offers")
        for note in preview.seed.notes:
            print(f"NOTE: {note}")
        if arguments.saved_data or arguments.aligned_live_data:
            print("No catalog products, links, or review decisions are pre-seeded.")
        print("Data is memory-only and resets when the process stops.")
        uvicorn.run(
            preview.application,
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
