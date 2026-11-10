from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest

from app.services.catalog_promotion_manifest import CatalogPromotionManifest
from app.services.catalog_promotion_preflight import CatalogPromotionPreflightResult
from app.services.catalog_promotion_release import CatalogPromotionReleasePreview
from scripts.run_catalog_promotion_release import (
    ACTOR_ID_ENV,
    APPLY_ENABLED_ENV,
    APPROVAL_PHRASE_ENV,
    BACKUP_CONFIRMATION_ENV,
    EXPECTED_TARGET_DATABASE_ENV,
    IDEMPOTENCY_KEY_ENV,
    MONITORING_CONFIRMATION_ENV,
    REASON_ENV,
    REQUEST_ID_ENV,
    SOURCE_DATABASE_URL_ENV,
    TARGET_DATABASE_URL_ENV,
    CatalogPromotionReleaseCliError,
    load_database_configuration,
    main,
    release_guard_phrases,
    validate_apply_guards,
)

TARGET_TENANT_ID = UUID("79000000-0000-4000-8000-000000000001")


def test_database_configuration_requires_distinct_postgres_databases() -> None:
    environment = {
        SOURCE_DATABASE_URL_ENV: (
            "postgresql+asyncpg://source:source-secret@db.internal/mediaengine_source"
        ),
        TARGET_DATABASE_URL_ENV: (
            "postgresql+asyncpg://target:target-secret@db.internal/mediaengine_target"
        ),
    }

    configuration = load_database_configuration(environment)

    assert configuration.source_database == "mediaengine_source"
    assert configuration.target_database == "mediaengine_target"

    environment[TARGET_DATABASE_URL_ENV] = environment[SOURCE_DATABASE_URL_ENV]
    with pytest.raises(CatalogPromotionReleaseCliError) as conflict:
        load_database_configuration(environment)
    assert conflict.value.code == "database_identity_conflict"
    assert "source-secret" not in str(conflict.value)


@pytest.mark.parametrize(
    "database_url",
    (
        "sqlite+aiosqlite:///target.db",
        "postgresql://db.internal/target",
        "not a database url",
    ),
)
def test_database_configuration_rejects_unsupported_urls(database_url: str) -> None:
    environment = {
        SOURCE_DATABASE_URL_ENV: database_url,
        TARGET_DATABASE_URL_ENV: (
            "postgresql+asyncpg://target:secret@db.internal/mediaengine_target"
        ),
    }

    with pytest.raises(CatalogPromotionReleaseCliError) as error:
        load_database_configuration(environment)

    assert error.value.code == "invalid_database_url"
    assert "secret" not in str(error.value)


def test_apply_guards_are_target_and_preview_bound() -> None:
    preview = _preview()
    backup, monitoring = release_guard_phrases(
        "mediaengine_target",
        TARGET_TENANT_ID,
    )
    environment = {
        APPLY_ENABLED_ENV: "1",
        EXPECTED_TARGET_DATABASE_ENV: "mediaengine_target",
        BACKUP_CONFIRMATION_ENV: backup,
        MONITORING_CONFIRMATION_ENV: monitoring,
        APPROVAL_PHRASE_ENV: preview.approval_phrase,
        ACTOR_ID_ENV: "release-operator",
        REQUEST_ID_ENV: "release-request",
        IDEMPOTENCY_KEY_ENV: "release-key-1",
        REASON_ENV: "Reviewed target catalog release",
    }

    operator = validate_apply_guards(
        environment,
        target_database="mediaengine_target",
        preview=preview,
    )

    assert operator.actor_id == "release-operator"
    assert operator.idempotency_key == "release-key-1"

    environment[MONITORING_CONFIRMATION_ENV] = "ready"
    with pytest.raises(CatalogPromotionReleaseCliError) as guard_error:
        validate_apply_guards(
            environment,
            target_database="mediaengine_target",
            preview=preview,
        )
    assert guard_error.value.code == "release_guard_failed"
    assert "ready" not in str(guard_error.value)


def test_cli_error_output_does_not_echo_database_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        SOURCE_DATABASE_URL_ENV,
        "not-a-url-with-database-secret",
    )
    monkeypatch.setenv(
        TARGET_DATABASE_URL_ENV,
        "postgresql+asyncpg://target:target-secret@db.internal/target",
    )

    result = main([])
    output = capsys.readouterr().out

    assert result == 2
    assert "database-secret" not in output
    assert "target-secret" not in output
    assert "invalid_database_url" in output


def _preview() -> CatalogPromotionReleasePreview:
    return CatalogPromotionReleasePreview(
        source_tenant_id=UUID("79000000-0000-4000-8000-000000000002"),
        target_tenant_id=TARGET_TENANT_ID,
        manifest=cast(CatalogPromotionManifest, object()),
        preflight=cast(CatalogPromotionPreflightResult, object()),
        approval_phrase="APPROVE CATALOG PROMOTION digest TO target",
    )
