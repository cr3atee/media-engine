# EPIC 25 - Local First Version

Initial launch verified on 2026-11-22; bounded price-refresh update verified on
2026-11-25. The user explicitly selected a local launch, not a VDS or
public-domain deployment. Dated publication prices below are historical.

## Current Price Refresh

`EPIC_25_PRICE_REFRESH.md` records the new opt-in six-offer worker, guards,
operation and full verification. A separate local process now schedules the
existing pipelines every 30 minutes without expanding the catalog. The first
live batch refreshed six of six offers; the 2026-11-25 batch refreshed five.
FunPay Spotify `79355854` was absent from that retrieved listing, so its previous
`164.87 RUB` quote was retained rather than claimed fresh. Other observed quotes were
ExitLag `599/754.58`, Duolingo `50/100` and GGSEL Spotify `250 RUB`.
After those two batches there were eleven real snapshots, still exactly three
products and six offers. A later 2026-11-25 periodic execution recovered the
same Spotify FunPay ID at `161.46 RUB`, observed at `09:02:49 UTC`, and cleared
its public source-failure timestamp. No substitute offer was added; real
history continues accumulating.

Five immutable/metadata hash collections remain unchanged. Full Pytest is
`956 passed, 65 skipped`, MyPy `581` files, isolated PostgreSQL `59/59` and
real-catalog browser `151/151`; focused Ruff/format pass. This is local periodic
operation, not Windows reboot-autostart or a public production deployment.
The subsequent read-side increment now exposes each quote's own observation
time and a newer unresolved source failure. Working/preview rows share the same
style and renderer; Spotify's saved quote is explicitly labelled, with a
comparison warning. Product update time alone does not prove both quotes fresh.
Latest checks: full Pytest `971 passed, 65 skipped`, MyPy `582`, isolated
PostgreSQL `65/65`, renderer `25/25`, real browser `160/160` and focused
Ruff/format. No catalog metadata/audit changes or new products were made.

## Running Version

- Catalog: `http://localhost:8000/terminal`.
- Original review cabinet: `http://127.0.0.1:8001/terminal/review`.
- PostgreSQL container: `mediaengine-epic25-manual-review`, bound to loopback
  port `55435`; its existing named volume retains both databases.
- Original review database: `epic23_catalog_review_epic25_manual`.
- Separate catalog database: `epic23_catalog_review_epic25_local_catalog`.
- Both databases now use revision `0028_offer_activation_audit`; the
  initial launch verification below used `0026`.

Use the distinct hostnames shown above. Cookies do not have port isolation, so
opening both independent authentication databases through the same hostname
would cause their browser-session cookies to conflict. These are separate
local environments, not a production shared-login configuration.

The catalog contains exactly these three reviewed products, all subscriptions:

| Product | GGSEL offer ID | Price at live verification |
| --- | --- | --- |
| ExitLag 1 month Key | `5077855` | `599 RUB` |
| Duolingo Super 1 Month Key | `103585387` | `50 RUB` |
| Spotify Premium Individual [1 Month] | `102361507` | `250 RUB` |

On 2026-11-24 the user explicitly approved FunPay ExitLag offer `19847269` as
a second source for the same existing ExitLag product. It is now published at
`754.58 RUB`, alongside the saved GGSEL `599.00 RUB` quote, with `price_only`
status and a `155.58 RUB` difference. At that first-pair release the catalog had
three products and four offers, not a fourth product. See
`EPIC_25_FIRST_MARKETPLACE_COMPARISON.md` for restored-backup rehearsal,
audit/replay and the source-rate-limit caveat.

The user then explicitly approved Spotify FunPay `79355854`. Its price decreased
from `164.83` to `164.33 RUB` before publication; it is now selected beside the
saved GGSEL `250.00 RUB` quote, with an `85.67 RUB` price-only difference. The
Spotify-step catalog had three products and five offers: two each for ExitLag
and Spotify, one for Duolingo. Restored-backup rehearsal, exact fresh-process
replay and eight original-table checksum checks passed; browser acceptance is `141/141`.

The separately approved Duolingo FunPay `82381719` is now published at `100 RUB`
beside saved GGSEL `50 RUB`, with a `50 RUB` price-only difference. Its original
title identifies invitation-link delivery, not a key. The current catalog has
exactly three products and six offers: GGSEL plus FunPay for each service.
Restored-backup rehearsal, fresh-process API/release replay and eight original
table checks pass; latest browser acceptance is `151/151`. Contradictory-duration
alternatives were not published. This is not a new GGSEL refresh or profit claim.

No longer-duration products, Minecraft launch products, unreviewed canonical
products, invented discounts or unapproved marketplace offers were added.

## Transfer Evidence

The current GGSEL category snapshots contained `85`, `29` and `412` items.
Their exact monthly candidate counts were `20`, `1` and `14`. All three reviewed
IDs were still available and each outbound URL returned HTTP `200`.

Fresh offers were fetched through the existing services, matched to the exact
reviewed identities and source fingerprints, and saved only in the separate
target with their source integrations/rules. No source offer or review decision
was rewritten. Local reviewer credentials were initialized by the existing
local-only seed helper, not copied from the review database.

The existing `CatalogPromotionReleaseService` produced a ready preview with
three products, three links and six required mutations. It applied the exact
target-bound approval through the existing atomic importer and immutable audit.

