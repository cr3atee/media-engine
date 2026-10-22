# EPIC 22 - Public Catalog Pagination

## Goal

Allow the embedded Market Terminal to continue through the public product
catalog without introducing offset pagination, a new persistence model, or
browser-side comparison logic.

## Implemented Boundary

- `RepositoryBackedPublicReadRepository.list_products()` returns a continuation
  position when more canonical products remain.
- The continuation uses the existing signed `CursorPosition` contract and the
  last canonical product UUID as its stable anchor.
- API cursors remain bound to resource, sort, direction, and effective filters,
  including the `q` search alias used by Market Terminal.
- All existing product sorts support deterministic continuation.
- A missing anchor terminates the result safely instead of restarting from the
  first page and duplicating products.
- Market Terminal forwards `next_cursor`, appends unique products, rejects stale
  responses through the existing request version, and exposes an accessible
  `Показать ещё` control.

## Deliberate Limits

- Offer, price-history, price-change, and category lists still return bounded
  first pages. Their projections do not all expose a stable UUID identity for
  the shared cursor contract.
- Pagination is not snapshot isolation. Concurrent product updates can change a
  later page's ordering, as with other live read models.
- No direct-SQL public query adapter, total-count query, infinite scrolling, or
  synthetic offset cursor was added.

## Verification

- Product continuation is covered for every supported sort, without overlap.
- Signed cursor round-trip and effective-filter mismatch rejection are covered
  at the FastAPI boundary.
- Focused repository/API/terminal tests pass `19/19`.
- Saved-payload public UI readiness passes `44/44`.
- Isolated PostgreSQL 17 verification passes `69/69`, including two product
  pages and fresh-session persistence at Alembic head
  `0017_marketplace_polling_runs`.
- Full Pytest passes `531` tests with `58` expected skips.
- MyPy checks `449` source files; focused Ruff and Ruff format checks pass.
- Alembic current/check and offline upgrade SQL pass with no schema change.

## Status

Complete.
