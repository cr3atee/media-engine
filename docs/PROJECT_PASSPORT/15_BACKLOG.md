# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 Task 2.

## Immediate

- Implement EPIC 17 Task 3: seller integration API routes for tenant-owned
  marketplace integration metadata.
- Keep credential routes tenant-scoped, permission-checked, redacted, and
  rollback-safe before tenant-specific authenticated ingestion is exposed.
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
