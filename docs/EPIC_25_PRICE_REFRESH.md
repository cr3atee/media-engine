# EPIC 25 - Bounded Local Price Refresh

Verified on 2026-11-25 (Asia/Vladivostok). This increment updates only the six
explicitly approved GGSEL/FunPay offers in the existing three-product catalog.
It does not expand the assortment, select a new seller, infer activation terms,
calculate resale profit, or call AI/Telegram.

## Scope And Composition

`scripts/run_epic25_price_refresh.py` composes the existing PostgreSQL runtime,
Scheduler, integration-execution job, marketplace application runner, parsers,
repository-backed price history and comparison pipeline. No database migration,
dependency or UI redesign was introduced. Existing unscoped ingestion behavior
is unchanged; scoped refresh is an explicit runner option.

| Product | GGSEL ID | FunPay ID |
| --- | --- | --- |
| ExitLag 1 month | `5077855` | `19847269` |
| Duolingo Super 1 month | `103585387` | `82381719` |
| Spotify Premium Individual 1 month | `102361507` | `79355854` |

The launcher requires exactly these three canonical products, six offer links
and six existing active integrations/source mappings. It accepts only the local
catalog database or the explicitly named price-refresh test-database prefix;
the separate review database and non-local production URLs are rejected.
The integration allowlist is applied before invoking runner factories.

Public category responses are fetched outside database transactions. Existing
GGSEL JSON pagination and FunPay listing extraction/normalization are reused.
The category must have complete parser evidence; only the approved identities
are persisted. Other category offers are not added. Disabled/out-of-stock
FunPay listing entries are excluded from refresh input.

Inside one repository scope per source, the runner rechecks active tenant,
integration/source URL, canonical ownership and source classification. The
new additive `get_by_identity_for_update` repository primitive locks the active
PostgreSQL offer before merging its price. This serializes the merge with
concurrent offer review/unlink/retirement. Memory uses its existing scope.

Only a finite positive price with unchanged currency, title, URL, seller ID,
seller name and source category is accepted. The saved offer supplies all other
fields: canonical link, reviewed activation conditions and catalog metadata are
not replaced by unreviewed source data. Missing, duplicate, changed or invalid
input fails that source and retains its old quote/history. No missing-offer
reconciliation, automatic retirement, relinking or reapproval is authorized.

Accepted prices, snapshots, source observations and any existing pipeline event
candidates commit through the existing transactional pipeline. No artificial
historical baseline is generated from an old saved catalog price. This worker
does not run scoring, content generation or publication jobs.

## Polling And Operation

The first retained local worker was started hidden on 2026-11-25. Its initial
next scheduled run was 17:45:06 Asia/Vladivostok (06:45:06 UTC); this is launch
evidence, not a permanent uptime or future execution guarantee. The ordinary
catalog and review servers were left running without reseeding or secret
changes:

- Catalog: `http://localhost:8000/terminal`.
- Separate original review: `http://127.0.0.1:8001/terminal/review`.
- PostgreSQL: retained `mediaengine-epic25-manual-review`, loopback port `55435`.
- Target database: `epic23_catalog_review_epic25_local_catalog`.
- Review database: `epic23_catalog_review_epic25_manual`, not refreshed here.

The worker is a local process, not a Windows startup service or VDS deployment.
It stops when its process/computer stops. Do not start a second copy. Existing
PostgreSQL Scheduler leases remain enabled with a per-process owner; the job
has no automatic retry and a 300-second timeout.

Use an existing local asyncpg connection URL supplied outside Git:

```powershell
$env:EPIC25_PRICE_REFRESH_DATABASE_URL = '<local target asyncpg URL>'
.\.venv\Scripts\python.exe scripts/run_epic25_price_refresh.py --check

$env:EPIC25_PRICE_REFRESH_LIVE = 'I_UNDERSTAND_THIS_UPDATES_APPROVED_LOCAL_PRICES'
.\.venv\Scripts\python.exe scripts/run_epic25_price_refresh.py --once
```

