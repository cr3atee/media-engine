from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.elements import TextClause

LEGACY_TENANT_ID = "00000000-0000-4000-8000-000000000001"
TENANT_B_ID = "20000000-0000-4000-8000-000000000002"
MARKETPLACE_ID = "30000000-0000-4000-8000-000000000003"
PRODUCT_ID = "40000000-0000-4000-8000-000000000004"
PRICE_ID = "50000000-0000-4000-8000-000000000005"
CANONICAL_ID = "60000000-0000-4000-8000-000000000006"
OFFER_ID = "70000000-0000-4000-8000-000000000007"
SECOND_OFFER_ID = "71000000-0000-4000-8000-000000000007"
DUPLICATE_OFFER_ID = "72000000-0000-4000-8000-000000000007"
EVENT_ID = "80000000-0000-4000-8000-000000000008"
CONTENT_ID = "90000000-0000-4000-8000-000000000009"
PUBLICATION_ID = "a0000000-0000-4000-8000-00000000000a"
ACTION_ID = "b0000000-0000-4000-8000-00000000000b"

TENANT_OWNED_TABLES = (
    "products",
    "prices",
    "canonical_products",
    "offers",
    "price_snapshots",
    "market_events",
    "generated_contents",
    "publications",
    "admin_actions",
)


def main() -> None:
    database_url = _database_url()
    config = Config("alembic.ini")

    command.upgrade(config, "0009_admin_actions")
    _run(_insert_legacy_rows(database_url))

    command.upgrade(config, "head")
    _run(_verify_legacy_backfill(database_url))
    _run(_verify_cross_tenant_identity(database_url))
    _run(_remove_second_tenant(database_url))

    command.downgrade(config, "0009_admin_actions")
    _run(_verify_tenant_columns_absent(database_url))
    command.upgrade(config, "head")
    _run(_verify_legacy_backfill(database_url))

    print("EPIC 16 tenant foundation verification passed")


