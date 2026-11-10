"""Preview or apply one guarded cross-environment catalog promotion."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hmac import compare_digest
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.public_read_scope import create_postgres_public_read_repository_scope
from app.database.repository_scope import create_postgres_repository_scope
from app.domain.admin_actions import AdminActorType
from app.services.admin_mutations import AdminCommandContext
from app.services.catalog_promotion_import import CatalogPromotionImportError
from app.services.catalog_promotion_manifest import CatalogPromotionManifestError
from app.services.catalog_promotion_preflight import CatalogPromotionPreflightStatus
from app.services.catalog_promotion_release import (
    CatalogPromotionReleaseError,
    CatalogPromotionReleasePreview,
    CatalogPromotionReleaseService,
)
from app.services.public_products import PublicProductReadService

SOURCE_DATABASE_URL_ENV = "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_DATABASE_URL"
TARGET_DATABASE_URL_ENV = "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE_URL"
SOURCE_TENANT_ID_ENV = "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_TENANT_ID"
TARGET_TENANT_ID_ENV = "MEDIAENGINE_CATALOG_PROMOTION_TARGET_TENANT_ID"
APPLY_ENABLED_ENV = "MEDIAENGINE_CATALOG_PROMOTION_APPLY"
EXPECTED_TARGET_DATABASE_ENV = "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE"
BACKUP_CONFIRMATION_ENV = "MEDIAENGINE_CATALOG_PROMOTION_BACKUP_CONFIRMATION"
MONITORING_CONFIRMATION_ENV = "MEDIAENGINE_CATALOG_PROMOTION_MONITORING_CONFIRMATION"
APPROVAL_PHRASE_ENV = "MEDIAENGINE_CATALOG_PROMOTION_APPROVAL_PHRASE"
ACTOR_ID_ENV = "MEDIAENGINE_CATALOG_PROMOTION_ACTOR_ID"
REQUEST_ID_ENV = "MEDIAENGINE_CATALOG_PROMOTION_REQUEST_ID"
IDEMPOTENCY_KEY_ENV = "MEDIAENGINE_CATALOG_PROMOTION_IDEMPOTENCY_KEY"
REASON_ENV = "MEDIAENGINE_CATALOG_PROMOTION_REASON"


@dataclass(slots=True, frozen=True)
class ReleaseDatabaseConfiguration:
    """Validated source and target database identities without credentials."""

    source_url: str
    target_url: str
    source_database: str
    target_database: str


@dataclass(slots=True, frozen=True)
class ReleaseOperatorInput:
    """Explicit operator input accepted only for apply mode."""

    approval_phrase: str
    actor_id: str
    request_id: str
    idempotency_key: str
    reason: str


class CatalogPromotionReleaseCliError(RuntimeError):
    """Sanitized operator error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main(argv: Sequence[str] | None = None) -> int:
    """Run preview by default or guarded apply when explicitly requested."""
    _configure_stdout()
    arguments = _parse_arguments(argv)
    try:
        return asyncio.run(_run(arguments, os.environ))
    except (
        CatalogPromotionImportError,
        CatalogPromotionManifestError,
        CatalogPromotionReleaseCliError,
        CatalogPromotionReleaseError,
        ValueError,
    ) as error:
        code = getattr(error, "code", "invalid_configuration")
        print(f"FAILED [{code}]: {error}")
        return 2
    except SQLAlchemyError:
        print("FAILED [database_error]: database operation failed.")
        return 2
    except Exception as error:  # pragma: no cover - defensive release boundary
        print(
            "FAILED [unexpected_error]: release aborted safely "
            f"({type(error).__name__})."
        )
        return 2


