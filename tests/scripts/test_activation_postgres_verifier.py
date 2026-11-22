from __future__ import annotations

import pytest

from scripts.verify_activation_conditions_postgres import (
    DATABASE_ENV,
    main,
    require_isolated_database,
)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:password@example.com/epic25_activation_test",
        "postgresql+asyncpg://user:password@127.0.0.1/production",
        "sqlite:///epic25_activation_test",
    ],
)
def test_verifier_rejects_non_disposable_targets(url: str) -> None:
    with pytest.raises(ValueError):
        require_isolated_database(url)


def test_missing_database_is_not_a_successful_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_ENV, raising=False)
    assert main() == 2
