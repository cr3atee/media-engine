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

## Safety

- No Telegram message is sent by the current application.
- A known failed delivery may be retried by a future delivery service.
- An expired/unknown delivery outcome becomes `ambiguous` and is never
  automatically returned to pending.
- Provider response and transport error mapping are implemented at the adapter
  boundary. Durable retry, rate limiting, claiming, and reconciliation remain
  application-service work.

## Verification Status

Publication intent, claim contention, idempotency, cancellation, terminal
published state, and protected ambiguous recovery are verified against live
PostgreSQL. The Telegram formatter/client/adapter foundation is verified offline;
no external message was sent. The next task is **EPIC 14 Task 2 - Durable delivery
orchestration**.
