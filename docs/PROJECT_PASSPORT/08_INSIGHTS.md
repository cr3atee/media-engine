# Insights

## Purpose

This document records the current deterministic event-scoring boundary.

## Scoring

`EventScorer` supports the existing price-drop scoring rules. Task 5 does not
change the scoring algorithm. `MarketEventScoringAdapter` converts a claimed
durable price-drop event into the temporary input expected by that scorer while
preserving durable context.

Scoring executes outside repository transactions. `EventProcessingService`
persists the resulting integer score and success state atomically, or records a
safe failure category and bounded retry time.

## Retry Policy

Transient failures receive deterministic exponential backoff. Development
defaults are three maximum attempts, a five-second initial delay, and a
five-minute maximum delay. Invalid immutable payloads and impossible price-drop
states are terminal. Repositories persist lifecycle facts but do not decide retry
policy.

## Selection

`InsightEngine.select_events()` remains a pass-through foundation. Event
selection, deduplication beyond durable identity, importance aggregation, and
publication ranking are not implemented.

The active content eligibility policy preserves existing behavior: events must
have an allowed disposition and successful persisted scoring, but there is no new
score threshold. Repository queries provide deterministic bounded pages; the
content service does not redesign `EventScorer` or infer an importance policy.

## Digest Preparation

Daily and weekly digest preparation remains planned infrastructure only. No
digest generation is connected to the durable event-processing path.

## Verification Status

Durable scoring was verified with committed claims, transaction-free scorer
execution, bounded retry, permanent failure, stale-token rejection, lease
recovery, and concurrent `SKIP LOCKED` workers. The scoring rules themselves were
not changed by final verification.
