# Playerok VDS Connector

## Status

MediaEngine has a read-only Playerok connector for the existing public GraphQL
`items` operation. It supports public access and an optional tenant-scoped
browser session. The authenticated path is intended for an authorized account
owned by the operator. It does not automate login, solve CAPTCHA, bypass access
controls, or change marketplace data.

The implementation is offline-verified. A live account-backed verification has
not been performed because no authorized session secret was supplied to the
runtime. Playerok can still reject a VDS because session acceptance depends on
the source IP, browser `User-Agent`, current cookies, rate limits, and its access
protection policy. The connector therefore improves operability but does not
claim guaranteed access.

## Runtime Boundary

- PostgreSQL stores only the existing opaque credential reference.
- A reference uses `env://NAME`, where `NAME` is uppercase letters, digits, and
  underscores.
- `EnvironmentMarketplaceCredentialResolver` derives a tenant- and
  integration-scoped variable:

  ```text
  MEDIAENGINE_MARKETPLACE_SECRET_<TENANT_UUID_HEX>_<INTEGRATION_UUID_HEX>_<NAME>
  ```

- The variable value is JSON:

  ```json
  {
    "user_agent": "the exact browser user agent used to create the session",
    "cookies": {
      "token": "current authorized Playerok token cookie",
      "__ddg3": "current access-protection cookie when present"
    }
  }
  ```

All current Playerok cookies may be included. `token` is required. Values are
validated against header injection, retained as `SecretStr`, omitted from
object representations, and used only when constructing the outgoing request.
Neither API responses nor polling diagnostics contain the secret or its opaque
reference.

## VDS Operating Rules

1. Use a stable, supported-region outbound IP.
2. Establish the authorized browser session from the same outbound IP that the
   worker uses.
3. Preserve the exact browser `User-Agent` with the exported cookies.
4. Inject the JSON through the host/container secret environment; never commit
   it to `.env`, source control, logs, screenshots, or seller API payloads.
   Production Compose reads these dynamic variables from the optional,
   git-ignored `.marketplace-secrets.env` file (or the path selected by
   `MARKETPLACE_SECRETS_ENV_FILE`) only for the worker container. Restrict that
   file to the deployment account.
5. Configure the integration with `auth_type=session` or `auth_type=cookie` and
   rotate its opaque reference to `env://NAME`.
6. Begin with a low polling frequency and run a 48-72 hour soak before enabling
   unattended production polling.
7. Rotate the session when Playerok reports it expired. Do not automate CAPTCHA
   solving or repeated retries against an access block.

## Retrieval Semantics

GraphQL collection follows `pageInfo.endCursor` while `hasNextPage` is true.
Traversal is bounded to 50 pages by default, rejects repeated/missing cursors,
and fails the run rather than returning a silently partial catalog when the
bound is exceeded. Current runtime still leaves missing-offer reconciliation
disabled because completeness also depends on the configured source scope.

Failures are explicit:

- `PlayerokSessionExpiredError`: HTTP 401;
- `PlayerokAccessBlockedError`: HTTP 403 or a DDoS/access challenge body;
- `PlayerokRateLimitedError`: HTTP 429, including numeric `Retry-After`;
- `PlayerokConnectionError`: transport failure;
- `PlayerokInvalidResponseError`: invalid JSON, GraphQL errors, or unsafe
  pagination state.

Ingestion fails before the repository transaction for these conditions, so
existing offers and snapshots are retained rather than replaced by an empty
result.

## Guarded Live Verification

`scripts/verify_playerok_session_connector.py` performs one live read only when
all required values are supplied and `PLAYEROK_LIVE_VERIFY` exactly equals
`I_UNDERSTAND_THIS_CONTACTS_PLAYEROK`. It prints only safe status, counts, and
public offer fields. It never prints cookies.

Live acceptance requires successful pagination from the target VDS, repeated
low-frequency runs for 48-72 hours, correct classification of an intentionally
expired session, and confirmation that 403/429 failures retain previously
persisted offers.
