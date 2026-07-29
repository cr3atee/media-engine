# Backlog

## Purpose

This document lists only confirmed work remaining after EPIC 13 Task 6.

## Immediate

- Run the final production-shaped EPIC 13 verification from ingestion through
  scoring, durable content, and publication intent, including restart and overlap
  evidence.

## Delivery

- Implement a Telegram delivery adapter that claims durable publications, maps
  confirmed/failed/ambiguous outcomes, and never automatically resends ambiguous
  deliveries.

## Operational

- Define Scheduler overlap and multi-process coordination before production.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- Complete GGSEL marketplace-specific price/currency normalization where the raw
  payload provides trustworthy values.
