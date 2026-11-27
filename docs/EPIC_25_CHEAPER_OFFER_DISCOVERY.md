# EPIC 25 - Cheaper Offer Discovery

Implemented on 2026-11-25; candidate detail/quote recheck on 2026-11-27 below.
This increment finds lower listed prices for the same
three monthly subscription hubs. It does not approve equivalence, calculate
resale profit, publish new sources or expand the public assortment.

## Candidate Recheck (2026-11-27)

The original discovery prices below are historical, not current quotes.
Repository reads confirm the retained public catalog still has three products,
six offers and six links. The private review database still has fifteen offers,
six links, three products, six decisions and nine pending offers. Both local
servers report HTTP 200 readiness. No candidate was approved, retired, updated
or promoted by this read-only follow-up.

Nine exact candidate detail pages were requested once through the existing
fetchers and `collect_epic25_activation_evidence.extract_sections`. Anonymous
GETs only, two-second minimum request pacing, no retries; host access denial
would stop further requests to that host. No 403/429 occurred. Six pages yielded
the expected description sections; three returned HTTP 404. Captured descriptions
are seller claims, not a purchase test or guaranteed service delivery.

The existing category ingestion path separately read GGSEL ExitLag and FunPay
Duolingo. Only exact known candidate IDs were inspected; this was not a new
discovery/intake run or a persisted price refresh. Detail evidence was captured
at approximately `13:13 UTC`, and category quotes at `13:14 UTC`
(`23:13` / `23:14 Asia/Vladivostok`).

