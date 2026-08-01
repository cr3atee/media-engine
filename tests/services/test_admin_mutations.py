from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    AmbiguousPublicationResolution,
)
from app.domain.generated_content import (
    GeneratedContentAttempt,
    calculate_content_checksum,
)
from app.domain.lifecycle import ContentReviewStatus, PublicationStatus
from app.domain.processing import ProcessingError
from app.domain.publications import Publication
from app.repositories.memory import MemoryAdminActionRepository
from app.repositories.provider import RepositoryProvider, create_memory_provider
from app.services.admin_mutations import (
    AdminCommandContext,
    AdminCommandError,
    AdminMutationService,
    ContentReviewCommand,
    PublicationCommand,
    ResolvePublicationCommand,
)
from app.services.repository_scope import create_memory_repository_scope
from tests.repositories.contracts.factories import (
    NOW,
    SequentialUuidFactory,
    make_content_command,
    make_publication_command,
    run_async,
    uuid_for,
)


class FailingAdminActionRepository(MemoryAdminActionRepository):
    """Fail after the state transition to verify outer rollback."""

    async def append(self, action: AdminAction) -> AdminAction:
        """Raise a deterministic storage failure."""
        del action
        msg = "controlled audit failure"
        raise RuntimeError(msg)


def test_approve_generated_content_records_action_and_replays() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        content = await _seed_generated_content(provider, number=1)
        service = _service(provider)
        context = _context("approve-content-1")

        result = await service.approve(
            ContentReviewCommand(
                content_id=content.id,
                expected_version=content.version,
            ),
            context,
        )
        replay = await service.approve(
            ContentReviewCommand(
                content_id=content.id,
                expected_version=content.version,
            ),
            context,
        )
        stored = await provider.generated_contents.get_by_id(content.id)
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert result.action is AdminActionType.APPROVE_CONTENT
        assert result.previous_state == ContentReviewStatus.PENDING.value
        assert result.resulting_state == ContentReviewStatus.APPROVED.value
        assert result.resulting_version == content.version + 1
        assert replay.action_id == result.action_id
        assert replay.replayed is True
        assert stored is not None
        assert stored.review_status is ContentReviewStatus.APPROVED
        assert stored.version == content.version + 1
        assert len(actions) == 1
        assert actions[0].actor_id == "test-admin"
        assert actions[0].request_id == "request-1"
        assert actions[0].expected_version == content.version
        assert actions[0].resulting_version == stored.version

    run_async(scenario())


def test_reject_generated_content_requires_reason_and_records_it() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        content = await _seed_generated_content(provider, number=2)
        service = _service(provider)

        with pytest.raises(ValueError, match="rejection reason"):
            await service.reject(
                ContentReviewCommand(
                    content_id=content.id,
                    expected_version=content.version,
                ),
                _context("reject-content-missing-reason"),
            )

        result = await service.reject(
            ContentReviewCommand(
                content_id=content.id,
                expected_version=content.version,
                reason="  wrong facts   in post  ",
            ),
            _context("reject-content-1"),
        )
        stored = await provider.generated_contents.get_by_id(content.id)
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert result.action is AdminActionType.REJECT_CONTENT
        assert stored is not None
        assert stored.review_status is ContentReviewStatus.REJECTED
        assert len(actions) == 1
        assert actions[0].reason == "wrong facts in post"

    run_async(scenario())


def test_invalid_content_transition_and_stale_version_do_not_create_actions() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        content = await _seed_generated_content(provider, number=3)
        service = _service(provider)

        with pytest.raises(AdminCommandError) as stale_error:
            await service.approve(
                ContentReviewCommand(
                    content_id=content.id,
                    expected_version=content.version - 1,
                ),
                _context("stale-content-version"),
            )
        assert stale_error.value.code == "optimistic_concurrency_conflict"

        await service.approve(
            ContentReviewCommand(
                content_id=content.id,
                expected_version=content.version,
            ),
            _context("approve-before-invalid"),
        )
        approved = await provider.generated_contents.get_by_id(content.id)
        assert approved is not None

        with pytest.raises(AdminCommandError) as invalid_error:
            await service.reject(
                ContentReviewCommand(
                    content_id=content.id,
                    expected_version=approved.version,
                    reason="operator changed mind",
                ),
                _context("invalid-review-transition"),
            )
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert invalid_error.value.code == "invalid_transition"
        assert len(actions) == 1

    run_async(scenario())


