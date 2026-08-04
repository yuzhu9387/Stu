from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    if not scheduler.running:
        register_jobs()
        scheduler.start()
        logger.info("scheduler started")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")


def register_jobs() -> None:
    """Add interval + cron jobs. Idempotent: replaces existing job ids."""
    from app.scheduler.jobs import (
        run_scan_reminders,
        run_orchestrate_daily,
        run_expire_stale_checkins,
        run_memory_consolidation,
    )
    from app.coach.signal_monitor import run_coach_signal_check

    scheduler.add_job(run_scan_reminders, "interval", minutes=1,
                      id="scan_reminders", replace_existing=True)
    scheduler.add_job(run_orchestrate_daily, "cron", minute=0,
                      id="orchestrate_daily", replace_existing=True)
    scheduler.add_job(run_expire_stale_checkins, "interval", hours=1,
                      id="expire_stale_checkins", replace_existing=True)
    scheduler.add_job(run_memory_consolidation, "cron", hour=3, minute=0,
                      id="memory_consolidation", replace_existing=True)
    scheduler.add_job(run_coach_signal_check, "cron", hour=9, minute=0,
                      id="coach_signal_check", replace_existing=True)


def _clear_jobs_for_test() -> None:
    for j in list(scheduler.get_jobs()):
        scheduler.remove_job(j.id)
