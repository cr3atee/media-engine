"""Run the existing catalog-review workspace against isolated PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.parsers.models import ParsedOffer
    from app.services.repository_scope import RepositoryScopeFactory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL_ENV = "EPIC23_CATALOG_REVIEW_DATABASE_URL"
DATABASE_NAME_PREFIX = "epic23_catalog_review_"
TENANT_ID = UUID("45000000-0000-4000-8000-000000000001")
USER_ID = UUID("45000000-0000-4000-8000-000000000002")
MEMBERSHIP_ID = UUID("45000000-0000-4000-8000-000000000003")
REVIEW_EMAIL = "reviewer@catalog.local"
REVIEW_PASSWORD = "catalog review local"


@dataclass(slots=True, frozen=True)
class RunnerArguments:
    """Validated local PostgreSQL review-runner arguments."""

    port: int
    check: bool
    aligned_live_data: bool


@dataclass(slots=True, frozen=True)
class ReviewSeedSummary:
    """Facts about offers written through the repository boundary."""

    mode: str
    offers_by_marketplace: tuple[tuple[str, int], ...]

    @property
    def offer_count(self) -> int:
        """Return the number of unique offers in this seed operation."""
        return sum(count for _, count in self.offers_by_marketplace)


def parse_args(argv: Sequence[str] | None = None) -> RunnerArguments:
    """Parse local runner options without performing I/O."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing catalog-review UI against an isolated local "
            "PostgreSQL database."
        ),
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
        help="Seed and verify the workspace without starting Uvicorn.",
    )
    parser.add_argument(
        "--aligned-live-data",
        action="store_true",
        help=(
            "Fetch the bounded three-marketplace live batch. Without this "
            "flag, captured real payloads are used."
        ),
    )
    namespace = parser.parse_args(argv)
    return RunnerArguments(
        port=cast(int, namespace.port),
        check=cast(bool, namespace.check),
        aligned_live_data=cast(bool, namespace.aligned_live_data),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Validate configuration and run one PostgreSQL-backed review process."""
    _configure_stdout()
    arguments = parse_args(argv)
    database_url = os.getenv(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(f"ERROR: set {DATABASE_URL_ENV} to an isolated local PostgreSQL URL.")
        return 2
    try:
        _require_isolated_database(database_url)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2

    # Application settings are instantiated during imports, so bind the vetted
    # URL before loading any MediaEngine composition modules.
    os.environ["DATABASE_URL"] = database_url
    try:
        return asyncio.run(_run(arguments, database_url))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {_safe_error_summary(exc, database_url)}")
        return 1


async def _run(arguments: RunnerArguments, database_url: str) -> int:
    from pydantic import SecretStr
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config.settings import AdminApiSettings, AuthSettings
    from app.database.public_read_scope import (
        create_postgres_public_read_repository_scope,
    )
    from app.database.repository_scope import create_postgres_repository_scope
    from app.database.session import engine as default_engine
    from app.main import create_app
    from app.repositories.queries.provider import create_postgres_read_repository_scope

    await asyncio.to_thread(_apply_migrations, database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository_scope = create_postgres_repository_scope(session_factory)
    try:
        offers, mode = await _load_offers(
            aligned_live_data=arguments.aligned_live_data,
        )
        summary = await _seed_database(repository_scope, offers, mode=mode)
        application = create_app(
            admin_api_settings=AdminApiSettings(
                api_enabled=False,
                api_docs_enabled=False,
            ),
            auth_settings=AuthSettings(
                access_token_secret=SecretStr(
                    "epic23-local-catalog-review-access-token-secret"
                ),
                password_hash_iterations=100_000,
            ),
            read_repository_scope_factory=(
                create_postgres_read_repository_scope(session_factory)
            ),
            public_read_repository_scope_factory=(
                create_postgres_public_read_repository_scope(session_factory)
            ),
            repository_scope_factory=repository_scope,
        )
        workspace = await _verify_application(
            application,
            minimum_offer_count=summary.offer_count,
        )
        _print_ready(arguments, summary, workspace)
        if arguments.check:
            return 0

        import uvicorn

        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=arguments.port,
                log_level="info",
            )
        )
        await server.serve()
        return 0 if server.started else 1
    finally:
        await engine.dispose()
        await default_engine.dispose()


async def _load_offers(
    *,
    aligned_live_data: bool,
) -> tuple[tuple[ParsedOffer, ...], str]:
    if aligned_live_data:
        from scripts.run_catalog_review_preview import (
            _select_aligned_review_offers,
        )
        from scripts.verify_aligned_marketplace_categories import (
            fetch_aligned_marketplace_categories,
        )

        batches = await fetch_aligned_marketplace_categories()
        offers = _select_aligned_review_offers(batches)
        if not offers:
            raise RuntimeError("Aligned live sources produced no reviewable batch.")
        return offers, "bounded aligned live review batch"

    from scripts.verify_marketplace_data_readiness import (
        load_saved_marketplace_offers,
    )

    loaded = load_saved_marketplace_offers()
    offers = tuple(
        offer
        for marketplace in ("ggsel", "playerok", "funpay")
        for offer in loaded.get(marketplace, ())
    )
    if not offers:
        raise RuntimeError("Captured marketplace payloads contain no offers.")
    return offers, "captured real marketplace payloads"


async def _seed_database(
    repository_scope: RepositoryScopeFactory,
    offers: tuple[ParsedOffer, ...],
    *,
    mode: str,
) -> ReviewSeedSummary:
    from app.domain.auth import PasswordCredential
    from app.domain.tenancy import Membership, Tenant, TenantRole, User
    from app.services.passwords import PasswordHasher

    now = datetime.now(UTC)
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    async with repository_scope() as repositories:
        tenant = await repositories.tenants.get_by_id(TENANT_ID)
        if tenant is None:
            await repositories.tenants.create(
                Tenant(
                    id=TENANT_ID,
                    name="Catalog Launch Review",
                    slug="catalog-launch-review",
                    created_at=now,
                    updated_at=now,
                )
            )
        elif tenant.slug != "catalog-launch-review":
            raise RuntimeError("Catalog-review tenant ID belongs to another tenant.")

        user = await repositories.users.get_by_email(REVIEW_EMAIL)
        if user is None:
            await repositories.users.create(
                User(
                    id=USER_ID,
                    email=REVIEW_EMAIL,
                    display_name="Catalog Reviewer",
                    created_at=now,
                    updated_at=now,
                )
            )
        elif user.id != USER_ID:
            raise RuntimeError("Catalog-review email belongs to another user.")

        credential = await repositories.password_credentials.get_by_user_id(USER_ID)
        if credential is None:
            hasher = PasswordHasher(iterations=100_000)
            await repositories.password_credentials.set_for_user(
                PasswordCredential(
                    user_id=USER_ID,
                    password_hash=hasher.hash_password(REVIEW_PASSWORD),
                    created_at=now,
                    updated_at=now,
                )
            )

        membership = await repositories.memberships.get_by_user_and_tenant(
            USER_ID,
            TENANT_ID,
        )
        if membership is None:
            await repositories.memberships.create(
                Membership(
                    id=MEMBERSHIP_ID,
                    user_id=USER_ID,
                    tenant_id=TENANT_ID,
                    role=TenantRole.REVIEWER,
                    joined_at=now,
                    updated_at=now,
                )
            )
        elif membership.role is not TenantRole.REVIEWER:
            raise RuntimeError("Catalog-review user has an unexpected tenant role.")

        for offer in offers:
            marketplace = offer.marketplace.strip().lower()
            external_id = (offer.external_id or "").strip()
            title = (offer.title or "").strip()
            identity = (marketplace, external_id)
            if not marketplace or not external_id or not title or identity in seen:
                continue
            seen.add(identity)
            counts[marketplace] += 1
            await repositories.offers.save(
                TENANT_ID,
                replace(
                    offer,
                    tenant_id=TENANT_ID,
                    marketplace=marketplace,
                    external_id=external_id,
                    title=title,
                ),
            )

    if not seen:
        raise RuntimeError("No unique reviewable offers were persisted.")
    return ReviewSeedSummary(
        mode=mode,
        offers_by_marketplace=tuple(sorted(counts.items())),
    )


async def _verify_application(
    application: FastAPI,
    *,
    minimum_offer_count: int,
) -> dict[str, Any]:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://catalog-review.local",
    ) as client:
        document = await client.get("/terminal/review")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": REVIEW_EMAIL, "password": REVIEW_PASSWORD},
        )
        if document.status_code != 200 or login.status_code != 200:
            raise RuntimeError(
                "Catalog-review UI or reviewer authentication is unavailable."
            )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        workspace = await client.get(
            f"/api/v1/tenants/{TENANT_ID}/catalog/onboarding-workspace?limit=200",
            headers=headers,
        )
        if workspace.status_code != 200:
            raise RuntimeError(
                f"Catalog-review workspace returned HTTP {workspace.status_code}."
            )
    body = cast(dict[str, Any], workspace.json())
    summary = cast(dict[str, Any], body.get("summary", {}))
    if int(summary.get("total_offers", 0)) < minimum_offer_count:
        raise RuntimeError("Catalog-review workspace omitted persisted offers.")
    return body


def _print_ready(
    arguments: RunnerArguments,
    seed: ReviewSeedSummary,
    workspace: dict[str, Any],
) -> None:
    summary = cast(dict[str, Any], workspace["summary"])
    sources = ", ".join(
        f"{marketplace}={count}" for marketplace, count in seed.offers_by_marketplace
    )
    print("Catalog review PostgreSQL workspace is ready.")
    print(f"Dataset: {seed.mode} ({sources})")
    print(
        "State: "
        f"offers={summary['total_offers']}, "
        f"linked={summary['linked_offers']}, "
        f"proposals={summary['product_proposals']}, "
        f"decisions={summary['terminal_decisions']}"
    )
    if arguments.check:
        return
    print(f"Open: http://127.0.0.1:{arguments.port}/terminal/review")
    print(f"Email: {REVIEW_EMAIL}")
    print(f"Password: {REVIEW_PASSWORD}")
    print("Decisions persist in the configured isolated PostgreSQL database.")


def _apply_migrations(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    host = (url.host or "").lower()
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must use PostgreSQL.")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{DATABASE_URL_ENV} must target a loopback host.")
    if not database_name.startswith(DATABASE_NAME_PREFIX):
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must target an isolated "
            f"{DATABASE_NAME_PREFIX}* database; got {database_name!r}."
        )


def _safe_error_summary(error: Exception, database_url: str) -> str:
    summary = str(error)
    parsed_url = make_url(database_url)
    secrets = (
        database_url,
        parsed_url.password or "",
        REVIEW_PASSWORD,
        "epic23-local-catalog-review-access-token-secret",
    )
    for secret in secrets:
        if secret:
            summary = summary.replace(secret, "[REDACTED]")
    summary = re.sub(r"<[^>]*>", " ", summary)
    summary = " ".join(summary.split())
    return summary[:500] or "Catalog-review startup failed."


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
