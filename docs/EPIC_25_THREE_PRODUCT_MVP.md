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

For this bounded first release each product has one explicitly reviewed offer.
Original source titles and URLs retain the available delivery evidence. The
optional structured activation profile and comparator guard are now implemented;
the existing source rows still have unknown profiles. All regions are in scope,
but price comparisons require equal explicit region, period, plan, device,
delivery, account, VPN and activation-window conditions. Missing facts are not
permissive defaults. Structured human review input is implemented with audited
condition-only writes; no real profiles were automatically confirmed.
Source-evidence collection, condition-aware promotion and a public variant
picker remain unfinished. MediaEngine does not collect buyer account
passwords or activation keys as part of this catalog. See
[activation comparability](EPIC_25_ACTIVATION_COMPARABILITY.md).

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