def _database_url() -> str:
    value = os.getenv("MEDIAENGINE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if value is None:
        msg = "MEDIAENGINE_DATABASE_URL or DATABASE_URL is required."
        raise RuntimeError(msg)
    return value


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


async def _insert_legacy_rows(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO marketplaces (id, code, name, enabled, created_at)
                    VALUES (
                        CAST(:id AS uuid), 'verify', 'Verification', TRUE,
                        TIMESTAMP '2026-08-02 08:00:00'
                    )
                    """
                ),
                {"id": MARKETPLACE_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO products (
                        id, external_id, title, marketplace_id, created_at
                    ) VALUES (
                        CAST(:id AS uuid), 'shared-offer', 'Shared offer',
                        CAST(:marketplace_id AS uuid),
                        TIMESTAMP '2026-08-02 08:00:00'
                    )
                    """
                ),
                {"id": PRODUCT_ID, "marketplace_id": MARKETPLACE_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO prices (
                        id, product_id, price, currency, seller, collected_at
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:product_id AS uuid),
                        990.00, 'RUB', 'Verifier',
                        TIMESTAMP '2026-08-02 08:00:00'
                    )
                    """
                ),
                {"id": PRICE_ID, "product_id": PRODUCT_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO canonical_products (
                        id, name, category, aliases, created_at
                    ) VALUES (
                        CAST(:id AS uuid), 'Shared product', 'games',
                        CAST('[]' AS json),
                        TIMESTAMPTZ '2026-08-02 08:00:00+00'
                    )
                    """
                ),
                {"id": CANONICAL_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO offers (
                        id, marketplace, external_id, title, url, price, currency,
                        seller_id, seller_name, canonical_product_id, created_at
                    ) VALUES (
                        CAST(:id AS uuid), 'ggsel', 'shared-offer', 'Shared offer',
                        'https://example.test/shared-offer', 790.00, 'RUB',
                        'seller-1', 'Verifier', CAST(:canonical_id AS uuid),
                        TIMESTAMPTZ '2026-08-02 08:05:00+00'
                    )
                    """
                ),
                {"id": OFFER_ID, "canonical_id": CANONICAL_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO price_snapshots (
                        id, marketplace, external_id, price, currency, collected_at
                    ) VALUES
                        (
                            1001, 'ggsel', 'shared-offer', 990.00, 'RUB',
                            TIMESTAMPTZ '2026-08-02 08:00:00+00'
                        ),
                        (
                            1002, 'ggsel', 'shared-offer', 790.00, 'RUB',
                            TIMESTAMPTZ '2026-08-02 08:05:00+00'
                        )
                    """
                )
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO market_events (
                        id, identity_key, identity_version, identity_source,
                        event_type, marketplace, external_id,
                        canonical_product_id, previous_snapshot_id,
                        current_snapshot_id, title, url, old_price, new_price,
                        currency, percentage, score, disposition, scoring_status,
                        scoring_attempt_count, next_retry_at, claim_token,
                        worker_id, claimed_at, lease_expires_at, last_error_code,
                        last_error_summary, occurred_at, detected_at, created_at,
                        updated_at, version, audit_metadata
                    ) VALUES (
                        CAST(:id AS uuid), :identity_key, 1, 'snapshot_ids',
                        'price_drop', 'ggsel', 'shared-offer',
                        CAST(:canonical_id AS uuid), 1001, 1002,
                        'Shared offer', 'https://example.test/shared-offer',
                        990.00, 790.00, 'RUB', 20.202020, NULL, 'active',
                        'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                        TIMESTAMPTZ '2026-08-02 08:05:00+00',
                        TIMESTAMPTZ '2026-08-02 08:06:00+00',
                        TIMESTAMPTZ '2026-08-02 08:07:00+00',
                        TIMESTAMPTZ '2026-08-02 08:07:00+00',
                        1, NULL
                    )
                    """
                ),
                {
                    "id": EVENT_ID,
                    "identity_key": "a" * 64,
                    "canonical_id": CANONICAL_ID,
                },
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO generated_contents (
                        id, event_id, parent_content_id, content_type, language,
                        origin, provider, model, prompt_version, content_text,
                        generation_status, review_status, attempt_number,
                        idempotency_key, content_checksum, next_retry_at,
                        claim_token, worker_id, claimed_at, lease_expires_at,
                        last_error_code, last_error_summary, created_at,
                        updated_at, completed_at, version
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:event_id AS uuid), NULL,
                        'telegram', 'ru', 'ai', 'fake', 'fake-model', 'v1', NULL,
                        'pending', 'not_required', 1, :idempotency_key, NULL,
                        NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                        TIMESTAMPTZ '2026-08-02 08:08:00+00',
                        TIMESTAMPTZ '2026-08-02 08:08:00+00',
                        NULL, 1
                    )
                    """
                ),
                {
                    "id": CONTENT_ID,
                    "event_id": EVENT_ID,
                    "idempotency_key": "b" * 64,
                },
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO publications (
                        id, event_id, content_id, channel, destination_key,
                        publication_status, attempt_count, idempotency_key,
                        external_message_id, scheduled_at, next_retry_at,
                        published_at, claim_token, worker_id, claimed_at,
                        lease_expires_at, last_error_code, last_error_summary,
                        created_at, updated_at, version
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:event_id AS uuid),
                        CAST(:content_id AS uuid), 'telegram', 'shared-channel',
                        'pending', 0, :idempotency_key, NULL, NULL, NULL, NULL,
                        NULL, NULL, NULL, NULL, NULL, NULL,
                        TIMESTAMPTZ '2026-08-02 08:09:00+00',
                        TIMESTAMPTZ '2026-08-02 08:09:00+00', 1
                    )
                    """
                ),
                {
                    "id": PUBLICATION_ID,
                    "event_id": EVENT_ID,
                    "content_id": CONTENT_ID,
                    "idempotency_key": "c" * 64,
                },
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO admin_actions (
                        id, action, resource_type, resource_id, previous_state,
                        resulting_state, reason, actor_id, request_id,
                        idempotency_key, request_fingerprint, expected_version,
                        resulting_version, created_at
                    ) VALUES (
                        CAST(:id AS uuid), 'approve_content', 'content',
                        CAST(:content_id AS uuid), 'pending', 'approved', NULL,
                        'verification-api-key', 'verification-request',
                        'verification-action', :fingerprint, 1, 2,
                        TIMESTAMPTZ '2026-08-02 08:10:00+00'
                    )
                    """
                ),
                {
                    "id": ACTION_ID,
                    "content_id": CONTENT_ID,
                    "fingerprint": "d" * 64,
                },
            )
    finally:
        await engine.dispose()


