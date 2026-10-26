# Product Access: Server Foundation

Verified on 2026-10-25. This is the server foundation for interface-plan package
2A, not completion of all four-role screens or the full product permission matrix.

## Implemented Boundary

- `User.product_role`: `user`, `partner`, `moderator`, `admin`. These are named
  grants, not an ordered numeric hierarchy. New users must start as `user`.
- Migration `0018_product_roles`, after `0017_marketplace_polling_runs`, gives
  all existing users the unprivileged `user` role. It does not map memberships.
- `ProductRoleService` checks the caller's current enabled user record and
  explicit `admin` role for every command/read. No role header or client menu
  grants access; revocation takes effect for an existing bearer token.
- `GET /api/v1/platform/users/{user_id}/role` returns role, status and version.
- `POST /api/v1/platform/users/{user_id}/role` requires bearer authentication,
  `Idempotency-Key`, a role, expected version and a nonblank reason.
- `GET /api/v1/platform/users/{user_id}/role-audit` returns up to 100 newest audit
  entries. Only current product admins can read them. Fingerprints, replay keys,
  credentials and email addresses are not in these responses.
- `/api/v1/me` reports the persisted product role. There is no bootstrap HTTP
  route and the older environment admin API key does not authorize these routes.

## Atomicity and Safeguards

Role changes, optimistic version increments and immutable audit append share the
existing repository-scope transaction. Audit includes actor, target, old/new role,
old/new version, reason and timestamp. Identical actor-scoped replay returns the
original action; reuse for another command conflicts. Revoked administrators
cannot use replay as a way around authorization.

PostgreSQL uses a `users` table `SHARE ROW EXCLUSIVE` lock for infrequent role and
enabled-state writes. Commands serialize before checking current state, preventing
two admins from simultaneously removing the last active admin. This lock also
briefly blocks other user writes; no network calls happen inside role commands.
Memory commands use the existing serialized, rollback-capable memory scope.

The last enabled product admin cannot be demoted or disabled through these
repository paths. Two admins can demote one of them. No new account-disable API
or tenant membership mutation was introduced.

Audit has actor/key uniqueness, user FKs, version/role checks and a PostgreSQL
trigger rejecting UPDATE, DELETE and TRUNCATE. This is not protection against a
trusted database owner changing the schema or disabling triggers. Runtime DB
credentials should not have schema-owner privileges. Service authorization is
the public boundary; internal repositories remain trusted infrastructure.

## Bootstrap and Deployment

`scripts/bootstrap_product_admin.py` is an explicit trusted-operator tool, not a
user registration path. It requires `PRODUCT_ACCESS_DATABASE_URL` with the
`postgresql+asyncpg` driver and an existing enabled user's UUID. By default it
only inspects role/version and counts explicit administrators.

```powershell
python scripts/bootstrap_product_admin.py --user-id <exact-user-uuid>
python scripts/bootstrap_product_admin.py --user-id <exact-user-uuid> --confirm-user-id <same-uuid> --expected-version <observed-version> --reason "Initial administrator" --idempotency-key <unique-command-key> --apply
```

Only the first administrator can be bootstrapped, under the same lock, and the
operation is audited with `actor_key=bootstrap`. Existing admins, even disabled
ones, prevent a new bootstrap. Identical replay does not grant access again.
Connection errors and malformed URLs are reported without echoing credentials.

Deploy migration 0018 before restarting the new application code. Take the normal
backup first. Downgrading 0018 discards product role assignments and role audit;
the downgrade check below was performed ONLY on the disposable verification DB.
The working catalog/review database was not migrated, reseeded or used for role
assignments. No real user was promoted. The running older app was not restarted.

## Verification Evidence

Isolated Docker PostgreSQL **17.10**, container/volume
`mediaengine-product-access-verify`, loopback port 55439, database
`product_access_test`. No production or user-review database was used.
The temporary container and its dedicated volume were removed after verification.

- Clean upgrade through 0017, insert a legacy test user, upgrade to 0018: that
  user's role is `user` and version remains 1.
- Alembic `current`: `0018_product_roles (head)`; `check`: no new operations.
- Downgrade to 0017 and upgrade to head: passed. PostgreSQL lifecycle test passed
  both before and after the migration round trip.
- Offline `upgrade head --sql`: generated successfully, outside tracked files.
- Focused memory/API suite: 9 passed. Includes all five existing workspace roles,
  including owner/administrator, being denied product-admin access by default.
- PostgreSQL lifecycle test: 1 passed without skip. Verifies fresh-session and
  fresh-engine persistence, bootstrap replay, self-escalation denial, version
  conflicts, fingerprint conflicts, concurrent competing assignments, atomic
  rollback after audit flush, uniqueness, invalid role constraints, immutable
  audit UPDATE/DELETE/TRUNCATE, simultaneous self-demotions, concurrent
  disable/demotion and retention of one enabled administrator.
