# Events

## Purpose

This document records the active event boundary and durable event lifecycle.

## Active Event Type

`MarketEvent[PriceDropPayload]` represents one durable price-drop transition. It
retains exact previous/current snapshot identities, Decimal monetary values, UTC
timestamps, and a deterministic versioned identity.

## Transaction Boundary

The marketplace ingestion transaction persists offers, the current snapshot, and
the market-event candidate atomically. Exact duplicate snapshots create no event
candidate. Compatible event replay is idempotent; incompatible immutable facts
raise an explicit repository identity conflict.

## Durable Scoring

The existing Pydantic `PriceDropEvent` remains a temporary application DTO for
`EventScorer`, prompt building, and content generation. The scoring adapter
preserves durable facts but does not own or rebuild event identity.

`EventProcessingService` claims bounded pending/retry-eligible events in a short
transaction, scores after that transaction closes, and persists success/failure
in a new guarded transaction. Active claims cannot be stolen. Stale claims are
recovered explicitly and idempotently after lease expiry.

## Current Lifecycle

Durable events are created with pending scoring state. Scoring status, score,
attempt count, retry time, safe error, lease metadata, and optimistic version are
persisted. Default retries are bounded to three attempts with exponential backoff
from five seconds to five minutes. Generated-content persistence, publication
persistence, and delivery are not connected yet.

## Boundaries

- Domain event contracts do not depend on SQLAlchemy, Scheduler, AI, or Telegram.
- Repositories do not commit or roll back.
- AI and content generation never run inside the ingestion transaction.
- Scheduler remains orchestration-only.
- Claim-token and version guards prevent stale workers from overwriting newer
  lifecycle state.
