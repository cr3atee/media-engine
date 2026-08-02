from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.elements import TextClause

LEGACY_PRODUCT_ID = "40000000-0000-4000-8000-000000000004"
LEGACY_CANONICAL_ID = "60000000-0000-4000-8000-000000000006"
LEGACY_EVENT_ID = "80000000-0000-4000-8000-000000000008"
LEGACY_CONTENT_ID = "90000000-0000-4000-8000-000000000009"
LEGACY_PREVIOUS_SNAPSHOT_ID = 1001
LEGACY_CURRENT_SNAPSHOT_ID = 1002

TENANT_ID = "20000000-0000-4000-8000-000000000002"
TENANT_EVENT_ID = "81000000-0000-4000-8000-000000000008"
TENANT_CONTENT_ID = "91000000-0000-4000-8000-000000000009"
TENANT_PREVIOUS_SNAPSHOT_ID = 3001
TENANT_CURRENT_SNAPSHOT_ID = 3002


def main() -> None:
    database_url = _database_url()
    _run(_verify(database_url))
    print("EPIC 16 tenant parent consistency verification passed")


def _database_url() -> str:
    value = os.getenv("MEDIAENGINE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if value is None:
        msg = "MEDIAENGINE_DATABASE_URL or DATABASE_URL is required."
        raise RuntimeError(msg)
    return value


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


async def _verify(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        await _create_valid_second_tenant_chain(engine)
        await _verify_cross_tenant_price_rejected(engine)
        await _verify_cross_tenant_offer_catalog_rejected(engine)
        await _verify_cross_tenant_event_snapshot_rejected(engine)
        await _verify_cross_tenant_event_catalog_rejected(engine)
        await _verify_cross_tenant_content_event_rejected(engine)
        await _verify_cross_tenant_content_parent_rejected(engine)
        await _verify_cross_tenant_publication_event_rejected(engine)
        await _verify_cross_tenant_publication_content_rejected(engine)
        await _cleanup(engine)
    finally:
        await engine.dispose()


async def _create_valid_second_tenant_chain(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                """
                INSERT INTO tenants (
                    id, name, slug, is_active, created_at, updated_at, version
                ) VALUES (
                    CAST(:tenant_id AS uuid),
                    'Parent consistency tenant',
                    'parent-consistency',
                    TRUE,
                    TIMESTAMPTZ '2026-08-02 10:00:00+00',
                    TIMESTAMPTZ '2026-08-02 10:00:00+00',
                    1
                )
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO price_snapshots (
                    id, tenant_id, marketplace, external_id, price,
                    currency, collected_at
                ) VALUES
                    (
                        :previous_id,
                        CAST(:tenant_id AS uuid),
                        'ggsel',
                        'tenant-parent-consistency',
                        990.00,
                        'RUB',
                        TIMESTAMPTZ '2026-08-02 10:01:00+00'
                    ),
                    (
                        :current_id,
                        CAST(:tenant_id AS uuid),
                        'ggsel',
                        'tenant-parent-consistency',
                        790.00,
                        'RUB',
                        TIMESTAMPTZ '2026-08-02 10:02:00+00'
                    )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "previous_id": TENANT_PREVIOUS_SNAPSHOT_ID,
                "current_id": TENANT_CURRENT_SNAPSHOT_ID,
            },
        )
        await connection.execute(
            _event_insert(
                event_id=TENANT_EVENT_ID,
                identity_key="1" * 64,
                previous_snapshot_id=TENANT_PREVIOUS_SNAPSHOT_ID,
                current_snapshot_id=TENANT_CURRENT_SNAPSHOT_ID,
                canonical_product_id=None,
                external_id="tenant-parent-consistency",
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            _content_insert(
                content_id=TENANT_CONTENT_ID,
                event_id=TENANT_EVENT_ID,
                parent_content_id=None,
                idempotency_key="2" * 64,
                content_type="tenant-valid",
            ),
            {"tenant_id": TENANT_ID},
        )


async def _verify_cross_tenant_price_rejected(engine: AsyncEngine) -> None:
    await _expect_integrity_error(
        engine,
        sa.text(
            """
            INSERT INTO prices (
                id, tenant_id, product_id, price, currency, seller, collected_at
            ) VALUES (
                CAST('a1000000-0000-4000-8000-000000000001' AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:product_id AS uuid),
                100.00,
                'RUB',
                'Verifier',
                TIMESTAMPTZ '2026-08-02 10:03:00+00'
            )
            """
        ),
        {"tenant_id": TENANT_ID, "product_id": LEGACY_PRODUCT_ID},
        "Cross-tenant price-to-product link was accepted.",
    )


async def _verify_cross_tenant_offer_catalog_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        sa.text(
            """
            INSERT INTO offers (
                id, tenant_id, marketplace, external_id, title,
                canonical_product_id, created_at
            ) VALUES (
                CAST('a2000000-0000-4000-8000-000000000002' AS uuid),
                CAST(:tenant_id AS uuid),
                'ggsel',
                'cross-tenant-canonical-offer',
                'Cross-tenant canonical offer',
                CAST(:canonical_id AS uuid),
                TIMESTAMPTZ '2026-08-02 10:04:00+00'
            )
            """
        ),
        {"tenant_id": TENANT_ID, "canonical_id": LEGACY_CANONICAL_ID},
        "Cross-tenant offer-to-canonical-product link was accepted.",
    )


async def _verify_cross_tenant_event_snapshot_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _event_insert(
            event_id="a3000000-0000-4000-8000-000000000003",
            identity_key="3" * 64,
            previous_snapshot_id=LEGACY_PREVIOUS_SNAPSHOT_ID,
            current_snapshot_id=LEGACY_CURRENT_SNAPSHOT_ID,
            canonical_product_id=None,
            external_id="cross-tenant-snapshots",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant event-to-snapshot link was accepted.",
    )


async def _verify_cross_tenant_event_catalog_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _event_insert(
            event_id="a4000000-0000-4000-8000-000000000004",
            identity_key="4" * 64,
            previous_snapshot_id=TENANT_PREVIOUS_SNAPSHOT_ID,
            current_snapshot_id=TENANT_CURRENT_SNAPSHOT_ID,
            canonical_product_id=LEGACY_CANONICAL_ID,
            external_id="cross-tenant-event-canonical",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant event-to-canonical-product link was accepted.",
    )


async def _verify_cross_tenant_content_event_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _content_insert(
            content_id="a5000000-0000-4000-8000-000000000005",
            event_id=LEGACY_EVENT_ID,
            parent_content_id=None,
            idempotency_key="5" * 64,
            content_type="cross-event",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant content-to-event link was accepted.",
    )


async def _verify_cross_tenant_content_parent_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _content_insert(
            content_id="a6000000-0000-4000-8000-000000000006",
            event_id=TENANT_EVENT_ID,
            parent_content_id=LEGACY_CONTENT_ID,
            idempotency_key="6" * 64,
            content_type="cross-parent",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant content parent link was accepted.",
    )


async def _verify_cross_tenant_publication_event_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _publication_insert(
            publication_id="a7000000-0000-4000-8000-000000000007",
            event_id=LEGACY_EVENT_ID,
            content_id=TENANT_CONTENT_ID,
            idempotency_key="7" * 64,
            destination="cross-event",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant publication-to-event link was accepted.",
    )


async def _verify_cross_tenant_publication_content_rejected(
    engine: AsyncEngine,
) -> None:
    await _expect_integrity_error(
        engine,
        _publication_insert(
            publication_id="a8000000-0000-4000-8000-000000000008",
            event_id=TENANT_EVENT_ID,
            content_id=LEGACY_CONTENT_ID,
            idempotency_key="8" * 64,
            destination="cross-content",
        ),
        {"tenant_id": TENANT_ID},
        "Cross-tenant publication-to-content link was accepted.",
    )


def _event_insert(
    *,
    event_id: str,
    identity_key: str,
    previous_snapshot_id: int,
    current_snapshot_id: int,
    canonical_product_id: str | None,
    external_id: str,
) -> TextClause:
    canonical_sql = (
        "NULL"
        if canonical_product_id is None
        else f"CAST('{canonical_product_id}' AS uuid)"
    )
    return sa.text(
        f"""
        INSERT INTO market_events (
            id, tenant_id, identity_key, identity_version, identity_source,
            event_type, marketplace, external_id, canonical_product_id,
            previous_snapshot_id, current_snapshot_id, title, url,
            old_price, new_price, currency, percentage, score,
            disposition, scoring_status, scoring_attempt_count,
            next_retry_at, claim_token, worker_id, claimed_at,
            lease_expires_at, last_error_code, last_error_summary,
            occurred_at, detected_at, created_at, updated_at,
            version, audit_metadata
        ) VALUES (
            CAST('{event_id}' AS uuid),
            CAST(:tenant_id AS uuid),
            '{identity_key}',
            2,
            'snapshot_ids',
            'price_drop',
            'ggsel',
            '{external_id}',
            {canonical_sql},
            {previous_snapshot_id},
            {current_snapshot_id},
            'Parent consistency event',
            'https://example.test/parent-consistency',
            990.00,
            790.00,
            'RUB',
            20.202020,
            NULL,
            'active',
            'pending',
            0,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            TIMESTAMPTZ '2026-08-02 10:02:00+00',
            TIMESTAMPTZ '2026-08-02 10:03:00+00',
            TIMESTAMPTZ '2026-08-02 10:03:00+00',
            TIMESTAMPTZ '2026-08-02 10:03:00+00',
            1,
            NULL
        )
        """
    )


def _content_insert(
    *,
    content_id: str,
    event_id: str,
    parent_content_id: str | None,
    idempotency_key: str,
    content_type: str,
) -> TextClause:
    parent_sql = (
        "NULL"
        if parent_content_id is None
        else f"CAST('{parent_content_id}' AS uuid)"
    )
    return sa.text(
        f"""
        INSERT INTO generated_contents (
            id, tenant_id, event_id, parent_content_id,
            content_type, language, origin, provider, model,
            prompt_version, content_text, generation_status,
            review_status, attempt_number, idempotency_key,
            content_checksum, next_retry_at, claim_token, worker_id,
            claimed_at, lease_expires_at, last_error_code,
            last_error_summary, created_at, updated_at,
            completed_at, version
        ) VALUES (
            CAST('{content_id}' AS uuid),
            CAST(:tenant_id AS uuid),
            CAST('{event_id}' AS uuid),
            {parent_sql},
            '{content_type}',
            'ru',
            'ai',
            'fake',
            'fake-model',
            'v1',
            NULL,
            'pending',
            'not_required',
            1,
            '{idempotency_key}',
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            TIMESTAMPTZ '2026-08-02 10:05:00+00',
            TIMESTAMPTZ '2026-08-02 10:05:00+00',
            NULL,
            1
        )
        """
    )


def _publication_insert(
    *,
    publication_id: str,
    event_id: str,
    content_id: str,
    idempotency_key: str,
    destination: str,
) -> TextClause:
    return sa.text(
        f"""
        INSERT INTO publications (
            id, tenant_id, event_id, content_id, channel,
            destination_key, publication_status, attempt_count,
            idempotency_key, external_message_id, scheduled_at,
            next_retry_at, published_at, claim_token, worker_id,
            claimed_at, lease_expires_at, last_error_code,
            last_error_summary, created_at, updated_at, version
        ) VALUES (
            CAST('{publication_id}' AS uuid),
            CAST(:tenant_id AS uuid),
            CAST('{event_id}' AS uuid),
            CAST('{content_id}' AS uuid),
            'telegram',
            '{destination}',
            'pending',
            0,
            '{idempotency_key}',
            NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            TIMESTAMPTZ '2026-08-02 10:06:00+00',
            TIMESTAMPTZ '2026-08-02 10:06:00+00',
            1
        )
        """
    )


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


async def _cleanup(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "DELETE FROM generated_contents "
                "WHERE tenant_id = CAST(:tenant_id AS uuid)"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            sa.text(
                "DELETE FROM market_events "
                "WHERE tenant_id = CAST(:tenant_id AS uuid)"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            sa.text(
                "DELETE FROM price_snapshots "
                "WHERE tenant_id = CAST(:tenant_id AS uuid)"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            sa.text("DELETE FROM tenants WHERE id = CAST(:tenant_id AS uuid)"),
            {"tenant_id": TENANT_ID},
        )


if __name__ == "__main__":
    main()
