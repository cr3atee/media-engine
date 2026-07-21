# Roadmap

## Purpose

This document tracks only work that is reflected by the current repository state.

## Completed

- Project foundation.
- Configuration foundation.
- Database foundation.
- Alembic foundation.
- Domain events foundation.
- Pipeline foundation.
- GGSEL response analysis.
- GGSEL raw product extraction from saved HTML payloads.
- Typed raw marketplace offer model.
- Parsed offer normalization boundary.
- Canonical product domain model.
- Matching Engine preprocessing.
- Matching Engine similarity scoring.
- Matching Engine confidence classification.
- MatchingService.
- Repository contracts.
- In-memory repositories.
- RepositoryProvider.
- MarketplacePipeline parsed offer persistence through RepositoryProvider.

## Current Status

MediaEngine has a working foundation for fetching GGSEL HTML, extracting raw product payloads, normalizing them into parsed offers, saving parsed offers through an in-memory repository provider, and running deterministic product matching against canonical products.

## Not Present Yet

- PostgreSQL repository implementations.
- Full price normalization for GGSEL extracted fields.
- Persistent price history implementation.
- Telegram delivery implementation.
- Production AI provider integration in the pipeline.
