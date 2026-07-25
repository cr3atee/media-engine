# Scheduler Jobs

## Purpose

This document describes the reusable job layer used by `SchedulerService`.

## Components

- `BaseJob` tracks name, execution status, timing, and errors.
- `MarketplaceJob` provides shared marketplace job structure.
- `GGSELJob` executes the existing GGSEL marketplace pipeline.
- `PlayerokJob` executes the existing Playerok pipeline.

## Behaviour

- Jobs wrap existing pipelines only.
- Jobs do not contain business logic.
- `SchedulerService` registers and executes job objects.
- Job execution status includes timestamps, duration, and error details.

## Demo

The demo starts the scheduler, registers `GGSELJob` and `PlayerokJob`, executes both jobs, prints execution details, and shuts the scheduler down.
