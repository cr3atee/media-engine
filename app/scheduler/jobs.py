from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from inspect import isawaitable
from time import perf_counter
from typing import cast

from app.comparator.result import ComparisonResult
from app.parsers.models import ParsedOffer
from app.parsers.playerok_fetcher import PlayerokFetcher
from app.services.marketplace_pipeline import MarketplacePipeline
from app.services.playerok_pipeline import PlayerokPipeline


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
        pipeline: MarketplacePipeline,
        url: str = DEFAULT_URL,
    ) -> None:
        """Initialize the GGSEL scheduler job with an existing pipeline."""
        super().__init__("ggsel", url)
        self._pipeline = pipeline

    def run(self) -> Awaitable[list[ComparisonResult]]:
        """Execute the existing GGSEL marketplace pipeline."""
        return cast(
            Awaitable[list[ComparisonResult]],
            self._pipeline.run(self.url),
        )


class PlayerokJob(MarketplaceJob):
    """Scheduler job that executes the existing Playerok pipeline."""

    def __init__(
        self,
        pipeline: PlayerokPipeline,
        url: str = PlayerokFetcher.DEFAULT_URL,
    ) -> None:
        """Initialize the Playerok scheduler job with an existing pipeline."""
        super().__init__("playerok", url)
        self._pipeline = pipeline

    def run(self) -> Awaitable[list[ParsedOffer]]:
        """Execute the existing Playerok pipeline."""
        return cast(Awaitable[list[ParsedOffer]], self._pipeline.run(self.url))
