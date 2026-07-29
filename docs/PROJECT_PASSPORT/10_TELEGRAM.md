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

## Safety

- No Telegram message is sent by the current application.
- A known failed delivery may be retried by a future delivery service.
- An expired/unknown delivery outcome becomes `ambiguous` and is never
  automatically returned to pending.
- Actual delivery, provider error mapping, rate limiting, and reconciliation are
  work for the Telegram delivery EPIC.
