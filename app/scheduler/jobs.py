from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from inspect import isawaitable
from time import perf_counter
from typing import Protocol

from app.parsers.playerok_fetcher import PlayerokFetcher


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MarketplaceRunner(Protocol):
    """Application entry point accepted by marketplace scheduler jobs."""

    async def run(self, url: str) -> object:
        """Execute one bounded marketplace application run."""


class EventProcessingRunner(Protocol):
    """Application boundary invoked by durable event Scheduler jobs."""

    async def process_pending(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> object:
        """Process one bounded batch of pending market events."""

    async def recover_stale_scoring_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> object:
        """Recover one bounded batch of expired scoring claims."""


class ContentProcessingRunner(Protocol):
    """Application boundary invoked by durable content Scheduler jobs."""

    async def process_pending(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime,
    ) -> object:
        """Process one bounded batch of generation attempts."""

    async def recover_stale_generation_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> object:
        """Recover one bounded batch of expired generation claims."""


class PublicationRecoveryRunner(Protocol):
    """Application boundary for publication-claim recovery."""

    async def recover_stale_publication_claims(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> object:
        """Recover one bounded batch of expired publication claims."""


class JobExecutionState(StrEnum):
    """Possible scheduler job execution states."""

    REGISTERED = "registered"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class JobExecutionStatus:
    """Last known execution status for a scheduler job."""

    name: str
    state: JobExecutionState
    run_count: int = 0
    failure_count: int = 0
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_duration: timedelta | None = None
    last_error: str | None = None


class BaseJob(ABC):
    """Abstract scheduler job with built-in status tracking."""

    def __init__(self, name: str) -> None:
        """Initialize the job with an execution name."""
        self._name = name
        self._status = JobExecutionStatus(
            name=name,
            state=JobExecutionState.REGISTERED,
        )

    @property
    def name(self) -> str:
        """Return the job name."""
        return self._name

    @property
    def status(self) -> JobExecutionStatus:
        """Return the last execution status."""
        return self._status

    async def execute(self) -> None:
        """Execute the job, track duration, and store the latest status."""
        started_at = datetime.now(UTC)
        started = perf_counter()
        self._status = replace(
            self._status,
            state=JobExecutionState.RUNNING,
            last_started_at=started_at,
            last_finished_at=None,
            last_duration=None,
            last_error=None,
        )

        try:
            result = self.run()
            if isawaitable(result):
                await result
        except Exception as exc:
            self._status = replace(
                self._status,
                state=JobExecutionState.FAILED,
                run_count=self._status.run_count + 1,
                failure_count=self._status.failure_count + 1,
                last_finished_at=datetime.now(UTC),
                last_duration=timedelta(seconds=perf_counter() - started),
                last_error=f"{type(exc).__name__}: {exc}",
            )
            return

        self._status = replace(
            self._status,
            state=JobExecutionState.SUCCEEDED,
            run_count=self._status.run_count + 1,
            last_finished_at=datetime.now(UTC),
            last_duration=timedelta(seconds=perf_counter() - started),
            last_error=None,
        )

    @abstractmethod
    def run(self) -> Awaitable[object] | object:
        """Execute the underlying application workflow."""


class MarketplaceJob(BaseJob, ABC):
    """Base class for marketplace pipeline scheduler jobs."""

    def __init__(self, name: str, url: str) -> None:
        """Store the job name and marketplace source URL."""
        super().__init__(name)
        self._url = url

    @property
    def url(self) -> str:
        """Return the marketplace source URL."""
        return self._url


class GGSELJob(MarketplaceJob):
    """Scheduler job that executes the existing GGSEL marketplace pipeline."""

    DEFAULT_URL = "https://ggsel.net/"

    def __init__(
        self,
        runner: MarketplaceRunner,
        url: str = DEFAULT_URL,
    ) -> None:
        """Initialize the GGSEL scheduler job with an application runner."""
        super().__init__("ggsel", url)
        self._runner = runner

    def run(self) -> Awaitable[object]:
        """Execute the configured GGSEL application runner."""
        return self._runner.run(self.url)


class PlayerokJob(MarketplaceJob):
    """Scheduler job that executes the existing Playerok pipeline."""

    def __init__(
        self,
        runner: MarketplaceRunner,
        url: str = PlayerokFetcher.DEFAULT_URL,
    ) -> None:
        """Initialize the Playerok scheduler job with an application runner."""
        super().__init__("playerok", url)
        self._runner = runner

    def run(self) -> Awaitable[object]:
        """Execute the configured Playerok application runner."""
        return self._runner.run(self.url)


class MarketEventScoringJob(BaseJob):
    """Invoke bounded durable market-event scoring."""

    def __init__(
        self,
        service: EventProcessingRunner,
        *,
        worker_id: str,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure service delegation without repository or scoring logic."""
        super().__init__("market-event-scoring")
        self._service = service
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._clock = clock

    def run(self) -> Awaitable[object]:
        """Delegate one bounded scoring batch to the application service."""
        return self._service.process_pending(
            worker_id=self._worker_id,
            limit=self._batch_size,
            now=self._clock(),
        )


class StaleScoringClaimRecoveryJob(BaseJob):
    """Invoke bounded recovery of expired market-event scoring claims."""

    def __init__(
        self,
        service: EventProcessingRunner,
        *,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure recovery delegation without persistence policy."""
        super().__init__("stale-scoring-claim-recovery")
        self._service = service
        self._batch_size = batch_size
        self._clock = clock

    def run(self) -> Awaitable[object]:
        """Delegate one bounded stale-claim recovery batch."""
        return self._service.recover_stale_scoring_claims(
            limit=self._batch_size,
            now=self._clock(),
        )


class PendingContentGenerationJob(BaseJob):
    """Invoke bounded durable content generation."""

    def __init__(
        self,
        service: ContentProcessingRunner,
        *,
        worker_id: str,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure service delegation without repository or AI logic."""
        super().__init__("pending-content-generation")
        self._service = service
        self._worker_id = worker_id
        self._batch_size = batch_size
        self._clock = clock

    def run(self) -> Awaitable[object]:
        """Delegate one bounded content-generation batch."""
        return self._service.process_pending(
            worker_id=self._worker_id,
            limit=self._batch_size,
            now=self._clock(),
        )


class StaleContentClaimRecoveryJob(BaseJob):
    """Invoke bounded recovery of expired generation claims."""

    def __init__(
        self,
        service: ContentProcessingRunner,
        *,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure recovery delegation without lifecycle policy."""
        super().__init__("stale-content-claim-recovery")
        self._service = service
        self._batch_size = batch_size
        self._clock = clock

    def run(self) -> Awaitable[object]:
        """Delegate one bounded stale generation-claim recovery batch."""
        return self._service.recover_stale_generation_claims(
            limit=self._batch_size,
            now=self._clock(),
        )


class StalePublicationClaimRecoveryJob(BaseJob):
    """Invoke bounded recovery of expired publication claims."""

    def __init__(
        self,
        service: PublicationRecoveryRunner,
        *,
        batch_size: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Configure recovery delegation without delivery behavior."""
        super().__init__("stale-publication-claim-recovery")
        self._service = service
        self._batch_size = batch_size
        self._clock = clock

    def run(self) -> Awaitable[object]:
        """Delegate one bounded stale publication-claim recovery batch."""
        return self._service.recover_stale_publication_claims(
            limit=self._batch_size,
            now=self._clock(),
        )
