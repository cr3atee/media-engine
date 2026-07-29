from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.generated_content import calculate_content_checksum
from app.domain.lifecycle import (
    ContentGenerationStatus,
    ContentReviewStatus,
    EventDisposition,
    PublicationStatus,
    ScoringStatus,
)
from app.domain.market_events import (
    EventAddResult,
    MarketEventCandidate,
    PriceDropMarketEvent,
)
from app.domain.processing import (
    IdempotentCreateStatus,
    ProcessingError,
    StateTransitionOutcome,
)
from app.repositories import (
    GeneratedContentRepository,
    MarketEventRepository,
    PublicationRepository,
    RepositoryIdentityConflictError,
)
from tests.repositories.contracts.factories import (
    NOW,
    make_content_command,
    make_event,
    make_publication_command,
    run_async,
    uuid_for,
)


class MarketEventRepositoryContract:
    """Behavior every persistent market-event repository must satisfy."""

    def make_repository(self) -> MarketEventRepository:
        raise NotImplementedError

    def prepare_event(
        self,
        repository: MarketEventRepository,
        event: PriceDropMarketEvent,
    ) -> None:
        """Prepare implementation-specific event dependencies when required."""

    def add_event(
        self,
        repository: MarketEventRepository,
        event: PriceDropMarketEvent,
    ) -> EventAddResult:
        """Prepare and persist an event through the shared contract."""
        self.prepare_event(repository, event)
        return run_async(
            repository.add_idempotently(MarketEventCandidate(event=event)),
        )

    def test_event_create_is_idempotent_and_retrievable(self) -> None:
        repository = self.make_repository()
        event = make_event()
        duplicate = replace(
            event,
            id=uuid_for(999),
            created_at=event.created_at + timedelta(minutes=1),
        )

        created = self.add_event(repository, event)
        existing = self.add_event(repository, duplicate)

        assert created.status is IdempotentCreateStatus.CREATED
        assert created.created is True
        assert existing.status is IdempotentCreateStatus.EXISTING
        assert existing.created is False
        assert existing.event.id == event.id
        assert existing.event.created_at == event.created_at
        assert existing.identity_version == event.identity_version
        assert run_async(repository.get_by_id(event.id)) == event
        assert run_async(repository.get_by_identity(event.identity_key)) == event

    def test_event_identity_conflict_is_explicit(self) -> None:
        repository = self.make_repository()
        event = make_event()
        conflicting = replace(
            event,
            id=uuid_for(998),
            payload=replace(event.payload, title="Conflicting immutable title"),
        )
        self.add_event(repository, event)

        with pytest.raises(RepositoryIdentityConflictError):
            self.add_event(repository, conflicting)

        assert run_async(repository.get_by_identity(event.identity_key)) == event

    def test_event_pending_list_has_stable_readiness_order(self) -> None:
        repository = self.make_repository()
        occurred_at = NOW
        later_high_id = make_event(
            event_id=uuid_for(113),
            external_id="later-high",
            occurred_at=occurred_at,
            created_at=NOW + timedelta(seconds=5),
        )
        earliest = make_event(
            event_id=uuid_for(112),
            external_id="earliest",
            occurred_at=occurred_at,
            created_at=NOW + timedelta(seconds=3),
        )
        later_low_id = make_event(
            event_id=uuid_for(111),
            external_id="later-low",
            occurred_at=occurred_at,
            created_at=NOW + timedelta(seconds=5),
        )
        for event in (later_high_id, earliest, later_low_id):
            self.add_event(repository, event)

        pending = run_async(repository.list_pending(NOW + timedelta(minutes=1), 10))

        assert tuple(item.id for item in pending) == (
            earliest.id,
            later_low_id.id,
            later_high_id.id,
        )
        limited = run_async(
            repository.list_pending(NOW + timedelta(minutes=1), 2),
        )
        assert len(limited) == 2

    def test_event_claim_is_exclusive_and_expiry_requires_recovery(self) -> None:
        repository = self.make_repository()
        event = make_event()
        self.add_event(repository, event)
        claimed_at = NOW + timedelta(minutes=10)
        lease_until = claimed_at + timedelta(minutes=1)

        first = run_async(
            repository.claim_pending(claimed_at, "worker-one", lease_until, 1),
        )
        unavailable = run_async(
            repository.claim_pending(
                claimed_at + timedelta(seconds=30),
                "worker-two",
                lease_until + timedelta(minutes=1),
                1,
            ),
        )
        still_unavailable = run_async(
            repository.claim_pending(
                lease_until,
                "worker-two",
                lease_until + timedelta(minutes=1),
                1,
            ),
        )

        assert len(first) == 1
        assert first[0].claim.worker_id == "worker-one"
        assert first[0].event.version == 2
        assert first[0].event.scoring_attempt_count == 1
        assert unavailable == ()
        expired = run_async(
            repository.list_expired_scoring_claims(lease_until, 1),
        )

        assert still_unavailable == ()
        assert len(expired) == 1
        assert expired[0].claim.token == first[0].claim.token
        assert expired[0].event.version == 2
        assert expired[0].event.scoring_attempt_count == 1

    def test_event_claim_and_version_conflicts_are_typed(self) -> None:
        repository = self.make_repository()
        event = make_event()
        self.add_event(repository, event)
        claim = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]

        claim_lost = run_async(
            repository.mark_scored(
                event.id,
                uuid_for(8_001),
                claim.event.version,
                90,
                NOW + timedelta(minutes=10, seconds=30),
            ),
        )
        version_conflict = run_async(
            repository.mark_scored(
                event.id,
                claim.claim.token,
                1,
                90,
                NOW + timedelta(minutes=10, seconds=30),
            ),
        )

        assert claim_lost.outcome is StateTransitionOutcome.CLAIM_LOST
        assert claim_lost.version == claim.event.version
        assert version_conflict.outcome is StateTransitionOutcome.VERSION_CONFLICT
        assert version_conflict.version == claim.event.version

    def test_event_scoring_failure_retry_release_and_success(self) -> None:
        repository = self.make_repository()
        event = make_event()
        self.add_event(repository, event)
        first = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        retry_at = NOW + timedelta(minutes=20)
        failed = run_async(
            repository.mark_scoring_failed(
                event.id,
                first.claim.token,
                first.event.version,
                ProcessingError(code="temporary", summary="Temporary failure"),
                NOW + timedelta(minutes=10, seconds=30),
                retry_at,
            ),
        )

        assert failed.outcome is StateTransitionOutcome.APPLIED
        before_retry = run_async(
            repository.list_pending(retry_at - timedelta(microseconds=1), 1),
        )
        assert before_retry == ()
        assert tuple(run_async(repository.list_pending(retry_at, 1)))[0].id == event.id

        second = run_async(
            repository.claim_pending(
                retry_at,
                "worker",
                retry_at + timedelta(minutes=1),
                1,
            ),
        )[0]
        released_until = retry_at + timedelta(minutes=5)
        released = run_async(
            repository.release_claim(
                event.id,
                second.claim.token,
                second.event.version,
                retry_at + timedelta(seconds=10),
                released_until,
            ),
        )
        assert released.outcome is StateTransitionOutcome.APPLIED
        before_release = run_async(
            repository.list_pending(released_until - timedelta(seconds=1), 1),
        )
        assert before_release == ()

        third = run_async(
            repository.claim_pending(
                released_until,
                "worker",
                released_until + timedelta(minutes=1),
                1,
            ),
        )[0]
        scored = run_async(
            repository.mark_scored(
                event.id,
                third.claim.token,
                third.event.version,
                91,
                released_until + timedelta(seconds=30),
            ),
        )
        stored = run_async(repository.get_by_id(event.id))

        assert scored.outcome is StateTransitionOutcome.APPLIED
        assert stored is not None
        assert stored.scoring_status is ScoringStatus.SUCCEEDED
        assert stored.score == 91
        after_success = run_async(
            repository.list_pending(released_until + timedelta(days=1), 1),
        )
        assert after_success == ()

    def test_event_disposition_transitions_and_terminal_exclusion(self) -> None:
        repository = self.make_repository()
        event = make_event()
        self.add_event(repository, event)

        ignored = run_async(
            repository.set_disposition(
                event.id,
                EventDisposition.IGNORED,
                NOW + timedelta(minutes=10),
                1,
            ),
        )
        invalid = run_async(
            repository.set_disposition(
                event.id,
                EventDisposition.APPROVED,
                NOW + timedelta(minutes=11),
                2,
            ),
        )

        assert ignored.outcome is StateTransitionOutcome.APPLIED
        assert invalid.outcome is StateTransitionOutcome.INVALID_STATE
        assert run_async(repository.list_pending(NOW + timedelta(days=1), 1)) == ()

    def test_event_missing_update_has_typed_not_found_outcome(self) -> None:
        repository = self.make_repository()

        result = run_async(
            repository.set_disposition(
                uuid_for(7_001),
                EventDisposition.REJECTED,
                NOW,
                1,
            ),
        )

        assert result.outcome is StateTransitionOutcome.NOT_FOUND
        assert result.version is None

    def test_only_successfully_scored_events_are_content_eligible(self) -> None:
        repository = self.make_repository()
        event = make_event()
        self.prepare_event(repository, event)
        run_async(repository.add_idempotently(MarketEventCandidate(event=event)))

        assert run_async(repository.list_content_eligible(10)) == ()
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        run_async(
            repository.mark_scored(
                event.id,
                claimed.claim.token,
                claimed.event.version,
                80,
                NOW + timedelta(minutes=10, seconds=1),
            ),
        )

        eligible = run_async(repository.list_content_eligible(10))
        assert tuple(item.id for item in eligible) == (event.id,)
        assert run_async(repository.list_content_eligible(10, 1)) == ()


