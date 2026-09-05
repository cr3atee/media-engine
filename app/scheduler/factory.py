from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import SchedulerSettings
from app.repositories.memory import MemorySchedulerLeaseRepository
from app.repositories.postgres import PostgresSchedulerLeaseRepository
from app.repositories.scheduler_leases import SchedulerLeaseRepository
from app.scheduler.service import SchedulerService


def create_scheduler_service(
    scheduler_settings: SchedulerSettings,
    *,
    lease_repository: SchedulerLeaseRepository | None = None,
) -> SchedulerService:
    """Create a SchedulerService from explicit scheduler settings."""
    if scheduler_settings.lease_enabled and lease_repository is None:
        msg = "Scheduler leases are enabled but no lease repository was provided."
        raise ValueError(msg)

    return SchedulerService(
        tick_seconds=scheduler_settings.tick_seconds,
        lease_repository=lease_repository if scheduler_settings.lease_enabled else None,
        owner_id=scheduler_settings.owner_id or None,
        lease_ttl_seconds=scheduler_settings.lease_ttl_seconds,
    )


def create_memory_scheduler_service(
    scheduler_settings: SchedulerSettings,
) -> SchedulerService:
    """Create a SchedulerService with optional in-memory lease guarding."""
    lease_repository = (
        MemorySchedulerLeaseRepository() if scheduler_settings.lease_enabled else None
    )
    return create_scheduler_service(
        scheduler_settings,
        lease_repository=lease_repository,
    )


def create_postgres_scheduler_service(
    scheduler_settings: SchedulerSettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> SchedulerService:
    """Create a SchedulerService with optional PostgreSQL lease guarding."""
    lease_repository = (
        PostgresSchedulerLeaseRepository(session_factory)
        if scheduler_settings.lease_enabled
        else None
    )
    return create_scheduler_service(
        scheduler_settings,
        lease_repository=lease_repository,
    )
