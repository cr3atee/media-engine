# EPIC 25 - Three Product MVP

## Goal

The product's business purpose is to find lower-priced equivalent digital
products as potential supply for resale, not merely display a catalog. Discovery
must prioritize the lowest eligible source price instead of the lowest offer ID.
Region, duration, device, fulfillment and activation conditions still need to
match; the cheapest incompatible offer is not a resale opportunity. Asking-price
differences alone are not net profit or evidence of permission to resell.

Release the smallest useful public catalog: three subscription services and
exactly three canonical products. Real-source verification, human review,
target promotion, and browser acceptance remain as simple as possible.

## Launch Assortment

| Hub | Canonical product | Duration | Section |
| --- | --- | ---: | --- |
| ExitLag | ExitLag - 1 month | 1 month | `subscriptions` |
| Duolingo | Duolingo Super - 1 month | 1 month | `subscriptions` |
| Spotify | Spotify Premium Individual - 1 month | 1 month | `subscriptions` |

Three-, six-, and twelve-month plans are explicitly deferred. They must not
appear in the first release merely to fill the catalog.

## Product Category And Delivery Method

Confirmed on 2026-11-22: all three launch products are subscriptions. A key is
a way to receive or activate a subscription, not a replacement for its product
category. The intended delivery choices are activation on the buyer's existing
account, delivery of a new account, and an activation key. They are distinct
purchase conditions and must not be presented as interchangeable offers.

The original local release had one explicitly reviewed offer per product.
On 2026-11-24 the user approved FunPay `19847269` as a second ExitLag source;
the catalog then had three products and four offers, without a new product.
The subsequently approved FunPay Spotify `79355854` brought the total to five.
The final separately approved Duolingo `82381719` brings the current total to
six: one GGSEL and one FunPay offer per product. No fourth product exists.
Original source titles and URLs retain the available delivery evidence. The
optional structured activation profile and comparator guard are now implemented;
the existing source rows still have unknown profiles. On 2026-11-24 the user
confirmed that the selected products are sufficient for the first version and
that exhaustive activation/seller questioning must not block it. The public
catalog can now rank prices of offers already linked to a product despite
unknown conditions, returning explicit `price_only` status and a short notice.
Known conflicting profiles and mixed currencies still block a common minimum.
Strict equivalence comparison remains the comparator's default for other
callers. Missing facts stay unknown; no profile is filled with permissive
defaults. Structured human review input is implemented with audited
condition-only writes; no real profiles were automatically confirmed.
Source-evidence collection, condition-aware promotion and a public variant
picker remain unfinished. MediaEngine does not collect buyer account
passwords or activation keys as part of this catalog. See
[activation comparability](EPIC_25_ACTIVATION_COMPARABILITY.md).

## Curated Price Comparison (2026-11-24)

For this first version, seller replies, complete activation profiles and proof
of resale permission are not mandatory development/release gates. Existing
human-approved product identities remain the input. New/unlinked alternatives
are not automatically confirmed because they are cheaper.

The existing selector has an explicit unknown-condition allowance. The public
read projection uses it for product cards/details and comparison consistently.
The selected result carries an unverified marker into the existing Decimal
difference service and returns `price_only`, not `complete` equivalence.
Both working UI and preview show the minimum price in the curated selection
and a brief unknown-conditions/price-not-profit notice, with existing styling.

Known complete profiles still cannot contradict one another, even when an
unknown third offer exists. The difference service checks this independently.
Currency, tenant, product identity, active-offer and canonical-link boundaries
are unchanged. Strict default comparison and profile-scoped grouping remain
available; the existing discovery-only opt-out does not silently grant a
verified difference result.

The scope remains three monthly products. This pricing policy alone does not
approve or publish unresolved proposals, fabricate alternatives, change source
prices, or collect account credentials. A single offer keeps its previous
source-price presentation, with no invented spread.

Verification of this increment:

- Focused comparator/public repository/API tests: `55 passed`. They cover
  strict defaults, marked unknown-condition results, known conflicts hidden
  behind an unknown offer, currencies, ties, missing prices and API status.
- Full Pytest: `913 passed, 65 skipped`; the existing guarded skips and
  Starlette/httpx deprecation warning remain unchanged. Strict MyPy: `577`
  files; changed-file Ruff/format and changed JavaScript syntax checks pass.
- Isolated PostgreSQL `17.10`: `21/21` checks, including the marked public
  price-only read, preserved strict default, known-region mismatch, fresh
  sessions, rollback, review audit and concurrency. Clean upgrade to existing
  `0028` and Alembic check pass; no new migration or schema change is needed.
