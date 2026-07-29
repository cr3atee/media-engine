# ruff: noqa: E402
from __future__ import annotations

import asyncio
import inspect
import os
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.fake_provider import FakeAIProvider
from app.analytics.price_change import PriceChangeDetector
from app.domain.generated_content import (
    CreateContentAttempt,
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import (
    ContentGenerationStatus,
    PublicationStatus,
    ScoringStatus,
)
from app.domain.market_events import (
    EventAddResult,
    MarketEvent,
    MarketEventCandidate,
    PriceDropMarketEvent,
)
from app.domain.marketplace import Marketplace
from app.domain.price_snapshot import PriceSnapshot
from app.domain.processing import StateTransitionOutcome
from app.domain.publications import ClaimedPublication, CreatePublication, Publication
from app.insights.scoring import EventScorer
from app.models.generated_content_record import GeneratedContentRecord
from app.models.market_event_record import MarketEventRecord
from app.models.offer import Offer
from app.models.price_snapshot_record import PriceSnapshotRecord
from app.models.publication_record import PublicationRecord
from app.parsers.ggsel_extractor import GGSelExtractor
from app.parsers.ggsel_fetcher import GGSelFetcher
from app.parsers.models import ParsedOffer
from app.parsers.normalizers import OfferNormalizer
from app.repositories.postgres import (
    PostgresMarketEventRepository,
    PostgresPriceHistoryRepository,
    PostgresPublicationRepository,
)
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.scheduler import (
    GGSELJob,
    JobExecutionState,
    MarketEventScoringJob,
    PendingContentGenerationJob,
    SchedulerService,
    StaleContentClaimRecoveryJob,
    StalePublicationClaimRecoveryJob,
    StaleScoringClaimRecoveryJob,
)
from app.services.content_generator import ContentGenerator
from app.services.event_builder import EventBuilder
from app.services.marketplace_application_runner import MarketplaceApplicationRunner
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.publication_intents import PublicationIntentService
from app.services.repository_scope import RepositoryScopeFactory
from scripts import verify_epic13_content_publication_postgres as content_verification
from scripts import verify_epic13_event_processing_postgres as event_verification
from scripts import verify_epic13_ingestion_postgres as ingestion_verification
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    uuid_for,
)

DATABASE_URL_ENV = "EPIC13_DATABASE_URL"
EXPECTED_REVISION = "0008_content_publications"


class Verification(
    ingestion_verification.Verification,
    event_verification.Verification,
    content_verification.Verification,
):
    """Shared counter accepted by all focused EPIC 13 verifier functions."""


@dataclass(slots=True, frozen=True)
class HappyPathState:
    """Stable identities retained across final verification stages."""

    event_id: UUID
    event_identity: str
    content_id: UUID
    content_identity: str
    publication_id: UUID
    publication_identity: str


@dataclass(slots=True)
class TransactionTracker:
    """Expose whether a repository transaction scope is currently active."""

    active: int = 0


class AddThenFailSnapshotRepository(PostgresPriceHistoryRepository):
    """Persist a snapshot inside the scope, then force outer rollback."""

    async def add(self, snapshot: PriceSnapshot) -> bool:
        """Execute the real insert before raising a controlled failure."""
        await super().add(snapshot)
        msg = "controlled snapshot persistence failure"
        raise RuntimeError(msg)


class AddThenFailEventRepository(PostgresMarketEventRepository):
    """Persist an event inside the scope, then force outer rollback."""

    async def add_idempotently(
        self,
        candidate: MarketEventCandidate,
    ) -> EventAddResult:
        """Execute the real insert before raising a controlled failure."""
        await super().add_idempotently(candidate)
        msg = "controlled event persistence failure"
        raise RuntimeError(msg)


