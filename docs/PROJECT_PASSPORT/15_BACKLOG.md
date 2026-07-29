# Backlog

## Purpose

This document lists only confirmed work remaining after final EPIC 13
verification.

## Immediate

- Implement **Telegram Publication Adapter and Delivery Workflow** over the
  existing durable publication repository.

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
