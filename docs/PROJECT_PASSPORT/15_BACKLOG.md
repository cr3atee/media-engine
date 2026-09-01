# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 16 Task 3 offline
implementation.

## Immediate

- Run EPIC 16 Task 3 PostgreSQL verifier with an isolated `EPIC16_DATABASE_URL`
  and record the results.
- Complete EPIC 16 Task 4 final isolation/readiness verification before
  exposing a public seller dashboard or seller API routes.
- Define tenant-owned marketplace credential and integration management before
  tenant-specific ingestion is exposed.
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