async def _run(
    arguments: argparse.Namespace,
    environment: Mapping[str, str],
) -> int:
    configuration = load_database_configuration(environment)
    source_tenant_id = _load_uuid(environment, SOURCE_TENANT_ID_ENV)
    target_tenant_id = _load_uuid(environment, TARGET_TENANT_ID_ENV)
    source_engine = create_async_engine(configuration.source_url)
    target_engine = create_async_engine(configuration.target_url)
    try:
        await _require_migration_head(source_engine, label="source")
        await _require_migration_head(target_engine, label="target")
        source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
        target_sessions = async_sessionmaker(target_engine, expire_on_commit=False)
        release_service = CatalogPromotionReleaseService(
            create_postgres_repository_scope(source_sessions),
            create_postgres_repository_scope(target_sessions),
        )
        preview = await release_service.preview(
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
        )
        _print_preview(configuration, preview, apply=arguments.apply)
        if not arguments.apply:
            _print_required_guards(configuration.target_database, preview)
            return (
                0
                if preview.preflight.status
                is not CatalogPromotionPreflightStatus.BLOCKED
                else 3
            )

        operator = validate_apply_guards(
            environment,
            target_database=configuration.target_database,
            preview=preview,
        )
        result = await release_service.apply(
            preview,
            approval_phrase=operator.approval_phrase,
            context=AdminCommandContext(
                tenant_id=target_tenant_id,
                actor_id=operator.actor_id,
                actor_type=AdminActorType.PLATFORM_ADMIN,
                elevated=True,
                request_id=operator.request_id,
                idempotency_key=operator.idempotency_key,
            ),
            reason=operator.reason,
        )
        if not result.verified:
            print(
                "FAILED [postcondition_failed]: import committed but "
                "verification failed."
            )
            return 4
        public_reads = await _verify_public_reads(
            target_sessions,
            preview,
        )
        if public_reads != len(preview.manifest.products):
            print(
                "FAILED [public_read_failed]: imported products are not fully visible."
            )
            return 5
        print()
        print("CATALOG PROMOTION RELEASE VERIFIED")
        print(f"Action: {result.imported.action_id}")
        print(f"Replay: {'yes' if result.imported.replayed else 'no'}")
        print(f"Products visible: {public_reads}")
        print(f"Links verified: {result.verification.links_present}")
        print("Credentials copied: no")
        return 0
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


def load_database_configuration(
    environment: Mapping[str, str],
) -> ReleaseDatabaseConfiguration:
    """Validate two distinct PostgreSQL URLs without exposing credentials."""
    source_url = _require_environment(environment, SOURCE_DATABASE_URL_ENV)
    target_url = _require_environment(environment, TARGET_DATABASE_URL_ENV)
    source = _validate_database_url(source_url, SOURCE_DATABASE_URL_ENV)
    target = _validate_database_url(target_url, TARGET_DATABASE_URL_ENV)
    if _database_identity(source) == _database_identity(target):
        raise CatalogPromotionReleaseCliError(
            "database_identity_conflict",
            "Source and target must be distinct PostgreSQL databases.",
        )
    return ReleaseDatabaseConfiguration(
        source_url=source_url,
        target_url=target_url,
        source_database=source.database or "",
        target_database=target.database or "",
    )


def validate_apply_guards(
    environment: Mapping[str, str],
    *,
    target_database: str,
    preview: CatalogPromotionReleasePreview,
) -> ReleaseOperatorInput:
    """Require every independent mutation guard before constructing a command."""
    expected_backup, expected_monitoring = release_guard_phrases(
        target_database,
        preview.target_tenant_id,
    )
    checks = (
        (
            APPLY_ENABLED_ENV,
            environment.get(APPLY_ENABLED_ENV, ""),
            "1",
        ),
        (
            EXPECTED_TARGET_DATABASE_ENV,
            environment.get(EXPECTED_TARGET_DATABASE_ENV, ""),
            target_database,
        ),
        (
            BACKUP_CONFIRMATION_ENV,
            environment.get(BACKUP_CONFIRMATION_ENV, ""),
            expected_backup,
        ),
        (
            MONITORING_CONFIRMATION_ENV,
            environment.get(MONITORING_CONFIRMATION_ENV, ""),
            expected_monitoring,
        ),
        (
            APPROVAL_PHRASE_ENV,
            environment.get(APPROVAL_PHRASE_ENV, ""),
            preview.approval_phrase,
        ),
    )
    for name, actual, expected in checks:
        if not compare_digest(actual, expected):
            raise CatalogPromotionReleaseCliError(
                "release_guard_failed",
                f"{name} does not match the current release preview.",
            )
    return ReleaseOperatorInput(
        approval_phrase=preview.approval_phrase,
        actor_id=_require_environment(environment, ACTOR_ID_ENV),
        request_id=_require_environment(environment, REQUEST_ID_ENV),
        idempotency_key=_require_environment(environment, IDEMPOTENCY_KEY_ENV),
        reason=_require_environment(environment, REASON_ENV),
    )


