"""Verify the EPIC 15 read-only administration API against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import httpx
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set the database URL before importing the application composition root.
_CONFIGURED_DATABASE_URL = os.getenv("EPIC15_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings
from app.database.session import engine
from app.domain.generated_content import (
    CreateContentAttempt,
    calculate_content_checksum,
)
from app.domain.market_events import MarketEventCandidate, SnapshotIdentity
from app.domain.price_snapshot import PriceSnapshot
from app.domain.publications import CreatePublication
from app.main import create_app
from app.repositories.provider import create_postgres_provider
from tests.repositories.contracts.factories import NOW, make_event, uuid_for

DATABASE_URL_ENV = "EPIC15_DATABASE_URL"
ADMIN_KEY = "epic15-verifier-key"
TOKEN = "123456:EPIC15_FAKE_TOKEN"


class Verification:
    """Collect and print named verification checks."""

    def __init__(self) -> None:
        self.passed: list[str] = []

    def check(self, name: str, condition: bool) -> None:
        """Record one passing check or raise a diagnostic assertion."""
        if not condition:
            raise AssertionError(name)
        self.passed.append(name)
        print(f"PASS: {name}")


async def main() -> int:
    """Run the isolated PostgreSQL read API verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    await _seed(database_url)

    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        )
    )
    verifier = Verification()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://epic15.test",
    ) as client:
        await _verify_http(client, verifier)

    await engine.dispose()
    fresh_application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fresh_application),
        base_url="http://epic15.test",
    ) as client:
        response = await client.get(
            "/api/v1/admin/events",
            headers={"X-Admin-API-Key": ADMIN_KEY},
        )
    verifier.check("restart/fresh-session reads", response.status_code == 200)
    print(f"EPIC 15 PostgreSQL verification: {len(verifier.passed)} checks passed.")
    return 0


async def _verify_http(
    client: httpx.AsyncClient,
    verifier: Verification,
) -> None:
    headers = {"X-Admin-API-Key": ADMIN_KEY}
    live = await client.get("/health/live")
    verifier.check(
        "liveness", live.status_code == 200 and live.json()["status"] == "ok"
    )

    ready = await client.get("/health/ready")
    verifier.check("readiness", ready.status_code == 200)

    missing = await client.get("/api/v1/admin/events")
    verifier.check(
        "missing authentication",
        missing.status_code == 401
        and missing.json()["error"]["code"] == "authentication_required",
    )
    invalid = await client.get(
        "/api/v1/admin/events",
        headers={"X-Admin-API-Key": "wrong"},
    )
    verifier.check("invalid authentication", invalid.status_code == 401)

    events = await client.get("/api/v1/admin/events?limit=1", headers=headers)
    verifier.check("valid authentication", events.status_code == 200)
    verifier.check(
        "event list",
        events.status_code == 200 and len(events.json()["items"]) == 1,
    )
    event_body = events.json()["items"][0]
    event_id = event_body["id"]
    verifier.check(
        "typed price-drop payload",
        event_body["payload"]["type"] == "price_drop"
        and event_body["payload"]["version"] == 1
        and isinstance(event_body["payload"]["old_price"], str),
    )
    detail = await client.get(f"/api/v1/admin/events/{event_id}", headers=headers)
    verifier.check("event detail", detail.status_code == 200)
    filtered = await client.get(
        "/api/v1/admin/events?marketplace=ggsel&min_score=1",
        headers=headers,
    )
    verifier.check("event filters", filtered.status_code == 200)
    cursor = events.json()["next_cursor"]
    verifier.check("event pagination", isinstance(cursor, str) and bool(cursor))
    next_page = await client.get(
        f"/api/v1/admin/events?limit=1&cursor={cursor}",
        headers=headers,
    )
    verifier.check("event pagination continuation", next_page.status_code == 200)

    content = await client.get("/api/v1/admin/content", headers=headers)
    verifier.check(
        "content list",
        content.status_code == 200 and len(content.json()["items"]) >= 1,
    )
    content_id = content.json()["items"][0]["id"]
    content_detail = await client.get(
        f"/api/v1/admin/content/{content_id}",
        headers=headers,
    )
    verifier.check("content detail", content_detail.status_code == 200)
    content_filtered = await client.get(
        "/api/v1/admin/content?generation_status=generated",
        headers=headers,
    )
    verifier.check("content filters", content_filtered.status_code == 200)
    verifier.check(
        "content pagination",
        content.json()["next_cursor"] is None
        or isinstance(content.json()["next_cursor"], str),
    )

    publications = await client.get("/api/v1/admin/publications", headers=headers)
    verifier.check(
        "publication list",
        publications.status_code == 200 and len(publications.json()["items"]) >= 1,
    )
    publication_id = publications.json()["items"][0]["id"]
    publication_detail = await client.get(
        f"/api/v1/admin/publications/{publication_id}",
        headers=headers,
    )
    verifier.check("publication detail", publication_detail.status_code == 200)
    publication_filtered = await client.get(
        "/api/v1/admin/publications?channel=telegram&status=pending",
        headers=headers,
    )
    verifier.check("publication filters", publication_filtered.status_code == 200)
    verifier.check(
        "publication pagination",
        publications.json()["next_cursor"] is None
        or isinstance(publications.json()["next_cursor"], str),
    )
    publication_body = publication_detail.json()
    verifier.check(
        "safe destination",
        publication_body["destination_reference"] != "-1001234567890",
    )
    verifier.check("claim token absent", "claim_token" not in publication_body)
    verifier.check(
        "sanitized errors",
        TOKEN not in content.text and TOKEN not in publications.text,
    )

    invalid_cursor = await client.get(
        "/api/v1/admin/events?cursor=invalid",
        headers=headers,
    )
    verifier.check(
        "invalid cursor",
        invalid_cursor.status_code == 422
        and invalid_cursor.json()["error"]["code"] == "invalid_cursor",
    )
    invalid_dates = await client.get(
        "/api/v1/admin/events"
        "?detected_from=2026-08-02T00:00:00Z"
        "&detected_to=2026-08-01T00:00:00Z",
        headers=headers,
    )
    verifier.check(
        "UTC date validation",
        invalid_dates.status_code == 422
        and invalid_dates.json()["error"]["code"] == "validation_error",
    )
    verifier.check(
        "request correlation",
        "X-Request-ID" in invalid_cursor.headers
        and invalid_cursor.json()["error"]["request_id"]
        == invalid_cursor.headers["X-Request-ID"],
    )
    unauthenticated_openapi = await client.get("/openapi.json")
    verifier.check(
        "protected OpenAPI",
        unauthenticated_openapi.status_code == 401,
    )
    openapi = await client.get("/openapi.json", headers=headers)
    paths = openapi.json()["paths"]
    verifier.check(
        "admin read mutation and dashboard routes registered",
        paths["/api/v1/admin/events"].keys() == {"get"}
        and paths["/api/v1/admin/dashboard/summary"].keys() == {"get"}
        and paths["/api/v1/admin/content/{content_id}/approve"].keys() == {"post"}
        and all(
            method.upper() in {"GET", "HEAD", "POST"}
            for path in paths.values()
            for method in path
        ),
    )
    verifier.check(
        "no Telegram calls",
        TOKEN not in live.text
        and TOKEN not in publication_detail.text
        and "bot_token" not in publication_detail.text.lower(),
    )


