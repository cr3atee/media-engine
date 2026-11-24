# EPIC 25 - First Published Marketplace Pair

Completed on 2026-11-24 after explicit user approval of the exact FunPay offer.
This is an operational use of existing services, not a new parser, repository,
approval bypass or local-agent feature.

## Visible Result

Open the existing product:

<http://localhost:8000/terminal?product=dc7a6323-d5fc-5675-a2ff-0fe6ab4a70d1>

| Product | Source | Offer | Stored RUB price |
| --- | --- | --- | ---: |
| ExitLag 1 month Key | GGSEL | `5077855` | 599.00 |
| Same existing product | FunPay | `19847269` | 754.58 |

The public response is `price_only`, with GGSEL selected at `599.00 RUB` and
an absolute difference of `155.58 RUB`. The percentage difference is calculated
against the selected minimum by the existing Decimal service. This is a price
spread, not resale profit or verified full activation equivalence.

The catalog still has exactly three products. ExitLag has two source logos and
two offers; Duolingo and Spotify retain one GGSEL offer each. No fourth product,
new duration, invented seller, condition profile or speculative discount exists.

This approved FunPay example is not the cheapest listing on that marketplace.
The user specifically chose it for the first real comparison rather than adding
the previously observed restricted promotional candidate. No marketplace-wide
minimum is claimed.

## Current Source Evidence

The existing unauthenticated `FunPayFetcher`, `FunPayExtractor`, normalizer and
source screener verified the exact offer in the returned `1568` listing:

- HTTP 200 on listing and detail; 2000 returned rows do not prove full coverage.
- `f-type=pc`, `f-method=цифровой код`, `f-time=1 месяц`.
- Source ID `19847269`, seller `ralli125` / `1817720`, price `754.58 RUB`.
- Source URL: <https://funpay.com/lots/offer?id=19847269>.

The GGSEL category API returned HTTP 429 during this operation. There was no
proxy/cookie workaround, retry loop, fake successful refresh or deletion of
missing offers. Its already persisted `599.00 RUB` remains a saved quote, not
a newly refreshed price. The other two GGSEL quotes are also not claimed newly
verified by this run. Automated freshness/polling remains separate work.

## Approval And Publication

The user explicitly approved linking this offer to existing canonical product
`dc7a6323-d5fc-5675-a2ff-0fe6ab4a70d1` and showing it beside GGSEL. There was
no automatic identity decision based only on a cheap price.

1. Backed up both retained local databases outside Git and restored the backups
   into two isolated rehearsal databases.
2. Rehearsed the existing proposal-resolution and release services against those
   restored databases. Three products, four links, one new link and exact replay
   passed before changing either real local database.
3. Used the authorized local reviewer API's existing `resolve-existing` route.
   The reason records explicit chat approval and public source facts, not a
   fabricated full-condition review. The authenticated reviewer is the source
   audit actor; a second request returned the same decision.
4. Prepared the exact public FunPay source integration/category rule and raw
   offer in the target using existing repository contracts and classification
   helper. The target offer was initially unlinked; no user was reseeded.
5. `CatalogPromotionReleaseService.preview()` produced three product reuses,
   three link reuses and one new link. Applied the exact target-bound approval
   phrase through the existing atomic importer. The local release audit actor
   explicitly identifies Codex executing the user's approved operation.
6. Fresh-process preview/apply returned `no_changes`, the same promotion action
   and `replayed=True`. Original products, GGSEL offers/decisions and the prior
   promotion audit retained their checked hashes.

```text
Source review decision: fd2ca347-174c-4144-baf1-7b4a3ece8e39
Review idempotency key: epic25-funpay-exitlag-user-approved-20261124
Manifest digest: 42f3afb89e5a1c6319c368691e3bddd92d942554c873670ed467a5443f428594
Promotion action: 311cd5cb-ba7f-4893-b3cb-9c96768cc9e8
Release idempotency key: epic25-funpay-exitlag-release-20261124
Source: 4 offers / 4 links / 3 products / 4 decisions / 0 pending proposals
Target: 4 offers / 4 links / 3 products / 0 copied review decisions
```

No production database, production monitoring/backup attestation, price-history
backfill, external AI, Telegram delivery, marketplace login or customer cookies
were used. No schema or business service needed modification. Both activation
profiles remain unknown; the public price-only notice stays visible.

## Web Acceptance

The existing browser verifier now treats three products as the bound, not one
offer per product forever. Its explicit second-source mode requires exactly
the approved two-source ExitLag pair and unchanged other launch products:

```powershell
$env:TERMINAL_PREVIEW_URL = 'http://localhost:8000'
$env:TERMINAL_CDP_URL = 'http://127.0.0.1:9224'
$env:EPIC25_THREE_PRODUCT_ACCEPTANCE = '1'
$env:EPIC25_FUNPAY_EXITLAG_ACCEPTANCE = '1'
node scripts/verify_terminal_preview_browser.mjs
```

Use a dedicated temporary Chromium profile. The verifier uses application GETs
only, never buying, confirming reviews or changing data. The original
single-source assumption in one detail-page assertion was updated to use the
actual API offer count; an initial run correctly failed on that obsolete test
expectation, not on the application.

Actual results: `134/134` browser checks passed on the real retained catalog,
with no runtime/CSP errors and application GETs only. Desktop/catalog/mobile
screenshots were inspected. Mobile emulation and accessibility-tree checks are
not a physical-phone or real screen-reader certification. Full Pytest remains
`913 passed, 65 skipped`, with the existing Starlette/httpx warning; strict MyPy
passes `577` files and Node syntax passes. No Python application/test file changed,
so no new changed-file Ruff/format result is claimed. PostgreSQL was exercised
through the restored-backup rehearsal, real API/release, fresh-process replay
and six checksum checks; these are not represented as a rerun of an unrelated
full PostgreSQL verifier suite.

## Deployment Boundary

The user chose web-only delivery for the first version. A downloadable/local
agent, marketplace cookie import and full customer self-hosting are deferred.
Running the development preview locally is not a promised desktop distribution.
Docker Desktop and the existing PostgreSQL container were restarted without
recreating data; both web servers were started detached/hidden with their prior
databases and signing settings. Log files are outside the repository. Internal
reviewer authentication is not marketplace-cookie collection.

The remaining first-version scope stays bounded: retain these three products,
extend their reviewed source coverage where available, and handle real source
rate limits honestly. This operation does not complete Playerok access, all
three multi-marketplace comparisons, unattended polling or public VDS rollout.