```text
Manifest digest: 762cbff5893f6201c7ee949fe28dae332556dcdeee14a052fe3cb0e647b4bc96
Promotion action: 6faaccb3-805f-409f-beaf-81453b2077b1
Idempotency key: epic25-local-release-20261122
Postflight: no_changes
Products: 3
Links: 3
```

A second process returned the same action with `replayed=True`. Source offers,
products, original decisions and admin-audit checksums were unchanged.

The pre-import target backup was restored successfully to a separate disposable
database: three fresh offers, zero products and zero admin actions. The backup
is retained outside Git as an OS-local temporary artifact. The restore-check
database was removed; the real source/target databases and volume were retained.

This local operation used the existing application release service, not the
production CLI. No production backup/monitoring attestation was fabricated,
and no production guard was disabled. Local liveness/readiness returned HTTP
`200`; application logs were available. A production monitoring stack is not
claimed to be commissioned.

## Presentation And Acceptance

Three original service images now come from attributed official sources and
are served locally through the existing asset allowlist. Verified hub codes,
not guesses from product titles, select the imagery. Original reviewed names
remain unchanged. Unknown identities retain the neutral placeholder.

The three hub buttons lead to their existing subscription sections. Catalog
spacing was tightened so the first cards remain above the desktop fold after
the hub row becomes visible. Header styling and cabinet design are unchanged.
The live banner no longer describes this subscription catalog as only games.

The opt-in three-product mode of the existing browser verifier checks the exact
upper bound, no hidden extra page, all three service hubs, each subscription
section and its one product, original names/source links, local images and
unknown-identity fallback.

```powershell
$env:TERMINAL_PREVIEW_URL = 'http://localhost:8000'
$env:TERMINAL_CDP_URL = 'http://127.0.0.1:9224'
$env:EPIC25_THREE_PRODUCT_ACCEPTANCE = '1'
node scripts/verify_terminal_preview_browser.mjs
```

Results:

- Browser: `127` checks passed, including desktop, mobile, keyboard, actual
  200% zoom, empty/error/offline recovery and safe outbound links. All
  application requests were GET; no runtime/CSP errors were observed.
- Desktop catalog, mobile catalog and product screenshots were inspected.
- The initial pre-change browser run timed out while waiting for a preview
  animation; a repeat passed `111` baseline checks. Subsequent checks exposed
  the missing service images and below-fold cards and caught an obsolete
  artwork expectation. The final expanded run passes after those fixes; it
  accepts the official Spotify image's original `939 x 940` dimensions inside
  a square `object-fit: contain` frame without editing the logo.
- Full Pytest: `793 passed, 65 skipped`. Guarded skips are not claimed passed.
  The existing Starlette/httpx TestClient warning remains unchanged.
- Strict MyPy including Alembic: `562` files passed.
- Changed-file Ruff/format and Node syntax checks passed.
- Target Alembic upgrade/current/check passed without schema drift.

## Restart

Do not recreate, reseed or drop the source database to restart the site. Start
Docker Desktop if necessary and start the existing PostgreSQL container. Supply
the local target connection URL through `DATABASE_URL`, keep administration
disabled, and reuse the same local access-token secret for session continuity:

```powershell
docker start mediaengine-epic25-manual-review
$env:DATABASE_URL = '<existing local catalog asyncpg URL>'
$env:ADMIN_API_ENABLED = 'false'
$env:ADMIN_API_DOCS_ENABLED = 'false'
$env:AUTH_ACCESS_TOKEN_SECRET = '<same local catalog secret>'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Connection credentials and backups are deliberately not committed to Git.

## Boundary

The all-regions policy now has a persisted optional activation profile and a
shared comparator guard. Legacy rows remain unknown; a multi-offer comparison
with unknown conditions can now return a marked public `price_only` minimum
after the user's 2026-11-24 simplification. Known different conditions still
block the common minimum; the strict comparator default remains unchanged.
Single-offer prices and the three-product catalog remain unchanged. See
`EPIC_25_ACTIVATION_COMPARABILITY.md` for the comparison guard and
`EPIC_25_ACTIVATION_REVIEW.md` for the implemented human review form. Automatic
source mapping, condition-aware transfer and public variant-selection UI remain
unfinished. No real condition profile was confirmed during verification.
Seller replies are optional research rather than a release blocker for this
curated first version. No new/unlinked offer is thereby approved or promoted.

The first local three-product catalog is available for user acceptance. This
does not mean the whole long-term MediaEngine roadmap or public launch is done.
GGSEL covers all three products; FunPay additionally covers the explicitly
approved ExitLag, Spotify and Duolingo pairs. Playerok remains empty for this
assortment. Price differences describe the saved curated selection, not net
profit or a marketplace-wide minimum. Price history now contains real
observations from the bounded refresh; old history was not fabricated. The web
launcher itself does not start ingestion: the separately launched price-refresh
process does. Refresh in the browser rereads persisted data, not marketplaces.
Public delivery-method filtering,
public asset-use approval,
VDS deployment, production monitoring and live Telegram delivery remain outside
this local acceptance boundary. No external AI or Telegram call was made.

First-version delivery is web-only. A local cookie-import agent, downloadable
application and customer self-hosting feature were deferred by the user. Local
development/acceptance URLs above do not imply those features are being built.
