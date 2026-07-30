# Telegram

## Purpose

This document records the boundary for future Telegram publication delivery.

## Publication State

The durable `Publication` model is channel independent. It stores event/content
references, channel, destination key, deterministic idempotency key, lifecycle,
schedule/retry fields, claims, safe error state, and an optional external message
ID. It does not import Telegram clients, Bot API objects, formatting parsers, or
credentials.

## Current Behavior

Successful generated content creates a pending publication intent only when the
application supplies an explicit `PublicationTarget`. No real chat ID is
hardcoded. If no target is configured, content remains generated and no intent is
invented.

EPIC 14 Task 1 adds an inactive outbound foundation: channel-independent delivery
DTOs and adapter protocol, deterministic plain-text formatting, a direct async
Bot API client, typed Telegram response/error classification, and token-safe
logging. All verification uses `httpx.MockTransport`. No repository or Scheduler
runtime path invokes the adapter yet.

EPIC 14 Task 2 connects that adapter boundary to durable publication state
without live sending. `PublicationDeliveryService` claims due Telegram
publications through the generic publication repository channel filter, loads
generated content and event data, formats a plain-text message, calls the adapter
outside repository transactions, and records success, retryable failure,
permanent failure, or ambiguous state through guarded publication transitions.
`PendingPublicationDeliveryJob` delegates bounded batches to the service only.
Dry-run renders an explicit publication without mutation or adapter calls.

## Safety

- No live Telegram message is sent by the current application.
- A known retryable delivery failure is retried through durable publication
  state by `PublicationDeliveryService`.
- An expired/unknown delivery outcome becomes `ambiguous` and is never
  automatically returned to pending.
- Provider response and transport error mapping remain implemented at the
  adapter boundary. Durable retry, rate limiting, claiming, dry-run, and
  ambiguous persistence are application-service work.

## Verification Status

Publication intent, claim contention, idempotency, cancellation, terminal
published state, and protected ambiguous recovery are verified against live
PostgreSQL. The Telegram formatter/client/adapter foundation is verified offline,
and Task 2 delivery orchestration is covered by focused offline tests. The Task 2
PostgreSQL verifier requires an isolated `EPIC14_DATABASE_URL`. The next task is
**EPIC 14 Task 3 - guarded live test-chat verification**.
