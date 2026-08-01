"""Verify final EPIC 15 admin API integration against isolated PostgreSQL."""

# ruff: noqa: E402
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import httpx
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONFIGURED_DATABASE_URL = os.getenv("EPIC15_DATABASE_URL", "").strip()
if _CONFIGURED_DATABASE_URL:
    os.environ["DATABASE_URL"] = _CONFIGURED_DATABASE_URL

from app.config.settings import AdminApiSettings, settings
from app.database.session import engine
from app.main import create_app
from scripts.verify_epic15_admin_mutations_postgres import (
    Verification,
    _seed_ambiguous_publication,
    _seed_failed_publication,
    _seed_pending_publication,
)
from scripts.verify_epic15_read_api_postgres import (
    _apply_migrations,
    _recreate_schema,
    _require_isolated_database,
    _seed,
)
from tests.repositories.contracts.factories import NOW

DATABASE_URL_ENV = "EPIC15_DATABASE_URL"
ADMIN_KEY = "epic15-final-admin-api-key"


async def main() -> int:
    """Run the final isolated PostgreSQL admin API verification."""
    database_url = _CONFIGURED_DATABASE_URL
    if not database_url:
        print(f"SKIPPED: set {DATABASE_URL_ENV} to an isolated PostgreSQL URL.")
        return 0
    _require_isolated_database(database_url)
    os.environ["DATABASE_URL"] = database_url
    settings.database.url = database_url

    await _recreate_schema(database_url)
    await asyncio.to_thread(_apply_migrations, database_url)
    await _seed(database_url)
    await _seed_dashboard_operational_rows()

    verifier = Verification()
    application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://epic15-final.test",
    ) as client:
        await _verify_health_docs_and_reads(client, verifier)
        await _verify_dashboard(client, verifier)

    await engine.dispose()

    fresh_application = create_app(
        admin_api_settings=AdminApiSettings(
            api_enabled=True,
            api_key=SecretStr(ADMIN_KEY),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fresh_application),
        base_url="http://epic15-final.test",
    ) as client:
        fresh_events = await client.get(
            "/api/v1/admin/events",
            headers=_headers(),
        )
        fresh_dashboard = await client.get(
            "/api/v1/admin/dashboard/summary",
            params=_dashboard_params(),
            headers=_headers(),
        )
    verifier.check("restart/fresh-session event reads", fresh_events.status_code == 200)
    verifier.check(
        "restart/fresh-session dashboard reads",
        fresh_dashboard.status_code == 200,
    )

    total = len(verifier.passed)
    print(f"EPIC 15 final admin API verification: {total}/{total} checks passed.")
    return 0


