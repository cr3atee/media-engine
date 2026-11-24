# EPIC 25 - Activation Condition Review

Verified on 2026-11-22. This is the human entry boundary for the existing
activation-compatibility value, not a new matching engine or automatic approval.

## Working Cabinet

Open `http://127.0.0.1:8001/terminal/review` and use **Условия активации**.
This is the source review environment, not the separate published catalog on
`localhost:8000`. Existing review queue cards also open the form for their exact
marketplace offer. Already-linked active offers can be loaded by marketplace
and external ID; a pending canonical proposal is not required.

1. Load the exact announcement and check its title, marketplace ID, price and
   source link. Prices, titles, availability and canonical links are read-only.
2. Read the source description or obtain explicit seller confirmation. Enter
   countries or worldwide scope with exclusions, device, plan, period, delivery
   method, account requirements, VPN requirement and activation deadline.
3. Record the factual basis. Missing facts are not permission to choose any
   country/account, no VPN or no deadline. Leave an incomplete profile unknown.
4. Check the confirmation summary before saving. Escape/cancel preserves the
   draft and submits nothing. An explicit reset returns the whole profile to
   unknown and records a separate audit.

Country codes have readable country-name previews. `P1M` and `P30D` remain
distinct. An explicit one-hour deadline persists as `3600` seconds. No key,
account password or marketplace session cookie belongs in the evidence field.
The UI follows the existing cabinet/catalog tokens and controls, not a redesign.

## Service And API Boundary

`OfferActivationReviewService` reuses the existing repository scope, tenant
authorization, administrative journal and transaction locks. GET/POST use:

```text
/api/v1/tenants/{tenant}/catalog/offers/{marketplace}/{external_id}/activation-conditions
```

Only the existing `catalog_review` permission grants access: tenant owner,
administrator or reviewer. Operator/viewer and foreign-tenant requests cannot
use the form/API; client-provided role headers do not grant access.

Writes require the displayed offer UUID, condition-audit revision, full source
fingerprint, explicit profile (or explicit null), factual reason and idempotency
key. The service compares the source snapshot again and atomically updates only
the conditions. PostgreSQL uses an UPDATE guarded by every ParsedOffer source
field and active availability; a source refresh cannot be overwritten by saving
an older form. The memory repository has the same guarded behavior.

The audit stores the actor, reason, source fingerprint, complete pre-change
source snapshot, requested profile and resulting revision in the same
transaction. Snapshot/profile chunks are base64-encoded to preserve exact
boundaries through the existing metadata normalization. Base64 is not encryption
or redaction: these are authorized source facts, not a secret storage mechanism.
An audit failure rolls back the profile update.

An identical idempotency replay returns the original action; changing its body
or actor conflicts. The browser freezes the original body/key while a result is
uncertain and offers a same-command retry. Source/revision conflicts require a
fresh load instead of silently retrying against newer data. Session/tenant
changes clear the panel's pending target and sensitive form contents.

## Migration

`0028_offer_activation_audit` extends the existing admin action check for
`set_offer_activation_conditions`. There is no offer backfill or data rewrite.
An UPDATE/DELETE trigger protects rows of this new action kind. Older audit
kinds retain their existing repository-level append-only behavior; this change
does not claim global database immutability or protection from a database owner,
TRUNCATE, trigger removal or external privileged administration.

A clean database can downgrade to `0027` and upgrade again. A downgrade with
retained activation-review audits intentionally fails rather than deleting
history. Its transactional rollback preserves revision `0028` and the trigger.

## Actual Checks

- Full Pytest: `891 passed, 65 skipped`; existing guarded skips and the existing
  Starlette/httpx deprecation warning are not claimed passed or fixed.
- Strict MyPy: `575` files; changed-file Ruff/format and Node syntax pass.
- Offline real-form converter: `29` assertions, including unknown/missing facts,
  explicit no-VPN/unlimited, country sets, exact period units and custom plans.
- Isolated PostgreSQL `17.10`: `20/20` checks on repeated fresh-process runs,
  covering JSONB, tenant isolation, safe selection, audit/revision persistence,
  idempotency, conflicting commands, UPDATE/DELETE protection, rollback, source
  CAS and resetting to unknown. Only synthetic fixtures are modified.
