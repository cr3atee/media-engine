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
- `SchedulerService` can execute enabled jobs periodically using per-job intervals.
- Schedule status includes the interval, enabled state, next scheduled run, and last execution time.
- Retry count, retry delay, and execution timeout are configured in the scheduler.
- Job failures do not stop the scheduler.
- Scheduler logs `START`, `SUCCESS`, `FAILURE`, `RETRY`, `TIMEOUT`, and `STOP` lifecycle messages.

## Demo

The demo starts the scheduler, registers `GGSELJob` and `PlayerokJob`, executes both jobs, prints execution details, and shuts the scheduler down.

`scripts/demo_scheduler_periodic.py` demonstrates periodic execution with different job intervals and graceful shutdown.

`scripts/demo_scheduler_retry.py` demonstrates retry handling with one successful job and one intentionally failing job.
