# EPIC 25 - FunPay Subscription Evidence And Review

Verified on 2026-11-22. Scope: the existing three-product monthly assortment,
not marketplace expansion or automatic canonical approval.

**Latest result, 2026-11-24:** all three monthly products now have separately
user-approved GGSEL/FunPay pairs, with three products and six offers/links.
Duolingo `82381719` was explicitly approved as invitation-link delivery, not a
key, at `100 RUB` beside saved GGSEL `50 RUB`. Source detail and parameters
agree on one month; contradictory alternatives remain excluded. Source has six
decisions and no pending proposal; no new product or permissive profile was
created. Latest real-catalog browser acceptance is `151/151`; detailed audit,
backup restoration and replay evidence are in `EPIC_25_FIRST_MARKETPLACE_COMPARISON.md`.
The smaller catalog states and strict screening results below are historical.

**Current result, 2026-11-24:** the user explicitly approved existing offer
`19847269` for the first price-only comparison. Its live public page/listing
still returned `754.58 RUB`; the existing reviewer API and guarded release
service published it beside GGSEL on the same ExitLag product. There are now
three products, four links and four source decisions, with no pending proposal.
This is not a claim that it is FunPay's cheapest offer or a full equivalence
review. The older candidate-only state below is historical; see
`EPIC_25_FIRST_MARKETPLACE_COMPARISON.md` for current acceptance evidence.

**Subsequent approval on the same date:** Spotify `79355854` is also published,
at a final checked `164.33 RUB` (the approved quote was `164.83`). It is a
one-month Individual account-activation offer with Egypt region, possible VPN
and no active subscription, not verified unrestricted equivalence. The public
price-only difference against saved GGSEL `250.00 RUB` is `85.67 RUB`. At that
step there were three products, five offers/links and five source decisions, with
no pending proposals. Duolingo was single-source; two newly sampled Individual
gift-link descriptions contradict their monthly fields with annual wording.
They were not staged or published. The detailed current audit/QA is in the
same comparison report; the original strict screening below is unchanged.

## Real Sources

The existing `FunPayFetcher` and installed `CategoriesParser` discovered these
categories in FunPay's public catalog; URLs were not guessed:

| Service | Source category | Listing URL |
| --- | --- | --- |
| ExitLag | Subscription, `1568` | <https://funpay.com/lots/1568/> |
| Duolingo | Subscription, `4522` | <https://funpay.com/lots/4522/> |
| Spotify | Premium, `1217` | <https://funpay.com/lots/1217/> |

All three returned HTTP 200. One read-only run returned 2000, 331 and 1535
offers respectively. These counts describe returned listings, not proven
marketplace-wide totals. This verification does not authorize missing-offer
deactivation or claim that the ExitLag listing is not server-capped.

## Retained Evidence

`FunPayExtractor.extract_with_parameters()` now retains the existing parser's
structured source parameters, disabled state and displayed quantity beside the
existing `ParsedOffer`. The old `extract()` / `extract_with_evidence()` contracts,
Decimal price mapping and completeness evidence remain unchanged. Business
fields are still mapped once by the existing extractor.

Source fields include `f-type`, `f-type2`, `f-time` and `f-method`. The guarded
read-only verifier `scripts/verify_epic25_funpay_sources.py` checks those fields
before offering a candidate for review:

- Require exactly one month, the source service's known tier/device filters,
  a trusted offer URL, a positive finite RUB price and seller identity.
- Reject disabled/out-of-stock listings and conflicting duration text. Real
  examples included a one-month filter with a week/year/27-day title. Rejection
  is conservative and may require human investigation rather than guessing.
- Digital code, a ready-made account, and activation involving account access
  are not interchangeable. `Without account login` establishes only the access
  condition; it does not by itself prove a key rather than a gift link.
- Promotional Discord codes are not assumed equivalent to ordinary keys.
- Unknown Duolingo account plan and Spotify fulfillment remain blockers.

This is pre-review candidate screening. It is **not** a new persisted delivery
schema, public delivery filter or universal comparator compatibility guard.
Matching thresholds, price selection and existing comparison logic were not
changed. No seller description is used to auto-create a product identity.

## Current Outcome

