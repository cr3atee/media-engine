from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.config.settings import PollingRetentionSettings
from scripts.check_api_health import check_api_health
from scripts.check_worker_health import check_worker_health
from scripts.run_mediaengine_worker import _wait_for_shutdown

ROOT = Path(__file__).resolve().parents[2]


def run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Run async deployment-boundary checks without an async pytest plugin."""
    return asyncio.run(awaitable)


def test_polling_retention_settings_are_disabled_without_policy() -> None:
    configuration = PollingRetentionSettings()

    assert configuration.enabled is False
    assert configuration.interval_seconds is None
    assert configuration.retain_for_seconds is None


def test_enabled_polling_retention_requires_complete_policy() -> None:
    with pytest.raises(ValidationError, match="explicit values"):
        PollingRetentionSettings(enabled=True)


def test_enabled_polling_retention_accepts_explicit_policy() -> None:
    configuration = PollingRetentionSettings(
        enabled=True,
        interval_seconds=86_400,
        retain_for_seconds=7_776_000,
        keep_latest_per_integration=10,
        batch_size=500,
        retry_count=1,
        retry_delay_seconds=5,
        timeout_seconds=60,
    )

    assert configuration.enabled is True
    assert configuration.batch_size == 500
    assert configuration.timeout_seconds == 60


def test_worker_shutdown_wait_returns_when_event_is_set() -> None:
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        shutdown_event.set()
        await _wait_for_shutdown(shutdown_event, duration_seconds=None)

    run_async(scenario())


def test_worker_shutdown_wait_honors_bounded_duration() -> None:
    async def scenario() -> None:
        await _wait_for_shutdown(asyncio.Event(), duration_seconds=0.001)

    run_async(scenario())


def test_api_health_requires_ready_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://127.0.0.1/health/ready")

    def ready_response(url: str, *, timeout: float) -> httpx.Response:
        assert timeout == 1
        return httpx.Response(200, json={"status": "ok"}, request=request)

    monkeypatch.setattr(httpx, "get", ready_response)

    check_api_health(str(request.url), timeout_seconds=1)


def test_api_health_rejects_not_ready_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", "http://127.0.0.1/health/ready")

    def unavailable_response(url: str, *, timeout: float) -> httpx.Response:
        return httpx.Response(200, json={"status": "not_ready"}, request=request)

    monkeypatch.setattr(httpx, "get", unavailable_response)

    with pytest.raises(RuntimeError, match="not ready"):
        check_api_health(str(request.url), timeout_seconds=1)


def test_worker_health_requires_fresh_scheduler_metrics(tmp_path: Path) -> None:
    metrics_file = tmp_path / "worker.prom"
    observed_at = time.time()
    metrics_file.write_text(
        'mediaengine_scheduler_job_state{job="polling",state="succeeded"} 1\n',
        encoding="utf-8",
    )
    os.utime(metrics_file, (observed_at - 5, observed_at - 5))

    check_worker_health(
        metrics_file,
        max_age_seconds=10,
        observed_at=observed_at,
    )


def test_worker_health_rejects_stale_metrics(tmp_path: Path) -> None:
    metrics_file = tmp_path / "worker.prom"
    observed_at = time.time()
    metrics_file.write_text(
        "mediaengine_scheduler_job_state 1\n",
        encoding="utf-8",
    )
    os.utime(metrics_file, (observed_at - 20, observed_at - 20))

    with pytest.raises(RuntimeError, match="stale"):
        check_worker_health(
            metrics_file,
            max_age_seconds=10,
            observed_at=observed_at,
        )


def test_catalog_release_compose_service_is_manual_and_fail_closed() -> None:
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    service = compose.split("  catalog-release:\n", maxsplit=1)[1].split(
        "\n  api:\n", maxsplit=1
    )[0]

    assert 'profiles: ["catalog-release"]' in service
    assert 'restart: "no"' in service
    assert (
        'entrypoint: [".venv/bin/python", '
        '"scripts/run_catalog_promotion_release.py"]' in service
    )
    assert "command: []" in service
    assert "ports:" not in service
    assert "volumes:" not in service
    assert "\n      DATABASE_URL:" not in service

    for variable in (
        "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_DATABASE_URL",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE_URL",
        "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_TENANT_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_TENANT_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_APPLY",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE",
        "MEDIAENGINE_CATALOG_PROMOTION_BACKUP_CONFIRMATION",
        "MEDIAENGINE_CATALOG_PROMOTION_MONITORING_CONFIRMATION",
        "MEDIAENGINE_CATALOG_PROMOTION_APPROVAL_PHRASE",
        "MEDIAENGINE_CATALOG_PROMOTION_ACTOR_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_REQUEST_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_IDEMPOTENCY_KEY",
        "MEDIAENGINE_CATALOG_PROMOTION_REASON",
    ):
        assert f"{variable}: ${{{variable}:-}}" in service


def test_catalog_release_environment_example_contains_no_operator_values() -> None:
    environment = (ROOT / "docker" / "production.env.example").read_text(
        encoding="utf-8"
    )

    for variable in (
        "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_DATABASE_URL",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE_URL",
        "MEDIAENGINE_CATALOG_PROMOTION_SOURCE_TENANT_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_TENANT_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_APPLY",
        "MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE",
        "MEDIAENGINE_CATALOG_PROMOTION_BACKUP_CONFIRMATION",
        "MEDIAENGINE_CATALOG_PROMOTION_MONITORING_CONFIRMATION",
        "MEDIAENGINE_CATALOG_PROMOTION_APPROVAL_PHRASE",
        "MEDIAENGINE_CATALOG_PROMOTION_ACTOR_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_REQUEST_ID",
        "MEDIAENGINE_CATALOG_PROMOTION_IDEMPOTENCY_KEY",
        "MEDIAENGINE_CATALOG_PROMOTION_REASON",
    ):
        assert f"{variable}=\n" in environment


def test_quality_workflow_is_read_only_and_uses_isolated_postgres() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )

    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@v7.0.1" in workflow
    assert "actions/setup-python@v7.1.0" in workflow
    assert "astral-sh/setup-uv@v10.3.3" in workflow
    assert "uv sync --frozen --dev" in workflow
    assert "mypy --explicit-package-bases" in workflow
    assert "python -m pytest" in workflow
    assert "verify_epic21_deployment.py" in workflow
    assert "verify_epic24_catalog_release_postgres.py" in workflow
    assert "postgres:17.10" in workflow
    assert "epic24_release_source_ci" in workflow
    assert "epic24_release_target_ci" in workflow
    assert "secrets." not in workflow
    assert "@127.0.0.1:5432/epic24_release_source_ci" in workflow
    assert "@127.0.0.1:5432/epic24_release_target_ci" in workflow