def release_guard_phrases(
    target_database: str,
    target_tenant_id: UUID,
) -> tuple[str, str]:
    """Return target-bound backup and monitoring attestations."""
    target = f"{target_database}:{target_tenant_id}"
    return (
        f"BACKUP VERIFIED FOR {target}",
        f"MONITORING READY FOR {target}",
    )


async def _verify_public_reads(
    target_sessions: async_sessionmaker[AsyncSession],
    preview: CatalogPromotionReleasePreview,
) -> int:
    scope = create_postgres_public_read_repository_scope(target_sessions)
    visible = 0
    async with scope() as repositories:
        service = PublicProductReadService(repositories.products)
        for product in preview.manifest.products:
            detail = await service.get_product(product.id, preview.target_tenant_id)
            if detail is not None:
                visible += 1
    return visible


async def _require_migration_head(engine: AsyncEngine, *, label: str) -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    expected = _migration_head()
    if revision != expected:
        raise CatalogPromotionReleaseCliError(
            "migration_mismatch",
            f"{label.capitalize()} database is not at the repository Alembic head.",
        )


def _print_preview(
    configuration: ReleaseDatabaseConfiguration,
    preview: CatalogPromotionReleasePreview,
    *,
    apply: bool,
) -> None:
    print("=== CATALOG PROMOTION RELEASE ===")
    print(f"Mode: {'APPLY' if apply else 'PREVIEW'}")
    print(f"Source database: {configuration.source_database}")
    print(f"Target database: {configuration.target_database}")
    print(f"Source tenant: {preview.source_tenant_id}")
    print(f"Target tenant: {preview.target_tenant_id}")
    print(f"Manifest digest: {preview.manifest.digest}")
    print(f"Products: {len(preview.manifest.products)}")
    print(f"Links: {len(preview.manifest.links)}")
    print(f"Preflight: {preview.preflight.status.value}")
    print(f"Required mutations: {preview.preflight.required_mutations}")
    for issue in preview.preflight.issues:
        print(f"BLOCKED: {issue.code.value} [{issue.resource}]")


def _print_required_guards(
    target_database: str,
    preview: CatalogPromotionReleasePreview,
) -> None:
    backup, monitoring = release_guard_phrases(
        target_database,
        preview.target_tenant_id,
    )
    print()
    print("Preview is read-only. To apply, review the plan and rerun with --apply.")
    print(f"{EXPECTED_TARGET_DATABASE_ENV}={target_database}")
    print(f"{BACKUP_CONFIRMATION_ENV}={backup}")
    print(f"{MONITORING_CONFIRMATION_ENV}={monitoring}")
    print(f"{APPROVAL_PHRASE_ENV}={preview.approval_phrase}")
    print(f"{APPLY_ENABLED_ENV}=1")
    print("Actor, request, idempotency key, and reason are also required.")


def _validate_database_url(raw_url: str, variable: str) -> URL:
    try:
        url = make_url(raw_url)
    except (ArgumentError, ValueError) as error:
        raise CatalogPromotionReleaseCliError(
            "invalid_database_url",
            f"{variable} is not a valid database URL.",
        ) from error
    if url.drivername != "postgresql+asyncpg" or not url.database:
        raise CatalogPromotionReleaseCliError(
            "invalid_database_url",
            f"{variable} must use postgresql+asyncpg and name a database.",
        )
    return url


def _database_identity(url: URL) -> tuple[str, str, int | None, str]:
    return (
        url.drivername,
        (url.host or "").lower(),
        url.port,
        url.database or "",
    )


def _load_uuid(environment: Mapping[str, str], variable: str) -> UUID:
    raw_value = _require_environment(environment, variable)
    try:
        return UUID(raw_value)
    except ValueError as error:
        raise CatalogPromotionReleaseCliError(
            "invalid_tenant_id",
            f"{variable} must be a UUID.",
        ) from error


def _require_environment(environment: Mapping[str, str], variable: str) -> str:
    value = environment.get(variable, "").strip()
    if not value:
        raise CatalogPromotionReleaseCliError(
            "missing_configuration",
            f"{variable} is required.",
        )
    return value


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head() or ""


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or apply a guarded catalog promotion release.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Enable mutation only when every environment guard also matches.",
    )
    return parser.parse_args(argv)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