For periodic operation, use `--interval-seconds 1800` or a longer interval.
`--defer-first-run` waits that interval before the first source fetch; it was
used after the manual verification pass to avoid an immediate duplicate fetch.
`--duration-seconds` permits a bounded test and `--stop-file <absolute path>`
permits graceful shutdown: creating that control file signals the process to
stop. A control file that already exists prevents polling. Keep the worker's
PID, control path and redirected stdout/stderr as local operational artifacts,
not committed credentials. The actual retained process uses OS-temp logs.

Each outgoing public request is paced at least one second apart. Only HTTPS
`api.ggsel.com`, `funpay.com` and its `www` alias on the standard port are
allowed; credentials in URLs and foreign redirect hosts are rejected. There
are no HTTP retries. HTTP 403/429 pauses that marketplace host for at least one
polling interval (minimum 30 minutes), honoring a longer numeric or HTTP-date
`Retry-After`. The other marketplace remains independent. This is polite
backoff, not an anti-bot bypass or promise of uninterrupted marketplace access.

Cooldown deadlines live in the process, not durable storage. After a restart,
use deferred startup and respect any previously observed longer retry deadline;
automatic recovery of such a deadline across restarts is not implemented.

Per-source outcome, error class, successful/failed timestamps and counts are
durable in the existing integration/polling-run records. Source error bodies
and secrets are not stored in the diagnostic summary. A one-shot partial batch
returns exit code 1. A completed Scheduler batch can still have failed sources;
its outer job-success counter is not evidence that every source refreshed.

## Actual Marketplace Evidence

The 2026-11-24 live batch succeeded for all six approved offers, persisted one
real snapshot/observation per offer, and created no fabricated prior history.
GGSEL category counts were 28/405/97; FunPay counts were 2000/1635/339. The
Spotify FunPay quote changed from its publication price `164.33` to `164.87 RUB`.

The 2026-11-25 batch succeeded for five of six sources:

| Offer | Retained price (RUB) | Latest verification |
| --- | --- | --- |
| GGSEL ExitLag `5077855` | 599.00 | Successfully observed on 2026-11-25 |
| FunPay ExitLag `19847269` | 754.58 | Successfully observed on 2026-11-25 |
| GGSEL Duolingo `103585387` | 50.00 | Successfully observed on 2026-11-25 |
| FunPay Duolingo `82381719` | 100.00 | Successfully observed on 2026-11-25 |
| GGSEL Spotify `102361507` | 250.00 | Successfully observed on 2026-11-25 |
| FunPay Spotify `79355854` | 164.87 | Previous successful 2026-11-24 quote retained |

The Spotify source failed with `PriceRefreshScopeError`. A subsequent read-only
diagnostic received HTTP 200 and complete listing evidence for category `1217`,
but found zero instances of that exact offer ID. This does not establish that
the offer is permanently deleted or why it is absent. No replacement seller,
fake availability or newly refreshed Spotify FunPay price is claimed.

After the two batches, the target has three products, six offers, eleven real
snapshots and six source-observation rows. All five baseline hash collections
match: products, canonical decisions, admin audit, source rules and offer fields
excluding price. The target retains zero copied canonical decision records and
four promotion audit records. Local backups were retained before live writes;
the original review database and `tmp/` were not modified.

## Verification

- Focused offline tests: **43 passed**, including price-only merge, scope
  rejection, inactive sources, review/link protection, pacing, 403/429 handling,
  destination guards, CLI validation and exactly-once launcher shutdown.
- Isolated restored PostgreSQL 17.10 copy: **59 checks passed**. Synthetic quotes
  exist only in that disposable test database. Verified rollback of
  price/history/observation, concurrent review row locking, unlink protection,
  actual Scheduler delegation, fresh-engine reads and unchanged audit/products.
  No marketplace, AI or Telegram calls were made by this verifier.
- Real deferred launcher start/stop on the test copy passed without network
  calls. Verification exposed a duplicate Scheduler stop call in the new
  launcher; it was fixed and covered by a regression test.
- Full Pytest: **956 passed, 65 skipped**, with the existing Starlette/httpx
  deprecation warning. Guarded skips are not claimed passed.
- Strict MyPy: **581 source files passed**. Changed-file Ruff and format: all
  **9 Python files passed**.
- Test-copy Alembic current: `0028_offer_activation_audit` (head); `alembic check`
  found no new upgrade operations. No schema change was needed.
