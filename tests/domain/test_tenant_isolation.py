from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.domain.generated_content import build_content_idempotency_key
from app.domain.identity import hash_identity_fields
from app.domain.market_events import (
    LEGACY_EVENT_IDENTITY_VERSION,
    MarketEvent,
    MarketEventCandidate,
    MarketEventType,
    PriceDropPayload,
    SnapshotIdentity,
    build_event_identity,
)
from app.domain.price_snapshot import PriceSnapshot
from app.domain.publications import (
    CreatePublication,
    build_publication_idempotency_key,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.parsers.models import ParsedOffer
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.memory.memory_events import MemoryMarketEventRepository
from app.repositories.memory.memory_offers import MemoryOfferRepository
from app.repositories.memory.memory_price_history import (
    MemoryPriceHistoryRepository,
)
from app.repositories.memory.memory_publications import MemoryPublicationRepository

TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("20000000-0000-4000-8000-000000000002")
EVENT_ID = UUID("30000000-0000-4000-8000-000000000003")
SECOND_EVENT_ID = UUID("31000000-0000-4000-8000-000000000003")
CONTENT_ID = UUID("40000000-0000-4000-8000-000000000004")
PUBLICATION_ID = UUID("50000000-0000-4000-8000-000000000005")
SECOND_PUBLICATION_ID = UUID("51000000-0000-4000-8000-000000000005")
PREVIOUS_AT = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
CURRENT_AT = datetime(2026, 8, 2, 8, 5, tzinfo=UTC)


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run one typed coroutine without requiring a pytest async plugin."""
    return asyncio.run(awaitable)


def make_offer(tenant_id: UUID) -> ParsedOffer:
    return ParsedOffer(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="shared-offer",
        title="Shared offer",
        url="https://example.test/shared-offer",
        price=Decimal("790.00"),
        currency="RUB",
    )


def make_snapshot(tenant_id: UUID, *, current: bool = False) -> PriceSnapshot:
    return PriceSnapshot(
        tenant_id=tenant_id,
        marketplace="ggsel",
        external_id="shared-offer",
        price=Decimal("790.00" if current else "990.00"),
        currency="RUB",
        collected_at=CURRENT_AT if current else PREVIOUS_AT,
    )


def make_snapshot_identity(
    tenant_id: UUID,
    *,
    current: bool = False,
) -> SnapshotIdentity:
    return SnapshotIdentity.from_snapshot(make_snapshot(tenant_id, current=current))


def make_legacy_event(tenant_id: UUID, event_id: UUID) -> MarketEvent[PriceDropPayload]:
    previous = make_snapshot_identity(tenant_id)
    current = make_snapshot_identity(tenant_id, current=True)
    payload = PriceDropPayload(
        title="Shared offer",
        url="https://example.test/shared-offer",
        old_price=previous.price,
        new_price=current.price,
        currency=current.currency,
        absolute_difference=previous.price - current.price,
        percentage=Decimal("20.20202020202020202020202020"),
        previous_snapshot=previous,
        current_snapshot=current,
    )
    identity = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=tenant_id,
        previous_snapshot=previous,
        current_snapshot=current,
        identity_version=LEGACY_EVENT_IDENTITY_VERSION,
    )
    return MarketEvent(
        id=event_id,
        identity_key=identity.key,
        identity_version=identity.version,
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=tenant_id,
        occurred_at=CURRENT_AT,
        detected_at=CURRENT_AT,
        created_at=CURRENT_AT,
        payload=payload,
    )


def test_event_identity_v2_is_tenant_scoped() -> None:
    first = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=TENANT_A,
        previous_snapshot=make_snapshot_identity(TENANT_A),
        current_snapshot=make_snapshot_identity(TENANT_A, current=True),
    )
    second = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=TENANT_B,
        previous_snapshot=make_snapshot_identity(TENANT_B),
        current_snapshot=make_snapshot_identity(TENANT_B, current=True),
    )

    assert first.key != second.key
    assert first.version == second.version == 2


def test_event_identity_v1_remains_stable_for_legacy_rows() -> None:
    first = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=TENANT_A,
        previous_snapshot=make_snapshot_identity(TENANT_A),
        current_snapshot=make_snapshot_identity(TENANT_A, current=True),
        identity_version=LEGACY_EVENT_IDENTITY_VERSION,
    )
    second = build_event_identity(
        event_type=MarketEventType.PRICE_DROP,
        marketplace="ggsel",
        external_id="shared-offer",
        tenant_id=TENANT_B,
        previous_snapshot=make_snapshot_identity(TENANT_B),
        current_snapshot=make_snapshot_identity(TENANT_B, current=True),
        identity_version=LEGACY_EVENT_IDENTITY_VERSION,
    )

    assert first.key == second.key


def test_legacy_content_and_publication_keys_remain_unchanged() -> None:
    content_key = build_content_idempotency_key(
        tenant_id=LEGACY_TENANT_ID,
        event_id=EVENT_ID,
        content_type="telegram",
        language="ru",
        prompt_version="v1",
        attempt_number=1,
    )
    publication_key = build_publication_idempotency_key(
        tenant_id=LEGACY_TENANT_ID,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="telegram",
        destination_key="shared-channel",
    )

    assert content_key == hash_identity_fields(
        str(EVENT_ID),
        "telegram",
        "ru",
        "v1",
        "1",
    )
    assert publication_key == hash_identity_fields(
        str(EVENT_ID),
        str(CONTENT_ID),
        "telegram",
        "shared-channel",
    )


def test_content_and_publication_idempotency_are_tenant_scoped() -> None:
    content_a = build_content_idempotency_key(
        tenant_id=TENANT_A,
        event_id=EVENT_ID,
        content_type="telegram",
        language="ru",
        prompt_version="v1",
        attempt_number=1,
    )
    content_b = build_content_idempotency_key(
        tenant_id=TENANT_B,
        event_id=EVENT_ID,
        content_type="telegram",
        language="ru",
        prompt_version="v1",
        attempt_number=1,
    )
    publication_a = build_publication_idempotency_key(
        tenant_id=TENANT_A,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="telegram",
        destination_key="shared-channel",
    )
    publication_b = build_publication_idempotency_key(
        tenant_id=TENANT_B,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="telegram",
        destination_key="shared-channel",
    )

    assert content_a != content_b
    assert publication_a != publication_b


def test_memory_event_lookup_is_explicitly_tenant_scoped() -> None:
    repository = MemoryMarketEventRepository()
    legacy_event = make_legacy_event(LEGACY_TENANT_ID, EVENT_ID)
    tenant_event = make_legacy_event(TENANT_B, SECOND_EVENT_ID)
    assert legacy_event.identity_key == tenant_event.identity_key

    run_async(repository.add_idempotently(MarketEventCandidate(event=legacy_event)))
    run_async(repository.add_idempotently(MarketEventCandidate(event=tenant_event)))

    assert run_async(repository.get_by_identity(legacy_event.identity_key)) == legacy_event
    assert (
        run_async(
            repository.get_by_identity_for_tenant(
                TENANT_B,
                tenant_event.identity_key,
            )
        )
        == tenant_event
    )


def test_memory_publication_lookup_is_explicitly_tenant_scoped() -> None:
    repository = MemoryPublicationRepository()
    legacy_command = CreatePublication(
        id=PUBLICATION_ID,
        tenant_id=LEGACY_TENANT_ID,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="telegram",
        destination_key="shared-channel",
        created_at=CURRENT_AT,
    )
    tenant_command = CreatePublication(
        id=SECOND_PUBLICATION_ID,
        tenant_id=TENANT_B,
        event_id=EVENT_ID,
        content_id=CONTENT_ID,
        channel="telegram",
        destination_key="shared-channel",
        created_at=CURRENT_AT,
    )

    legacy_result = run_async(repository.create_idempotently(legacy_command))
    tenant_result = run_async(repository.create_idempotently(tenant_command))

    assert (
        run_async(repository.get_by_idempotency_key(legacy_command.idempotency_key))
        == legacy_result.publication
    )
    assert (
        run_async(
            repository.get_by_idempotency_key_for_tenant(
                TENANT_B,
                tenant_command.idempotency_key,
            )
        )
        == tenant_result.publication
    )


def test_memory_offer_repository_isolates_shared_external_identity() -> None:
    repository = MemoryOfferRepository()
    offer_a = make_offer(TENANT_A)
    offer_b = make_offer(TENANT_B)

    run_async(repository.save_for_tenant(TENANT_A, offer_a))
    run_async(repository.save_for_tenant(TENANT_B, offer_b))

    assert (
        run_async(
            repository.get_by_identity_for_tenant(
                TENANT_A,
                "ggsel",
                "shared-offer",
            )
        )
        == offer_a
    )
    assert (
        run_async(
            repository.get_by_identity_for_tenant(
                TENANT_B,
                "ggsel",
                "shared-offer",
            )
        )
        == offer_b
    )
    assert len(run_async(repository.list_all())) == 2


def test_memory_price_history_isolates_shared_external_identity() -> None:
    repository = MemoryPriceHistoryRepository()
    snapshot_a = make_snapshot(TENANT_A)
    snapshot_b = make_snapshot(TENANT_B)

    assert run_async(repository.add_for_tenant(TENANT_A, snapshot_a)) is True
    assert run_async(repository.add_for_tenant(TENANT_B, snapshot_b)) is True

    assert run_async(
        repository.get_history_for_tenant(
            TENANT_A,
            "ggsel",
            "shared-offer",
        )
    ) == [snapshot_a]
    assert run_async(
        repository.get_history_for_tenant(
            TENANT_B,
            "ggsel",
            "shared-offer",
        )
    ) == [snapshot_b]


def test_explicit_tenant_context_rejects_mismatched_entities() -> None:
    offers = MemoryOfferRepository()
    snapshots = MemoryPriceHistoryRepository()

    with pytest.raises(RepositoryIdentityConflictError, match="Offer tenant mismatch"):
        run_async(offers.save_for_tenant(TENANT_A, make_offer(TENANT_B)))

    with pytest.raises(
        RepositoryIdentityConflictError,
        match="Snapshot tenant mismatch",
    ):
        run_async(
            snapshots.add_for_tenant(
                TENANT_A,
                make_snapshot(TENANT_B),
            )
        )
