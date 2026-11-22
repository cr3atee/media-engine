"""Preview or apply an audited category correction in an isolated review database."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from hmac import compare_digest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.catalog.categories import (  # noqa: E402
    MVP_CATALOG_CATEGORIES,
    CatalogCategoryCode,
)
from scripts.run_catalog_review_postgres import (  # noqa: E402
    DATABASE_URL_ENV,
    _require_isolated_database,
    _safe_error_summary,
)


def approval_phrase(
    tenant_id: UUID,
    product_id: UUID,
    expected_version: int,
    expected_category: str,
    category: str,
) -> str:
    """Bind operator approval to one exact tenant, product and category revision."""
    return (
        f"CHANGE CATEGORY {tenant_id} {product_id} v{expected_version} "
        f"{expected_category} TO {category}"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse an explicit single-product correction, read-only by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    codes = [item.code for item in MVP_CATALOG_CATEGORIES]
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--product-id", type=UUID, required=True)
    parser.add_argument("--expected-version", type=int, required=True)
    parser.add_argument("--expected-category", choices=codes, required=True)
    parser.add_argument("--category", choices=codes, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval", default="")
    parser.add_argument("--actor-id", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--reason", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the isolated database and redact any unexpected error output."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    arguments = parse_args(argv)
    database_url = os.getenv(DATABASE_URL_ENV, "").strip()
    try:
        _require_isolated_database(database_url)
    except Exception:
        print("FAILED: invalid isolated review database configuration.")
        return 2
    os.environ["DATABASE_URL"] = database_url
    try:
        return asyncio.run(_run(arguments, database_url))
    except Exception as exc:
        print(f"FAILED: {_safe_error_summary(exc, database_url)}")
        return 1


async def _run(arguments: argparse.Namespace, database_url: str) -> int:
    from typing import cast

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database.repository_scope import create_postgres_repository_scope
    from app.database.session import engine as default_engine
    from app.domain.admin_actions import AdminActorType, AdminResourceType
    from app.services.admin_mutations import AdminCommandContext
    from app.services.canonical_product_categories import (
        CanonicalProductCategoryService,
        ChangeProductCategoryCommand,
    )

    engine = create_async_engine(database_url)
    scope = create_postgres_repository_scope(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    phrase = approval_phrase(
        arguments.tenant_id,
        arguments.product_id,
        arguments.expected_version,
        arguments.expected_category,
        arguments.category,
    )
    try:
        if not arguments.apply:
            async with scope() as repositories:
                product = await repositories.canonical_products.get_by_tenant_and_id(
                    arguments.tenant_id, arguments.product_id
                )
                if product is None:
                    raise ValueError("product_not_found")
                trail = await repositories.admin_actions.list_for_resource(
                    AdminResourceType.CANONICAL_PRODUCT, product.id
                )
            print(f"Product: {product.id} | {product.name}")
            print(f"Current category: {product.category}")
            version = max((a.resulting_version for a in trail), default=1)
            print(f"Category audit revision: {version}")
            print(
                f"Requested change: {arguments.expected_category} "
                f"-> {arguments.category}"
            )
            print(f"Approval: {phrase}")
            print("PREVIEW ONLY: no product, offer, or audit was changed.")
            return 0
        if not compare_digest(arguments.approval, phrase):
            raise ValueError("exact_approval_required")
        if not arguments.actor_id.strip() or not arguments.idempotency_key.strip():
            raise ValueError("actor_and_idempotency_key_required")
        action = await CanonicalProductCategoryService(scope).change(
            ChangeProductCategoryCommand(
                tenant_id=arguments.tenant_id,
                product_id=arguments.product_id,
                expected_version=arguments.expected_version,
                expected_category=cast(
                    CatalogCategoryCode, arguments.expected_category
                ),
                category=cast(CatalogCategoryCode, arguments.category),
                reason=arguments.reason,
            ),
            AdminCommandContext(
                tenant_id=arguments.tenant_id,
                actor_id=arguments.actor_id,
                actor_type=AdminActorType.PLATFORM_ADMIN,
                elevated=True,
                request_id=arguments.idempotency_key,
                idempotency_key=arguments.idempotency_key,
            ),
        )
        print(
            f"Audit: {action.id} | {action.previous_state} -> {action.resulting_state}"
        )
        print("Original names, offers and canonical review decisions were not changed.")
        return 0
    finally:
        await engine.dispose()
        await default_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