- Real retained-catalog browser: **151 checks passed**, read-only application
  requests, no runtime/CSP errors, desktop/mobile, keyboard and 200% zoom.
  Source rows, actual spreads and history screenshots were inspected. The first
  run timed out waiting for a mobile animation; the unchanged rerun passed.
  This intermittent browser timing issue was not hidden by disabling the gate.

## Public Per-Offer Evidence (2026-11-25)

The public offer projection/API now exposes two nullable UTC timestamps:

- `price_observed_at`: the latest snapshot for this exact tenant, marketplace
  and external ID, only when its price and currency match the saved quote.
- `source_failed_at`: a later unresolved failure of the exact source identified
  by the offer's tenant-owned classification rule. A later/equal successful
  source run or a newer quote observation suppresses an old failure.

Missing/mismatched history stays unknown; a product's latest successful source
cannot supply a different offer's timestamp. Missing, foreign or mismatched
source rules do not borrow another integration's failure. Internal error text,
integration IDs, credentials and tenant IDs are not added to the public DTO.
These are read projections over existing repositories, not new persistence or
polling semantics. Comparison selection, prices and source links are unchanged.

Working catalog and preview share one presentation helper and the existing
style tokens. Each source row shows its observation date with an explicit
browser-local timezone and machine-readable UTC `<time>`. An unresolved failure
adds a short saved-price warning; the comparison also warns when some source
prices did not refresh. No green/live freshness promise or invented age is
displayed. Legacy payloads without evidence show unknown time safely.

The local API was updated without reseeding or changing its signing secret;
the previous configuration was retained in memory, not committed. A staging
read verified all six timestamps before the catalog server on port 8000 was
restarted. The independent 8001 review server and 30-minute worker continued
running. Actual catalog API verification reports three products, six timestamped
offers and one source failure for the retained Spotify FunPay quote. All five
metadata/audit hash collections still match; periodic real history may advance.

Verification for this follow-up:

- New offline Python tests: **15 passed**, covering current-quote evidence,
  source recovery, missing/mismatched history, marketplace/tenant isolation,
  API redaction and timezone validation. One existing exact API fixture was
  updated for the two new nullable response fields.
- Shared UI renderer: **25 offline checks passed**, now included in CI; invalid,
  naive and injection-like date values cannot invent a timestamp or markup.
- Extended restored-copy PostgreSQL verifier: **65 checks passed**, including
  exact per-offer timestamps after fresh-engine reads, existing rollback,
  concurrent review/unlink and Scheduler checks. Synthetic test prices remain
  isolated from the public catalog.
- Full Pytest: **971 passed, 65 skipped**, with the unchanged Starlette/httpx
  deprecation warning. Strict MyPy: **582 files passed**.
- Changed-file Ruff and format: **7 Python files passed**; JavaScript syntax
  checks, deployment verifier **38/38**, and Alembic schema check pass.
- Real retained-catalog browser: **160 checks passed**, including each pair's
  individual timestamps, truthful failure warning, comparison notice and mobile
  bounds. No runtime/CSP errors; all application requests GET. Desktop/mobile
  Spotify screenshots were inspected. The initial animation wait timed out at
  the last product screenshot; the unchanged rerun passed without disabling
  animation checks. That intermittent verifier timing debt remains.

The local `/health/ready` response currently reports `status=not_ready` with
HTTP 200 even though its database/migration/repository components are
`ok/head/configured`. The health implementation and settings were not changed
by this follow-up. Do not treat the working local catalog as proof of production
readiness; readiness response consistency is a separate operational follow-up.

## Remaining Boundary

This is periodic refresh of a curated selection, not marketplace-wide cheapest
offer discovery. It does not add Playerok, new products, longer durations,
credential import, AI browsing, Telegram sending or production deployment.
Duolingo invitation-link delivery and original marketplace titles remain visible;
unknown activation profiles remain unknown. Comparisons remain `price_only`,
not verified equivalence or resale profit.

The browser's Refresh action rereads persisted data; it does not launch a
marketplace fetch. The background process updates that data separately. Product
`updated_at` is an aggregate, not proof that every source refreshed. Per-offer
evidence is now visible as described above, but it is not a promise of present
availability or full activation equivalence. Review of the missing exact source
remains open; do not silently substitute an unapproved offer or label all six
prices fresh.