**Initial ExitLag review example:** monthly PC digital-code candidates exist.
The original identity-based example was
[FunPay offer 19847269](https://funpay.com/lots/offer?id=19847269),
seller `ralli125`, `754.58 RUB` at the recorded run. Its page returned HTTP 200.
It was not selected for lowest price. It remains a candidate, not an assertion
of equivalence or a recommendation to buy.
The detail page states activation/region restrictions, so the reviewer must
compare these and the device entitlement with the existing
[GGSEL source 5077855](https://ggsel.net/en/catalog/product/podpiska-exitlag-30-dnei-kliuc-rossiia-157-stran-5077855).

**Duolingo:** monthly Super listings exist, including different account plans
and with/without-account-access methods. They were not treated as equivalent
to the current key-labelled launch offer. No Duolingo candidate was queued.

**Spotify:** monthly Individual listings exist, but their listing parameters do
not specify fulfillment. A sampled public detail page described account-access
activation; that does not establish the existing GGSEL offer's method. No
Spotify candidate was queued. Additional detail verification is possible; the
field is not claimed permanently unobtainable.

## Existing Human Review Path

The existing runner accepts mutually exclusive `--epic25-funpay-data`. It reuses
the same tenant-owned integration/rule construction and repository seed as the
GGSEL mode; deterministic GGSEL identity formulas are preserved. Only candidates
passing the source-evidence checks are queued, with no canonical product ID.

```powershell
# Use only the existing isolated local review URL, never a production database.
$env:EPIC23_CATALOG_REVIEW_DATABASE_URL = '<existing local review asyncpg URL>'
.\.venv\Scripts\python.exe scripts/run_catalog_review_postgres.py --epic25-funpay-data --check
```

Two separate real PostgreSQL runs produced the same state:
`4 offers / 3 linked / 1 proposal / 3 decisions`. The only new offer is the
unlinked FunPay ExitLag candidate. Fresh-engine queue reads suggest the existing
`ExitLag 1 month Key` product, ID `dc7a6323-d5fc-5675-a2ff-0fe6ab4a70d1`.
Existing GGSEL rows, canonical products and original decision checksums are
unchanged. The separately published local catalog remains at three products
with one GGSEL offer each; no unapproved FunPay row was published.

Reviewer action at `http://127.0.0.1:8001/terminal/review`: refresh the queues,
open the new FunPay proposal, inspect both source pages and verify device,
region and activation restrictions. If equivalent, choose the shown existing
ExitLag product and record the verified facts. Do not create a fourth product
to bypass missing terms. If equivalence cannot be established, do not link.

## Verification

- Focused extractor, source-screening and runner tests: `50 passed`.
- Full Pytest: `822 passed, 65 skipped`. Existing guarded skips and the existing
  Starlette/httpx TestClient warning are not represented as passed/fixed.
- MyPy: `564` files including Alembic; changed-file Ruff/format pass.
- Live source verifier passed read-only source access for 3/3, not comparable
  coverage for all three subscriptions. No successful response was fabricated.
- Existing read-only post-review PostgreSQL verifier: `55/55`, including fresh
  engine persistence and public reads. Repeated staging created no duplicate
  source offer or decision. Alembic current/check remain clean at `0026`.
- No database schema, repository contract, public UI or comparator redesign.
- No automatic review decision, target promotion, scheduler, AI or Telegram call.

The next gate is the explicit ExitLag review. Broader fulfillment modelling and
verified Duolingo/Spotify equivalents remain unfinished, not silently approved.

## Price-First Correction

The user's intended value is finding supply for resale, not an arbitrary sample
listing. The source verifier now delegates screened candidate selection to the
existing `BestOfferSelector` using `MarketplaceOffer` and
`ProductComparisonInput`. No new comparison algorithm or canonical link is
created. Lowest price wins; equal-price ordering follows the existing selector,
not a separate numeric-ID rule. A blocked listing never becomes eligible just
because it is cheap.

The actual FunPay month button was also checked in a separate browser. Clicking
`1 month` sets `f-time` and filters the loaded listing without a new Fetch/XHR
request. The verifier checks that same structured field rather than guessing
the duration from the title. Browser lazy rendering of 200 rows is not proof
that only 200 offers exist; the returned HTML contained 2000. These observations
do not establish complete marketplace-wide coverage.

A real read-only run after the correction returned:

- ExitLag: 2000 rows, 673 monthly PC variants, 473 screened candidates and 22
  title-duration conflicts.
- Duolingo: 328 rows, 31 monthly Super variants and no review-ready candidate.
- Spotify: 1528 rows, 304 monthly Individual variants and no review-ready
  candidate. Existing method/plan blockers are unchanged.

The minimum screened ExitLag offer was
[82792757](https://funpay.com/lots/offer?id=82792757), seller `BuyerBOBR`,
`208.96 RUB`; its detail page returned HTTP 200. Its description restricts use
to a new account, requires VPN, excludes Russia and requires using the code
within one hour. Other low-priced examples name different country sets. Thus
the listing parameters alone do not establish equivalence to the existing
Russia-including launch product or suitability for holding/reselling inventory.

The cheapest candidate was **not** staged, approved or published. The existing
`754.58 RUB` review example is retained as historical evidence, not advertised
as the cheapest. This correction performs no database mutation and does not
override any human decision. It does not certify sellers, resale permission,
successful activation or net profit. Source price differences do not account
for sale/payment fees, sale price, refund exposure or fulfillment costs.

Current automated checks: focused `61 passed`; full Pytest `833 passed, 65
skipped`; MyPy `564` files; changed-file Ruff/format pass. Existing guarded
PostgreSQL skips and the existing TestClient warning remain unaltered. No schema,
repository, public UI, scheduler, AI or Telegram change was required.
