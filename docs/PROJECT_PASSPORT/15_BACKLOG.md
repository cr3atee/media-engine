# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 15 Task 2.

## Immediate

- Implement EPIC 15 Task 3 operational completion: dashboard summary,
  final health/readiness polish, OpenAPI/admin docs protection review, and final
  API verification.
- If explicitly approved credentials and a test chat are available, run exactly
  one guarded live Telegram test-chat verification.

## Delivery

- Keep production Telegram delivery disabled until PostgreSQL verification,
  optional live test-chat verification, monitoring, and operational
  reconciliation are approved.

## Operational

- Define Scheduler overlap and multi-process coordination before production.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- Complete GGSEL marketplace-specific price/currency normalization where the raw
  payload provides trustworthy values.
