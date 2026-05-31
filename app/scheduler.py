from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.briefing import morning_brief, send_morning_brief
from app.config import settings
from app.retrospective import evening_retro


scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.morning_brief_timezone))


def start_scheduler() -> None:
    if scheduler.running:
        return

    if settings.morning_brief_enabled:
        scheduler.add_job(
            morning_brief,
            trigger="cron",
            hour=settings.morning_brief_hour,
            minute=settings.morning_brief_minute,
            timezone=ZoneInfo(settings.morning_brief_timezone),
            id="morning_brief",
            replace_existing=True,
        )

    if settings.evening_retro_enabled:
        scheduler.add_job(
            evening_retro,
            trigger="cron",
            hour=settings.evening_retro_hour,
            minute=settings.evening_retro_minute,
            timezone=ZoneInfo(settings.evening_retro_timezone),
            id="evening_retro",
            replace_existing=True,
        )

    scheduler.start()


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def schedule_morning_brief_snooze(chat_id: int, minutes: int = 60) -> None:
    if not scheduler.running:
        start_scheduler()

    run_date = datetime.now(ZoneInfo(settings.morning_brief_timezone)) + timedelta(minutes=minutes)
    scheduler.add_job(
        send_morning_brief,
        trigger="date",
        run_date=run_date,
        args=[chat_id],
        id=f"morning_brief_snooze_{chat_id}",
        replace_existing=True,
    )
