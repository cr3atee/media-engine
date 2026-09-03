# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 Task 4 offline
implementation.

## Immediate

- Run EPIC 17 Task 4 live PostgreSQL verification once Docker Desktop or an
  isolated `EPIC17_DATABASE_URL` is available.
- Verify disabled integration exclusion, inactive tenant exclusion, fresh-session
  persistence, and Scheduler delegation against PostgreSQL.
- Complete EPIC 17 final verification after Task 4 PostgreSQL verification
  passes.
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