async def _verify_legacy_backfill(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            legacy = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM tenants "
                    "WHERE id = CAST(:tenant_id AS uuid) "
                    "AND slug = 'legacy' AND is_active = TRUE"
                ),
                {"tenant_id": LEGACY_TENANT_ID},
            )
            _require(legacy == 1, "Legacy tenant was not seeded correctly.")

            for table_name in TENANT_OWNED_TABLES:
                invalid = await connection.scalar(
                    sa.text(
                        f"SELECT COUNT(*) FROM {table_name} "
                        "WHERE tenant_id IS NULL "
                        "OR tenant_id <> CAST(:tenant_id AS uuid)"
                    ),
                    {"tenant_id": LEGACY_TENANT_ID},
                )
                _require(
                    invalid == 0,
                    f"Legacy ownership backfill failed for {table_name}.",
                )

            actor = (
                await connection.execute(
                    sa.text(
                        "SELECT actor_type, elevated FROM admin_actions "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": ACTION_ID},
                )
            ).one()
            _require(actor[0] == "api_key", "Admin actor type was not backfilled.")
            _require(actor[1] is False, "Admin elevation was not backfilled.")
    finally:
        await engine.dispose()


async def _verify_cross_tenant_identity(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO tenants (
                        id, name, slug, is_active, created_at, updated_at, version
                    ) VALUES (
                        CAST(:id AS uuid), 'Second tenant', 'second-tenant', TRUE,
                        TIMESTAMPTZ '2026-08-02 09:00:00+00',
                        TIMESTAMPTZ '2026-08-02 09:00:00+00', 1
                    )
                    """
                ),
                {"id": TENANT_B_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO offers (
                        id, tenant_id, marketplace, external_id, title, created_at
                    ) VALUES (
                        CAST(:id AS uuid), CAST(:tenant_id AS uuid),
                        'ggsel', 'shared-offer', 'Second tenant offer',
                        TIMESTAMPTZ '2026-08-02 09:01:00+00'
                    )
                    """
                ),
                {"id": SECOND_OFFER_ID, "tenant_id": TENANT_B_ID},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO price_snapshots (
                        id, tenant_id, marketplace, external_id, price,
                        currency, collected_at
                    ) VALUES (
                        2001, CAST(:tenant_id AS uuid), 'ggsel', 'shared-offer',
                        990.00, 'RUB',
                        TIMESTAMPTZ '2026-08-02 08:00:00+00'
                    )
                    """
                ),
                {"tenant_id": TENANT_B_ID},
            )

        await _expect_integrity_error(
            engine,
            sa.text(
                """
                INSERT INTO offers (
                    id, tenant_id, marketplace, external_id, title, created_at
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tenant_id AS uuid),
                    'ggsel', 'shared-offer', 'Duplicate tenant offer',
                    TIMESTAMPTZ '2026-08-02 09:02:00+00'
                )
                """
            ),
            {"id": DUPLICATE_OFFER_ID, "tenant_id": TENANT_B_ID},
            "Same-tenant duplicate offer identity was accepted.",
        )
        await _expect_integrity_error(
            engine,
            sa.text(
                """
                INSERT INTO price_snapshots (
                    id, tenant_id, marketplace, external_id, price,
                    currency, collected_at
                ) VALUES (
                    2002, CAST(:tenant_id AS uuid), 'ggsel', 'shared-offer',
                    990.00, 'RUB',
                    TIMESTAMPTZ '2026-08-02 08:00:00+00'
                )
                """
            ),
            {"tenant_id": TENANT_B_ID},
            "Same-tenant duplicate snapshot identity was accepted.",
        )

        async with engine.connect() as connection:
            offer_count = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM offers "
                    "WHERE marketplace = 'ggsel' AND external_id = 'shared-offer'"
                )
            )
            snapshot_count = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM price_snapshots "
                    "WHERE marketplace = 'ggsel' "
                    "AND external_id = 'shared-offer' "
                    "AND price = 990.00 "
                    "AND collected_at = "
                    "TIMESTAMPTZ '2026-08-02 08:00:00+00'"
                )
            )
            _require(offer_count == 2, "Cross-tenant offer identity collided.")
            _require(snapshot_count == 2, "Cross-tenant snapshot identity collided.")
    finally:
        await engine.dispose()


async def _expect_integrity_error(
    engine: AsyncEngine,
    statement: TextClause,
    parameters: dict[str, str],
    failure_message: str,
) -> None:
    try:
        async with engine.begin() as connection:
            await connection.execute(statement, parameters)
    except IntegrityError:
        return
    raise AssertionError(failure_message)


async def _remove_second_tenant(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "DELETE FROM price_snapshots "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid)"
                ),
                {"tenant_id": TENANT_B_ID},
            )
            await connection.execute(
                sa.text(
                    "DELETE FROM offers WHERE tenant_id = CAST(:tenant_id AS uuid)"
                ),
                {"tenant_id": TENANT_B_ID},
            )
            await connection.execute(
                sa.text("DELETE FROM tenants WHERE id = CAST(:tenant_id AS uuid)"),
                {"tenant_id": TENANT_B_ID},
            )
    finally:
        await engine.dispose()


async def _verify_tenant_columns_absent(database_url: str) -> None:
    engine = create_async_engine(database_url)
    table_names = ", ".join(f"'{table}'" for table in TENANT_OWNED_TABLES)
    try:
        async with engine.connect() as connection:
            tenant_table = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'tenants'"
                )
            )
            tenant_columns = await connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
                    f"AND table_name IN ({table_names})"
                )
            )
            _require(tenant_table == 0, "Tenant table survived downgrade.")
            _require(tenant_columns == 0, "Tenant columns survived downgrade.")
    finally:
        await engine.dispose()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
