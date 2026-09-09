from __future__ import annotations

from uuid import UUID

from app.domain.marketplace import Marketplace
from app.runtime.monitoring import RuntimeMonitor
from app.services.marketplace_application_runner import MarketplaceRunResult
from app.services.marketplace_integration_execution import (
    MarketplaceIntegrationExecution,
    MarketplaceIntegrationExecutionBatch,
)


def test_runtime_monitor_summarizes_marketplace_execution_batch() -> None:
    result = MarketplaceRunResult(
        marketplace=Marketplace.GGSEL,
        offers_received=10,
        offers_persisted=9,
        comparison_results=3,
        snapshots_created=8,
        snapshots_persisted=7,
        skipped_offers=2,
        price_changes_detected=1,
        event_candidates_built=1,
        events_created=1,
        events_existing=0,
        skipped_event_candidates=0,
        event_ids=(UUID("10000000-0000-4000-8000-000000000701"),),
        events_scored=0,
        content_items_generated=0,
        persistence_committed=True,
        errors=("skipped malformed offer",),
    )
    batch = MarketplaceIntegrationExecutionBatch(
        selected_integrations=2,
        executed_integrations=1,
        skipped_integrations=1,
        executions=(
            MarketplaceIntegrationExecution(
                integration_id=UUID("10000000-0000-4000-8000-000000000702"),
                tenant_id=UUID("10000000-0000-4000-8000-000000000703"),
                marketplace="ggsel",
                source_url="https://ggsel.net/catalog",
                executed=True,
                result=result,
            ),
            MarketplaceIntegrationExecution(
                integration_id=UUID("10000000-0000-4000-8000-000000000704"),
                tenant_id=UUID("10000000-0000-4000-8000-000000000703"),
                marketplace="future-market",
                source_url=None,
                executed=False,
                skipped_reason="missing_source_url",
            ),
        ),
    )

    diagnostic = RuntimeMonitor().summarize_marketplace_batch(batch)

    assert diagnostic.selected_integrations == 2
    assert diagnostic.executed_integrations == 1
    assert diagnostic.skipped_integrations == 1
    assert diagnostic.executions[0].run is not None
    assert diagnostic.executions[0].run.offers_received == 10
    assert diagnostic.executions[0].run.events_created == 1
    assert diagnostic.executions[0].run.errors == ("skipped malformed offer",)
    assert diagnostic.executions[1].source_url_present is False
    assert diagnostic.executions[1].skipped_reason == "missing_source_url"