def postgres_scope_factory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    failure: str | None = None,
    tracker: TransactionTracker | None = None,
) -> RepositoryScopeFactory:
    """Create a shared-session scope with optional rollback injection."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[RepositoryProvider]:
        async with session_factory() as session, session.begin():
            if tracker is not None:
                tracker.active += 1
            try:
                repositories = create_postgres_provider(session)
                if failure == "snapshot":
                    repositories.price_history = AddThenFailSnapshotRepository(session)
                elif failure == "event":
                    repositories.events = AddThenFailEventRepository(session)
                yield repositories
                if failure == "commit":
                    msg = "controlled commit failure"
                    raise RuntimeError(msg)
            finally:
                if tracker is not None:
                    tracker.active -= 1

    return scope


def make_offer(price: Decimal, *, external_id: str = "epic13-final") -> ParsedOffer:
    """Build deterministic complete marketplace input."""
    return ParsedOffer(
        marketplace="ggsel",
        external_id=external_id,
        title="Minecraft Premium",
        url=f"https://example.com/ggsel/{external_id}",
        price=price,
        currency="RUB",
        seller_name="Verification Seller",
    )


def make_runner(
    *,
    offer: ParsedOffer,
    collected_at_offset: timedelta,
    scope_factory: RepositoryScopeFactory,
    ingestion_scope_states: list[int] | None = None,
    transaction_tracker: TransactionTracker | None = None,
) -> MarketplaceApplicationRunner:
    """Compose the real ingestion runner around deterministic prepared input."""

    async def ingestion(url: str) -> Sequence[ParsedOffer]:
        del url
        if ingestion_scope_states is not None:
            active = transaction_tracker.active if transaction_tracker else 0
            ingestion_scope_states.append(active)
        return (offer,)

    pipeline = MarketplacePipeline(
        fetcher=cast(GGSelFetcher, object()),
        extractor=GGSelExtractor(),
        normalizer=OfferNormalizer("ggsel"),
        snapshot_builder=ingestion_verification.FixedSnapshotBuilder(
            NOW + collected_at_offset
        ),
        price_change_detector=PriceChangeDetector(),
        event_builder=EventBuilder(),
        event_scorer=EventScorer(),
        content_generator=ContentGenerator(FakeAIProvider()),
    )
    return MarketplaceApplicationRunner(
        marketplace=Marketplace.GGSEL,
        ingestion=ingestion,
        repository_scope_factory=scope_factory,
        pipeline=pipeline,
    )


async def recreate_schema(database_url: str) -> None:
    """Recreate public schema only in the guarded isolated database."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def reset_data(engine: AsyncEngine) -> None:
    """Clear all active persistence rows while retaining the migrated schema."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE publications, generated_contents, market_events, "
                "offers, price_snapshots, canonical_products "
                "RESTART IDENTITY CASCADE"
            )
        )


async def table_count(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[Offer]
    | type[PriceSnapshotRecord]
    | type[MarketEventRecord]
    | type[GeneratedContentRecord]
    | type[PublicationRecord],
) -> int:
    """Count records in one known persistence table."""
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def load_event(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: UUID,
) -> PriceDropMarketEvent:
    """Load one durable event through its repository mapping."""
    async with session_factory() as session:
        event = await create_postgres_provider(session).events.get_by_id(event_id)
    if event is None:
        raise content_verification.VerificationError(f"event {event_id} is missing")
    return event


async def load_content_and_publications(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: UUID,
) -> tuple[tuple[GeneratedContentAttempt, ...], tuple[Publication, ...]]:
    """Load durable downstream work through fresh repository instances."""
    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        return (
            tuple(await repositories.generated_contents.list_for_event(event_id)),
            tuple(await repositories.publications.list_for_event(event_id)),
        )


async def verify_environment(
    verification: Verification,
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Inspect live PostgreSQL version, revision, schema, and isolation mode."""
    async with engine.connect() as connection:
        database = await connection.scalar(text("SELECT current_database()"))
        version = await connection.scalar(text("SHOW server_version"))
        isolation = await connection.scalar(text("SHOW transaction_isolation"))
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        tables = set(
            (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).scalars()
        )
        constraints = set(
            (
                await connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conrelid IN "
                        "('market_events'::regclass, 'generated_contents'::regclass, "
                        "'publications'::regclass)"
                    )
                )
            ).scalars()
        )
        indexes = set(
            (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
                        "AND tablename IN "
                        "('market_events', 'generated_contents', 'publications')"
                    )
                )
            ).scalars()
        )
    url = make_url(database_url)
    print(f"PostgreSQL: {version}")
    print(f"Connection: {url.host or 'localhost'}:{url.port or 5432}/{database}")
    print(f"Isolation: {isolation}")
    print(f"Alembic revision: {revision}")
    verification.check(
        "isolated PostgreSQL database and expected revision",
        str(database).startswith("epic13_") and revision == EXPECTED_REVISION,
    )
    verification.check(
        "EPIC 13 tables exist",
        {"market_events", "generated_contents", "publications"} <= tables,
    )
    verification.check(
        "EPIC 13 identity and lifecycle constraints exist",
        {
            "uq_market_events_identity_key",
            "ck_market_events_claim_state",
            "uq_generated_contents_idempotency_key",
            "ck_generated_contents_claim_state",
            "uq_publications_idempotency_key",
            "ck_publications_claim_state",
        }
        <= constraints,
    )
    verification.check(
        "EPIC 13 claim and idempotency indexes exist",
        {
            "uq_market_events_snapshot_transition",
            "ix_market_events_scoring_claim",
            "uq_generated_contents_active_generation",
            "ix_generated_contents_claim",
            "ix_publications_claim",
            "ix_publications_lease_expiry",
        }
        <= indexes,
    )
    verification.check(
        "PostgreSQL uses read committed transaction isolation",
        isolation == "read committed",
    )