- Browser: `133/133` checks. The original three-product acceptance still runs
  against the real local catalog. Six additional opt-in checks read synthetic
  fixtures from a separate test database/app; they prove the real API and both
  working/preview interfaces show a minimum, spread and warning rather than
  blocking unknown terms. Desktop/mobile screenshots were inspected; these
  remain device emulation, not physical-phone/screen-reader certification.
- Early browser harness runs exposed cross-origin navigation timing and a
  test-helper argument mistake. Those were fixed in the verifier; they were
  not reported as successful runs or as application bugs.

To reproduce the extra read-only browser checks, migrate a disposable loopback
`epic25_activation_*` database and run the existing
`verify_activation_conditions_postgres.py` to seed its synthetic fixtures.
Start a separate app against that database on port `8002`, then use:

```powershell
$env:TERMINAL_PREVIEW_URL = 'http://localhost:8000'
$env:TERMINAL_CDP_URL = 'http://127.0.0.1:9224'
$env:EPIC25_THREE_PRODUCT_ACCEPTANCE = '1'
$env:EPIC25_PRICE_ONLY_TEST_URL = 'http://127.0.0.1:8002'
node scripts/verify_terminal_preview_browser.mjs
```

Use a dedicated temporary browser profile. The optional fixture URL is
loopback-only, rejects working-app ports `8000`/`8001` and verifies fixture
identity before reads. Screenshots stay in OS temporary storage. No synthetic
offers, new canonical decisions or condition confirmations are inserted by
these fixture checks into either real local database.

## First Real Pair (2026-11-24)

The user separately approved the exact FunPay ExitLag proposal for publication.
Existing review and release services now expose GGSEL `5077855` (`599.00 RUB`,
saved quote) and FunPay `19847269` (`754.58 RUB`, freshly source-checked), with
a `155.58 RUB` price-only spread. Three canonical products and all original
GGSEL decisions remain intact. GGSEL's refresh attempt returned 429 and is not
claimed as fresh verification. See
[first marketplace comparison](EPIC_25_FIRST_MARKETPLACE_COMPARISON.md).

The same existing services subsequently published user-approved Spotify FunPay
`79355854` at the final observed `164.33 RUB` (down from the approved `164.83`)
beside saved GGSEL `102361507` at `250.00 RUB`. The marked difference is
`85.67 RUB`, not profit. Source/target backup restoration, one-link rehearsal,
fresh-process review/release replay and eight original-table checksum checks
passed. Real-catalog browser acceptance is now `141/141`; full Pytest remains
`913 passed, 65 skipped`, MyPy `577` files. Duolingo was then GGSEL-only: cheap
new gift-link samples explicitly contradicted the monthly duration. They were
not staged or approved, and no extra release-gate functionality was introduced.

The user subsequently approved the consistent one-month Duolingo invitation
offer `82381719` at `100 RUB`, explicitly not a key-equivalence confirmation.
It is now published beside saved GGSEL `50 RUB` with a `50 RUB` price-only
spread. Three products/six offers and no pending source proposal remain.
Both backups restored, zero-product/one-link rehearsal, fresh-process exact
review/release replay and eight original-table checks pass. All three pairs,
their original titles and both source links pass `151/151` browser checks;
full Pytest remains `913 passed, 65 skipped`, MyPy `577` files. Existing business
services, styling, schema and unknown-condition policy were not changed.

The user also deferred a downloadable/local cookie-import agent and customer
self-hosting. The first version remains a web catalog/comparison service. Local
development preview is not a separate consumer application. Do not start new
desktop/auth-cookie features while completing the bounded web experience.

## Data Rules

- A canonical product may reach the public catalog only after at least one real
  marketplace offer has been collected and explicitly reviewed.
- Prices, discounts, seller identity, availability, marketplace logos, and
  outbound URLs must come from persisted source evidence. No placeholder offer
  or invented commercial value is allowed.
- Source-category rules classify each service hub and the stable
  `subscriptions` section. The one-month duration remains part of canonical
  product identity, not a guessed marketplace category.
- The production target receives only the reviewed three-product manifest
  through the existing EPIC 24 preview, preflight, atomic import, and release
  gate.

## Delivery Sequence

1. Expose ExitLag, Duolingo, and Spotify in the shared catalog taxonomy.
2. Collect one current real one-month offer for each service from available
   integrations.
3. Review names, durations, URLs, prices, and source evidence; create or link
   exactly three canonical products.
4. Produce a three-product promotion manifest and require a clean target
   preflight.
5. Apply the guarded target release, then verify repository-backed public reads.
6. Run desktop/mobile browser acceptance for hubs, product cards, comparisons,
   outbound links, empty/error states, and the three-card upper bound.

