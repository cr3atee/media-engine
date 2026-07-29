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

## Post-Commit Compatibility

The existing Pydantic `PriceDropEvent` remains a temporary application DTO for
`EventScorer`, prompt building, and content generation. It is adapted from the
durable event after commit and does not own persistent identity.

## Current Lifecycle

Durable events are created with pending scoring state. Runtime scoring and content
generation still run immediately after commit and remain in memory. Claim-based
durable scoring, generated-content persistence, publication persistence, and
delivery are not connected yet.

## Boundaries

- Domain event contracts do not depend on SQLAlchemy, Scheduler, AI, or Telegram.
- Repositories do not commit or roll back.
- AI and content generation never run inside the ingestion transaction.
- Scheduler remains orchestration-only.