class GeneratedContentRepositoryContract:
    """Behavior every generated-content repository must satisfy."""

    def make_repository(self) -> GeneratedContentRepository:
        raise NotImplementedError

    def test_content_create_is_idempotent_retrievable_and_conflict_safe(self) -> None:
        repository = self.make_repository()
        command = make_content_command()
        duplicate = replace(
            command,
            id=uuid_for(999),
            created_at=command.created_at + timedelta(minutes=1),
        )

        created = run_async(repository.create_attempt(command))
        existing = run_async(repository.create_attempt(duplicate))

        assert created.status is IdempotentCreateStatus.CREATED
        assert existing.status is IdempotentCreateStatus.EXISTING
        assert existing.content.id == command.id
        assert existing.content.created_at == command.created_at
        assert run_async(repository.get_by_id(command.id)) == created.content

        conflicting = replace(duplicate, provider="different-provider")
        with pytest.raises(RepositoryIdentityConflictError):
            run_async(repository.create_attempt(conflicting))

        second_active = make_content_command(number=2, attempt_number=2)
        with pytest.raises(RepositoryIdentityConflictError):
            run_async(repository.create_attempt(second_active))

    def test_content_event_isolation_revision_order_and_latest(self) -> None:
        repository = self.make_repository()
        event_id = uuid_for(101)
        other_event_id = uuid_for(102)
        first_command = make_content_command(event_id=event_id)
        first = run_async(repository.create_attempt(first_command)).content
        claim = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        text = "First immutable content"
        run_async(
            repository.complete_attempt(
                first.id,
                claim.claim.token,
                claim.content.version,
                text,
                calculate_content_checksum(text),
                NOW + timedelta(minutes=10, seconds=30),
            ),
        )
        second_command = make_content_command(
            number=2,
            event_id=event_id,
            attempt_number=2,
            parent_content_id=first.id,
        )
        second = run_async(repository.create_attempt(second_command)).content
        other = run_async(
            repository.create_attempt(
                make_content_command(
                    number=3,
                    event_id=other_event_id,
                    attempt_number=1,
                ),
            ),
        ).content

        assert tuple(run_async(repository.list_for_event(event_id))) == (
            run_async(repository.get_by_id(first.id)),
            second,
        )
        assert tuple(run_async(repository.list_for_event(other_event_id))) == (other,)
        assert second.parent_content_id == first.id
        assert (
            run_async(
                repository.get_latest_revision(
                    event_id,
                    "TELEGRAM_POST",
                    "RU",
                ),
            )
            == second
        )

    def test_content_completion_validates_claim_version_and_checksum(self) -> None:
        repository = self.make_repository()
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
        text = "Generated content"

        claim_lost = run_async(
            repository.complete_attempt(
                command.id,
                uuid_for(8_002),
                claimed.content.version,
                text,
                calculate_content_checksum(text),
                NOW + timedelta(minutes=10, seconds=10),
            ),
        )
        version_conflict = run_async(
            repository.complete_attempt(
                command.id,
                claimed.claim.token,
                1,
                text,
                calculate_content_checksum(text),
                NOW + timedelta(minutes=10, seconds=10),
            ),
        )
        with pytest.raises(ValueError, match="checksum"):
            run_async(
                repository.complete_attempt(
                    command.id,
                    claimed.claim.token,
                    claimed.content.version,
                    text,
                    "0" * 64,
                    NOW + timedelta(minutes=10, seconds=10),
                ),
            )
        completed = run_async(
            repository.complete_attempt(
                command.id,
                claimed.claim.token,
                claimed.content.version,
                text,
                calculate_content_checksum(text),
                NOW + timedelta(minutes=10, seconds=10),
            ),
        )
        stored = run_async(repository.get_by_id(command.id))

        assert claim_lost.outcome is StateTransitionOutcome.CLAIM_LOST
        assert version_conflict.outcome is StateTransitionOutcome.VERSION_CONFLICT
        assert completed.outcome is StateTransitionOutcome.APPLIED
        assert stored is not None
        assert stored.generation_status is ContentGenerationStatus.GENERATED
        assert stored.content_text == text

    def test_failed_content_is_terminal_and_retry_uses_new_attempt(self) -> None:
        repository = self.make_repository()
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
        failed = run_async(
            repository.fail_attempt(
                command.id,
                claimed.claim.token,
                claimed.content.version,
                ProcessingError(code="provider", summary="Known provider failure"),
                NOW + timedelta(minutes=10, seconds=10),
                NOW + timedelta(minutes=20),
            ),
        )

        assert failed.outcome is StateTransitionOutcome.APPLIED
        assert (
            run_async(
                repository.claim_pending(
                    NOW + timedelta(days=1),
                    "worker",
                    NOW + timedelta(days=1, minutes=1),
                    10,
                ),
            )
            == ()
        )

        retry = make_content_command(number=2, attempt_number=2)
        retry_result = run_async(repository.create_attempt(retry))
        assert retry_result.status is IdempotentCreateStatus.CREATED

    def test_content_review_transitions_are_guarded_and_terminal(self) -> None:
        for number, decision, forbidden in (
            (1, ContentReviewStatus.APPROVED, ContentReviewStatus.REJECTED),
            (2, ContentReviewStatus.REJECTED, ContentReviewStatus.APPROVED),
        ):
            repository = self.make_repository()
            command = make_content_command(
                number=number,
                event_id=uuid_for(100 + number),
            )
            run_async(repository.create_attempt(command))
            claimed = run_async(
                repository.claim_pending(
                    NOW + timedelta(minutes=10),
                    "worker",
                    NOW + timedelta(minutes=11),
                    1,
                ),
            )[0]
            text = "Reviewed content"
            run_async(
                repository.complete_attempt(
                    command.id,
                    claimed.claim.token,
                    claimed.content.version,
                    text,
                    calculate_content_checksum(text),
                    NOW + timedelta(minutes=10, seconds=10),
                ),
            )
            generated = run_async(repository.get_by_id(command.id))
            assert generated is not None
            decided = run_async(
                repository.set_review_status(
                    command.id,
                    decision,
                    NOW + timedelta(minutes=11),
                    generated.version,
                ),
            )
            invalid = run_async(
                repository.set_review_status(
                    command.id,
                    forbidden,
                    NOW + timedelta(minutes=12),
                    decided.version or 0,
                ),
            )

            assert decided.outcome is StateTransitionOutcome.APPLIED
            assert invalid.outcome is StateTransitionOutcome.INVALID_STATE

    def test_content_not_required_and_premature_review_are_invalid(self) -> None:
        repository = self.make_repository()
        command = make_content_command()
        created = run_async(repository.create_attempt(command)).content

        premature = run_async(
            repository.set_review_status(
                command.id,
                ContentReviewStatus.APPROVED,
                NOW + timedelta(minutes=10),
                created.version,
            ),
        )
        not_required = run_async(
            repository.set_review_status(
                command.id,
                ContentReviewStatus.NOT_REQUIRED,
                NOW + timedelta(minutes=10),
                created.version,
            ),
        )

        assert premature.outcome is StateTransitionOutcome.INVALID_STATE
        assert not_required.outcome is StateTransitionOutcome.INVALID_STATE

    def test_expired_content_claim_is_abandoned_not_stolen(self) -> None:
        repository = self.make_repository()
        command = make_content_command()
        run_async(repository.create_attempt(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker-one",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]

        unavailable = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10, seconds=30),
                "worker-two",
                NOW + timedelta(minutes=12),
                1,
            ),
        )

        recovered = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=11),
                "worker-two",
                NOW + timedelta(minutes=12),
                1,
            ),
        )
        stored = run_async(repository.get_by_id(command.id))
        stale = run_async(
            repository.fail_attempt(
                command.id,
                claimed.claim.token,
                claimed.content.version,
                ProcessingError(code="late", summary="Late worker"),
                NOW + timedelta(minutes=11),
                None,
            ),
        )

        assert unavailable == ()
        assert recovered == ()
        assert stored is not None
        assert stored.generation_status is ContentGenerationStatus.ABANDONED
        assert stored.claim is None
        assert stale.outcome is StateTransitionOutcome.VERSION_CONFLICT

    def test_expired_content_claim_supports_explicit_idempotent_recovery(self) -> None:
        repository = self.make_repository()
        command = make_content_command()
        run_async(repository.create_attempt(command))
        run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )

        expired = run_async(
            repository.list_expired_claims(NOW + timedelta(minutes=11), 10)
        )
        transition = run_async(
            repository.release_claim(
                command.id,
                expired[0].claim.token,
                expired[0].content.version,
                NOW + timedelta(minutes=11),
            )
        )

        assert transition.outcome is StateTransitionOutcome.APPLIED
        assert (
            run_async(repository.list_expired_claims(NOW + timedelta(minutes=12), 10))
            == ()
        )

    def test_content_missing_update_has_typed_not_found_outcome(self) -> None:
        repository = self.make_repository()

        result = run_async(
            repository.set_review_status(
                uuid_for(7_002),
                ContentReviewStatus.REJECTED,
                NOW,
                1,
            ),
        )

        assert result.outcome is StateTransitionOutcome.NOT_FOUND
        assert result.version is None


