# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 completion.

## Immediate

- Add marketplace payload/source drift monitoring before relying on GGSEL,
  Playerok, or FunPay for scheduled production ingestion.
- Keep FunPay extraction guarded by captured-response verification and add drift
  monitoring before relying on it for scheduled production ingestion.
- Define the next EPIC before implementing live marketplace credential storage
  or execution-time credential retrieval.
- Keep tenant-owned marketplace integrations redacted and metadata-only until a
  secret-storage design is explicitly approved.
- If explicitly approved credentials and a test chat are available, run exactly
  one guarded live Telegram test-chat verification.

## Delivery

- Keep production Telegram delivery disabled until PostgreSQL verification,
  optional live test-chat verification, monitoring, and operational
  reconciliation are approved.

## Operational

- Wire production Scheduler entrypoints through the PostgreSQL scheduler factory
  when the deployment process is introduced.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- GGSEL, Playerok, and FunPay are ready from current real captured-response
  proof, but should still have payload drift monitoring before production
  scheduling.
