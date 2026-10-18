"""Verify EPIC 21 deployment wiring without external marketplace calls."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import PollingRetentionSettings, SchedulerSettings
from app.domain.marketplace_polling import (
    MarketplacePollingRun,
    MarketplacePollingRunStatus,
)
from app.runtime.bootstrap import create_memory_runtime_components
from app.runtime.process import RuntimeJobConfig, RuntimeProcess
from app.runtime.worker import register_marketplace_polling_retention_job
from app.services.marketplace_polling_retention import (
    MarketplacePollingRetentionBatch,
)
from scripts.check_worker_health import check_worker_health
from scripts.run_mediaengine_worker import _wait_for_shutdown

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
TENANT_A_ID = UUID("55000000-0000-4000-8000-000000000001")
TENANT_B_ID = UUID("55000000-0000-4000-8000-000000000002")
INTEGRATION_A_ID = UUID("55000000-0000-4000-8000-000000000011")
INTEGRATION_B_ID = UUID("55000000-0000-4000-8000-000000000012")


@dataclass(slots=True)
class Verifier:
    """Count named deployment assertions."""

    checks: int = 0

    def check(self, condition: bool, label: str) -> None:
        """Record one successful assertion or fail with its stable label."""
        if not condition:
            raise RuntimeError(f"EPIC 21 deployment verification failed: {label}.")
        self.checks += 1
        print(f"PASS: {label}")


async def _verify_runtime(verifier: Verifier) -> None:
    configuration = PollingRetentionSettings()
    verifier.check(not configuration.enabled, "retention is opt-in by default")
    try:
        PollingRetentionSettings(enabled=True)
    except ValidationError:
        verifier.check(True, "enabled retention rejects an incomplete policy")
    else:
        verifier.check(False, "enabled retention rejects an incomplete policy")

    explicit = PollingRetentionSettings(
        enabled=True,
        interval_seconds=86_400,
        retain_for_seconds=7_776_000,
        keep_latest_per_integration=1,
        batch_size=10,
        retry_count=1,
        retry_delay_seconds=5,
        timeout_seconds=60,
    )
    verifier.check(explicit.retain_for_seconds == 7_776_000, "policy is explicit")
    retain_for_seconds = explicit.retain_for_seconds
    keep_latest = explicit.keep_latest_per_integration
    batch_size = explicit.batch_size
    if retain_for_seconds is None or keep_latest is None or batch_size is None:
        raise RuntimeError("Explicit retention configuration was incomplete.")

    components = create_memory_runtime_components(
        SchedulerSettings(lease_enabled=False, tick_seconds=0.01)
    )
    process = RuntimeProcess(components)
    async with components.repository_scope_factory() as repositories:
        for run in _polling_runs():
            await repositories.marketplace_polling_runs.save(run)

    register_marketplace_polling_retention_job(
        process,
        retain_for_seconds=retain_for_seconds,
        keep_latest_per_integration=keep_latest,
        batch_size=batch_size,
        config=RuntimeJobConfig(
            interval_seconds=explicit.interval_seconds,
            retry_count=explicit.retry_count,
            retry_delay_seconds=explicit.retry_delay_seconds,
            timeout_seconds=explicit.timeout_seconds,
        ),
    )
    verifier.check(
        process.list_schedule_statuses()[0].interval_seconds == 86_400,
        "retention job uses the configured schedule",
    )

    await process.execute_once("marketplace-polling-retention")
    result = process.get_last_result("marketplace-polling-retention")
    verifier.check(
        isinstance(result, MarketplacePollingRetentionBatch),
        "Scheduler stores the retention batch result",
    )
    if not isinstance(result, MarketplacePollingRetentionBatch):
        raise RuntimeError("Retention result type was not preserved.")
    verifier.check(result.tenant_count == 2, "all history tenants are included")
    verifier.check(result.deleted_count == 2, "expired runs are removed per tenant")
    verifier.check(not result.batch_limit_reached, "bounded pass reports its limit")

    async with components.repository_scope_factory() as repositories:
        remaining_a = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_A_ID,
            INTEGRATION_A_ID,
            limit=10,
        )
        remaining_b = await repositories.marketplace_polling_runs.list_by_integration(
            TENANT_B_ID,
            INTEGRATION_B_ID,
            limit=10,
        )
    verifier.check(len(remaining_a) == 1, "tenant A newest run is preserved")
    verifier.check(len(remaining_b) == 1, "tenant B newest run is preserved")

    shutdown_event = asyncio.Event()
    shutdown_event.set()
    await _wait_for_shutdown(shutdown_event, duration_seconds=None)
    verifier.check(True, "graceful shutdown wait honors a termination event")


def _verify_deployment_files(verifier: Verifier) -> None:
    compose_path = ROOT / "docker-compose.production.yml"
    environment_path = ROOT / "docker" / "production.env.example"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = compose_path.read_text(encoding="utf-8")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(environment_path),
        "-f",
        str(compose_path),
        "config",
        "--quiet",
    ]
    unconfigured_environment = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "ADMIN_API_KEY",
        "ADMIN_CURSOR_SIGNING_KEY",
        "AUTH_ACCESS_TOKEN_SECRET",
    ):
        unconfigured_environment.pop(name, None)
    unconfigured = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=unconfigured_environment,
    )
    verifier.check(
        unconfigured.returncode != 0,
        "production Compose rejects missing secrets",
    )
    configured_environment = unconfigured_environment | {
        "DATABASE_URL": (
            "postgresql+asyncpg://verification:verification@"
            "127.0.0.1:5432/epic21_deployment_verify"
        ),
        "ADMIN_API_KEY": "verification-admin-key",
        "ADMIN_CURSOR_SIGNING_KEY": "verification-cursor-key",
        "AUTH_ACCESS_TOKEN_SECRET": "verification-auth-key",
    }
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=configured_environment,
    )
    verifier.check(completed.returncode == 0, "production Compose is valid")
    verifier.check("uv sync --frozen --no-dev" in dockerfile, "image uses uv lock")
    verifier.check("USER mediaengine" in dockerfile, "image runs as non-root")
    verifier.check('SCHEDULER_LEASE_ENABLED: "true"' in compose, "leases are enabled")
    verifier.check("$${HOSTNAME}.prom" in compose, "replicas use unique metric files")
    verifier.check("/health/ready" in compose, "API readiness is configured")
    verifier.check("check_worker_health.py" in compose, "worker health is configured")
    verifier.check("stop_grace_period" in compose, "shutdown grace is configured")
    verifier.check("metrics-collector" in compose, "textfile collection is configured")
    policy = _read_environment(environment_path)
    retry_budget = float(policy["WORKER_POLL_TIMEOUT_SECONDS"]) * (
        int(policy["WORKER_POLL_RETRY_COUNT"]) + 1
    ) + float(policy["WORKER_POLL_RETRY_DELAY_SECONDS"]) * int(
        policy["WORKER_POLL_RETRY_COUNT"]
    )
    verifier.check(
        float(policy["SCHEDULER_LEASE_TTL_SECONDS"]) >= retry_budget,
        "polling lease covers timeout and retry budget",
    )
    verifier.check(
        float(policy["WORKER_STOP_GRACE_PERIOD"].removesuffix("s")) >= retry_budget,
        "worker grace covers timeout and retry budget",
    )


def _verify_worker_health(verifier: Verifier) -> None:
    with tempfile.TemporaryDirectory(prefix="mediaengine-epic21-") as directory:
        metrics_file = Path(directory) / "worker.prom"
        observed_at = time.time()
        metrics_file.write_text(
            'mediaengine_scheduler_job_state{job="polling",state="succeeded"} 1\n',
            encoding="utf-8",
        )
        os.utime(metrics_file, (observed_at - 1, observed_at - 1))
        check_worker_health(
            metrics_file,
            max_age_seconds=10,
            observed_at=observed_at,
        )
        verifier.check(True, "fresh worker metrics pass health")
        try:
            check_worker_health(
                metrics_file,
                max_age_seconds=0.5,
                observed_at=observed_at,
            )
        except RuntimeError:
            verifier.check(True, "stale worker metrics fail health")
        else:
            verifier.check(False, "stale worker metrics fail health")


def _read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if not separator:
            raise RuntimeError(f"Invalid deployment environment entry: {name}.")
        values[name] = value
    return values


def _polling_runs() -> tuple[MarketplacePollingRun, ...]:
    return (
        _polling_run(1, TENANT_A_ID, INTEGRATION_A_ID, days_ago=120),
        _polling_run(2, TENANT_A_ID, INTEGRATION_A_ID, days_ago=1),
        _polling_run(3, TENANT_B_ID, INTEGRATION_B_ID, days_ago=120),
        _polling_run(4, TENANT_B_ID, INTEGRATION_B_ID, days_ago=1),
    )


def _polling_run(
    number: int,
    tenant_id: UUID,
    integration_id: UUID,
    *,
    days_ago: int,
) -> MarketplacePollingRun:
    finished_at = NOW - timedelta(days=days_ago)
    return MarketplacePollingRun(
        id=UUID(int=55_000 + number),
        tenant_id=tenant_id,
        integration_id=integration_id,
        marketplace="ggsel",
        status=MarketplacePollingRunStatus.SUCCEEDED,
        started_at=finished_at - timedelta(seconds=1),
        finished_at=finished_at,
    )


async def main() -> int:
    """Run the complete offline deployment verification."""
    verifier = Verifier()
    _verify_deployment_files(verifier)
    _verify_worker_health(verifier)
    await _verify_runtime(verifier)
    print(
        f"EPIC 21 deployment verification passed: {verifier.checks}/{verifier.checks}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
