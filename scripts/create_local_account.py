"""Provision a new local account with a privately entered password; never reset one."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import warnings
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database.repository_scope import create_postgres_repository_scope  # noqa: E402
from app.domain.auth import PasswordCredential  # noqa: E402
from app.domain.tenancy import User, normalize_email, utc_now  # noqa: E402
from app.services.passwords import PasswordHasher  # noqa: E402
from app.services.repository_scope import RepositoryScopeFactory  # noqa: E402


async def create_account(
    scope: RepositoryScopeFactory, *, email: str, password_hash: str
) -> UUID:
    """Atomically create an unprivileged identity and credential, refusing reuse."""
    normalized_email = normalize_email(email)
    async with scope() as repositories:
        await repositories.users.lock_role_changes()
        if await repositories.users.get_by_email(normalized_email) is not None:
            raise ValueError("Account already exists; no password or role was changed.")
        now = utc_now()
        user = User(id=uuid4(), email=normalized_email, created_at=now, updated_at=now)
        await repositories.users.create(user)
        await repositories.password_credentials.set_for_user(
            PasswordCredential(
                user_id=user.id,
                password_hash=password_hash,
                created_at=now,
                updated_at=now,
            )
        )
        return user.id


def read_password_hash() -> str:
    """Refuse redirected input or echo fallback; do not accept password arguments."""
    if not sys.stdin.isatty():
        raise ValueError("Open an interactive local terminal to enter the password.")
    print("Choose a password with 12-1024 characters. Input is hidden.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        while True:
            password = getpass.getpass("New password: ")
            confirmation = getpass.getpass("Repeat password: ")
            if password != confirmation:
                print("Passwords do not match. Try again.")
                continue
            if not 12 <= len(password) <= 1024:
                print("Use 12-1024 characters. Try again.")
                continue
            return PasswordHasher(iterations=600_000).hash_password(password)


async def run(args: argparse.Namespace) -> int:
    """Inspect an explicit local target and create only after operator confirmation."""
    url = make_url(os.environ.get("PRODUCT_ACCESS_DATABASE_URL", ""))
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (url.database or "").startswith("epic23_catalog_review_")
    ):
        raise ValueError("Requires an explicit local catalog-review database URL.")
    email = normalize_email(args.email)
    if args.apply and normalize_email(args.confirm_email or "") != email:
        raise ValueError("Repeat the exact email with --confirm-email before --apply.")
    engine = create_async_engine(url)
    scope = create_postgres_repository_scope(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        async with scope() as repositories:
            if await repositories.users.get_by_email(email) is not None:
                raise ValueError("Account already exists; nothing was changed.")
        print(f"New account: {email}")
        if not args.apply:
            print("Inspection only. Re-run with --confirm-email and --apply.")
            return 0
        # No DB transaction is held while the operator chooses a password.
        password_hash = await asyncio.to_thread(read_password_hash)
        user_id = await create_account(scope, email=email, password_hash=password_hash)
        print(f"Account created. ID: {user_id}")
        print("Initial product role: user. Administrative bootstrap is separate.")
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    """Run trusted local provisioning without printing credentials or SQL errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--confirm-email")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (KeyboardInterrupt, EOFError):
        print("Cancelled. Inspect the account status before retrying.")
        return 1
    except Exception:
        # Database exceptions may contain credential hashes and connection details.
        print(
            "Account creation refused or failed. No existing account was overwritten."
        )
        print("Check the email, local database, migration and confirmation flags.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