- Separate headless Edge browser: `23/23` checks against a fixture-only app,
  including real login/API, native validation, confirmation/cancel, keyboard
  focus, lost HTTP response after actual DB commit, exact same-key retry,
  concurrent revision conflict, reset and session restoration. Desktop/mobile
  screenshots were inspected. Device emulation/accessibility-tree checks are
  not physical-phone or real screen-reader certification.
- Existing three-product catalog browser acceptance: `127/127`, no runtime/CSP
  errors and application GETs only. No new catalog product was introduced.
- Deployment wiring verifier: `38/38`. CI now includes the offline form
  assertions; its existing isolated PostgreSQL step runs the expanded verifier.
- Alembic: clean upgrade, current/check, clean downgrade/upgrade, offline SQL,
  and expected rollback of a downgrade with retained new audit rows passed.
- Both existing local databases were backed up outside Git and migrated to
  `0028`, with the new trigger checked. Backup files were listed/read; restore
  of these new pre-migration backups is not claimed. Existing offer, product,
  canonical-decision and admin-audit checksums remained identical in both DBs.
- The real reviewer can read the original unresolved FunPay offer. No real
  activation profile or canonical decision was submitted by verification.

Verification exposed missing raw-SQL protection for the new audit kind; the
unreleased migration was corrected before applying it to the real local DBs.
Early browser harness runs also exposed test-only navigation timing and fixture
marketplace-selection mistakes; these were fixed in the verifier, not hidden
as successful runs. They did not change any real source data.

The PostgreSQL verifier remains opt-in and rejects non-loopback/non-test names:

```powershell
$env:ACTIVATION_TEST_DATABASE_URL = '<isolated epic25_activation_* asyncpg URL>'
$env:DATABASE_URL = $env:ACTIVATION_TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts/verify_activation_conditions_postgres.py
node scripts/verify_activation_review_form.mjs
```

To reproduce the browser mutation test, set a test-only password through
`ACTIVATION_REVIEW_TEST_PASSWORD` before running the PG verifier. Its optional
fixture seed creates only `activation-reviewer@example.test` in the guarded test
database, with reviewer access to the synthetic tenant. Start a separate app on
loopback port `8002` against that same DB using a test-only auth secret and a
separate temporary Chromium profile/debugging port. Do not reuse a personal
browser profile. Then run:

```powershell
$env:ACTIVATION_REVIEW_BROWSER_URL = 'http://127.0.0.1:8002'
$env:ACTIVATION_REVIEW_BROWSER_MUTATIONS = 'TEST_FIXTURES_ONLY'
$env:TERMINAL_CDP_URL = 'http://127.0.0.1:9224'
node scripts/verify_activation_review_browser.mjs
```

The script rejects ports `8000`/`8001`, checks the fixture identity/title and
only mutates `activation-fixture-2` in the synthetic tenant. It clears cookies
only in that dedicated test browser. Screenshots go to OS temporary storage,
not the repository. Stop the test app/browser and remove only disposable test
databases afterward; retain both user-facing databases and their volume.

## Remaining Boundary

The subsequent [2026-11-24 source audit](EPIC_25_ACTIVATION_SOURCE_EVIDENCE.md)
captured nine actual descriptions and identified concrete eligibility facts
that the current value cannot yet encode. In particular, do not discard
active-subscription/trial/IP-history restrictions or treat gift links as keys
when filling this form. A free-text reason is not a comparator guard; keep an
incompletely representable profile unknown.

All real offer profiles remain unknown. This form neither fetches source pages
nor proves a seller's claims, resale permission, net profit or current stock.
Saving terms does not confirm a canonical match, publish a proposal or copy it
into the separate catalog. Fresh ingestion without current profile evidence
continues to clear old conditions by the existing safety rule.

Automatic complete source mapping, condition-aware promotion manifests, public
variant selection, condition-aware historical analytics and verified equivalent
FunPay/Playerok launch offers remain unfinished. The public catalog still has
exactly three GGSEL offers at the existing source prices, not a demonstrated
multi-marketplace resale opportunity. Next: collect and review actual source
conditions before promoting any equivalent alternative.
