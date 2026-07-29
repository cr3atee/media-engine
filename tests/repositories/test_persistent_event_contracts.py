from __future__ import annotations

import inspect
from pathlib import Path

from app.repositories.events import MarketEventRepository
from app.repositories.generated_contents import GeneratedContentRepository
from app.repositories.publications import PublicationRepository

REPOSITORY_CONTRACTS = (
    MarketEventRepository,
    GeneratedContentRepository,
    PublicationRepository,
)


def test_persistent_event_repository_contracts_are_abstract() -> None:
    for repository_contract in REPOSITORY_CONTRACTS:
        assert inspect.isabstract(repository_contract)
        assert repository_contract.__abstractmethods__


def test_all_persistent_event_repository_operations_are_async() -> None:
    for repository_contract in REPOSITORY_CONTRACTS:
        for method_name in repository_contract.__abstractmethods__:
            method = getattr(repository_contract, method_name)
            assert inspect.iscoroutinefunction(method), (
                f"{repository_contract.__name__}.{method_name} must be async"
            )


def test_repository_contracts_expose_lifecycle_specific_operations() -> None:
    assert MarketEventRepository.__abstractmethods__ == frozenset(
        {
            "add_idempotently",
            "get_by_id",
            "get_by_identity",
            "list_pending",
            "claim_pending",
            "list_expired_scoring_claims",
            "mark_scored",
            "mark_scoring_failed",
            "set_disposition",
            "release_claim",
        },
    )
    assert GeneratedContentRepository.__abstractmethods__ == frozenset(
        {
            "create_attempt",
            "get_by_id",
            "list_for_event",
            "get_latest_revision",
            "claim_pending",
            "complete_attempt",
            "fail_attempt",
            "set_review_status",
            "release_claim",
        },
    )
    assert PublicationRepository.__abstractmethods__ == frozenset(
        {
            "create_idempotently",
            "get_by_id",
            "get_by_idempotency_key",
            "list_for_event",
            "list_pending",
            "claim_pending",
            "mark_published",
            "mark_failed",
            "mark_ambiguous",
            "cancel",
        },
    )


def test_domain_and_repository_contracts_do_not_import_sqlalchemy() -> None:
    paths = (
        Path("app/domain/identity.py"),
        Path("app/domain/processing.py"),
        Path("app/domain/lifecycle.py"),
        Path("app/domain/market_events.py"),
        Path("app/domain/generated_content.py"),
        Path("app/domain/publications.py"),
        Path("app/repositories/events.py"),
        Path("app/repositories/generated_contents.py"),
        Path("app/repositories/publications.py"),
    )

    for path in paths:
        assert "sqlalchemy" not in path.read_text(encoding="utf-8").lower()