def test_idempotency_key_mismatch_is_rejected_without_second_transition() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        content = await _seed_generated_content(provider, number=4)
        service = _service(provider)
        context = _context("same-key-different-command")

        await service.approve(
            ContentReviewCommand(
                content_id=content.id,
                expected_version=content.version,
                reason="ok",
            ),
            context,
        )
        stored = await provider.generated_contents.get_by_id(content.id)
        assert stored is not None

        with pytest.raises(AdminCommandError) as conflict:
            await service.approve(
                ContentReviewCommand(
                    content_id=content.id,
                    expected_version=content.version,
                    reason="different reason",
                ),
                context,
            )
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert conflict.value.code == "idempotency_conflict"
        assert stored.version == content.version + 1
        assert len(actions) == 1

    run_async(scenario())


def test_audit_write_failure_rolls_back_memory_state_transition() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        provider.admin_actions = FailingAdminActionRepository()
        content = await _seed_generated_content(provider, number=5)
        service = _service(provider)

        with pytest.raises(RuntimeError, match="controlled audit failure"):
            await service.approve(
                ContentReviewCommand(
                    content_id=content.id,
                    expected_version=content.version,
                ),
                _context("audit-rollback"),
            )

        stored = await provider.generated_contents.get_by_id(content.id)
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert stored is not None
        assert stored.review_status is ContentReviewStatus.PENDING
        assert stored.version == content.version
        assert actions == ()

    run_async(scenario())


def test_publication_retry_cancel_and_ambiguous_resolution_are_audited() -> None:
    async def scenario() -> None:
        retry_provider = create_memory_provider()
        retry_service = _service(retry_provider)
        retryable = await _seed_failed_publication(retry_provider, number=1)
        retry = await retry_service.retry(
            PublicationCommand(
                publication_id=retryable.id,
                expected_version=retryable.version,
                reason="retry after operator review",
            ),
            _context("retry-publication-1"),
        )

        cancel_provider = create_memory_provider()
        cancel_service = _service(cancel_provider)
        pending = await _seed_pending_publication(cancel_provider, number=2)
        cancel = await cancel_service.cancel(
            PublicationCommand(
                publication_id=pending.id,
                expected_version=pending.version,
                reason="campaign cancelled",
            ),
            _context("cancel-publication-1"),
        )

        resolve_provider = create_memory_provider()
        resolve_service = _service(resolve_provider)
        ambiguous = await _seed_ambiguous_publication(resolve_provider, number=3)
        resolve = await resolve_service.resolve_ambiguous(
            ResolvePublicationCommand(
                publication_id=ambiguous.id,
                expected_version=ambiguous.version,
                resolution=AmbiguousPublicationResolution.DELIVERED,
                reason="confirmed in Telegram",
                external_message_id="message-42",
            ),
            _context("resolve-publication-1"),
        )

        stored_retry = await retry_provider.publications.get_by_id(retryable.id)
        stored_cancel = await cancel_provider.publications.get_by_id(pending.id)
        stored_resolve = await resolve_provider.publications.get_by_id(ambiguous.id)
        resolve_actions = await resolve_provider.admin_actions.list_for_resource(
            AdminResourceType.PUBLICATION,
            ambiguous.id,
        )

        assert retry.action is AdminActionType.RETRY_PUBLICATION
        assert stored_retry is not None
        assert stored_retry.status is PublicationStatus.PENDING
        assert stored_retry.next_retry_at is None
        assert cancel.action is AdminActionType.CANCEL_PUBLICATION
        assert stored_cancel is not None
        assert stored_cancel.status is PublicationStatus.CANCELLED
        assert resolve.action is AdminActionType.RESOLVE_PUBLICATION_DELIVERED
        assert stored_resolve is not None
        assert stored_resolve.status is PublicationStatus.PUBLISHED
        assert stored_resolve.external_message_id == "message-42"
        assert len(resolve_actions) == 1
        assert ("resolution", "delivered") in resolve_actions[0].metadata
        assert ("external_message_id", "message-42") in resolve_actions[0].metadata

    run_async(scenario())


def test_publication_guards_reject_non_retryable_and_ambiguous_cancel() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        service = _service(provider)
        permanent = await _seed_failed_publication(
            provider,
            number=4,
            retryable=False,
        )
        ambiguous = await _seed_ambiguous_publication(provider, number=5)

        with pytest.raises(AdminCommandError) as retry_error:
            await service.retry(
                PublicationCommand(
                    publication_id=permanent.id,
                    expected_version=permanent.version,
                    reason="try again",
                ),
                _context("non-retryable-publication"),
            )
        with pytest.raises(AdminCommandError) as cancel_error:
            await service.cancel(
                PublicationCommand(
                    publication_id=ambiguous.id,
                    expected_version=ambiguous.version,
                    reason="cancel ambiguous",
                ),
                _context("cancel-ambiguous-publication"),
            )

        permanent_actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.PUBLICATION,
            permanent.id,
        )
        ambiguous_actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.PUBLICATION,
            ambiguous.id,
        )

        assert retry_error.value.code == "invalid_transition"
        assert cancel_error.value.code == "invalid_transition"
        assert permanent_actions == ()
        assert ambiguous_actions == ()

    run_async(scenario())


