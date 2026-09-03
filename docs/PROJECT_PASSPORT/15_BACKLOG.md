# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 17 completion.

## Immediate

- Capture and analyze a real Playerok listing response, then harden extraction
  only against the confirmed response shape.
- Capture and analyze a real FunPay listing response, then implement extraction
  only after the source structure is confirmed.
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

- Define Scheduler overlap and multi-process coordination before production.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- Playerok cannot be marked marketplace-ready until a real captured listing
  response produces snapshot-ready `ParsedOffer` objects.
- FunPay cannot be marked marketplace-ready until extractor and normalizer
  boundaries exist and are proven against a real captured response.
