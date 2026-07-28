# Changelog

## Purpose

This document records notable Project Passport updates.

## Unreleased

- Migrated active runtime price history to `RepositoryProvider.price_history`.
- Removed the duplicate standalone `PriceHistoryService`.
- Documented deterministic snapshot ordering and duplicate behavior.
- Updated scheduler and PostgreSQL verification paths for repository-backed history.
- Synchronized Project Passport with the current implementation state.
- Documented completed Matching Engine components.
- Documented `MatchingService`.
- Documented repository contracts.
- Documented in-memory repositories.
- Documented `RepositoryProvider`.
- Documented `MarketplacePipeline` parsed offer persistence through `RepositoryProvider`.
- Documented current known gaps around GGSEL price normalization, price history persistence, Telegram delivery, and production AI wiring.

## Previous Notes

- Initial Project Passport structure was created.
- First local Architecture Review was recorded for the price-change processing flow.
