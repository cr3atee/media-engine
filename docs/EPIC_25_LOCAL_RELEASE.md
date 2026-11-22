# EPIC 25 - Local First Version

Verified on 2026-11-22. The user explicitly selected a local launch, not a VDS
or public-domain deployment.

## Running Version

- Catalog: `http://localhost:8000/terminal`.
- Original review cabinet: `http://127.0.0.1:8001/terminal/review`.
- PostgreSQL container: `mediaengine-epic25-manual-review`, bound to loopback
  port `55435`; its existing named volume retains both databases.
- Original review database: `epic23_catalog_review_epic25_manual`.
- Separate catalog database: `epic23_catalog_review_epic25_local_catalog`.
- Both databases now use revision `0027_offer_activation_conditions`; the
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

No longer-duration products, Minecraft launch products, unreviewed canonical
products, invented discounts or additional marketplace offers were added.

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
with unknown/different conditions produces no asserted best offer or savings.
Single-offer prices and the three-product catalog remain unchanged. See
`EPIC_25_ACTIVATION_COMPARABILITY.md` for checks and the still-unfinished source
mapping, review input and variant-selection UI.

The first local three-product catalog is available for user acceptance. This
does not mean the whole long-term MediaEngine roadmap or public launch is done.
Only GGSEL offers are present for this assortment; Playerok/FunPay filters are
honestly empty. There is one offer per product, so no cross-seller savings are
claimed. Price history can be empty and is not fabricated. The local launcher
does not start a scheduled ingestion worker: Refresh rereads persisted data,
not the marketplaces. Public delivery-method filtering, public asset-use approval,
VDS deployment, production monitoring and live Telegram delivery remain outside
this local acceptance boundary. No external AI or Telegram call was made.