## Acceptance Criteria

- Public navigation contains the ExitLag, Duolingo, and Spotify hubs.
- The launch tenant exposes exactly three product cards, one per hub.
- Every card has at least one active real offer with marketplace, price,
  currency, and outbound URL evidence.
- No longer-duration card, Minecraft launch card, placeholder offer, or
  unreviewed source appears in the launch catalog.
- Re-running ingestion or the release command creates no duplicate products,
  links, or audit records.
- Full quality, PostgreSQL release, and browser gates pass on the release SHA.

## Current Status

The three service hubs are part of the shared taxonomy and explicit
ExitLag/Duolingo/Spotify titles resolve to the subscription category. Existing
Minecraft taxonomy remains available for saved rules but is not part of this
launch assortment.

On 2026-11-13 the guarded read-only verifier used GGSEL's current public
`/elastic/goods/categories` contract and proved complete category snapshots for
all three launch sources: ExitLag `80/80`, Duolingo `30/30`, and Spotify
`305/305`. It found `13`, `1`, and `9` exact one-month candidates respectively.
The selected evidence examples contained stable IDs, titles, sellers, RUB
prices, currencies, source categories, and outbound product URLs that each
returned HTTP `200`. The run persisted nothing and made no review decision.
Focused verification passes `19` tests; changed-file Ruff and format pass, full
Pytest passes `766` with `64` guarded skips, and strict MyPy passes across `530`
source files.

### Three-product review preparation (2026-11-21)

`scripts/run_catalog_review_postgres.py --epic25-live-data` now loads only the
three source-verified launch examples into the existing isolated PostgreSQL
review workspace. It uses the existing loopback/database-name guard and is
mutually exclusive with `--aligned-live-data`. The runner persists three
deterministic tenant-owned integrations and source-category rules before saving
classified offers; no database constraint was weakened. It does not approve a
proposal or fabricate a price, duration, seller, or URL.

The reviewer can now supply a clean canonical product name rather than copying
marketplace advertising into the public catalog. The UI requires a nonempty
name, repeats it in the confirmation dialog, and includes it in the request.
The service normalizes whitespace, rejects invalid names, includes an explicit
name in the idempotency fingerprint, and preserves the original offer title.
Clients omitting the optional API field retain the existing fallback behavior.

Verification on 2026-11-21:

- The isolated PostgreSQL 17 review database was restarted and the live runner
  executed twice. Both runs exposed `3 offers / 0 linked / 3 proposals /
  0 decisions`; fresh reads showed exactly `3 integrations / 3 source rules`
  and the correct hub and `subscriptions` section on every offer.
- Alembic current is `0025_catalog_promotion_audit`; `alembic check` detected no
  new upgrade operations. No migration or production mutation was required.
- Focused tests: `66 passed`; full Pytest: `773 passed, 64 skipped`.
  Guarded skips are not claimed as passed. The existing Starlette/httpx
  deprecation warning remains unchanged.
- Strict MyPy passes `556` files including Alembic; changed-file Ruff and format
  pass. Deployment verification passes `38/38`.
- Review browser verification passes `79` fixture-only checks. The first run
  hit a CDP `Runtime.evaluate` timeout during mobile emulation; a repeat passed
  without a code change. Desktop and mobile-dialog screenshots were inspected.
  These are not real catalog decisions or final public three-card acceptance.

At that point, human review, target promotion and final public acceptance were
still pending. The subsequent result is recorded below.

### Human review and category correction (2026-11-22)

The user confirmed all three offers in the separate local review database:
`3 products / 3 active links / 3 confirmed decisions / 0 pending proposals`.
The reviewed names are `ExitLag 1 month Key`, `Duolingo Super 1 Month Key`, and
`Spotify Premium Individual [1 Month]`. These names are preserved rather than
silently replacing the user's choices with the plan's example spelling.

With the user's approval, ExitLag and Duolingo were moved from the `keys`
category to `subscriptions`. Spotify already had that category. A focused
operator-only service uses the existing repository scope and immutable admin
audit; migration `0026_product_category_audit` only extends accepted audit
types. Each correction requires tenant context, elevated operator input,
expected category/audit revision, reason and idempotency key. The local-only CLI
previews by default and requires an exact product-bound approval for apply.
It does not expose a new HTTP administration route.

The separate category audit revision starts at one; it is not a new version
field on the canonical product. Original review decisions are never amended.
An old confirmation request expecting a superseded category can still receive
the existing state-conflict response; replay the correction using its own key,
not the earlier create request. Downgrading below `0026` with retained new audit
rows fails rather than deleting immutable history.

Verification:

