"""Temporal native schedule management for consolidation crons."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from temporalio.client import Client


async def create_daily_consolidation_schedule(
    client: "Client",
    workspace_id: str,
    timezone: str = "UTC",
    task_queue: str = "default-tasks",
) -> None:
    """Create a Temporal schedule for daily memory consolidation.

    Runs at 2:00 AM in the workspace's configured timezone.
    Jitter of 15 minutes to spread load across workspaces.
    """
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleCalendarSpec,
        ScheduleRange,
        ScheduleSpec,
        ScheduleState,
    )

    schedule_id = f"daily-consolidation-{workspace_id[:16]}"

    try:
        await client.create_schedule(
            id=schedule_id,
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    "ConsolidateMemoryWorkflow",
                    args=[workspace_id, "daily"],
                    id=f"consolidate-daily-{workspace_id[:16]}",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(
                    calendars=[
                        ScheduleCalendarSpec(
                            hour=[ScheduleRange(start=2)],
                            minute=[ScheduleRange(start=0)],
                        )
                    ],
                    jitter=timedelta(minutes=15),
                ),
                state=ScheduleState(
                    note=f"Daily consolidation for workspace {workspace_id[:8]}",
                ),
            ),
        )
        logger.info(
            f"Created daily consolidation schedule: {schedule_id} "
            f"(timezone={timezone}, queue={task_queue})"
        )
    except Exception as e:
        if "already exists" in str(e).lower():
            logger.debug(f"Schedule {schedule_id} already exists, skipping")
        else:
            raise


async def create_weekly_consolidation_schedule(
    client: "Client",
    workspace_id: str,
    timezone: str = "UTC",
    task_queue: str = "default-tasks",
) -> None:
    """Create Temporal schedule for weekly consolidation (Sunday 3 AM)."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleCalendarSpec,
        ScheduleRange,
        ScheduleSpec,
        ScheduleState,
    )

    schedule_id = f"weekly-consolidation-{workspace_id[:16]}"

    try:
        await client.create_schedule(
            id=schedule_id,
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    "ConsolidateMemoryWorkflow",
                    args=[workspace_id, "weekly"],
                    id=f"consolidate-weekly-{workspace_id[:16]}",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(
                    calendars=[
                        ScheduleCalendarSpec(
                            day_of_week=[ScheduleRange(start=0)],
                            hour=[ScheduleRange(start=3)],
                            minute=[ScheduleRange(start=0)],
                        )
                    ],
                    jitter=timedelta(minutes=15),
                ),
                state=ScheduleState(
                    note=f"Weekly consolidation for workspace {workspace_id[:8]}",
                ),
            ),
        )
        logger.info(f"Created weekly consolidation schedule: {schedule_id}")
    except Exception as e:
        if "already exists" in str(e).lower():
            logger.debug(f"Schedule {schedule_id} already exists, skipping")
        else:
            raise


async def create_monthly_consolidation_schedule(
    client: "Client",
    workspace_id: str,
    timezone: str = "UTC",
    task_queue: str = "default-tasks",
) -> None:
    """Create Temporal schedule for monthly consolidation (1st, 4 AM)."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleCalendarSpec,
        ScheduleRange,
        ScheduleSpec,
        ScheduleState,
    )

    schedule_id = f"monthly-consolidation-{workspace_id[:16]}"

    try:
        await client.create_schedule(
            id=schedule_id,
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    "ConsolidateMemoryWorkflow",
                    args=[workspace_id, "monthly"],
                    id=f"consolidate-monthly-{workspace_id[:16]}",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(
                    calendars=[
                        ScheduleCalendarSpec(
                            day_of_month=[ScheduleRange(start=1)],
                            hour=[ScheduleRange(start=4)],
                            minute=[ScheduleRange(start=0)],
                        )
                    ],
                    jitter=timedelta(minutes=30),
                ),
                state=ScheduleState(
                    note=f"Monthly consolidation for workspace {workspace_id[:8]}",
                ),
            ),
        )
        logger.info(f"Created monthly consolidation schedule: {schedule_id}")
    except Exception as e:
        if "already exists" in str(e).lower():
            logger.debug(f"Schedule {schedule_id} already exists, skipping")
        else:
            raise


async def ensure_job_schedules(
    client: "Client",
    bot_name: str,
    workspace_id: str,
    jobs: dict,
    task_queue: str = "default-tasks",
) -> int:
    """Create Temporal schedules for bot cron jobs. Idempotent.

    Returns number of schedules created/updated.
    """
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleOverlapPolicy,
        SchedulePolicy,
        ScheduleSpec,
        ScheduleState,
        ScheduleUpdate,
    )

    count = 0
    for job_name, job in jobs.items():
        if not job.enabled:
            logger.debug(f"Job {bot_name}:{job_name} disabled, skipping")
            continue
        if not job.targets:
            logger.warning(f"Job {bot_name}:{job_name} has no targets, skipping")
            continue

        schedule_id = f"job:{bot_name}:{job_name}"
        task_info = {
            "workspace_id": workspace_id,
            "bot_name": bot_name,
            "job_name": job_name,
            "prompt": job.prompt,
            "targets": [t.model_dump() for t in job.targets],
        }

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "CronTaskWorkflow",
                args=[task_info],
                id=f"cron-job-{bot_name}-{job_name}",
                task_queue=task_queue,
            ),
            spec=ScheduleSpec(
                cron_expressions=[job.schedule],
                jitter=timedelta(minutes=2),
                time_zone_name=job.timezone or "UTC",
            ),
            policy=SchedulePolicy(
                overlap=ScheduleOverlapPolicy.SKIP,
            ),
            state=ScheduleState(
                note=f"Cron job: {bot_name}/{job_name} - {job.description}",
            ),
        )

        try:
            await client.create_schedule(schedule_id, schedule)
            logger.info(f"Created job schedule: {schedule_id} ({job.schedule})")
            count += 1
        except Exception as e:
            if "already" in str(e).lower():
                try:
                    handle = client.get_schedule_handle(schedule_id)
                    await handle.update(
                        lambda _: ScheduleUpdate(schedule=schedule)
                    )
                    logger.debug(f"Updated job schedule: {schedule_id}")
                    count += 1
                except Exception as ue:
                    logger.warning(f"Failed to update schedule {schedule_id}: {ue}")
            else:
                logger.error(f"Failed to create schedule {schedule_id}: {e}")

    return count


async def delete_consolidation_schedule(
    client: "Client",
    workspace_id: str,
) -> None:
    """Delete the daily consolidation schedule for a workspace."""
    schedule_id = f"daily-consolidation-{workspace_id[:16]}"
    try:
        handle = client.get_schedule_handle(schedule_id)
        await handle.delete()
        logger.info(f"Deleted consolidation schedule: {schedule_id}")
    except Exception as e:
        logger.debug(f"Could not delete schedule {schedule_id}: {e}")