| Candidate | Detail result / source conditions | Fresh category quote RUB | Recommendation |
| --- | --- | ---: | --- |
| [ExitLag GGSEL 103758568](https://ggsel.net/en/catalog/product/exitlag-1-mesiac-kliuc-podpiski-rossiia-ru-kod-aktivacii-avto-24-7-103758568) | HTTP 200; seller describes a month key for RU-region accounts, self-activation and renewals; Russian IP/account-region and continuous-video warranty requirements | 539.00, previously 449.00 | Candidate for explicit price-only publication, not worldwide equivalence |
| [ExitLag GGSEL 103545290](https://ggsel.net/en/catalog/product/exitlag-kliuc-na-1-mesiac-globalno-avtovydaca-24-7-103545290) | HTTP 200; description offers several country/device variants, not one unrestricted Global key | Not found among 104 returned category offers; old 455.00 is not refreshed | Hold; variant and current quote are unresolved, not proven permanently unavailable |
| [ExitLag FunPay 82792757](https://funpay.com/lots/offer?id=82792757) | HTTP 200; seller requires a new account, VPN, a one-hour activation window and excludes multiple countries including Russia; the description also contains conflicting instructions | Not rechecked; old 208.96 is historical | Do not propose as an ordinary unrestricted key |
| [ExitLag FunPay 71761660](https://funpay.com/lots/offer?id=71761660) | HTTP 404 | Not rechecked; old 214.00 is historical | Do not publish from stale evidence |
| [ExitLag FunPay 83182691](https://funpay.com/lots/offer?id=83182691) | HTTP 404 | Not rechecked; old 199.00 is historical | Do not publish from stale evidence |
| [Duolingo FunPay 82141660](https://funpay.com/lots/offer?id=82141660) | HTTP 200; structured fields say Individual / one month; seller describes invitation-link access on the buyer's account, not a key | 30.00, previously 10.00 | Candidate for explicit price-only publication; plan/delivery equivalence is not certified |
| [Duolingo FunPay 82765333](https://funpay.com/lots/offer?id=82765333) | HTTP 200; account login required to activate a trial; eligibility depends on account history | 18.25 | Exclude from the proposed ordinary-month shortlist; no repository rejection submitted |
| [Duolingo FunPay 81387965](https://funpay.com/lots/offer?id=81387965) | HTTP 200; structured plan is Family, delivery is a gift link; seller disclaims warranty | 28.51 | Keep separate from an Individual comparison; no repository rejection submitted |
| [Spotify FunPay 79021009](https://funpay.com/lots/offer?id=79021009) | HTTP 404 | Not rechecked; old 157.95 is historical | Do not publish from stale evidence |

At recheck start, saved public minima were ExitLag `599 RUB`, Duolingo `50 RUB`
and Spotify `164 RUB`. These are persisted curated prices, not a simultaneous
fresh recheck of all six approved offers. The shortlisted source quotes imply
listed-price gaps of `60 RUB` and `20 RUB` against those saved references, not
resale profit or confirmed activation equivalence. Revalidate before any release.

An explicit question was presented for adding GGSEL `103758568` at `539 RUB`
and FunPay `82141660` at `30 RUB` to their existing canonical products, keeping
the old sellers. No affirmative answer is assumed. Publication must also update
the exact approved-refresh scope and corresponding acceptance checks: the
current launcher intentionally permits only the original six identities. Do not
add public links and leave their worker scope inconsistent.

Local artifacts retain repository baselines, response/section digests, source
descriptions and fresh category quotes outside Git. Existing collector and
source/discovery regression tests pass: **102 passed, 1 guarded PostgreSQL
skip**. No Python, UI, migration, dependency, authentication or database behavior
changed. The full-suite/MyPy/PostgreSQL results below belong to the preceding
implementation verification, not a new rerun of every integration.

### Local Runtime Recovery

During postflight, Docker Desktop and both API processes stopped responding.
The first control read failed with connection refused; this was not recorded
as a successful database check. Docker Desktop was reopened and the existing
PostgreSQL container/volume started without recreating, reseeding or migrating
either database. A startup-time Docker 500 response resolved after waiting for
the daemon to become ready.

Both APIs were relaunched from existing `app.main:app` on loopback ports 8000
and 8001. The review signing key reuses its existing local-runner configuration.
The public process-only signing key was no longer available: a fresh random
local key is now retained encrypted with Windows DPAPI at
`%LOCALAPPDATA%\MediaEngine\local-runtime\catalog-auth-secret.dpapi`, outside
Git and bound to the Windows user/machine. Existing public access tokens may
require refresh/relogin. No password or account was reset. This is local
operational key recovery, not a production secret-management implementation.

The original six-offer worker passed its read-only scope preflight and was
restarted with a 1800-second interval and deferred first run. Its new stop file
is `%LOCALAPPDATA%\MediaEngine\local-runtime\price-refresh.stop`; API/worker
logs are in the same directory. No immediate marketplace refresh or new-source
approval was performed by recovery; reboot-autostart is still not implemented.

After recovery, both readiness URLs return HTTP 200 and the public API exposes
three cards/two offers each. Fresh repository sessions verify the original
public source fields (excluding independently refreshed prices), all private
offer records, products, link counts, decision counts and nine pending proposals
against the pre-read baseline. The initially failed postflight was rerun and
passed. Candidate prices in the private queue remain historical until a later
explicit release operation refreshes its chosen source observations.

## Implemented Boundary

`CheaperOfferDiscoveryService` reads captured approved price references and
orchestrates the existing fetchers, extractors, normalizers and
`BestOfferSelector`. Network access is outside repository transactions. Existing
source rules were moved from the verification scripts into
`subscription_candidate_rules.py`; those scripts re-export their previous
public symbols, and their original strict admission policies remain intact.

- Exactly ExitLag, Duolingo Super and Spotify Premium Individual, one month.
- One tenant, three distinct linked canonical products, valid RUB references
  and the existing subscription hub/section classification are required.
- Six allowlisted category sources; at most three selected candidates per
  source. Selection is by Decimal price, not smallest marketplace ID. Equal
  prices use the existing selector's deterministic tie-breaking.
- Candidates must have a positive finite price, title, seller, numeric source
  identity, category and trusted HTTPS URL. Foreign-tenant, approved, duplicate,
  invalid and other-currency quotes cannot enter selection.
- GGSEL uses its existing complete-category retrieval, bounded to ten pages,
  and existing title/period rules with the shared mixed-language duration
  conflict guard. FunPay uses the category's real `f-time`, `f-type` and
  `f-method` evidence. Explicit non-monthly/conflicting durations, unavailable
  offers, wrong variants and unsupported promotional methods remain excluded.
- Uncertain or different fulfillment is retained only as a review candidate,
  with original source parameters and review reasons in the report. A new
  account, family membership, invitation link or trial must not be called an
  equivalent unrestricted activation key.
- The existing `PollingHttpClient` supplies host allowlisting, pacing, no
  automatic HTTP retries and per-process 403/429 cooldown. A source failure
  reports its sanitized error class and does not hide other source results.

Completeness here means extraction of the returned response, not access to
every marketplace offer. FunPay ExitLag returned 2,000 rows; no marketplace-wide
minimum or pagination coverage beyond that response is claimed. Saved reference
prices may differ from a later periodic refresh.

## Private Review Intake

`CheaperOfferReviewIntakeService` reuses repository scopes, source rules, the
existing matching service and existing human-review queue. It accepts at most
six distinct source reports and eighteen unique candidates, at most three per
source. The active tenant, captured product reference and exact existing source
mapping must agree. Incoming activation profiles and canonical links are
rejected rather than invented or confirmed automatically.

An existing offer-decision advisory lock protects each identity. Existing,
retired or previously reviewed identities are skipped without overwrite or
reactivation. Missing/ambiguous source mapping and unsuitable review routing
are explicit skips. The existing best title match must point to the expected
product; automatic matches are not silently linked. New rows are saved as
unlinked source observations in one atomic transaction. No product, review
decision, canonical link, price snapshot, event or publication is created.

The current title matcher classifies all nine staged real rows as `NO_MATCH`.
They are therefore visible in the existing **Create or link** proposal queue,
with the nearest existing product shown explicitly; this is not nine new
canonical products. Reviewers must check the source and choose deliberately.
Structured delivery parameters/review reasons remain in the discovery JSON;
this increment does not add a new persisted evidence DTO or a new UI panel.

## Operation

`scripts/discover_epic25_cheaper_offers.py` defaults to read-only discovery.
Supply local connection URLs through environment variables, never command-line
credentials or committed files:

```powershell
$env:EPIC25_PRICE_REFRESH_DATABASE_URL = '<existing local public catalog URL>'
$env:EPIC25_CANDIDATE_DISCOVERY_LIVE = 'I_UNDERSTAND_THIS_CONTACTS_GGSEL_AND_FUNPAY'
.\.venv\Scripts\python.exe scripts/discover_epic25_cheaper_offers.py --limit-per-source 3
```

Optional intake additionally requires
`EPIC25_CANDIDATE_REVIEW_DATABASE_URL` and `--stage-review`. Only the retained
separate `epic23_catalog_review_epic25_manual` database or an explicitly named
local `epic23_catalog_review_epic25_discovery_verify_*` database is accepted.
The public target cannot be used for intake. The public-reference preflight
still requires its exact six approved identities.

`--output <new-json-path>` writes only public source facts, captured prices,
review reasons and intake outcomes, never credentials. The parent must already
exist and an existing report is not overwritten. Partial source failure exits
nonzero. Repeating intake skips already-known identities.

Discovery is a guarded one-shot operation, not a new periodic job or a browser
Refresh action. The existing 30-minute worker continues refreshing only the six
approved offers; it does not automatically discover or approve new sellers.

## Real Source Results

All six source requests succeeded in the recorded pass. Reference prices are
the saved minimum among approved offers at scan time, not guaranteed fresh
marketplace minima. `Selected` is bounded to three even when more rows qualify.

| Product | Source | Returned | Monthly screened | Below saved reference | Selected | Reference RUB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ExitLag | GGSEL | 97 | 20 | 11 | 3 | 599 |
| ExitLag | FunPay | 2000 | 637 | 202 | 3 | 599 |
| Duolingo | GGSEL | 27 | 1 | 0 | 0 | 50 |
| Duolingo | FunPay | 357 | 24 | 4 | 3 | 50 |
| Spotify | GGSEL | 403 | 14 | 0 | 0 | 159.16 |
| Spotify | FunPay | 1577 | 313 | 1 | 1 | 159.16 |

Ten selected candidates, nine staged for review:

| Product | Source ID | Saved price RUB | Outcome / evidence caveat |
| --- | --- | ---: | --- |
| ExitLag | GGSEL 104237197 | 300 | Skipped: different source category, no verified mapping |
| ExitLag | GGSEL 103758568 | 449 | Staged: title says RU key, activation terms unconfirmed |
| ExitLag | GGSEL 103545290 | 455 | Staged: title says Global key, activation terms unconfirmed |
| ExitLag | FunPay 83182691 | 199 | Staged: new account, not a confirmed key equivalent |
| ExitLag | FunPay 82792757 | 208.96 | Staged: digital code; restrictions/equivalence still unconfirmed |
| ExitLag | FunPay 71761660 | 214 | Staged: new account, not a confirmed key equivalent |
| Duolingo | FunPay 82141660 | 10 | Staged: individual invitation link |
| Duolingo | FunPay 82765333 | 18.25 | Staged: title identifies trial activation |
| Duolingo | FunPay 81387965 | 28.51 | Staged: family access and gift link |
| Spotify | FunPay 79021009 | 157.95 | Staged: Individual month; delivery method unverified |

The public catalog remains exactly **3 products / 6 offers / 6 links**. Five
public metadata/audit checksum collections match the pre-scan baseline; price
fields are excluded because the independently running approved-offer worker
continues to refresh them. Seven private table collections preserve every old
row; source rules, integrations, products, decisions and audit are unchanged.
The private queue is now **15 offers / 6 links / 3 products / 6 decisions /
9 pending / 0 unqueued**. No approval or public release was executed.

The pre-intake backup was restored into a separate disposable database and
confirmed as **6 offers / 6 links / 3 products / 6 decisions**, at schema head.
Reports, screenshots, hashes and backup remain local operational artifacts,
outside Git. Working databases, volume, APIs, price worker and untracked `tmp/`
are retained unchanged except for the nine new private review observations.

## Verification

- Focused discovery plus original source-rule tests: **90 passed, 1 skipped**.
  The skip is the explicit PostgreSQL guard, exercised separately without skip.
- Fresh PostgreSQL 17.10 isolated test: passed; intake, fresh-session persistence,
  replay, two concurrent workers, rollback, no links/decisions/history creation.
- Alembic clean upgrade/current/check: `0028_offer_activation_audit`, no drift.
  No schema change was required. CI now includes this test in a dedicated DB.
- Full Pytest: **1028 passed, 66 skipped**, with the existing Starlette/httpx
  warning. Other guarded integrations are not claimed passed by this run.
- Strict MyPy: **588 files**; changed-file Ruff and format: **7 Python files**.
- Existing deployment verification: **38/38**, including changed CI wiring.
- Actual cabinet, not API fixtures: login, all nine identities and correct
  nearest-product IDs, exact queue counts, safe source-link destinations,
  desktop/mobile without horizontal overflow, session survives reopening,
  no application runtime/CSP errors and no catalog mutations. Screenshots were
  inspected. A supplemental one-off browser harness had a selector-quoting
  error; after correcting the harness, its unchanged-app rerun passed.

Remaining: human source/fulfillment review and explicit approval/promotion of
any selected replacement or additional seller. This increment alone does not
make the public catalog show the cheapest equivalent offer. Playerok coverage,
automated discovery scheduling, broader assortment, profit calculations and
production deployment are not claimed complete. No AI or Telegram call ran.
