"""Verify audited canonical offer review against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_URL_ENV = "EPIC19_CANONICAL_REVIEW_DATABASE_URL"
_CONFIGURED_DATABASE_URL = os.getenv(DATABASE_URL_ENV, "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.database.repository_scope import create_postgres_repository_scope
from app.domain.admin_actions import AdminActorType
from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
    build_canonical_offer_decision_fingerprint,
)
from app.domain.tenancy import Tenant
from app.models.canonical_product import CanonicalProduct
from app.models.canonical_product_record import CanonicalProductRecord
from app.parsers.models import ParsedOffer
from app.repositories.postgres import PostgresCanonicalOfferDecisionRepository
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.canonical_offer_linking import CanonicalProductUnavailableError
from app.services.canonical_offer_review import (
    CanonicalOfferDecisionConflictError,
    CanonicalOfferReviewContext,
    CanonicalOfferReviewResult,
    CanonicalOfferReviewService,
    ReviewCanonicalOfferCommand,
)
from app.services.repository_scope import RepositoryScopeFactory

TENANT_A_ID = UUID("19000000-0000-4000-8000-000000010001")
TENANT_B_ID = UUID("19000000-0000-4000-8000-000000010002")
PRODUCT_A_ID = UUID("19000000-0000-4000-8000-000000020001")
PRODUCT_B_ID = UUID("19000000-0000-4000-8000-000000020002")
NOW = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)


class Verification:
    """Collect and print named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


class FailingDecisionRepository(PostgresCanonicalOfferDecisionRepository):
    """Repository double that fails after a link write in the same transaction."""

    async def append(
        self,
        decision: CanonicalOfferDecision,
    ) -> CanonicalOfferDecision:
        del decision
        raise RuntimeError("controlled canonical decision failure")


