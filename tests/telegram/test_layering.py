from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").lower()


def test_delivery_contracts_are_database_independent() -> None:
    source = _source("app/delivery/contracts.py")

    assert "sqlalchemy" not in source
    assert "app.repositories" not in source
    assert "app.telegram" not in source


def test_telegram_adapter_has_no_repository_or_scheduler_dependency() -> None:
    source = _source("app/telegram/adapter.py")

    assert "app.repositories" not in source
    assert "app.scheduler" not in source
    assert "sqlalchemy" not in source


def test_formatter_has_no_http_or_telegram_framework_dependency() -> None:
    source = _source("app/telegram/formatter.py")

    assert "httpx" not in source
    assert "aiogram" not in source
    assert "telegram.ext" not in source


def test_core_domain_has_no_telegram_dependency() -> None:
    source = _source("app/domain/publications.py")

    assert "app.telegram" not in source
    assert "telegrambot" not in source
