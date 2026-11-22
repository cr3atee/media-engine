"""Verify activation condition persistence using an isolated test database only."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

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
        return count
    finally:
        await engine.dispose()
        if fresh is not None:
            await fresh.dispose()
        await default_engine.dispose()


class _RollbackProbe(Exception):
    """Intentional test rollback, never an application failure."""


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