async def main() -> int:
    """Run the canonical offer review verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)

    verifier = Verification()
    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _verify_schema(session_factory, verifier)
        await _seed_data(session_factory)
        await _verify_confirm_and_reject(session_factory, verifier)
        await _verify_tenant_guards(session_factory, verifier)
        await _verify_rollback(session_factory, verifier)
        await _verify_concurrency(session_factory, verifier)
        await _verify_fresh_session(session_factory, verifier)
        await _verify_audit_retention(session_factory, verifier)
    finally:
        await engine.dispose()

    print(
        "Canonical offer review PostgreSQL verification: "
        f"{len(verifier.passed)} checks passed."
    )
    return 0


async def _verify_schema(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    async with session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        constraints = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = 'canonical_offer_decisions'::regclass
                        """
                    )
                )
            ).scalars()
        )
        indexes = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                            AND tablename = 'canonical_offer_decisions'
                        """
                    )
                )
            ).scalars()
        )

    verifier.check(
        "migration head is 0016",
        revision == "0016_canonical_offer_decisions",
    )
    verifier.check(
        "decision constraints exist",
        {
            "pk_canonical_offer_decisions",
            "uq_canonical_offer_decisions_idempotency",
            "uq_canonical_offer_decisions_pair",
            "fk_canonical_offer_decisions_tenant",
            "fk_canonical_offer_decisions_product",
            "ck_canonical_offer_decisions_decision",
            "ck_canonical_offer_decisions_actor_type",
            "ck_canonical_offer_decisions_nonempty",
            "ck_canonical_offer_decisions_fingerprint",
        }.issubset(constraints),
    )
    verifier.check(
        "offer decision lookup index exists",
        "ix_canonical_offer_decisions_offer_created" in indexes,
    )


async def _seed_data(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.tenants.create(_tenant(TENANT_A_ID, "Tenant A", "tenant-a"))
        await repositories.tenants.create(_tenant(TENANT_B_ID, "Tenant B", "tenant-b"))
        await repositories.canonical_products.save(_product(PRODUCT_A_ID))
        await repositories.canonical_products.save(_product(PRODUCT_B_ID))
        for external_id in (
            "offer-confirm",
            "offer-reject",
            "offer-rollback",
            "offer-conflict",
            "offer-idempotent",
        ):
            await repositories.offers.save(
                TENANT_A_ID,
                _offer(TENANT_A_ID, external_id),
            )
        await repositories.offers.save(
            TENANT_B_ID,
            _offer(TENANT_B_ID, "offer-foreign"),
        )


async def _verify_confirm_and_reject(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    service = _service(session_factory)
    confirm = _command(
        "offer-confirm",
        PRODUCT_A_ID,
        CanonicalOfferDecisionType.CONFIRMED,
    )
    confirmed = await service.review(confirm, _context("confirm-1"))
    replayed = await service.review(confirm, _context("confirm-1"))
    rejected = await service.review(
        _command(
            "offer-reject",
            PRODUCT_A_ID,
            CanonicalOfferDecisionType.REJECTED,
        ),
        _context("reject-1"),
    )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        linked_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-confirm",
        )
        unlinked_offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-reject",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-confirm",
        )

    verifier.check(
        "confirmed decision links offer atomically",
        confirmed.decision.decision is CanonicalOfferDecisionType.CONFIRMED
        and linked_offer is not None
        and linked_offer.canonical_product_id == PRODUCT_A_ID,
    )
    verifier.check(
        "same idempotency key replays decision",
        replayed.replayed and replayed.decision == confirmed.decision,
    )
    verifier.check("confirmed audit remains singular", len(decisions) == 1)
    verifier.check(
        "rejected decision leaves offer unlinked",
        rejected.decision.decision is CanonicalOfferDecisionType.REJECTED
        and unlinked_offer is not None
        and unlinked_offer.canonical_product_id is None,
    )


async def _verify_tenant_guards(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    try:
        await _service(session_factory).review(
            ReviewCanonicalOfferCommand(
                tenant_id=TENANT_B_ID,
                marketplace="ggsel",
                external_id="offer-foreign",
                canonical_product_id=PRODUCT_A_ID,
                decision=CanonicalOfferDecisionType.CONFIRMED,
            ),
            _context("foreign-service"),
        )
    except CanonicalProductUnavailableError:
        verifier.check("service hides cross-tenant canonical product", True)
    else:
        raise AssertionError("service accepted a cross-tenant canonical product")

    invalid = _decision(
        tenant_id=TENANT_B_ID,
        external_id="offer-foreign",
        canonical_product_id=PRODUCT_A_ID,
        idempotency_key="foreign-direct",
    )
    try:
        async with session_factory() as session, session.begin():
            repositories = create_postgres_provider(session)
            await repositories.canonical_offer_decisions.append(invalid)
    except IntegrityError:
        verifier.check("database rejects cross-tenant decision product", True)
    else:
        raise AssertionError("database accepted a cross-tenant decision product")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        stored = await repositories.canonical_offer_decisions.get_by_id(invalid.id)
    verifier.check("cross-tenant decision transaction rolled back", stored is None)


async def _verify_rollback(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    service = CanonicalOfferReviewService(_failing_scope(session_factory))
    try:
        await service.review(
            _command(
                "offer-rollback",
                PRODUCT_A_ID,
                CanonicalOfferDecisionType.CONFIRMED,
            ),
            _context("rollback-1"),
        )
    except RuntimeError as exc:
        verifier.check(
            "controlled decision failure surfaced",
            "controlled canonical decision" in str(exc),
        )
    else:
        raise AssertionError("controlled decision failure did not raise")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        offer = await repositories.offers.get_by_identity(
            TENANT_A_ID,
            "ggsel",
            "offer-rollback",
        )
        decisions = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-rollback",
        )
    verifier.check(
        "failed audit rolls back offer link",
        offer is not None and offer.canonical_product_id is None,
    )
    verifier.check("failed audit leaves no decision", decisions == ())


async def _verify_concurrency(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    conflicting_results = await asyncio.gather(
        _service(session_factory).review(
            _command(
                "offer-conflict",
                PRODUCT_B_ID,
                CanonicalOfferDecisionType.CONFIRMED,
            ),
            _context("conflict-confirm"),
        ),
        _service(session_factory).review(
            _command(
                "offer-conflict",
                PRODUCT_B_ID,
                CanonicalOfferDecisionType.REJECTED,
            ),
            _context("conflict-reject"),
        ),
        return_exceptions=True,
    )
    accepted = [
        result
        for result in conflicting_results
        if isinstance(result, CanonicalOfferReviewResult)
    ]
    conflicts = [
        result
        for result in conflicting_results
        if isinstance(result, CanonicalOfferDecisionConflictError)
    ]
    verifier.check(
        "concurrent conflicting decisions serialize",
        len(accepted) == 1 and len(conflicts) == 1,
    )

    command_value = _command(
        "offer-idempotent",
        PRODUCT_B_ID,
        CanonicalOfferDecisionType.CONFIRMED,
    )
    context = _context("concurrent-idempotent")
    duplicate_results = await asyncio.gather(
        _service(session_factory).review(command_value, context),
        _service(session_factory).review(command_value, context),
    )
    verifier.check(
        "concurrent duplicate command is idempotent",
        {result.replayed for result in duplicate_results} == {False, True}
        and duplicate_results[0].decision == duplicate_results[1].decision,
    )


async def _verify_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        confirmed = await repositories.canonical_offer_decisions.get_for_pair(
            TENANT_A_ID,
            "ggsel",
            "offer-confirm",
            PRODUCT_A_ID,
        )
        rejected = await repositories.canonical_offer_decisions.get_for_pair(
            TENANT_A_ID,
            "ggsel",
            "offer-reject",
            PRODUCT_A_ID,
        )
        conflicting = await repositories.canonical_offer_decisions.list_for_offer(
            TENANT_A_ID,
            "ggsel",
            "offer-conflict",
        )

    verifier.check(
        "fresh session retains confirmed decision",
        confirmed is not None
        and confirmed.decision is CanonicalOfferDecisionType.CONFIRMED,
    )
    verifier.check(
        "fresh session retains rejected decision",
        rejected is not None
        and rejected.decision is CanonicalOfferDecisionType.REJECTED,
    )
    verifier.check("conflicting pair has one terminal row", len(conflicting) == 1)


async def _verify_audit_retention(
    session_factory: async_sessionmaker[AsyncSession],
    verifier: Verification,
) -> None:
    try:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(CanonicalProductRecord).where(
                    CanonicalProductRecord.id == PRODUCT_A_ID
                )
            )
    except IntegrityError:
        verifier.check("review evidence restricts product deletion", True)
    else:
        raise AssertionError("reviewed canonical product was deleted")

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        product = await repositories.canonical_products.get_by_tenant_and_id(
            TENANT_A_ID,
            PRODUCT_A_ID,
        )
    verifier.check("failed product deletion rolls back", product is not None)


def _service(
    session_factory: async_sessionmaker[AsyncSession],
) -> CanonicalOfferReviewService:
    return CanonicalOfferReviewService(
        create_postgres_repository_scope(session_factory),
    )


def _failing_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryScopeFactory:
    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            provider = create_postgres_provider(session)
            provider.canonical_offer_decisions = FailingDecisionRepository(session)
            yield provider

    return scope


def _tenant(tenant_id: UUID, name: str, slug: str) -> Tenant:
    return Tenant(
        id=tenant_id,
        name=name,
        slug=slug,
        created_at=NOW,
        updated_at=NOW,
    )


def _product(product_id: UUID) -> CanonicalProduct:
    return CanonicalProduct(
        id=product_id,
        tenant_id=TENANT_A_ID,
        name=f"Canonical product {product_id}",
        category="Games",
        aliases=(),
    )


def _offer(tenant_id: UUID, external_id: str) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        title=f"Source offer {external_id}",
        url=f"https://ggsel.net/en/catalog/product/{external_id}",
        price=Decimal("1999.00"),
        currency="RUB",
    )


def _command(
    external_id: str,
    canonical_product_id: UUID,
    decision: CanonicalOfferDecisionType,
) -> ReviewCanonicalOfferCommand:
    return ReviewCanonicalOfferCommand(
        tenant_id=TENANT_A_ID,
        marketplace="ggsel",
        external_id=external_id,
        canonical_product_id=canonical_product_id,
        decision=decision,
        reason=f"reviewed as {decision.value}",
    )


def _context(idempotency_key: str) -> CanonicalOfferReviewContext:
    return CanonicalOfferReviewContext(
        actor_id="postgres-reviewer",
        actor_type=AdminActorType.USER,
        request_id=f"request-{idempotency_key}",
        idempotency_key=idempotency_key,
    )


def _decision(
    *,
    tenant_id: UUID,
    external_id: str,
    canonical_product_id: UUID,
    idempotency_key: str,
) -> CanonicalOfferDecision:
    fingerprint = build_canonical_offer_decision_fingerprint(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        canonical_product_id=canonical_product_id,
        decision=CanonicalOfferDecisionType.REJECTED,
        actor_id="direct-writer",
        actor_type=AdminActorType.SYSTEM,
        reason="invalid cross-tenant test",
    )
    return CanonicalOfferDecision(
        id=uuid4(),
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id=external_id,
        canonical_product_id=canonical_product_id,
        decision=CanonicalOfferDecisionType.REJECTED,
        actor_id="direct-writer",
        actor_type=AdminActorType.SYSTEM,
        request_id="request-direct-invalid",
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        reason="invalid cross-tenant test",
        created_at=NOW,
    )


async def _recreate_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _apply_migrations(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _require_isolated_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        msg = f"{DATABASE_URL_ENV} must use PostgreSQL."
        raise RuntimeError(msg)
    if not database_name.startswith("epic19_review_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated epic19_review_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
