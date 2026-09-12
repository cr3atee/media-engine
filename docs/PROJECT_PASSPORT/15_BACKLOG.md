# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 completion.

## Immediate

- Continue EPIC 19 by implementing public query adapters, consumer read
  services, and `/api/v1/public` routes for Market Terminal over the new DTO and
  query-contract foundations.
- Run guarded live polling verification around the production worker command
  before unattended scheduled ingestion.
- Add live marketplace polling monitoring and production runtime integration
  configuration before relying on GGSEL, Playerok, or FunPay for scheduled
  ingestion.
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

- Add persisted runtime diagnostics for worker command failures, skipped
  integrations, and marketplace source drift after the in-process diagnostic
  boundary is exercised live.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- GGSEL, Playerok, and FunPay are ready from current real captured-response
  proof and strict saved-payload verification. Production scheduling still needs
  live polling monitoring.
