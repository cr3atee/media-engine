# Working review cabinet verification

Updated: 2026-10-29. Scope: `/terminal/review`, its shared application shell,
browser session continuity, presentation and confirmation interactions. The
repository model, authorization policy and database schema were not changed.

## Delivered

- Shared local Onest font, dark catalog tokens and existing marketplace logos.
- The catalog and cabinet now use the same shell width, header surface, logo,
  wordmark, search, profile slot, spacing, radii, icon treatment, footer and
  responsive breakpoints. Cabinet sections use the same underlined navigation
  pattern as the catalog marketplace row. The project plan records this as a
  permanent cross-screen acceptance rule.
- Compact session area, collapsible statistics and visible queue first.
- Clearly labelled source offer and canonical target with full names and IDs.
  The marketplace source link belongs to the source, not the target.
- Native confirmation dialog for create, link, confirm and reject. It repeats
  the exact source, target and supplied facts; cancel is initially focused.
- Tab/Shift+Tab containment, Escape dismissal and opener focus restoration.
- Each record now asks for one explicit decision before submission. The selected
  action updates the field label, visible example, required state and submit
  label: create is optional, proposal linking and rejection are required, and
  candidate confirmation remains optional. Field errors stay beside the field;
  comments survive failed requests and cancellation.
- Only the short-lived access token remains in tab memory. The rotating refresh
  credential is an `HttpOnly`, `SameSite=Strict` session cookie scoped to the
  browser-auth endpoint. It is not exposed to JavaScript or web storage.
- Reload, browser Back and cabinet → catalog → cabinet restore the identity from
  that cookie. Logout revokes the server session and clears restoration.
- Tenant context, request timeout, endpoint/payload construction and
  idempotency mechanism are preserved.
- UI defect fixed: a failed create request used to re-enable a disabled link
  button even when no canonical target existed. Busy-state restoration now
  preserves each control's prior disabled state.
- Tenant-scoped offer lifecycle controls now let an authorized catalog reviewer
  inspect, retire, or restore one marketplace offer by stable external ID. The
  flow requires a reason, repeats the retained-history consequence before
  confirmation, uses optimistic versioning and preserves one idempotency key
  across an ambiguous retry. Tenant/session invalidation clears the panel.

## Verification boundary

`scripts/verify_terminal_review_browser.mjs` uses the actual served cabinet
HTML/CSS/JS in a separate Chromium CDP tab. Every API request is intercepted
and fulfilled with explicitly isolated fixtures. Only same-origin static GET
requests reach the server; external requests are blocked. It never inserts
test offers or submits decisions to a database. These are frontend behavior
checks, **not new PostgreSQL mutation verification**.

Run with Node 22+ and a dedicated loopback Chromium debugging port:

```powershell
node scripts/verify_terminal_review_browser.mjs
node scripts/verify_terminal_preview_browser.mjs
```

Default review URL: `http://127.0.0.1:8001`; CDP: `http://127.0.0.1:9224`.
Override using `TERMINAL_PREVIEW_URL` and `TERMINAL_CDP_URL`. Screenshots are
saved in a new OS temporary directory, not committed to the repository.
Native browser zoom is restored and test tabs are closed on completion.

`scripts/verify_browser_session.mjs` is a separate real-cookie check. It starts
an isolated loopback app with memory repositories, uses the actual authentication
service and browser cookie jar, and does not intercept authentication requests.

### Results

- Review browser: **72 checks passed**. Login errors, permissions, filtering,
  exact target, escaped titles, safe source links, action-dependent facts,
  cancel without submission, keyboard dialog, 409 conflict, 503 retry with
  identical idempotency key, changed ambiguous payload refusal, refresh,
  no-target disabled state, completed queue and logout covered. The new checks
  also cover lifecycle lookup, current version, required reason, confirmation,
  a failed retire request, explicit retry with the same idempotency key,
  retained-history copy, resulting state and restoration with a new command key.
- Desktop, 800/390/320 px, native 200% browser zoom and reduced motion passed.
  No runtime/CSP errors. Desktop, mobile and zoom screenshots visually inspected.
- Product-access browser: **39 checks passed** after the shared-header change.
- Real-cookie browser: **9 checks passed**. The run covers exact computed shell
  geometry/style parity, an invisible `HttpOnly` refresh credential, catalog
  round-trip, reload, browser Back, rotation, logout and non-restoration after
  logout.
- Existing preview + working public catalog: **99 checks passed**, GET only.
- Full Pytest: **637 passed, 60 skipped**. Existing optional integration skips
  remain; this run does not establish that those skipped checks passed.
- Full MyPy with `--explicit-package-bases app scripts tests`: **489 files passed**.
- Ruff and Ruff format check: all changed Python files passed. Ruff does not
  validate JavaScript/CSS; browser checks and Node syntax checks cover JS.
- Existing Starlette/httpx TestClient deprecation warning remains unchanged.

### Real workspace read

The running local API on port 8001 was separately authenticated and read, then
the temporary session was logged out. No catalog decision endpoint was called.
It reported **6 offers, 6 linked offers, 2 canonical products, 6 terminal
decisions, 0 unresolved offers**; FunPay/GGSEL/Playerok each had 2 linked offers.
The seed runner was not executed. User decisions were not reset or replaced.

## Remaining work

This completes the cabinet presentation transfer and browser navigation-session
repair, not the whole UI plan. Durable error diagnostics remain separate work.
Existing owner/admin/reviewer/viewer memberships retain their existing meaning.
Public asset licensing/release review and final integrated acceptance remain.
The real queue is already completed, so this pass intentionally did not perform
new real catalog mutations; browser mutation coverage is fixture-based.
The known stale FunPay `80145738` row remains pending an authenticated lifecycle
action in its owning tenant database; the new browser panel makes that operation
available but does not silently execute it.

## Access-revocation follow-up

The working cabinet now clears protected state and dialog contents when the API
returns permission denial, `tenant_not_found`, or account disablement. A missing
individual product is not confused with removal of workspace access. Reload
revalidates the context; switching workspaces clears the previous form before
the new response arrives. Context, queue and mutation responses are guarded by
session/workspace generations, including stale failure responses. Logout clears
local identity immediately, without waiting for the network; failed server
revocation is reported rather than claimed successful. Existing administrator
and operator workspace roles have accurate Russian labels, not global-role labels.

Retry keys are scoped by tenant as well as action identity. Switching to another
authorized tenant cannot reuse the first tenant's key for identical marketplace
IDs. Existing idempotency behavior within a tenant remains unchanged.

New browser fixtures exercise read/write revocation, inaccessible tenant,
missing object, account disablement, delayed context and mutation responses,
tenant-specific retry keys and a successful queue response arriving after logout.
All fixture API calls are intercepted; no user decisions or roles are changed.

Seven additional direct API cases cover all five existing workspace roles,
ignored client-supplied role headers/query parameters, foreign-tenant denial,
and revocation of reads and writes for an already-issued access token. The
revocation cases verify that no decision was persisted. Focused auth/catalog/UI
test run: **26 passed**. These tests use isolated memory repositories and do not
claim a new PostgreSQL permissions migration or four-product-role implementation.
