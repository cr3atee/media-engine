# Scheduler Foundation

## Purpose

The scheduler layer coordinates execution of existing marketplace pipelines. It does not contain marketplace parsing, matching, comparison, persistence, Telegram delivery, or AI business logic.

## Components

- `SchedulerService` registers jobs and optionally schedules interval execution.
- `SchedulerService.execute_job()` runs a registered job and records the latest status.
- `JobExecutionStatus` reports the latest state, run count, failure count, timestamps, and error message.
- Scheduler retry handling is configured per job and remains outside business logic.
- Scheduler statistics track total executions, successful executions, failed executions, retry attempts, last error, and last successful run.

## Verified Flow

The demo registers two jobs:

1. GGSEL pipeline execution.
2. Playerok pipeline execution.

The scheduler starts, executes both jobs, prints execution statuses, and shuts down gracefully.

## Current Limitations

- Marketplace pipeline success still depends on the underlying marketplace fetchers and network access.
- Scheduler integration with PostgreSQL-backed providers is intentionally left for a later story.