- Operator CLI inspection: passed without mutations. No working account bootstrap.
- CLI apply without the exact confirmation/version/reason/key: refused. Malformed
  database URL: refused without printing its contents. Legacy role/version and
  the six test audit records remained unchanged after these CLI checks.
- Full offline Pytest: **586 passed, 59 skipped, 1 warning**. The new PostgreSQL
  test is one of these environment-dependent skips and was separately executed
  successfully as described above. Other external integration checks were not
  enabled in this run. Existing Starlette/httpx deprecation warning remains.
- MyPy (`app scripts tests --explicit-package-bases`): **464 files**, no issues.
- Ruff and Ruff format check: all **23 touched Python files** passed.
- `git diff --check`: passed. No new dependency or frontend changes.

Re-run the DB test only on a fresh disposable DB already migrated to head:

```powershell
$env:PRODUCT_ACCESS_TEST_DATABASE_URL = '<explicit loopback test URL>'
python -m pytest tests/repositories/test_product_access_postgres.py -v
```

The test refuses a non-loopback URL, a database not named `product_access_test`,
or pre-existing product admins. It does not drop/truncate tables or clean up an
existing database to make itself pass. Without its explicit URL it skips in the
ordinary offline suite. Recreate the disposable DB for an independent repeat.

## Cabinet Integration: 2026-10-26

The existing `/terminal/review` cabinet now includes an administrator-only
**Access** section using the existing authentication service and role APIs. No
independent login, JavaScript credential storage, new dependency or backend
authorization policy was added.

- Explicit account lookup by UUID, current role/version, four role choices,
  required reason, native confirmation dialog and a read-only audit timeline.
- The dialog names the exact target, old/new role and reason; self-demotion is
  clearly identified. Keyboard focus is contained and Escape returns to the form.
- A missing, disabled or stale target cannot be silently submitted. Conflict
  responses clear the stale editor and require a fresh lookup.
- On an ambiguous network/5xx result, the command stays locked with the same
  idempotency key and body for an explicit retry. Focus checks do not discard an
  uncertain command. This pending state is in memory only, not durable across a
  page reload; after reload inspect the current role/history before a new change.
- Logout, a rejected authorization request or confirmed role revocation clears
  account details and audit. Late responses cannot restore a previous session.
  Focus/visibility checks refresh access while idle; during a pending operation
  server-side authorization remains authoritative. There is no push revocation.
- Account identity is visible without a workspace membership. Product admins
  can manage roles without tenant grants; other roles cannot. Catalog-review
  navigation follows actual tenant permissions, not the product role label.
- UUID lookup is deliberate: no email search or user directory endpoint exists
  in this slice. An account holder can see their own UUID below their name.

Verification used a separate loopback app on port 8003 and isolated headless Edge
with a temporary profile. **All browser API traffic was intercepted with explicit
fixtures**; only static GETs reached the app. These are UI interaction tests, not
additional live PostgreSQL or real-account role assignment evidence.

- `node scripts/verify_product_access_browser.mjs`: **39 checks passed**. Covers
  all four role views, invalid IDs, blank reasons, confirmation/cancel/focus,
  lost-success replay without duplicate audit, version/idempotency/last-admin
  conflicts, malformed responses, disabled targets, token refresh, revocation,
  late responses after logout, self-demotion and safe rendering of audit text.
- `verify_terminal_review_browser.mjs` on the same isolated app: **55 checks
  passed**, preserving existing workspace, queue and mutation behavior.
- Visually inspected desktop, 390px mobile and native 200% zoom screenshots.
  No horizontal overflow; reduced-motion and keyboard behavior passed.
- Full Pytest: **587 passed, 59 skipped, 1 existing deprecation warning**.
- MyPy (`app scripts tests --explicit-package-bases`): **464 files**, no issues.
- Ruff and Ruff format check passed for both touched Python files. Node syntax
  checks passed for the browser modules; `git diff --check` passed.
- No application database was migrated, no existing decisions were changed,
  and no real user was assigned a privileged role during UI verification.

To repeat: serve the current application on a separate loopback port, start a
dedicated Chromium debugging profile on 9224, then run the browser verifier.
`TERMINAL_PREVIEW_URL` defaults to `http://127.0.0.1:8003` and
`TERMINAL_CDP_URL` defaults to `http://127.0.0.1:9224`; non-loopback targets are
refused. Screenshots go to a new OS temporary directory, never into the catalog.

## Browser Session Continuity: 2026-10-27

