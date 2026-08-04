import asyncio


def test_scheduler_instance_is_async_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.scheduler.runtime import scheduler
    assert isinstance(scheduler, AsyncIOScheduler)


def test_scheduler_not_running_at_import():
    from app.scheduler.runtime import scheduler
    assert not scheduler.running


async def test_start_and_shutdown_helpers():
    from app.scheduler.runtime import scheduler, start_scheduler, shutdown_scheduler
    start_scheduler()
    assert scheduler.running
    shutdown_scheduler()
    # AsyncIOScheduler.shutdown is deferred to the event loop via @run_in_event_loop,
    # so the state transition needs an event-loop turn to complete.
    await asyncio.sleep(0.05)
    assert not scheduler.running


def test_register_jobs_adds_expected_job_ids():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "scan_reminders" in ids
    assert "orchestrate_daily" in ids
    assert "expire_stale_checkins" in ids
    _clear_jobs_for_test()


def test_register_jobs_includes_memory_consolidation():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "memory_consolidation" in ids
    _clear_jobs_for_test()


def test_register_jobs_includes_coach_signal_check():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "coach_signal_check" in ids
    _clear_jobs_for_test()
