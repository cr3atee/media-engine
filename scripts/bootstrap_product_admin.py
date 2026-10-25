"""Explicit operator bootstrap; defaults to inspection and never creates users."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import ArgumentError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database.repository_scope import create_postgres_repository_scope  # noqa: E402
from app.services.product_roles import (  # noqa: E402
    ProductRoleError,
    ProductRoleService,
)


async def run(args: argparse.Namespace) -> int:
    """Inspect first; require a repeated UUID and explicit apply for elevation."""
    raw_url = os.environ.get("PRODUCT_ACCESS_DATABASE_URL", "")
    try:
        valid_url = (
            bool(raw_url) and make_url(raw_url).drivername == "postgresql+asyncpg"
        )
    except ArgumentError:
        valid_url = False
    if not valid_url:
        print("Set an explicit PRODUCT_ACCESS_DATABASE_URL using postgresql+asyncpg.")
        return 2
    if args.apply and (
        args.confirm_user_id != args.user_id
        or not args.reason
        or not args.idempotency_key
        or args.expected_version is None
    ):
        print(
            "Apply requires matching --confirm-user-id, --expected-version, "
            "--reason and --idempotency-key."
        )
        return 2
    engine = create_async_engine(raw_url)
    scope = create_postgres_repository_scope(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        async with scope() as repositories:
            user = await repositories.users.get_by_id(args.user_id)
            if user is None or not user.enabled:
                print("Target user is unavailable.")
                return 2
            print(
                f"User: {user.id}; role: {user.product_role.value}; "
                f"version: {user.version}"
            )
            admins = await repositories.users.list_product_admins()
            print(f"Existing explicit administrators: {len(admins)}")
        if not args.apply:
            print("Inspection only. No role or audit changes.")
            return 0
        action = await ProductRoleService(scope).bootstrap(
            user_id=args.user_id,
            expected_version=args.expected_version,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
        print(
            f"Bootstrap recorded: {action.id}; "
            f"resulting version: {action.resulting_version}"
        )
        return 0
    except ProductRoleError as exc:
        print(f"Bootstrap refused: {exc.code}")
        return 1
    except Exception:
        # Connection exceptions may embed credentials; do not print the raw error.
        print(
            "Database operation failed. Check connectivity and migration "
            "0018_product_roles; URL suppressed."
        )
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    """Parse the trusted operator's exact target and command guards."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--confirm-user-id", type=UUID)
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--reason")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
