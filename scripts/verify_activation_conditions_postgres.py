"""Verify activation condition persistence using an isolated test database only."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from app.parsers.models import ParsedOffer
    from app.repositories.provider import RepositoryProvider
    from app.services.repository_scope import RepositoryScopeFactory

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_ENV = "ACTIVATION_TEST_DATABASE_URL"


def require_isolated_database(value: str) -> None:
    """Reject absent, remote and non-test database targets before any writes."""
    url = make_url(value)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "localhost"}
        or not (url.database or "").startswith("epic25_activation_")
    ):
        raise ValueError("Requires a loopback epic25_activation_* test database.")


async def verify(database_url: str) -> int:
    """Exercise synthetic fixtures through real repositories and public reads."""
    require_isolated_database(database_url)
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database.repository_scope import create_postgres_repository_scope
    from app.database.session import engine as default_engine
    from app.domain.activation_conditions import (
        AccountRequirement,
        ActivationConditions,
        DeliveryMethod,
    )
    from app.domain.tenancy import Tenant
    from app.models.canonical_product import CanonicalProduct
    from app.parsers.models import ParsedOffer
    from app.repositories.public_queries.repository_backed import (
        RepositoryBackedPublicReadRepository,
    )

    count = 0

    def check(condition: bool, name: str) -> None:
        nonlocal count
        if not condition:
            raise RuntimeError(f"Verification failed: {name}")
        count += 1
        print(f"PASS {name}")

    now = datetime.now(UTC)
    tenant_a, tenant_b = UUID(int=25001), UUID(int=25002)
    product = CanonicalProduct(
        id=UUID(int=25003),
        tenant_id=tenant_a,
        name="Offline fixture subscription 1 month",
        category="subscriptions",
        aliases=(),
    )
    terms = ActivationConditions(
        regions=("RU", "KZ"),
        excluded_regions=(),
        device="pc",
        plan="individual",
        period="P1M",
        delivery_method=DeliveryMethod.KEY,
        account_requirement=AccountRequirement.ANY,
        vpn_required=False,
        activation_window_seconds=None,
    )
    first = ParsedOffer(
        tenant_id=tenant_a,
        marketplace="funpay",
        external_id="activation-fixture-1",
        title=product.name,
        url="https://example.com/test-only",
        price=Decimal("700"),
        currency="RUB",
        canonical_product_id=product.id,
        activation_conditions=terms,
    )
    second = replace(first, external_id="activation-fixture-2", price=Decimal("500"))
    engine = create_async_engine(database_url)
    fresh = None
    try:
        scope = create_postgres_repository_scope(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        async with scope() as repos:
            for tenant_id, slug in (
                (tenant_a, "activation-fixture-a"),
                (tenant_b, "activation-fixture-b"),
            ):
                if await repos.tenants.get_by_id(tenant_id) is None:
                    await repos.tenants.create(
                        Tenant(
                            id=tenant_id,
                            name=slug,
                            slug=slug,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            await repos.canonical_products.save(product)
            await repos.offers.save(first)
            await repos.offers.save(second)
            await repos.offers.save(second)
            await repos.offers.save(
                replace(
                    first,
                    tenant_id=tenant_b,
                    canonical_product_id=None,
                    activation_conditions=replace(terms, regions=("BR",)),
                )
            )
        await engine.dispose()
        fresh = create_async_engine(database_url)
        scope = create_postgres_repository_scope(
            async_sessionmaker(fresh, expire_on_commit=False)
        )
        async with scope() as repos:
            stored = await repos.offers.get_by_identity(
                tenant_a, "funpay", "activation-fixture-1"
            )
            check(
                stored is not None and stored.activation_conditions == terms,
                "fresh-engine JSONB roundtrip",
            )
            check(
                len(await repos.offers.list_by_tenant(tenant_a)) == 2,
                "idempotent upsert",
            )
            other = await repos.offers.get_by_identity(
                tenant_b, "funpay", "activation-fixture-1"
            )
            check(
                other is not None
                and other.activation_conditions == replace(terms, regions=("BR",)),
                "tenant isolation",
            )
            public = RepositoryBackedPublicReadRepository(repos)
            result = await public.get_comparison(product.id, tenant_a)
            check(
                result is not None
                and result.best_offer is not None
                and result.best_offer.price == Decimal("500"),
                "compatible minimum price",
            )
            check(
                result is not None
                and len(result.differences) == 1
                and result.differences[0].absolute_difference == Decimal("200"),
                "compatible Decimal difference",
            )

        try:
            async with scope() as repos:
                await repos.offers.save(
                    replace(
                        second, activation_conditions=replace(terms, regions=("BR",))
                    )
                )
                raise _RollbackProbe
        except _RollbackProbe:
            pass
        async with scope() as repos:
            stored = await repos.offers.get_by_identity(
                tenant_a, "funpay", "activation-fixture-2"
            )
            check(
                stored is not None and stored.activation_conditions == terms,
                "transaction rollback",
            )
            await repos.offers.save(
                replace(second, activation_conditions=replace(terms, regions=("BR",)))
            )
        async with scope() as repos:
            result = await RepositoryBackedPublicReadRepository(repos).get_comparison(
                product.id, tenant_a
            )
            check(
                result is not None
                and result.status == "activation_conditions_mismatch"
                and result.best_offer is None
                and not result.differences,
                "region mismatch blocks savings",
            )
            await repos.offers.save(replace(second, activation_conditions=None))
        async with scope() as repos:
            stored = await repos.offers.get_by_identity(
                tenant_a, "funpay", "activation-fixture-2"
            )
            check(
                stored is not None and stored.activation_conditions is None,
                "unknown refresh clears stale conditions",
            )
            result = await RepositoryBackedPublicReadRepository(repos).get_comparison(
                product.id, tenant_a
            )
            check(
                result is not None
                and result.status == "activation_conditions_unknown"
                and result.best_offer is None
                and not result.differences,
                "unknown conditions block savings",
            )
        await _verify_review(scope, database_url, second, terms, check)
        if password := os.getenv("ACTIVATION_REVIEW_TEST_PASSWORD"):
            await _seed_browser_reviewer(scope, password)
        return count
    finally:
        await engine.dispose()
        if fresh is not None:
            await fresh.dispose()
        await default_engine.dispose()


async def _seed_browser_reviewer(scope: RepositoryScopeFactory, password: str) -> None:
    """Opt-in fixture identity for the separate browser test, never real users."""
    from app.domain.auth import PasswordCredential
    from app.domain.tenancy import Membership, TenantRole, User
    from app.services.passwords import PasswordHasher

    now = datetime.now(UTC)
    tenant_id = UUID(int=25001)
    async with scope() as repos:
        user = await repos.users.get_by_email("activation-reviewer@example.test")
        if user is None:
            user = await repos.users.create(
                User(
                    id=uuid4(),
                    email="activation-reviewer@example.test",
                    created_at=now,
                    updated_at=now,
                )
            )
        await repos.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user.id,
                password_hash=PasswordHasher(iterations=100_000).hash_password(
                    password
                ),
                created_at=now,
                updated_at=now,
            )
        )
        membership = await repos.memberships.get_by_user_and_tenant(user.id, tenant_id)
        if membership is None:
            await repos.memberships.create(
                Membership(
                    id=uuid4(),
                    user_id=user.id,
                    tenant_id=tenant_id,
                    role=TenantRole.REVIEWER,
                    joined_at=now,
                    updated_at=now,
                )
            )
        elif membership.role is not TenantRole.REVIEWER or not membership.is_active:
            raise RuntimeError("Browser fixture membership has unexpected access.")
    print("PASS opt-in isolated browser reviewer prepared; credentials not logged.")


class _RollbackProbe(Exception):
    """Intentional test rollback, never an application failure."""


async def _verify_review(
    scope: RepositoryScopeFactory,
    database_url: str,
    offer: ParsedOffer,
    terms: object,
    check: Callable[[bool, str], None],
) -> None:
    """Exercise real review transactions; no real seller data is modified."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database.repository_scope import create_postgres_repository_scope
    from app.domain.activation_conditions import ActivationConditions
    from app.domain.admin_actions import AdminActorType, AdminResourceType
    from app.services.admin_mutations import AdminCommandContext, AdminMutationResult
    from app.services.offer_activation_review import (
        ActivationReviewError,
        OfferActivationReviewService,
        ReviewActivationConditionsCommand,
    )

    assert isinstance(terms, ActivationConditions)
    assert offer.external_id is not None
    service = OfferActivationReviewService(scope)
    initial = await service.get(offer.tenant_id, offer.marketplace, offer.external_id)
    prefix = f"activation-fixture-{uuid4().hex}"
    context = AdminCommandContext(
        tenant_id=offer.tenant_id,
        actor_id="offline-fixture-reviewer",
        actor_type=AdminActorType.USER,
        request_id=prefix,
        idempotency_key=prefix,
    )
    command = ReviewActivationConditionsCommand(
        tenant_id=offer.tenant_id,
        marketplace=offer.marketplace,
        external_id=offer.external_id,
        offer_id=initial.offer_id,
        expected_version=initial.version,
        expected_source_fingerprint=initial.source_fingerprint,
        conditions=terms,
        reason="Synthetic fixture confirmation; not real marketplace verification.",
    )
    accepted = await service.review(command, context)
    check(
        accepted.resulting_version == initial.version + 1,
        "review creates audit revision",
    )
    replay = await service.review(command, context)
    check(
        replay.replayed and replay.action_id == accepted.action_id,
        "review idempotent replay",
    )
    try:
        await service.review(replace(command, conditions=None), context)
    except ActivationReviewError as error:
        check(error.code == "idempotency_conflict", "review fingerprint conflict")
    else:
        raise RuntimeError("Conflicting idempotency payload was accepted.")

    fresh = create_async_engine(database_url)
    factory = async_sessionmaker(fresh, expire_on_commit=False)
    try:
        fresh_scope = create_postgres_repository_scope(factory)
        current = await OfferActivationReviewService(fresh_scope).get(
            offer.tenant_id, offer.marketplace, offer.external_id
        )
        check(
            current.offer.activation_conditions == terms
            and current.version == accepted.resulting_version,
            "review survives fresh engine",
        )
        blocked = []
        for statement in (
            "UPDATE admin_actions SET reason = 'forbidden fixture edit' WHERE id = :id",
            "DELETE FROM admin_actions WHERE id = :id",
        ):
            async with factory() as session:
                immutable = False
                try:
                    await session.execute(text(statement), {"id": accepted.action_id})
                except DBAPIError:
                    immutable = True
                finally:
                    await session.rollback()
                blocked.append(immutable)
        check(all(blocked), "review audit rejects UPDATE and DELETE")

        @asynccontextmanager
        async def failing_scope() -> AsyncIterator[RepositoryProvider]:
            async with fresh_scope() as repos:
                with patch.object(
                    repos.admin_actions,
                    "append",
                    side_effect=RuntimeError("controlled audit failure"),
                ):
                    yield repos

        next_command = replace(
            command,
            expected_version=current.version,
            expected_source_fingerprint=current.source_fingerprint,
            conditions=replace(terms, regions=("BR",)),
        )
        try:
            await OfferActivationReviewService(failing_scope).review(
                next_command, replace(context, idempotency_key=prefix + "-rollback")
            )
        except RuntimeError as error:
            if str(error) != "controlled audit failure":
                raise
        else:
            raise RuntimeError("Expected audit failure did not occur.")
        rolled_back = await service.get(
            offer.tenant_id, offer.marketplace, offer.external_id
        )
        check(
            rolled_back.offer.activation_conditions == terms
            and rolled_back.version == current.version,
            "review audit failure rolls back profile",
        )

        results = await asyncio.gather(
            service.review(
                next_command, replace(context, idempotency_key=prefix + "-one")
            ),
            service.review(
                replace(next_command, conditions=replace(terms, regions=("*",))),
                replace(context, idempotency_key=prefix + "-two"),
            ),
            return_exceptions=True,
        )
        check(
            sum(isinstance(item, AdminMutationResult) for item in results) == 1
            and sum(isinstance(item, ActivationReviewError) for item in results) == 1,
            "concurrent reviews have one winner",
        )
        current = await service.get(
            offer.tenant_id, offer.marketplace, offer.external_id
        )
        cleared = await service.review(
            replace(
                command,
                expected_version=current.version,
                expected_source_fingerprint=current.source_fingerprint,
                conditions=None,
            ),
            replace(context, idempotency_key=prefix + "-clear"),
        )
        check(
            cleared.resulting_state == "unknown"
            and (
                await service.get(offer.tenant_id, offer.marketplace, offer.external_id)
            ).offer.activation_conditions
            is None,
            "review explicitly resets unknown",
        )

        current = await service.get(
            offer.tenant_id, offer.marketplace, offer.external_id
        )
        async with fresh_scope() as repos:
            await repos.offers.save(replace(current.offer, price=Decimal("501")))
        async with fresh_scope() as repos:
            updated = await repos.offers.compare_and_set_activation_conditions(
                offer.tenant_id, current.offer, terms
            )
            stored = await repos.offers.get_by_identity(
                offer.tenant_id, offer.marketplace, offer.external_id
            )
            check(
                not updated
                and stored is not None
                and stored.price == Decimal("501")
                and stored.activation_conditions is None,
                "atomic CAS preserves changed source price",
            )
        try:
            await service.review(
                replace(
                    command,
                    expected_version=current.version,
                    expected_source_fingerprint=current.source_fingerprint,
                ),
                replace(context, idempotency_key=prefix + "-stale"),
            )
        except ActivationReviewError as error:
            check(
                error.code == "activation_source_conflict",
                "review rejects changed source snapshot",
            )
        else:
            raise RuntimeError("Stale source snapshot was accepted.")
        async with fresh_scope() as repos:
            trail = await repos.admin_actions.list_for_resource(
                AdminResourceType.OFFER, initial.offer_id
            )
            check(
                len([item for item in trail if item.idempotency_key.startswith(prefix)])
                == 3,
                "retries failures and conflicts add no audit duplicates",
            )
    finally:
        await fresh.dispose()


def main() -> int:
    """Run against a pre-migrated disposable database, never skip as success."""
    value = os.getenv(DATABASE_ENV, "")
    if not value:
        print(f"ERROR: set {DATABASE_ENV} to a migrated isolated test database.")
        return 2
    try:
        require_isolated_database(value)
    except ValueError:
        print("ERROR: only loopback epic25_activation_* test databases are allowed.")
        return 2
    os.environ["DATABASE_URL"] = value
    count = asyncio.run(verify(value))
    print(f"PASS {count} PostgreSQL activation checks; synthetic fixtures only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