async def _seed(database_url: str) -> None:
    """Seed durable records using existing repository contracts only."""
    seed_engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(
        bind=seed_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        for number in (1, 2):
            await _seed_event(session_factory, number)
    finally:
        await seed_engine.dispose()


async def _seed_event(
    session_factory: async_sessionmaker[AsyncSession],
    number: int,
) -> None:
    event = make_event(
        number=number,
        event_id=uuid_for(150_000 + number),
        occurred_at=NOW + timedelta(hours=number),
        created_at=NOW + timedelta(hours=number, seconds=2),
    )
    content_id = uuid_for(160_000 + number)
    publication_id = uuid_for(170_000 + number)
    async with session_factory() as session, session.begin():
        repositories = create_postgres_provider(session)
        await repositories.price_history.add(_snapshot(event.previous_snapshot))
        await repositories.price_history.add(_snapshot(event.current_snapshot))
        await repositories.events.add_idempotently(MarketEventCandidate(event=event))
        await repositories.generated_contents.create_attempt(
            CreateContentAttempt(
                id=content_id,
                event_id=event.id,
                content_type="telegram_post",
                language="ru",
                prompt_version="price_drop_v1",
                attempt_number=1,
                provider="fake",
                model="deterministic",
                created_at=NOW + timedelta(hours=number, minutes=1),
            )
        )
        claimed = (
            await repositories.generated_contents.claim_pending(
                NOW + timedelta(hours=number, minutes=2),
                f"epic15-content-{number}",
                NOW + timedelta(hours=number, minutes=3),
                1,
            )
        )[0]
        text_value = f"EPIC 15 read verification {number}"
        await repositories.generated_contents.complete_attempt(
            content_id,
            claimed.claim.token,
            claimed.content.version,
            text_value,
            calculate_content_checksum(text_value),
            NOW + timedelta(hours=number, minutes=4),
        )
        await repositories.publications.create_idempotently(
            CreatePublication(
                id=publication_id,
                event_id=event.id,
                content_id=content_id,
                channel="telegram",
                destination_key="-1001234567890",
                created_at=NOW + timedelta(hours=number, minutes=5),
            )
        )


def _snapshot(identity: SnapshotIdentity) -> PriceSnapshot:
    """Convert a domain snapshot identity into the existing snapshot contract."""
    return PriceSnapshot(
        marketplace=identity.marketplace,
        external_id=identity.external_id,
        price=identity.price,
        currency=identity.currency,
        collected_at=identity.collected_at,
    )


async def _recreate_schema(database_url: str) -> None:
    """Reset only the explicitly named isolated EPIC 15 database."""
    isolated_engine = create_async_engine(database_url)
    try:
        async with isolated_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await isolated_engine.dispose()


def _apply_migrations(database_url: str) -> None:
    """Apply the current Alembic head to the isolated database."""
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def _require_isolated_database(database_url: str) -> None:
    parsed = make_url(database_url)
    database_name = (parsed.database or "").lower()
    if not database_name.startswith("epic15"):
        msg = (
            "Refusing to run outside an isolated database named with the "
            "'epic15' prefix."
        )
        raise RuntimeError(msg)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