async def verify_complete_workflow(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> HappyPathState:
    """Run ingestion through durable publication intent with fresh services."""
    await reset_data(engine)
    transaction_tracker = TransactionTracker()
    scope_factory = postgres_scope_factory(
        session_factory,
        tracker=transaction_tracker,
    )
    ingestion_states: list[int] = []
    first = await make_runner(
        offer=make_offer(Decimal("990.00")),
        collected_at_offset=timedelta(0),
        scope_factory=scope_factory,
        ingestion_scope_states=ingestion_states,
        transaction_tracker=transaction_tracker,
    ).run("prepared://first-observation")
    verification.check(
        "first observation persists one offer and one snapshot",
        first.persistence_committed
        and first.events_created == 0
        and await table_count(session_factory, Offer) == 1
        and await table_count(session_factory, PriceSnapshotRecord) == 1,
    )

    second = await make_runner(
        offer=make_offer(Decimal("790.00")),
        collected_at_offset=timedelta(minutes=1),
        scope_factory=scope_factory,
        ingestion_scope_states=ingestion_states,
        transaction_tracker=transaction_tracker,
    ).run("prepared://price-drop")
    verification.check(
        "second observation creates one deterministic market event",
        second.events_created == 1
        and second.price_changes_detected == 1
        and await table_count(session_factory, PriceSnapshotRecord) == 2
        and await table_count(session_factory, MarketEventRecord) == 1,
    )
    event_id = second.event_ids[0]
    event_after_ingestion = await load_event(session_factory, event_id)
    verification.check(
        "ingestion commit survives a fresh session",
        event_after_ingestion.scoring_status is ScoringStatus.PENDING,
    )

    scoring_scopes = event_verification.ScopeTracker(session_factory)
    scorer = event_verification.ScopeAssertingScorer(scoring_scopes)
    scoring_service = event_verification.make_service(
        session_factory,
        scorer,
        scope_factory=scoring_scopes.factory(),
    )
    scoring = await scoring_service.process_pending(
        worker_id="final-scoring-worker",
        limit=1,
        now=NOW + timedelta(minutes=10),
    )
    scored_event = await load_event(session_factory, event_id)
    verification.check(
        "fresh scoring service claims and persists one score",
        scoring.scored == 1
        and scorer.calls == 1
        and scored_event.scoring_status is ScoringStatus.SUCCEEDED
        and scored_event.score is not None,
    )

    content_scopes = content_verification.TrackedScopes(session_factory)
    claim_visible = False

    async def inspect_content_claim() -> None:
        nonlocal claim_visible
        contents, _ = await load_content_and_publications(
            session_factory,
            event_id,
        )
        claim_visible = (
            len(contents) == 1
            and contents[0].generation_status is ContentGenerationStatus.IN_PROGRESS
            and contents[0].claim is not None
        )

    provider = content_verification.DeterministicProvider(
        content_scopes,
        ["Verified deterministic publication content"],
        on_call=inspect_content_claim,
    )
    content_service = content_verification.make_content_service(
        content_scopes,
        provider,
    )
    generated = await content_service.process_pending(
        worker_id="final-content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    contents, publications = await load_content_and_publications(
        session_factory,
        event_id,
    )
    verification.check(
        "content claim commits before fake AI executes",
        claim_visible,
    )
    verification.check(
        "generated content and publication intent commit atomically",
        generated.generated == 1
        and generated.publications_created == 1
        and len(contents) == len(publications) == 1,
    )

    async with session_factory() as session:
        repositories = create_postgres_provider(session)
        offers = tuple(await repositories.offers.list_all())
        history = tuple(
            await repositories.price_history.get_history("ggsel", "epic13-final")
        )
        final_event = await repositories.events.get_by_id(event_id)
    verification.check(
        "offer snapshots event content and publication are exactly linked",
        len(offers) == 1
        and len(history) == 2
        and final_event is not None
        and final_event.previous_snapshot.collected_at == history[0].collected_at
        and final_event.current_snapshot.collected_at == history[1].collected_at
        and contents[0].event_id == final_event.id
        and publications[0].event_id == final_event.id
        and publications[0].content_id == contents[0].id,
    )
    verification.check(
        "application boundaries expose domain DTOs rather than ORM records",
        isinstance(offers[0], ParsedOffer)
        and isinstance(history[0], PriceSnapshot)
        and isinstance(final_event, MarketEvent)
        and isinstance(contents[0], GeneratedContentAttempt)
        and isinstance(publications[0], Publication),
    )
    verification.check(
        "fetch scoring and AI boundaries run outside repository transactions",
        ingestion_states == [0, 0]
        and scoring_scopes.active == 0
        and content_scopes.active == 0
        and provider.scope_states == [0],
    )

    replay = await make_runner(
        offer=make_offer(Decimal("790.00")),
        collected_at_offset=timedelta(minutes=1),
        scope_factory=postgres_scope_factory(session_factory),
    ).run("prepared://idempotent-restart")
    repeated_scoring = await event_verification.make_service(
        session_factory,
        EventScorer(),
    ).process_pending(
        worker_id="restart-scoring-worker",
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    repeated_scopes = content_verification.TrackedScopes(session_factory)
    repeated_ai = content_verification.DeterministicProvider(
        repeated_scopes,
        ["must not execute"],
    )
    repeated_content = await content_verification.make_content_service(
        repeated_scopes,
        repeated_ai,
    ).process_pending(
        worker_id="restart-content-worker",
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    reloaded_event = await load_event(session_factory, event_id)
    reloaded_contents, reloaded_publications = await load_content_and_publications(
        session_factory,
        event_id,
    )
    verification.check(
        "idempotent restart creates no duplicate event content or publication",
        replay.event_candidates_built == 0
        and repeated_scoring.claimed == 0
        and repeated_content.claimed == 0
        and repeated_ai.calls == 0
        and len(reloaded_contents) == len(reloaded_publications) == 1,
    )
    verification.check(
        "event content and publication identity keys survive restart",
        reloaded_event.identity_key == event_after_ingestion.identity_key
        and reloaded_contents[0].idempotency_key == contents[0].idempotency_key
        and reloaded_publications[0].idempotency_key == publications[0].idempotency_key,
    )
    verification.check(
        "no external delivery occurs",
        reloaded_publications[0].status is PublicationStatus.PENDING
        and reloaded_publications[0].external_message_id is None,
    )
    return HappyPathState(
        event_id=event_id,
        event_identity=reloaded_event.identity_key,
        content_id=reloaded_contents[0].id,
        content_identity=reloaded_contents[0].idempotency_key,
        publication_id=reloaded_publications[0].id,
        publication_identity=reloaded_publications[0].idempotency_key,
    )


async def verify_ingestion_failures(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify snapshot, event, and commit failures cannot leak partial work."""
    for failure in ("snapshot", "event", "commit"):
        await reset_data(engine)
        baseline = make_offer(Decimal("990.00"), external_id=f"failure-{failure}")
        await ingestion_verification.seed_snapshot(session_factory, baseline, NOW)
        try:
            await make_runner(
                offer=make_offer(
                    Decimal("790.00"),
                    external_id=f"failure-{failure}",
                ),
                collected_at_offset=timedelta(minutes=1),
                scope_factory=postgres_scope_factory(
                    session_factory,
                    failure=failure,
                ),
            ).run(f"prepared://{failure}-failure")
        except RuntimeError as exc:
            if "controlled" not in str(exc):
                raise
        else:
            raise ingestion_verification.VerificationError(
                f"{failure} failure was not raised"
            )

        async with session_factory() as session:
            eligible = await create_postgres_provider(
                session
            ).events.list_content_eligible(10)
        verification.check(
            f"{failure} failure rolls back current ingestion work",
            await table_count(session_factory, Offer) == 0
            and await table_count(session_factory, PriceSnapshotRecord) == 1
            and await table_count(session_factory, MarketEventRecord) == 0
            and eligible == (),
        )

        if failure == "commit":
            retry = await make_runner(
                offer=make_offer(
                    Decimal("790.00"),
                    external_id="failure-commit",
                ),
                collected_at_offset=timedelta(minutes=1),
                scope_factory=postgres_scope_factory(session_factory),
            ).run("prepared://commit-retry")
            verification.check(
                "fresh-session retry succeeds after commit failure",
                retry.events_created == 1 and retry.persistence_committed,
            )


async def verify_scoring_crash_recovery(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify restart after a scoring claim and stale worker rejection."""
    await reset_data(engine)
    event = await event_verification.seed_event(session_factory)
    claimed_at = NOW + timedelta(minutes=10)
    lease_until = claimed_at + timedelta(minutes=1)
    async with session_factory() as session, session.begin():
        old_claim = (
            await create_postgres_provider(session).events.claim_pending(
                claimed_at,
                "crashed-scoring-worker",
                lease_until,
                1,
            )
        )[0]

    blocked = await event_verification.make_service(
        session_factory,
        EventScorer(),
    ).process_pending(
        worker_id="blocked-scoring-worker",
        limit=1,
        now=claimed_at + timedelta(seconds=30),
    )
    recovery_service = event_verification.make_service(
        session_factory,
        EventScorer(),
    )
    recovered = await recovery_service.recover_stale_scoring_claims(
        limit=1,
        now=lease_until,
    )
    async with session_factory() as session, session.begin():
        stale = await create_postgres_provider(session).events.mark_scored(
            event.id,
            old_claim.claim.token,
            old_claim.event.version,
            60,
            lease_until + timedelta(seconds=1),
        )
    completed = await event_verification.make_service(
        session_factory,
        EventScorer(),
    ).process_pending(
        worker_id="replacement-scoring-worker",
        limit=1,
        now=lease_until + timedelta(seconds=5),
    )
    stored = await load_event(session_factory, event.id)
    verification.check(
        "scoring claim survives restart and active lease blocks another worker",
        blocked.claimed == 0,
    )
    verification.check(
        "expired scoring claim recovers and stale worker loses authority",
        recovered.recovered == 1
        and stale.outcome is not StateTransitionOutcome.APPLIED,
    )
    verification.check(
        "replacement scoring worker completes safely",
        completed.scored == 1
        and stored.scoring_status is ScoringStatus.SUCCEEDED
        and stored.scoring_attempt_count == 2,
    )


async def verify_content_crash_and_atomic_retry(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify content claim restart, atomic rollback, and a new safe attempt."""
    await reset_data(engine)
    event = await content_verification.seed_scored_event(session_factory)
    command_to_claim = CreateContentAttempt(
        id=uuid_for(70_001),
        event_id=event.id,
        content_type="telegram_post",
        language="ru",
        prompt_version="price_drop_v1",
        attempt_number=1,
        provider="fake",
        model="deterministic",
        created_at=NOW + timedelta(minutes=20),
    )
    async with session_factory() as session, session.begin():
        repository = create_postgres_provider(session).generated_contents
        await repository.create_attempt(command_to_claim)
        old_claim = (
            await repository.claim_pending(
                NOW + timedelta(minutes=20),
                "crashed-content-worker",
                NOW + timedelta(minutes=21),
                1,
            )
        )[0]

    blocked_scopes = content_verification.TrackedScopes(session_factory)
    blocked_ai = content_verification.DeterministicProvider(
        blocked_scopes,
        ["must not execute"],
    )
    blocked = await content_verification.make_content_service(
        blocked_scopes,
        blocked_ai,
    ).process_pending(
        worker_id="blocked-content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20, seconds=30),
    )
    recovery_scopes = content_verification.TrackedScopes(session_factory)
    recovery_service = content_verification.make_content_service(
        recovery_scopes,
        content_verification.DeterministicProvider(recovery_scopes, []),
    )
    recovered = await recovery_service.recover_stale_generation_claims(
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    async with session_factory() as session, session.begin():
        stale = await create_postgres_provider(
            session
        ).generated_contents.complete_attempt(
            command_to_claim.id,
            old_claim.claim.token,
            old_claim.content.version,
            "stale worker output",
            calculate_content_checksum("stale worker output"),
            NOW + timedelta(minutes=21, seconds=1),
        )
    replacement_scopes = content_verification.TrackedScopes(session_factory)
    replacement = await content_verification.make_content_service(
        replacement_scopes,
        content_verification.DeterministicProvider(
            replacement_scopes,
            ["replacement content"],
        ),
    ).process_pending(
        worker_id="replacement-content-worker",
        limit=1,
        now=NOW + timedelta(minutes=21),
    )
    contents, publications = await load_content_and_publications(
        session_factory,
        event.id,
    )
    verification.check(
        "content claim survives restart and active lease blocks another worker",
        blocked.claimed == 0 and blocked_ai.calls == 0,
    )
    verification.check(
        "expired content claim is abandoned and stale completion is rejected",
        recovered.abandoned == 1
        and stale.outcome is not StateTransitionOutcome.APPLIED,
    )
    verification.check(
        "replacement content attempt succeeds with immutable history",
        replacement.generated == 1
        and tuple(item.attempt_number for item in contents) == (1, 2)
        and contents[0].generation_status is ContentGenerationStatus.ABANDONED
        and contents[1].generation_status is ContentGenerationStatus.GENERATED
        and len(publications) == 1,
    )

    await reset_data(engine)
    event = await content_verification.seed_scored_event(session_factory)
    rollback_scopes = content_verification.TrackedScopes(
        session_factory,
        fail_on_exit_entry=2,
    )
    rolled_back = await content_verification.make_content_service(
        rollback_scopes,
        content_verification.DeterministicProvider(
            rollback_scopes,
            ["transaction rollback output"],
        ),
    ).process_pending(
        worker_id="completion-rollback-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    (
        rolled_back_contents,
        rolled_back_publications,
    ) = await load_content_and_publications(session_factory, event.id)
    verification.check(
        "content completion failure rolls back publication intent atomically",
        rolled_back.errors == 1
        and rolled_back_contents[0].generation_status
        is ContentGenerationStatus.IN_PROGRESS
        and rolled_back_contents[0].content_text is None
        and rolled_back_publications == (),
    )
    recovery_scopes = content_verification.TrackedScopes(session_factory)
    recovery_service = content_verification.make_content_service(
        recovery_scopes,
        content_verification.DeterministicProvider(recovery_scopes, []),
    )
    await recovery_service.recover_stale_generation_claims(
        limit=1,
        now=NOW + timedelta(minutes=22),
    )
    retry_scopes = content_verification.TrackedScopes(session_factory)
    retry = await content_verification.make_content_service(
        retry_scopes,
        content_verification.DeterministicProvider(
            retry_scopes,
            ["post-rollback retry"],
        ),
    ).process_pending(
        worker_id="post-rollback-worker",
        limit=1,
        now=NOW + timedelta(minutes=22),
    )
    retry_contents, retry_publications = await load_content_and_publications(
        session_factory,
        event.id,
    )
    verification.check(
        "completion rollback remains recoverable without false success",
        retry.generated == 1
        and tuple(item.attempt_number for item in retry_contents) == (1, 2)
        and len(retry_publications) == 1,
    )


async def verify_permanent_content_failure(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify invalid generated output is terminal and cannot publish."""
    await reset_data(engine)
    event = await content_verification.seed_scored_event(session_factory)
    scopes = content_verification.TrackedScopes(session_factory)
    service = content_verification.make_content_service(
        scopes,
        content_verification.DeterministicProvider(scopes, ["   "]),
    )
    failed = await service.process_pending(
        worker_id="permanent-content-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    repeated = await service.process_pending(
        worker_id="permanent-content-worker",
        limit=1,
        now=NOW + timedelta(days=1),
    )
    contents, publications = await load_content_and_publications(
        session_factory,
        event.id,
    )
    stored_event = await load_event(session_factory, event.id)
    verification.check(
        "permanent content failure is terminal and creates no publication",
        failed.items[0].next_retry_at is None
        and repeated.claimed == 0
        and contents[0].generation_status is ContentGenerationStatus.FAILED
        and publications == ()
        and stored_event.scoring_status is ScoringStatus.SUCCEEDED,
    )


async def verify_publication_lifecycle(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify claim contention, terminal publish, cancel, and idempotency."""
    await reset_data(engine)
    event = await content_verification.seed_scored_event(session_factory)
    scopes = content_verification.TrackedScopes(session_factory)
    await content_verification.make_content_service(
        scopes,
        content_verification.DeterministicProvider(scopes, ["publication source"]),
    ).process_pending(
        worker_id="publication-source-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    contents, publications = await load_content_and_publications(
        session_factory,
        event.id,
    )
    pending = publications[0]

    async def claim(worker: str, token_start: int) -> tuple[ClaimedPublication, ...]:
        async with session_factory() as session, session.begin():
            repository = PostgresPublicationRepository(
                session,
                claim_token_factory=SequentialUuidFactory(token_start),
            )
            return tuple(
                await repository.claim_pending(
                    NOW + timedelta(minutes=21),
                    worker,
                    NOW + timedelta(minutes=22),
                    1,
                )
            )

    first, second = await asyncio.gather(
        claim("publication-worker-one", 80_000),
        claim("publication-worker-two", 81_000),
    )
    claimed = first or second
    async with session_factory() as session, session.begin():
        repository = PostgresPublicationRepository(session)
        blocked = await repository.claim_pending(
            NOW + timedelta(minutes=21, seconds=30),
            "publication-worker-three",
            NOW + timedelta(minutes=23),
            1,
        )
        winner = claimed[0]
        published = await repository.mark_published(
            pending.id,
            winner.claim.token,
            winner.publication.version,
            "verification-message-id",
            NOW + timedelta(minutes=21, seconds=31),
        )
    async with session_factory() as session, session.begin():
        repository = PostgresPublicationRepository(session)
        terminal_cancel = await repository.cancel(
            pending.id,
            NOW + timedelta(minutes=22),
            published.version or 1,
        )
    verification.check(
        "two publication workers have one claim owner and active lease is protected",
        len(first) + len(second) == 1 and blocked == (),
    )
    verification.check(
        "repository-confirmed published state is terminal",
        published.outcome is StateTransitionOutcome.APPLIED
        and terminal_cancel.outcome is not StateTransitionOutcome.APPLIED,
    )

    cancel_command = CreatePublication(
        id=uuid_for(80_010),
        event_id=event.id,
        content_id=contents[0].id,
        channel="preview",
        destination_key="cancel-verification",
        created_at=NOW + timedelta(minutes=22),
    )
    duplicate_command = CreatePublication(
        id=uuid_for(80_011),
        event_id=event.id,
        content_id=contents[0].id,
        channel="preview",
        destination_key="cancel-verification",
        created_at=NOW + timedelta(minutes=23),
    )
    async with session_factory() as session, session.begin():
        repository = PostgresPublicationRepository(session)
        created = await repository.create_idempotently(cancel_command)
        duplicate = await repository.create_idempotently(duplicate_command)
        cancelled = await repository.cancel(
            created.publication.id,
            NOW + timedelta(minutes=24),
            created.publication.version,
        )
    verification.check(
        "publication cancellation and logical idempotency are valid",
        created.created
        and not duplicate.created
        and duplicate.publication.id == created.publication.id
        and cancelled.outcome is StateTransitionOutcome.APPLIED,
    )


async def verify_audit_trail(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify successful and failed processing remains explainable."""
    await reset_data(engine)
    event = await content_verification.seed_scored_event(session_factory)
    failed_scopes = content_verification.TrackedScopes(session_factory)
    await content_verification.make_content_service(
        failed_scopes,
        content_verification.DeterministicProvider(
            failed_scopes,
            [RuntimeError("secret provider detail")],
        ),
    ).process_pending(
        worker_id="audit-failure-worker",
        limit=1,
        now=NOW + timedelta(minutes=20),
    )
    success_scopes = content_verification.TrackedScopes(session_factory)
    await content_verification.make_content_service(
        success_scopes,
        content_verification.DeterministicProvider(
            success_scopes,
            ["auditable generated text"],
        ),
    ).process_pending(
        worker_id="audit-success-worker",
        limit=1,
        now=NOW + timedelta(minutes=20, seconds=5),
    )
    stored_event = await load_event(session_factory, event.id)
    contents, publications = await load_content_and_publications(
        session_factory,
        event.id,
    )
    verification.check(
        "audit trail retains observation identity prices score and attempt history",
        stored_event.previous_snapshot.price == Decimal("1000.00")
        and stored_event.current_snapshot.price == Decimal("800.00")
        and stored_event.identity_key == event.identity_key
        and stored_event.score == 80
        and tuple(item.attempt_number for item in contents) == (1, 2),
    )
    verification.check(
        "audit trail retains safe generation metadata checksum retry and publication",
        contents[0].last_error is not None
        and "secret" not in contents[0].last_error.summary
        and contents[0].next_retry_at == NOW + timedelta(minutes=20, seconds=5)
        and contents[1].provider == "fake"
        and contents[1].model == "deterministic"
        and contents[1].prompt_version == "price_drop_v1"
        and contents[1].content_checksum
        == calculate_content_checksum("auditable generated text")
        and len(publications) == 1
        and publications[0].status is PublicationStatus.PENDING,
    )


async def verify_scheduler_sequence(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run ingestion, scoring, content, and recovery jobs in one Scheduler."""
    await reset_data(engine)
    scheduler = SchedulerService()
    scheduler.start()
    try:
        first_runner = make_runner(
            offer=make_offer(Decimal("990.00"), external_id="scheduler-final"),
            collected_at_offset=timedelta(0),
            scope_factory=postgres_scope_factory(session_factory),
        )
        scheduler.register_job(GGSELJob(first_runner, url="prepared://scheduler-first"))
        await scheduler.execute_job("ggsel")

        drop_runner = make_runner(
            offer=make_offer(Decimal("790.00"), external_id="scheduler-final"),
            collected_at_offset=timedelta(minutes=1),
            scope_factory=postgres_scope_factory(session_factory),
        )
        scheduler.register_job(GGSELJob(drop_runner, url="prepared://scheduler-drop"))
        await scheduler.execute_job("ggsel")

        event_service = event_verification.make_service(
            session_factory,
            EventScorer(),
        )
        content_scopes = content_verification.TrackedScopes(session_factory)
        content_service = content_verification.make_content_service(
            content_scopes,
            content_verification.DeterministicProvider(
                content_scopes,
                ["scheduler end-to-end content"],
            ),
        )
        publication_service = PublicationIntentService(
            repository_scope_factory=content_scopes.factory()
        )
        jobs = (
            MarketEventScoringJob(
                event_service,
                worker_id="scheduler-scoring-worker",
                batch_size=10,
                clock=lambda: NOW + timedelta(minutes=10),
            ),
            StaleScoringClaimRecoveryJob(
                event_service,
                batch_size=10,
                clock=lambda: NOW + timedelta(minutes=11),
            ),
            PendingContentGenerationJob(
                content_service,
                worker_id="scheduler-content-worker",
                batch_size=10,
                clock=lambda: NOW + timedelta(minutes=20),
            ),
            StaleContentClaimRecoveryJob(
                content_service,
                batch_size=10,
                clock=lambda: NOW + timedelta(minutes=22),
            ),
            StalePublicationClaimRecoveryJob(
                publication_service,
                batch_size=10,
                clock=lambda: NOW + timedelta(minutes=22),
            ),
        )
        for job in jobs:
            scheduler.register_job(job)
            await scheduler.execute_job(job.name)
    finally:
        await scheduler.stop()

    async with session_factory() as session:
        event_id = await session.scalar(select(MarketEventRecord.id))
    if event_id is None:
        raise event_verification.VerificationError("Scheduler event is missing")
    event = await load_event(session_factory, event_id)
    contents, publications = await load_content_and_publications(
        session_factory,
        event_id,
    )
    verification.check(
        "Scheduler executes ingestion scoring content and recovery jobs in sequence",
        event.scoring_status is ScoringStatus.SUCCEEDED
        and len(contents) == len(publications) == 1
        and all(
            scheduler.get_status(name).state is JobExecutionState.SUCCEEDED
            for name in (
                "ggsel",
                "market-event-scoring",
                "stale-scoring-claim-recovery",
                "pending-content-generation",
                "stale-content-claim-recovery",
                "stale-publication-claim-recovery",
            )
        ),
    )
    job_source = "\n".join(
        inspect.getsource(job_type)
        for job_type in (
            MarketEventScoringJob,
            StaleScoringClaimRecoveryJob,
            PendingContentGenerationJob,
            StaleContentClaimRecoveryJob,
            StalePublicationClaimRecoveryJob,
        )
    )
    verification.check(
        "Scheduler jobs remain orchestration-only",
        "sqlalchemy" not in job_source.lower()
        and "create_postgres_provider" not in job_source
        and "mark_scored(" not in job_source
        and "mark_ambiguous(" not in job_source
        and "generate(" not in job_source,
    )


async def verify_legacy_cleanup(verification: Verification) -> None:
    """Confirm one detector, event identity, and durable content path remain."""
    application_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "app").rglob("*.py")
    )
    verification.check(
        "legacy detector and inactive event hierarchy remain removed",
        not (ROOT / "app/analytics/price_change_detector.py").exists()
        and not (ROOT / "app/core/events.py").exists()
        and "app.analytics.price_change_detector" not in application_sources
        and "app.core.events" not in application_sources,
    )
    verification.check(
        "one active detector identity and durable content path remain",
        PriceChangeDetector.__module__ == "app.analytics.price_change"
        and not hasattr(MarketplacePipeline, "process_after_commit")
        and application_sources.count("def build_event_identity(") == 1,
    )


async def verify_focused_suites(
    verification: Verification,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reuse focused live suites for all lifecycle and concurrency variants."""
    await ingestion_verification.verify_shared_session(
        verification,
        session_factory,
    )
    await ingestion_verification.verify_ingestion(
        verification,
        engine,
        session_factory,
    )
    await ingestion_verification.verify_rollback(
        verification,
        engine,
        session_factory,
    )
    await ingestion_verification.verify_marketplace_isolation(
        verification,
        engine,
        session_factory,
    )
    await ingestion_verification.verify_content_boundary(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_success(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_concurrency(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_retry(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_recovery_job(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_permanent_failure(
        verification,
        engine,
        session_factory,
    )
    await event_verification.verify_scoring_job(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_success_and_idempotency(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_retry(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_concurrency(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_completion_rollback(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_recovery_jobs(
        verification,
        engine,
        session_factory,
    )
    await content_verification.verify_generation_job(
        verification,
        engine,
        session_factory,
    )


async def run_verification(database_url: str) -> None:
    """Run the complete final EPIC 13 verification."""
    verification = Verification()
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await verify_environment(verification, engine, database_url)
        happy_path = await verify_complete_workflow(
            verification,
            engine,
            session_factory,
        )
        verification.check(
            "happy-path stable identities are populated",
            all(
                (
                    happy_path.event_identity,
                    happy_path.content_identity,
                    happy_path.publication_identity,
                )
            ),
        )
        await verify_ingestion_failures(verification, engine, session_factory)
        await verify_scoring_crash_recovery(
            verification,
            engine,
            session_factory,
        )
        await verify_content_crash_and_atomic_retry(
            verification,
            engine,
            session_factory,
        )
        await verify_permanent_content_failure(
            verification,
            engine,
            session_factory,
        )
        await verify_publication_lifecycle(
            verification,
            engine,
            session_factory,
        )
        await verify_audit_trail(verification, engine, session_factory)
        await verify_scheduler_sequence(verification, engine, session_factory)
        await verify_focused_suites(verification, engine, session_factory)
        await verify_legacy_cleanup(verification)
        await reset_data(engine)
        print(f"Checks passed: {verification.passed}")
        print("EPIC 13 STATUS: verified and complete")
        print("SUCCESS")
    finally:
        await engine.dispose()


def migrate_and_check(database_url: str) -> None:
    """Apply, downgrade, re-apply, and compare all migrations."""
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "0007_create_market_events")
    command.upgrade(config, "head")
    command.check(config)


def main() -> None:
    """Guard isolation, rebuild schema, migrate, and run verification."""
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        raise SystemExit(
            f"Set {DATABASE_URL_ENV} to an isolated PostgreSQL test database."
        )
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql" or not database_name.startswith(
        "epic13_"
    ):
        raise SystemExit(
            f"{DATABASE_URL_ENV} must target an isolated epic13_* PostgreSQL database."
        )
    asyncio.run(recreate_schema(database_url))
    migrate_and_check(database_url)
    asyncio.run(run_verification(database_url))


if __name__ == "__main__":
    main()
