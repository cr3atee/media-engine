from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import SchedulerSettings, Settings, settings
from app.database.repository_scope import create_postgres_repository_scope
from app.database.session import SessionLocal
from app.repositories.provider import RepositoryProvider
from app.scheduler.factory import (
    create_memory_scheduler_service,
    create_postgres_scheduler_service,
)
from app.scheduler.service import SchedulerService
from app.services.repository_scope import (
    RepositoryScopeFactory,
    create_memory_repository_scope,
)


@dataclass(slots=True, frozen=True)
class RuntimeComponents:
    """Application runtime components shared by process entrypoints."""

    repository_scope_factory: RepositoryScopeFactory
    scheduler: SchedulerService


def create_memory_runtime_components(
    scheduler_settings: SchedulerSettings,
    *,
    provider: RepositoryProvider | None = None,
) -> RuntimeComponents:
    """Create runtime components backed by in-memory infrastructure."""
    return RuntimeComponents(
        repository_scope_factory=create_memory_repository_scope(provider),
        scheduler=create_memory_scheduler_service(scheduler_settings),
    )


def create_postgres_runtime_components(
    scheduler_settings: SchedulerSettings,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> RuntimeComponents:
    """Create runtime components backed by PostgreSQL infrastructure."""
    return RuntimeComponents(
        repository_scope_factory=create_postgres_repository_scope(session_factory),
        scheduler=create_postgres_scheduler_service(
            scheduler_settings,
            session_factory,
        ),
    )


def create_default_runtime_components(
    app_settings: Settings = settings,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> RuntimeComponents:
    """Create the default production runtime components from project settings."""
    return create_postgres_runtime_components(
        app_settings.scheduler,
        session_factory=session_factory,
    )
