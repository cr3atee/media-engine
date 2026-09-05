"""Verify Scheduler lease coordination against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("SCHEDULER_LEASE_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import settings
from app.database.session import SessionLocal, engine
from app.repositories.postgres import PostgresSchedulerLeaseRepository

DATABASE_URL_ENV = "SCHEDULER_LEASE_DATABASE_URL"
NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


class Verification:
    """Collect named Scheduler lease verification checks."""

    def __init__(self) -> None:
        """Initialize an empty verification result list."""
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record a passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run PostgreSQL Scheduler lease verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated scheduler_* database.")
        return 0

    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)

    verifier = Verification()
    repository = PostgresSchedulerLeaseRepository(SessionLocal)
    await _verify_basic_lifecycle(repository, verifier)
    await _verify_expired_recovery(repository, verifier)
    await _verify_concurrent_acquire(repository, verifier)
    await engine.dispose()

    count = len(verifier.passed)
    print(f"Scheduler lease PostgreSQL verification: {count} checks passed.")
    return 0


async def _verify_basic_lifecycle(
    repository: PostgresSchedulerLeaseRepository,
    verifier: Verification,
) -> None:
    first = await repository.acquire(
        job_name="marketplace-sync",
        owner_id="node-a",
        acquired_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    blocked = await repository.acquire(
        job_name="marketplace-sync",
        owner_id="node-b",
        acquired_at=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(seconds=31),
    )
    stored = await repository.get("marketplace-sync")
    wrong_release = await repository.release(
        job_name="marketplace-sync",
        owner_id="node-b",
    )
    released = await repository.release(
        job_name="marketplace-sync",
        owner_id="node-a",
    )
    missing = await repository.get("marketplace-sync")

    verifier.check("first acquire succeeds", first is True)
    verifier.check("active lease blocks competing owner", blocked is False)
    verifier.check(
        "stored lease keeps owner identity",
        stored is not None and stored.owner_id == "node-a",
    )
    verifier.check("wrong owner cannot release", wrong_release is False)
    verifier.check("owner can release", released is True)
    verifier.check("release removes lease", missing is None)


async def _verify_expired_recovery(
    repository: PostgresSchedulerLeaseRepository,
    verifier: Verification,
) -> None:
    first = await repository.acquire(
        job_name="stale-job",
        owner_id="node-a",
        acquired_at=NOW,
        expires_at=NOW + timedelta(seconds=1),
    )
    recovered = await repository.acquire(
        job_name="stale-job",
        owner_id="node-b",
        acquired_at=NOW + timedelta(seconds=2),
        expires_at=NOW + timedelta(seconds=32),
    )
    stored = await repository.get("stale-job")

    verifier.check("expired lease seed succeeds", first is True)
    verifier.check("expired lease can be recovered", recovered is True)
    verifier.check(
        "expired recovery replaces owner",
        stored is not None and stored.owner_id == "node-b",
    )


async def _verify_concurrent_acquire(
    repository: PostgresSchedulerLeaseRepository,
    verifier: Verification,
) -> None:
    first, second = await asyncio.gather(
        repository.acquire(
            job_name="concurrent-job",
            owner_id="node-a",
            acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        ),
        repository.acquire(
            job_name="concurrent-job",
            owner_id="node-b",
            acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        ),
    )
    stored = await repository.get("concurrent-job")

    verifier.check("concurrent acquire has one winner", sum((first, second)) == 1)
    verifier.check("concurrent winner persisted", stored is not None)


async def _recreate_schema(database_url: str) -> None:
    temporary_engine = create_async_engine(database_url)
    try:
        async with temporary_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await temporary_engine.dispose()


def _apply_migrations(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def _require_isolated_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.startswith("scheduler_"):
        msg = (
            f"{DATABASE_URL_ENV} must target an isolated scheduler_* database; "
            f"got {database_name!r}."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