class PublicationRepositoryContract:
    """Behavior every persistent publication repository must satisfy."""

    def make_repository(self) -> PublicationRepository:
        raise NotImplementedError

    def test_publication_create_is_idempotent_and_retrievable(self) -> None:
        repository = self.make_repository()
        scheduled_at = NOW + timedelta(minutes=30)
        command = make_publication_command(scheduled_at=scheduled_at)
        duplicate = replace(
            command,
            id=uuid_for(999),
            scheduled_at=scheduled_at + timedelta(hours=1),
            created_at=command.created_at + timedelta(minutes=1),
        )

        created = run_async(repository.create_idempotently(command))
        existing = run_async(repository.create_idempotently(duplicate))

        assert created.status is IdempotentCreateStatus.CREATED
        assert existing.status is IdempotentCreateStatus.EXISTING
        assert existing.publication.id == command.id
        assert existing.publication.scheduled_at == scheduled_at
        assert run_async(repository.get_by_id(command.id)) == created.publication
        assert (
            run_async(repository.get_by_idempotency_key(command.idempotency_key))
            == created.publication
        )

    def test_publication_channel_destination_and_event_isolation(self) -> None:
        repository = self.make_repository()
        event_id = uuid_for(101)
        other_event_id = uuid_for(102)
        preview = run_async(
            repository.create_idempotently(
                make_publication_command(event_id=event_id),
            ),
        ).publication
        email = run_async(
            repository.create_idempotently(
                make_publication_command(
                    number=2,
                    event_id=event_id,
                    channel="email",
                    destination_key="review-channel",
                ),
            ),
        ).publication
        other = run_async(
            repository.create_idempotently(
                make_publication_command(
                    number=3,
                    event_id=other_event_id,
                    destination_key="other",
                ),
            ),
        ).publication

        assert preview.idempotency_key != email.idempotency_key
        assert tuple(run_async(repository.list_for_event(event_id))) == (
            preview,
            email,
        )
        assert tuple(run_async(repository.list_for_event(other_event_id))) == (other,)

    def test_publication_pending_list_is_scheduled_and_stably_ordered(self) -> None:
        repository = self.make_repository()
        late_high = make_publication_command(
            number=1,
            publication_id=uuid_for(313),
            content_id=uuid_for(211),
            destination_key="late-high",
            scheduled_at=NOW + timedelta(minutes=20),
            created_at=NOW + timedelta(minutes=1),
        )
        early = make_publication_command(
            number=2,
            publication_id=uuid_for(312),
            content_id=uuid_for(212),
            destination_key="early",
            scheduled_at=NOW + timedelta(minutes=10),
            created_at=NOW + timedelta(minutes=2),
        )
        late_low = make_publication_command(
            number=3,
            publication_id=uuid_for(311),
            content_id=uuid_for(213),
            destination_key="late-low",
            scheduled_at=NOW + timedelta(minutes=20),
            created_at=NOW + timedelta(minutes=1),
        )
        for command in (late_high, early, late_low):
            run_async(repository.create_idempotently(command))

        assert tuple(
            publication.id
            for publication in run_async(
                repository.list_pending(NOW + timedelta(minutes=15), 10),
            )
        ) == (early.id,)
        assert tuple(
            publication.id
            for publication in run_async(
                repository.list_pending(NOW + timedelta(minutes=20), 10),
            )
        ) == (early.id, late_low.id, late_high.id)

    def test_publication_claim_is_exclusive_and_expiry_becomes_ambiguous(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker-one",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        unavailable = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10, seconds=30),
                "worker-two",
                NOW + timedelta(minutes=12),
                1,
            ),
        )
        recovered = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=11),
                "worker-two",
                NOW + timedelta(minutes=12),
                1,
            ),
        )
        stored = run_async(repository.get_by_id(command.id))

        assert claimed.claim.worker_id == "worker-one"
        assert claimed.publication.attempt_count == 1
        assert unavailable == ()
        assert recovered == ()
        assert stored is not None
        assert stored.status is PublicationStatus.AMBIGUOUS
        assert stored.last_error is not None
        assert stored.last_error.code == "lease_expired_ambiguous"

    def test_publication_expiry_supports_explicit_ambiguous_recovery(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )

        expired = run_async(
            repository.list_expired_claims(NOW + timedelta(minutes=11), 10)
        )
        transition = run_async(
            repository.mark_ambiguous(
                command.id,
                expired[0].claim.token,
                expired[0].publication.version,
                ProcessingError(
                    code="lease_expired_ambiguous",
                    summary="Publication claim expired.",
                ),
                NOW + timedelta(minutes=11),
            )
        )

        assert transition.outcome is StateTransitionOutcome.APPLIED
        assert (
            run_async(repository.list_expired_claims(NOW + timedelta(minutes=12), 10))
            == ()
        )

    def test_publication_publish_is_idempotent_and_terminal(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        published_at = NOW + timedelta(minutes=10, seconds=10)
        published = run_async(
            repository.mark_published(
                command.id,
                claimed.claim.token,
                claimed.publication.version,
                "message-1",
                published_at,
            ),
        )
        duplicate = run_async(
            repository.mark_published(
                command.id,
                claimed.claim.token,
                claimed.publication.version,
                "message-1",
                published_at + timedelta(seconds=1),
            ),
        )
        conflicting = run_async(
            repository.mark_published(
                command.id,
                claimed.claim.token,
                published.version or 0,
                "message-2",
                published_at + timedelta(seconds=2),
            ),
        )
        stored = run_async(repository.get_by_id(command.id))

        assert published.outcome is StateTransitionOutcome.APPLIED
        assert duplicate.outcome is StateTransitionOutcome.APPLIED
        assert duplicate.version == published.version
        assert conflicting.outcome is StateTransitionOutcome.INVALID_STATE
        assert stored is not None
        assert stored.status is PublicationStatus.PUBLISHED
        assert stored.external_message_id == "message-1"
        assert stored.published_at == published_at
        assert run_async(repository.list_pending(NOW + timedelta(days=1), 1)) == ()
        cancelled = run_async(
            repository.cancel(
                command.id,
                NOW + timedelta(minutes=12),
                published.version or 0,
            ),
        )
        assert cancelled.outcome is StateTransitionOutcome.INVALID_STATE

    def test_publication_failed_delivery_retries_only_when_due(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        retry_at = NOW + timedelta(minutes=20)
        failed = run_async(
            repository.mark_failed(
                command.id,
                claimed.claim.token,
                claimed.publication.version,
                ProcessingError(code="transport", summary="Known failure"),
                NOW + timedelta(minutes=10, seconds=10),
                retry_at,
            ),
        )

        assert failed.outcome is StateTransitionOutcome.APPLIED
        before_retry = run_async(
            repository.list_pending(retry_at - timedelta(microseconds=1), 1),
        )
        due = run_async(repository.list_pending(retry_at, 1))
        assert before_retry == ()
        assert tuple(due)[0].id == command.id

        retried = run_async(
            repository.claim_pending(
                retry_at,
                "worker-two",
                retry_at + timedelta(minutes=1),
                1,
            ),
        )[0]
        assert retried.publication.status is PublicationStatus.IN_PROGRESS
        assert retried.publication.attempt_count == 2

    def test_publication_claim_and_version_conflicts_are_typed(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]

        claim_lost = run_async(
            repository.mark_failed(
                command.id,
                uuid_for(8_003),
                claimed.publication.version,
                ProcessingError(code="failure", summary="Known failure"),
                NOW + timedelta(minutes=10, seconds=10),
                None,
            ),
        )
        version_conflict = run_async(
            repository.mark_failed(
                command.id,
                claimed.claim.token,
                1,
                ProcessingError(code="failure", summary="Known failure"),
                NOW + timedelta(minutes=10, seconds=10),
                None,
            ),
        )

        assert claim_lost.outcome is StateTransitionOutcome.CLAIM_LOST
        assert version_conflict.outcome is StateTransitionOutcome.VERSION_CONFLICT

    def test_ambiguous_publication_blocks_retry_but_can_be_cancelled(self) -> None:
        repository = self.make_repository()
        command = make_publication_command()
        run_async(repository.create_idempotently(command))
        claimed = run_async(
            repository.claim_pending(
                NOW + timedelta(minutes=10),
                "worker",
                NOW + timedelta(minutes=11),
                1,
            ),
        )[0]
        ambiguous = run_async(
            repository.mark_ambiguous(
                command.id,
                claimed.claim.token,
                claimed.publication.version,
                ProcessingError(code="timeout", summary="Outcome is unknown"),
                NOW + timedelta(minutes=10, seconds=10),
            ),
        )

        assert ambiguous.outcome is StateTransitionOutcome.APPLIED
        assert run_async(repository.list_pending(NOW + timedelta(days=1), 1)) == ()
        cancelled = run_async(
            repository.cancel(
                command.id,
                NOW + timedelta(minutes=12),
                ambiguous.version or 0,
            ),
        )
        invalid = run_async(
            repository.cancel(
                command.id,
                NOW + timedelta(minutes=13),
                cancelled.version or 0,
            ),
        )
        assert cancelled.outcome is StateTransitionOutcome.APPLIED
        assert invalid.outcome is StateTransitionOutcome.INVALID_STATE

    def test_publication_missing_update_has_typed_not_found_outcome(self) -> None:
        repository = self.make_repository()

        result = run_async(repository.cancel(uuid_for(7_003), NOW, 1))

        assert result.outcome is StateTransitionOutcome.NOT_FOUND
        assert result.version is None
