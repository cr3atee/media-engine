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
publication policy are not implemented.

## Digest Preparation

Daily and weekly digest preparation remains planned infrastructure only. No
digest generation is connected to the durable event-processing path.
