# Live Marketplace Polling Verification

## Purpose

Record the guarded operational verification of the existing MediaEngine worker
against live public GGSEL, Playerok, and FunPay sources. This verification does
not authorize production credentials, unattended deployment, or automatic
catalog decisions.

## Guardrails

- The verifier requires `EPIC19_POLLING_DATABASE_URL`.
- The database name must start with `epic19_polling_`.
- The schema is recreated before verification, so production databases are
  rejected by name and must never be supplied.
- Marketplace requests use public, unauthenticated source data only.
- The failure probe is verifier-only and confirms that exception text and source
  URLs are absent from runtime diagnostics.
- Each polling tick uses the existing `RuntimeProcess`, Scheduler job, runner
  factories, pipelines, repository scope, and PostgreSQL implementations.

## Verified Sources

| Marketplace | Runtime source | Persisted offers | Persisted snapshots |
| --- | --- | ---: | ---: |
| GGSEL | Minecraft PC keys category HTML | 60 | 60 |
| Playerok | Category-scoped GraphQL items page | 20 | 20 |
| FunPay | Bounded public lot category HTML | 1 | 1 |

Playerok source configuration uses only allowlisted query parameters on the
known GraphQL endpoint. These parameters configure the existing `fetch_items`
operation; they are not forwarded as credentials or arbitrary HTTP parameters.

## Result

The final isolated PostgreSQL 17 run passed `22/22` checks in one Scheduler
tick. It verified:

- all enabled integrations were selected and attempted;
- an intentional integration failure was isolated and safely classified;
- GGSEL, Playerok, and FunPay produced real application input;
- offers and price snapshots committed through existing repositories;
- integration success/failure metadata committed without leaking source URLs or
  exception text;
- Scheduler status and statistics remained available;
- committed data and outcomes survived a fresh SQLAlchemy engine;
- Alembic head, metadata check, and offline SQL generation remained clean.

Focused tests passed `24/24`. Full Pytest passed `466` tests with `58` expected
skips and one pre-existing Starlette deprecation warning. MyPy checked `415`
source files; Ruff and Ruff format passed for all touched Python files.

Transient Playerok and FunPay transport failures were observed during earlier
live attempts. The verifier therefore permits up to three independent Scheduler
ticks and still requires every real marketplace to succeed at least once. This
models recovery at a later polling interval and does not add hidden retries to
the application service.

## Command

```powershell
$env:EPIC19_POLLING_DATABASE_URL = `
  "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/epic19_polling_verify"
.venv\Scripts\python.exe scripts\verify_live_marketplace_polling_postgres.py
```

## Remaining Limitations

- Production monitoring, alert routing, and retained per-run operational history
  are not implemented.
- Authenticated marketplace credential retrieval is not implemented.
- Public source contracts can drift and need continued monitoring.
- Live source success does not prove cross-marketplace product identity; catalog
  links still require explicit human evidence.
