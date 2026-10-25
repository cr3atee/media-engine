# Working review cabinet verification

Date: 2026-10-25. Scope: `/terminal/review`, its presentation and confirmation
interactions. No backend, repository, authorization policy or migration changes.

## Delivered

- Shared local Onest font, dark catalog tokens and existing marketplace logos.
- Compact header/session, collapsible statistics and visible queue first.
- Clearly labelled source offer and canonical target with full names and IDs.
  The marketplace source link belongs to the source, not the target.
- Native confirmation dialog for create, link, confirm and reject. It repeats
  the exact source, target and supplied facts; cancel is initially focused.
- Tab/Shift+Tab containment, Escape dismissal and opener focus restoration.
- Existing required-reason rules retained. Failures appear beside the form;
  comments survive failed requests and cancellation.
- Existing tokens remain in tab memory. Tenant context, refresh, request
  timeout, endpoint/payload construction and idempotency mechanism preserved.
- UI defect fixed: a failed create request used to re-enable a disabled link
  button even when no canonical target existed. Busy-state restoration now
  preserves each control's prior disabled state.

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

### Results

- Review browser: **42 checks passed**. Login errors, permissions, filtering,
  exact target, escaped titles, safe source links, optional/required facts,
  cancel without submission, keyboard dialog, 409 conflict, 503 retry with
  identical idempotency key, changed ambiguous payload refusal, refresh,
  no-target disabled state, completed queue and logout covered.
- Desktop, 800/390/320 px, native 200% browser zoom and reduced motion passed.
  No runtime/CSP errors. Desktop, mobile and zoom screenshots visually inspected.
- Existing preview + working public catalog: **99 checks passed**, GET only.
- Full Pytest: **570 passed, 58 skipped**. Existing optional integration skips
  remain; this run does not establish that those skipped checks passed.
- Full MyPy with `--explicit-package-bases app scripts tests`: **452 files passed**.
- Ruff and Ruff format check: changed Python test file passed. Ruff does not
  validate JavaScript/CSS; browser checks and Node syntax checks cover JS.
- Existing Starlette/httpx TestClient deprecation warning remains unchanged.

### Real workspace read

The running local API on port 8001 was separately authenticated and read, then
the temporary session was logged out. No catalog decision endpoint was called.
It reported **6 offers, 6 linked offers, 2 canonical products, 6 terminal
decisions, 0 unresolved offers**; FunPay/GGSEL/Playerok each had 2 linked offers.
The seed runner was not executed. User decisions were not reset or replaced.

## Remaining work

This completes the cabinet presentation transfer, not the whole UI plan.
Four product-level roles and durable error diagnostics remain separate work.
Existing owner/admin/reviewer/viewer memberships retain their existing meaning.
Public asset licensing/release review and final integrated acceptance remain.
The real queue is already completed, so this pass intentionally did not perform
new real catalog mutations; browser mutation coverage is fixture-based.
