# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 Task 3.

## Immediate

- Implement EPIC 17 Task 4: Scheduler selection of enabled tenant-owned
  marketplace integrations.
- Exclude disabled integrations and deactivated tenants from automatic
  marketplace work.
- Keep parsers tenant-unaware; Scheduler should only select integration
  configuration and delegate orchestration.
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