async def _verify_health_docs_and_reads(
    client: httpx.AsyncClient,
    verifier: Verification,
) -> None:
    headers = _headers()
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")
    admin_ready_missing = await client.get("/api/v1/admin/readiness")
    admin_ready = await client.get("/api/v1/admin/readiness", headers=headers)

    verifier.check(
        "liveness is public and sanitized",
        live.status_code == 200
        and live.json()["status"] == "ok"
        and live.json()["database"] == "not_checked"
        and ADMIN_KEY not in live.text,
    )
    verifier.check(
        "readiness reaches migrated PostgreSQL head",
        ready.status_code == 200
        and ready.json()["status"] == "ok"
        and ready.json()["database"] == "ok"
        and ready.json()["migration"] == "head",
    )
    verifier.check(
        "admin readiness is protected",
        admin_ready_missing.status_code == 401 and admin_ready.status_code == 200,
    )

    openapi_missing = await client.get("/openapi.json")
    docs_missing = await client.get("/docs")
    redoc_missing = await client.get("/redoc")
    openapi = await client.get("/openapi.json", headers=headers)
    docs = await client.get("/docs", headers=headers)
    redoc = await client.get("/redoc", headers=headers)
    paths = openapi.json()["paths"]
    security_scheme = openapi.json()["components"]["securitySchemes"]["AdminApiKey"]

    verifier.check(
        "OpenAPI assets require admin authentication",
        openapi_missing.status_code == 401
        and docs_missing.status_code == 401
        and redoc_missing.status_code == 401,
    )
    verifier.check(
        "authenticated OpenAPI assets are available",
        openapi.status_code == 200
        and docs.status_code == 200
        and redoc.status_code == 200,
    )
    verifier.check(
        "OpenAPI declares admin API key security",
        security_scheme["type"] == "apiKey"
        and security_scheme["in"] == "header"
        and security_scheme["name"] == "X-Admin-API-Key",
    )
    verifier.check(
        "OpenAPI exposes final admin surface",
        "/api/v1/admin/dashboard/summary" in paths
        and "/api/v1/admin/content/{content_id}/approve" in paths
        and "/api/v1/admin/publications/{publication_id}/resolve-ambiguous" in paths,
    )

    missing = await client.get("/api/v1/admin/events")
    invalid = await client.get(
        "/api/v1/admin/events",
        headers={"X-Admin-API-Key": "wrong"},
    )
    events = await client.get("/api/v1/admin/events?limit=1", headers=headers)
    event_body = events.json()["items"][0]
    event_detail = await client.get(
        f"/api/v1/admin/events/{event_body['id']}",
        headers=headers,
    )
    filtered_events = await client.get(
        "/api/v1/admin/events?marketplace=ggsel&min_score=1",
        headers=headers,
    )
    next_page = await client.get(
        "/api/v1/admin/events",
        params={"limit": 1, "cursor": events.json()["next_cursor"]},
        headers=headers,
    )

    verifier.check(
        "read API authentication failures are stable",
        missing.status_code == 401
        and invalid.status_code == 401
        and missing.json()["error"]["code"] == "authentication_required",
    )
    verifier.check(
        "event list detail filters and pagination",
        events.status_code == 200
        and event_detail.status_code == 200
        and filtered_events.status_code == 200
        and next_page.status_code == 200,
    )
    verifier.check(
        "event payload uses typed price-drop DTO",
        event_body["payload"]["type"] == "price_drop"
        and isinstance(event_body["payload"]["old_price"], str)
        and isinstance(event_body["payload"]["previous_snapshot"], dict),
    )

    content = await client.get("/api/v1/admin/content?limit=1", headers=headers)
    content_body = content.json()["items"][0]
    content_detail = await client.get(
        f"/api/v1/admin/content/{content_body['id']}",
        headers=headers,
    )
    content_filter = await client.get(
        "/api/v1/admin/content?generation_status=generated",
        headers=headers,
    )
    publications = await client.get(
        "/api/v1/admin/publications?limit=1",
        headers=headers,
    )
    publication_body = publications.json()["items"][0]
    publication_detail = await client.get(
        f"/api/v1/admin/publications/{publication_body['id']}",
        headers=headers,
    )
    publication_filter = await client.get(
        "/api/v1/admin/publications?channel=telegram",
        headers=headers,
    )

    verifier.check(
        "content list detail filters and pagination",
        content.status_code == 200
        and content_detail.status_code == 200
        and content_filter.status_code == 200
        and (
            content.json()["next_cursor"] is None
            or isinstance(content.json()["next_cursor"], str)
        ),
    )
    verifier.check(
        "publication list detail filters and pagination",
        publications.status_code == 200
        and publication_detail.status_code == 200
        and publication_filter.status_code == 200
        and (
            publications.json()["next_cursor"] is None
            or isinstance(publications.json()["next_cursor"], str)
        ),
    )
    verifier.check(
        "publication read hides operational secrets",
        "claim_token" not in publication_detail.text
        and ADMIN_KEY not in publication_detail.text,
    )

    invalid_cursor = await client.get(
        "/api/v1/admin/events?cursor=invalid",
        headers=headers,
    )
    invalid_dates = await client.get(
        "/api/v1/admin/events",
        params={
            "detected_from": "2026-08-02T00:00:00Z",
            "detected_to": "2026-08-01T00:00:00Z",
        },
        headers=headers,
    )
    correlated = await client.get(
        "/api/v1/admin/events/not-a-uuid",
        headers={**headers, "X-Request-ID": "final-verification-request"},
    )
    verifier.check(
        "cursor and UTC date validation are stable",
        invalid_cursor.status_code == 422
        and invalid_cursor.json()["error"]["code"] == "invalid_cursor"
        and invalid_dates.status_code == 422
        and invalid_dates.json()["error"]["code"] == "validation_error",
    )
    verifier.check(
        "request correlation is returned in errors",
        correlated.status_code == 422
        and correlated.json()["error"]["request_id"] == "final-verification-request",
    )


async def _verify_dashboard(
    client: httpx.AsyncClient,
    verifier: Verification,
) -> None:
    headers = _headers()
    summary = await client.get(
        "/api/v1/admin/dashboard/summary",
        params=_dashboard_params(),
        headers=headers,
    )
    default_summary = await client.get(
        "/api/v1/admin/dashboard/summary",
        headers=headers,
    )
    too_wide = await client.get(
        "/api/v1/admin/dashboard/summary",
        params={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-03-01T00:00:00Z",
        },
        headers=headers,
    )
    reversed_range = await client.get(
        "/api/v1/admin/dashboard/summary",
        params={
            "from": "2026-08-03T00:00:00Z",
            "to": "2026-08-01T00:00:00Z",
        },
        headers=headers,
    )
    body = summary.json()

    verifier.check(
        "dashboard summary endpoint",
        summary.status_code == 200
        and body["window"]["boundary"] == "from_inclusive_to_exclusive",
    )
    verifier.check(
        "dashboard event and content counters",
        body["total_new_market_events"] >= 4
        and body["generated_content_awaiting_review"] >= 1,
    )
    verifier.check(
        "dashboard publication counters",
        body["publications_pending"] >= 1
        and body["publications_retryable"] >= 1
        and body["publications_permanently_failed"] >= 1
        and body["publications_ambiguous"] >= 1,
    )
    verifier.check(
        "dashboard timestamps are bounded and safe",
        body["latest_event_activity_at"] is not None and ADMIN_KEY not in summary.text,
    )
    verifier.check(
        "dashboard default window is valid",
        default_summary.status_code == 200,
    )
    verifier.check(
        "dashboard rejects invalid windows",
        too_wide.status_code == 422
        and reversed_range.status_code == 422
        and too_wide.json()["error"]["code"] == "invalid_dashboard_window",
    )


async def _seed_dashboard_operational_rows() -> None:
    await _seed_failed_publication(201, retryable=True)
    await _seed_failed_publication(202, retryable=False)
    await _seed_ambiguous_publication(203)
    await _seed_pending_publication(204)


def _headers() -> dict[str, str]:
    return {"X-Admin-API-Key": ADMIN_KEY}


def _dashboard_params() -> dict[str, str]:
    return {
        "from": (NOW - timedelta(hours=1)).isoformat(),
        "to": (NOW + timedelta(days=2)).isoformat(),
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