The cabinet no longer loses authentication when navigation destroys its
in-memory JavaScript state. Browser login, refresh and logout reuse the existing
`AuthenticationService` through a dedicated same-origin transport:

- the rotating refresh token is held only in an `HttpOnly`, `SameSite=Strict`
  session cookie scoped to `/api/v1/auth/browser`;
- JavaScript receives only the short-lived access token and keeps it in memory;
- cookie mutations require the exact request origin plus `X-Terminal-Request`;
- HTTPS is mandatory outside explicit loopback development;
- invalid refresh clears the cookie, and logout revokes the server session;
- no localStorage or sessionStorage fallback was introduced.

An isolated real Edge run with memory repositories passed **9 checks** for
exact catalog/cabinet shell parity, login, cookie visibility and rotation,
cabinet → catalog → cabinet, reload, browser Back, logout and failed restoration
after logout. The existing fixture runs also passed: **59 cabinet checks** and
**39 product-access checks**. Full
Pytest: **596 passed, 59 skipped**; MyPy: **468 files**, no issues. Ruff, Ruff
format, Node syntax and `git diff --check` passed. No application database or
real account was used by the session verifier.

## Local Working Deployment: 2026-10-26

This supersedes the earlier statements that the working database had not been
migrated and no first administrator had been selected. The owner explicitly
selected a new account, approved separate account creation and requested a
private local password-entry window. The email and account identifiers are not
included in this repository documentation.

- Started the existing `mediaengine-epic23-review-postgres` container; no fresh
  catalog seed or reset was executed.
- Saved a custom-format PostgreSQL 17.10 backup under untracked `tmp/backups/`,
  checked its archive listing and computed SHA-256. No dump or credential is
  committed. This was archive readability verification, not a restore rehearsal.
- Upgraded `0017_marketplace_polling_runs` to `0018_product_roles`. Alembic current
  reports head; Alembic check reports no new upgrade operations.
- Before/after: **6 offers, 6 canonical links, 2 canonical products, 6 decisions**.
  Existing account retains product role `user` and its previous memberships.
- Added `scripts/create_local_account.py`, a trusted local operator tool reusing
  the existing repositories and PasswordHasher. It refuses existing emails,
  requires a confirmed email and explicit apply, and limits DB targets to the
  loopback catalog-review namespace. Default execution is inspection only.
- The owner entered the password twice in a separate console with hidden input.
  No password was sent through chat, arguments, environment variables or logs.
  The identity and salted verifier are created in one repository transaction;
  user creation grants no membership and starts with product role `user`.
- Existing guarded bootstrap assigned the selected account `admin`, version 2.
  An identical rerun returned the same audit action; exactly **one** bootstrap
  audit entry exists. No other user was promoted or modified.
- Updated app runs on loopback port 8001 using this database, no seed runner,
  no external API calls and a process-local random signing secret. Restarting
  with a different secret requires users to log in again; production needs a
  persistent managed signing secret and normal deployment configuration.
- Authenticated the old local review account, read its workspace and logged out:
  **6 offers, 6 links, 2 products, 6 decisions, 0 unresolved**. New browser module
  serves HTTP 200. The new administrator's browser login still requires the
  owner to enter their private password; it was not impersonated by the agent.
- Provisioning tests cover initial unprivileged creation, no implicit membership,
  duplicate email refusal without credential replacement, transactional rollback,
  redirected-input rejection and password mismatch retry without secret output.
  Full Pytest: **591 passed, 59 skipped, 1 existing warning**. MyPy: **466 files**,
  no issues. Ruff and format checks passed for the two added Python files.

Example for another explicitly approved new local account (no role grant):

```powershell
# Set PRODUCT_ACCESS_DATABASE_URL privately to the intended local DB first.
python scripts/create_local_account.py --email <new-email>
python scripts/create_local_account.py --email <new-email> --confirm-email <same-email> --apply
```

The account setup is not public signup, email ownership verification or password
recovery. No confirmation email was sent. The proposed email-verification flow
remains separate work; product-admin access came from the operator's explicit
bootstrap approval, not from claiming an email address.

## Remaining Work

The existing tenant permission model remains authoritative for workspace data.
Product `partner`/`moderator` labels do not yet grant new tenant permissions;
existing memberships remain effective even when product role is `user`.
Product `admin` only grants the new product-role administration boundary, not
automatic access to all tenants or conversion of older API-key admin endpoints.

Next: owner acceptance of the new administrator's login and Access section.
The app and static files must be deployed together; the new browser module has
its own explicit asset route. Apply the remaining product permission matrix
without silently revoking or
elevating existing memberships. Then implement durable error diagnostics and
complete browser/release acceptance.
