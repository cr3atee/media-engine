# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import Settings
from app.domain.lifecycle import PublicationStatus
from app.domain.publications import Publication
from app.repositories.provider import RepositoryProvider, create_postgres_provider
from app.services.publication_delivery import (
    PublicationDeliveryPolicy,
    PublicationDeliveryRetryPolicy,
    PublicationDeliveryService,
)
from app.telegram.adapter import TelegramPublicationAdapter
from app.telegram.client import TelegramBotApiClient
from app.telegram.security import redact_sensitive_text, safe_destination_reference
from scripts.verify_epic14_delivery_service_postgres import (
    apply_migrations,
    load_publication,
    recreate_schema,
    seed_publication,
)
from tests.repositories.contracts.factories import NOW


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


async def _print_postgres_environment(
    engine: AsyncEngine,
    database_url: str,
) -> None:
    url = make_url(database_url)
    async with engine.connect() as connection:
        version = await connection.scalar(text("SHOW server_version"))
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    print(
        "PostgreSQL environment: "
        f"host={url.host} port={url.port} database={url.database}",
    )
    print(f"PostgreSQL version: {version}")
    print(f"Alembic revision: {revision}")


def _validate_live_guards(
    *,
    settings: Settings,
    database_url: str | None,
    confirm_chat: str | None,
    live_flag: bool,
) -> list[str]:
    missing: list[str] = []
    if not live_flag:
        missing.append("CLI --live")
    if not database_url:
        missing.append("EPIC14_DATABASE_URL")
    if not _truthy(os.getenv("TELEGRAM_LIVE_DELIVERY_ENABLED")):
        missing.append("TELEGRAM_LIVE_DELIVERY_ENABLED=true")
    if not settings.telegram.delivery_enabled:
        missing.append("TELEGRAM_DELIVERY_ENABLED=true")
    if settings.telegram.dry_run:
        missing.append("dry-run disabled")
    if not settings.telegram.allow_live_delivery:
        missing.append("TELEGRAM_ALLOW_LIVE_DELIVERY=true")
    token = settings.telegram.bot_token.get_secret_value().strip()
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    test_chat_id = settings.telegram.test_chat_id.strip()
    if not test_chat_id:
        missing.append("TELEGRAM_TEST_CHAT_ID")
    if confirm_chat is None:
        missing.append("--confirm-chat")
    elif test_chat_id and confirm_chat != test_chat_id:
        missing.append("exact test-chat confirmation")
    if test_chat_id and test_chat_id not in settings.telegram.allowed_destination_ids:
        missing.append("test chat allowlist entry")
    if database_url:
        url = make_url(database_url)
        database = url.database or ""
        if url.get_backend_name() != "postgresql" or not database.startswith("epic14_"):
            missing.append("isolated epic14_* PostgreSQL database")
    return missing


async def _run_live_delivery(
    *,
    database_url: str,
    confirm_chat: str,
    settings: Settings,
) -> None:
    await recreate_schema(database_url)
    apply_migrations(database_url)

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _print_postgres_environment(engine, database_url)
        publication_id = await seed_publication(
            session_factory,
            destination_id=confirm_chat,
            channel="telegram",
            approve=True,
        )

        @asynccontextmanager
        async def scope() -> AsyncIterator[RepositoryProvider]:
            async with session_factory() as session, session.begin():
                yield create_postgres_provider(session)

        async with TelegramBotApiClient(
            token=settings.telegram.bot_token,
            api_base_url=settings.telegram.api_base_url,
        ) as client:
            adapter = TelegramPublicationAdapter(client)
            service = PublicationDeliveryService(
                repository_scope_factory=scope,
                adapter=adapter,
                policy=PublicationDeliveryPolicy(
                    retry_policy=PublicationDeliveryRetryPolicy(),
                    allowed_destination_ids=frozenset({confirm_chat}),
                ),
                clock=lambda: NOW + timedelta(minutes=20),
            )
            result = await service.process_batch(worker_id="epic14-live", limit=1)
            if result.published != 1 or not result.items:
                details = result.items[0].status.value if result.items else "no result"
                msg = f"Live Telegram delivery failed: {details}"
                raise RuntimeError(msg)

            loaded = await load_publication(session_factory, publication_id)
            assert loaded is not None
            stored = cast("Publication", loaded)
            if stored.status is not PublicationStatus.PUBLISHED:
                msg = "Live Telegram publication was not persisted as published."
                raise RuntimeError(msg)
            if stored.external_message_id is None:
                msg = "Live Telegram publication did not persist external message ID."
                raise RuntimeError(msg)

            second = await service.process_batch(worker_id="epic14-live", limit=1)
            if second.claimed != 0:
                msg = "Live Telegram publication was claimed again on rerun."
                raise RuntimeError(msg)

            print("LIVE MODE: verified one Telegram test publication.")
            print(f"Test chat reference: {safe_destination_reference(confirm_chat)}")
            print(f"Telegram message ID: {stored.external_message_id}")
            print("SUCCESS")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guarded live Telegram verification for EPIC 14.",
    )
    parser.add_argument("--live", action="store_true", help="Enable live delivery.")
    parser.add_argument(
        "--confirm-chat",
        dest="confirm_chat",
        help="Exact Telegram test chat ID confirmation.",
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="Isolated PostgreSQL verification database URL.",
    )
    args = parser.parse_args()
    try:
        settings = Settings()
    except ValueError as error:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        print("OFFLINE MODE: live Telegram verification was not executed.")
        print("Missing guards:")
        safe_error = redact_sensitive_text(str(error), token=token)
        print(f"- settings validation failed: {safe_error}")
        return
    database_url = args.database_url or os.getenv("EPIC14_DATABASE_URL")
    missing = _validate_live_guards(
        settings=settings,
        database_url=database_url,
        confirm_chat=args.confirm_chat,
        live_flag=args.live,
    )
    if missing:
        print("OFFLINE MODE: live Telegram verification was not executed.")
        print("Missing guards:")
        for item in missing:
            print(f"- {item}")
        return

    assert database_url is not None
    assert args.confirm_chat is not None
    asyncio.run(
        _run_live_delivery(
            database_url=database_url,
            confirm_chat=args.confirm_chat,
            settings=settings,
        )
    )


if __name__ == "__main__":
    main()
