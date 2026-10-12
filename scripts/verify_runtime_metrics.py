"""Verify dependency-free worker metrics export without external services."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import SchedulerSettings
from app.domain.marketplace_integrations import (
    MarketplaceIntegration,
    MarketplaceIntegrationStatus,
)
from app.domain.tenancy import Tenant
from app.runtime.bootstrap import create_memory_runtime_components
from app.runtime.metrics import PrometheusTextfileWriter
from app.runtime.process import RuntimeProcess
from app.runtime.worker import register_enabled_marketplace_integrations_job
from app.scheduler.jobs import JobExecutionState
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecutionBatch,
)
from scripts.run_mediaengine_worker import _write_metrics

TENANT_ID = UUID("51000000-0000-4000-8000-000000000001")
INTEGRATION_ID = UUID("51000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
SOURCE_URL = "https://example.invalid/catalog?token=must-not-leak"


@dataclass(slots=True)
class Verification:
    """Count deterministic runtime metrics assertions."""

    checks: int = 0

    def expect(self, condition: bool, label: str) -> None:
        """Record one check or stop with a useful diagnostic."""
        if not condition:
            raise RuntimeError(f"Runtime metrics verification failed: {label}.")
        self.checks += 1


async def verify() -> Verification:
    """Execute one real memory-backed worker job and export its metrics."""
    components = create_memory_runtime_components(
        SchedulerSettings(lease_enabled=False, tick_seconds=0.1),
    )
    process = RuntimeProcess(components)
    async with components.repository_scope_factory() as repositories:
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="Metrics verification",
                slug="metrics-verification",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.marketplace_integrations.save(
            MarketplaceIntegration(
                id=INTEGRATION_ID,
                tenant_id=TENANT_ID,
                marketplace="funpay",
                display_name="FunPay verification",
                source_url=SOURCE_URL,
                enabled=True,
                status=MarketplaceIntegrationStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    register_enabled_marketplace_integrations_job(process, runner_factories={})
    job_name = process.list_statuses()[0].name
    await process.execute_once(job_name)
    result = process.get_last_result(job_name)
    if not isinstance(result, MarketplaceIntegrationExecutionBatch):
        raise RuntimeError("Worker did not produce a marketplace execution batch.")

    verification = Verification()
    verification.expect(
        process.list_statuses()[0].state is JobExecutionState.SUCCEEDED,
        "Scheduler job succeeded",
    )
    verification.expect(result.selected_integrations == 1, "one integration selected")
    verification.expect(result.skipped_integrations == 1, "unsupported source skipped")
    with TemporaryDirectory(prefix="mediaengine-metrics-") as directory:
        metrics_path = Path(directory) / "mediaengine.prom"
        writer = PrometheusTextfileWriter(metrics_path)
        _write_metrics(process, job_name, writer)
        payload = metrics_path.read_text(encoding="utf-8")
        verification.expect(
            "mediaengine_scheduler_job_executions_total" in payload,
            "Scheduler counters exported",
        )
        verification.expect(
            'mediaengine_marketplace_batch_integrations{outcome="selected"} 1'
            in payload,
            "batch counts exported",
        )
        verification.expect(
            'marketplace="funpay",outcome="skipped"} 1' in payload,
            "marketplace outcome exported",
        )
        verification.expect(SOURCE_URL not in payload, "source URL omitted")
        verification.expect("must-not-leak" not in payload, "query secret omitted")
        verification.expect(str(TENANT_ID) not in payload, "tenant ID omitted")
        verification.expect(
            str(INTEGRATION_ID) not in payload,
            "integration ID omitted",
        )
        verification.expect(
            payload.endswith("\n"),
            "complete textfile persisted",
        )
        verification.expect(
            tuple(metrics_path.parent.glob("*.tmp")) == (),
            "temporary file removed",
        )
    return verification


def main() -> int:
    """Run the isolated runtime metrics verifier."""
    _configure_stdout()
    try:
        verification = asyncio.run(verify())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "Runtime metrics verification passed: "
        f"{verification.checks}/{verification.checks} checks."
    )
    print("External network, PostgreSQL, Telegram, and AI calls: disabled.")
    return 0


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