def test_concurrent_duplicate_idempotency_creates_one_action() -> None:
    async def scenario() -> None:
        provider = create_memory_provider()
        content = await _seed_generated_content(provider, number=6)
        service = _service(provider)
        command = ContentReviewCommand(
            content_id=content.id,
            expected_version=content.version,
        )
        context = _context("concurrent-approve")

        first, second = await asyncio.gather(
            service.approve(command, context),
            service.approve(command, context),
        )
        stored = await provider.generated_contents.get_by_id(content.id)
        actions = await provider.admin_actions.list_for_resource(
            AdminResourceType.CONTENT,
            content.id,
        )

        assert first.action_id == second.action_id
        assert {first.replayed, second.replayed} == {False, True}
        assert stored is not None
        assert stored.version == content.version + 1
        assert len(actions) == 1

    run_async(scenario())


def _service(provider: RepositoryProvider) -> AdminMutationService:
    return AdminMutationService(
        create_memory_repository_scope(provider),
        maximum_publication_attempts=5,
        clock=lambda: NOW + timedelta(hours=1),
        action_id_factory=SequentialUuidFactory(90_000),
    )


def _context(idempotency_key: str) -> AdminCommandContext:
    return AdminCommandContext(
        actor_id="test-admin",
        request_id="request-1",
        idempotency_key=idempotency_key,
    )


async def _seed_generated_content(
    provider: RepositoryProvider,
    *,
    number: int,
) -> GeneratedContentAttempt:
    command = make_content_command(number=number)
    await provider.generated_contents.create_attempt(command)
    claimed = (
        await provider.generated_contents.claim_pending(
            NOW + timedelta(minutes=10),
            "content-worker",
            NOW + timedelta(minutes=11),
            1,
        )
    )[0]
    text = f"Generated content {number}"
    await provider.generated_contents.complete_attempt(
        command.id,
        claimed.claim.token,
        claimed.content.version,
        text,
        calculate_content_checksum(text),
        NOW + timedelta(minutes=10, seconds=1),
    )
    stored = await provider.generated_contents.get_by_id(command.id)
    assert stored is not None
    return stored


async def _seed_pending_publication(
    provider: RepositoryProvider,
    *,
    number: int,
) -> Publication:
    command = make_publication_command(
        number=number,
        event_id=uuid_for(10_000 + number),
        content_id=uuid_for(20_000 + number),
        publication_id=uuid_for(30_000 + number),
        channel="telegram",
        destination_key=f"channel-{number}",
    )
    result = await provider.publications.create_idempotently(command)
    return result.publication


async def _seed_failed_publication(
    provider: RepositoryProvider,
    *,
    number: int,
    retryable: bool = True,
) -> Publication:
    pending = await _seed_pending_publication(provider, number=number)
    claimed = (
        await provider.publications.claim_pending(
            NOW + timedelta(minutes=20),
            "publication-worker",
            NOW + timedelta(minutes=21),
            1,
        )
    )[0]
    assert claimed.publication.id == pending.id
    await provider.publications.mark_failed(
        claimed.publication.id,
        claimed.claim.token,
        claimed.publication.version,
        ProcessingError(code="telegram_retryable", summary="retry later"),
        NOW + timedelta(minutes=20, seconds=1),
        NOW + timedelta(minutes=22) if retryable else None,
    )
    stored = await provider.publications.get_by_id(pending.id)
    assert stored is not None
    return stored


async def _seed_ambiguous_publication(
    provider: RepositoryProvider,
    *,
    number: int,
) -> Publication:
    pending = await _seed_pending_publication(provider, number=number)
    claimed = (
        await provider.publications.claim_pending(
            NOW + timedelta(minutes=30),
            "publication-worker",
            NOW + timedelta(minutes=31),
            1,
        )
    )[0]
    assert claimed.publication.id == pending.id
    await provider.publications.mark_ambiguous(
        claimed.publication.id,
        claimed.claim.token,
        claimed.publication.version,
        ProcessingError(code="telegram_timeout", summary="unknown outcome"),
        NOW + timedelta(minutes=30, seconds=1),
    )
    stored = await provider.publications.get_by_id(pending.id)
    assert stored is not None
    return stored
