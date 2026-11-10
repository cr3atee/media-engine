from __future__ import annotations

import pytest

from scripts.verify_epic24_catalog_promotion_postgres import (
    DATABASE_URL_ENV,
    _require_isolated_database,
)


@pytest.mark.parametrize("host", ("localhost", "127.0.0.1", "::1"))
def test_verifier_accepts_isolated_loopback_postgres(host: str) -> None:
    url_host = f"[{host}]" if ":" in host else host
    _require_isolated_database(
        f"postgresql+asyncpg://user:secret@{url_host}/epic24_catalog_promotion_test"
    )


@pytest.mark.parametrize(
    "database_url",
    (
        "sqlite+aiosqlite:///epic24_catalog_promotion_test.db",
        "postgresql+asyncpg://db.internal/epic24_catalog_promotion_test",
        "postgresql+asyncpg://localhost/mediaengine",
    ),
)
def test_verifier_rejects_non_isolated_database(database_url: str) -> None:
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        _require_isolated_database(database_url)
