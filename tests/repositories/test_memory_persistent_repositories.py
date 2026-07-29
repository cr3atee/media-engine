from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from app.domain.lifecycle import ContentGenerationStatus
from app.domain.market_events import MarketEventCandidate
from app.domain.processing import StateTransitionOutcome
from app.repositories.memory import (
    MemoryGeneratedContentRepository,
    MemoryMarketEventRepository,
    MemoryPublicationRepository,
)
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_content_command,
    make_event,
    make_publication_command,
    run_async,
    uuid_for,
)
from tests.repositories.contracts.persistent import (
    GeneratedContentRepositoryContract,
    MarketEventRepositoryContract,
    PublicationRepositoryContract,
)


class TestMemoryMarketEventRepository(MarketEventRepositoryContract):
    """Run the shared event contract against isolated memory storage."""

    def make_repository(self) -> MemoryMarketEventRepository:
        return MemoryMarketEventRepository(
            claim_token_factory=SequentialUuidFactory(20_000),
        )


class TestMemoryGeneratedContentRepository(GeneratedContentRepositoryContract):
    """Run the shared content contract against isolated memory storage."""

    def make_repository(self) -> MemoryGeneratedContentRepository:
        return MemoryGeneratedContentRepository(
            claim_token_factory=SequentialUuidFactory(30_000),
        )


class TestMemoryPublicationRepository(PublicationRepositoryContract):
    """Run the shared publication contract against isolated memory storage."""

    def make_repository(self) -> MemoryPublicationRepository:
        return MemoryPublicationRepository(
            claim_token_factory=SequentialUuidFactory(40_000),
        )


def test_memory_repository_instances_do_not_share_state() -> None:
    event_repositories = (
        MemoryMarketEventRepository(),
        MemoryMarketEventRepository(),
    )
    content_repositories = (
        MemoryGeneratedContentRepository(),
        MemoryGeneratedContentRepository(),
    )
    publication_repositories = (
        MemoryPublicationRepository(),
        MemoryPublicationRepository(),
    )
    event = make_event()
    content = make_content_command()
    publication = make_publication_command()

    run_async(
        event_repositories[0].add_idempotently(MarketEventCandidate(event=event)),
    )
    run_async(content_repositories[0].create_attempt(content))
    run_async(publication_repositories[0].create_idempotently(publication))

    assert run_async(event_repositories[1].get_by_id(event.id)) is None
    assert run_async(content_repositories[1].get_by_id(content.id)) is None
    assert run_async(publication_repositories[1].get_by_id(publication.id)) is None


def test_memory_list_results_are_immutable_snapshots() -> None:
    event_repository = MemoryMarketEventRepository()
    content_repository = MemoryGeneratedContentRepository()
    publication_repository = MemoryPublicationRepository()
    event = make_event()
    content = make_content_command()
    publication = make_publication_command()
    run_async(event_repository.add_idempotently(MarketEventCandidate(event=event)))
    run_async(content_repository.create_attempt(content))
    run_async(publication_repository.create_idempotently(publication))

    events = run_async(event_repository.list_pending(NOW + timedelta(hours=1), 10))
    contents = run_async(content_repository.list_for_event(content.event_id))
    publications = run_async(
        publication_repository.list_for_event(publication.event_id),
    )

    assert isinstance(events, tuple)
    assert isinstance(contents, tuple)
    assert isinstance(publications, tuple)
    with pytest.raises(FrozenInstanceError):
        events[0].version = 99
    stored = run_async(event_repository.get_by_id(event.id))
    assert stored is not None
    assert stored.version == 1


def test_memory_claim_token_factory_is_injectable() -> None:
    token = uuid_for(50_000)
    repository = MemoryMarketEventRepository(claim_token_factory=lambda: token)
    event = make_event()
    run_async(repository.add_idempotently(MarketEventCandidate(event=event)))

    claimed = run_async(
        repository.claim_pending(
            NOW + timedelta(minutes=10),
            "worker",
            NOW + timedelta(minutes=11),
            1,
        ),
    )

    assert claimed[0].claim.token == token


def test_memory_content_claim_can_be_released_as_abandoned() -> None:
    repository = MemoryGeneratedContentRepository(
        claim_token_factory=SequentialUuidFactory(60_000),
    )
    command = make_content_command()
    run_async(repository.create_attempt(command))
    claimed = run_async(
        repository.claim_pending(
            NOW + timedelta(minutes=10),
            "worker",
            NOW + timedelta(minutes=11),
            1,
        ),
    )[0]

    released = run_async(
        repository.release_claim(
            command.id,
            claimed.claim.token,
            claimed.content.version,
            NOW + timedelta(minutes=10, seconds=30),
        ),
    )
    stored = run_async(repository.get_by_id(command.id))

    assert released.outcome is StateTransitionOutcome.APPLIED
    assert stored is not None
    assert stored.generation_status is ContentGenerationStatus.ABANDONED


@pytest.mark.parametrize(
    "repository",
    [
        MemoryMarketEventRepository(),
        MemoryGeneratedContentRepository(),
        MemoryPublicationRepository(),
    ],
)
def test_memory_claim_operations_reject_naive_time(repository: object) -> None:
    naive_now = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        if isinstance(repository, MemoryMarketEventRepository):
            run_async(repository.claim_pending(naive_now, "worker", NOW, 1))
        elif isinstance(repository, MemoryGeneratedContentRepository):
            run_async(repository.claim_pending(naive_now, "worker", NOW, 1))
        else:
            assert isinstance(repository, MemoryPublicationRepository)
            run_async(repository.claim_pending(naive_now, "worker", NOW, 1))
