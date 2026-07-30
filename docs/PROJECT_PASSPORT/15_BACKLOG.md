# Backlog

## Purpose

This document lists only confirmed work remaining after final EPIC 13
verification.

## Immediate

- Run **Telegram guarded live test-chat verification** over the existing durable
  delivery workflow.

## Delivery

- Add an explicitly gated live verification path for one allowlisted Telegram
  test chat.
- Keep production Telegram delivery disabled until live verification, monitoring,
  and operational reconciliation are approved.

## Operational

- Define Scheduler overlap and multi-process coordination before production.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- Complete GGSEL marketplace-specific price/currency normalization where the raw
  payload provides trustworthy values.