- Backed up the local review database before mutation, outside the repository.
- Applied each of the two corrections twice; both replays returned the same
  action IDs and exactly two category audits remain.
- Offer and original decision checksums are unchanged. Existing post-review
  public API/fresh-engine verification passes `55/55` after correction.
- The existing manifest service successfully builds three products and three
  confirmed links, all in the subscription category. The running local public
  API also exposes three products with one offer each. No target was imported.
- Focused memory/CLI/PostgreSQL tests pass `15`, covering rollback, tenant
  isolation, fingerprint/revision conflicts, concurrent commands, replay and
  fresh-engine persistence. PostgreSQL uses a separate disposable database.
- Clean Alembic upgrade/current/check, downgrade/upgrade before audit insertion,
  and offline SQL generation passed. Review current/check also pass at `0026`.
- Full Pytest: `787 passed, 65 skipped`; the new guarded PostgreSQL test was run
  separately without skip. MyPy: `562` files including Alembic. Changed-file
  Ruff/format pass. The existing Starlette/httpx warning remains; an elevated
  initial focused run also reported a pytest cache permission warning, and the
  final focused run passed with cache disabled.

### Local first version (2026-11-22)

The user selected a local first version instead of a VDS/public launch. Fresh
GGSEL evidence still matches the three reviewed IDs and source fingerprints;
all three outbound links return HTTP `200`. A separate persistent local catalog
database was initialized and the existing release service applied the exact
three-product manifest. Target preflight converged to `no_changes`; fresh-process
replay returned the same immutable promotion audit without duplicates. The
source offers, products, decisions and audit checksums remain unchanged.

The running local catalog is `http://localhost:8000/terminal`. The existing
review workspace remains on `127.0.0.1:8001`. Service images and hub navigation
now work for all three products, with the original reviewed names. Expanded
browser acceptance passes `127` checks; full Pytest passes `793` with `65`
guarded skips, MyPy passes `562` files, and focused Ruff/format and JS syntax
checks pass. See [local release evidence](EPIC_25_LOCAL_RELEASE.md) for backup,
replay, startup commands and exact limitations.

Local first-version transfer and browser gates are complete for user acceptance.
Public production deployment, licensed public brand use, automatic local polling
and delivery-method filtering are not claimed complete.

### FunPay evidence and review (2026-11-22)

The three subscription categories are reachable through the existing FunPay
integration. Structured listing parameters are now available beside the existing
ParsedOffer contract and screened for period, device/tier, fulfillment, title
conflicts and availability. Only an ExitLag PC monthly digital-code candidate
was queued in the isolated review database, without creating a link or product.
Two runs retained `4 offers / 3 links / 1 proposal / 3 decisions`; existing
GGSEL/product/decision checksums and the published local catalog are unchanged.
Duolingo plan/method and Spotify fulfillment are not yet verified as equivalent.
This is candidate screening, not a completed runtime delivery-method schema or
automatic comparison guard. Focused tests pass `50`, full Pytest `822` with `65`
guarded skips, MyPy `564` files, and focused Ruff/format pass. PostgreSQL
post-review verification passes `55/55`; Alembic remains `0026` with no drift.
See [FunPay evidence and the one manual review action](EPIC_25_FUNPAY_REVIEW.md).

### Price-first source selection (2026-11-22)

The FunPay review verifier now reuses the existing `BestOfferSelector` instead
of choosing the smallest numeric source ID. Regression checks cover cheaper
high-ID offers, order independence, deterministic price ties and blocked offers.
Live verification selected the cheapest screened ExitLag listing at `208.96 RUB`,
but reading its detail exposed new-account, VPN, region and one-hour-use limits.
It was not staged, linked or published as equivalent to the reviewed launch
product. The previous review row and all human decisions remain unchanged.
This completes the price-ranking correction, not automated resale eligibility
or margin calculation. Focused tests pass `61`, full Pytest `833` with `65`
guarded skips, and strict MyPy passes across `564` files.

### Activation review entry (2026-11-22)

The existing cabinet now supports explicit activation-condition review for an
active offer without changing its title, price or canonical link. Tenant-scoped
permissions, source/revision CAS, same-key replay, rollback and immutable audit
are verified at migration `0028`. The form has no permissive defaults and an
explicit confirmation/reset flow in the existing visual language. Full Pytest
passes `891` with `65` skips, MyPy `575`, isolated PostgreSQL `20/20`, browser
form `23/23` and existing catalog `127/127`; focused Ruff/format pass.
No real profile was filled or new link created. See
[activation review evidence](EPIC_25_ACTIVATION_REVIEW.md) for reproduction and
the still-unfinished real source mapping/promotion boundary.
