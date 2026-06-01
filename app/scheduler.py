from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.briefing import morning_brief, send_morning_brief
from app.config import settings
from app.database import get_task, list_pending_reminder_tasks, mark_task_reminder_sent
from app.retrospective import evening_retro
from app.telegram_client import telegram_client


async def _send_weekly_finance_report() -> None:
    """Send the weekly finance report to all registered chats."""
    from datetime import date, timedelta
    from app.finance.handlers import handle_report_command
    from app.database import DATABASE_PATH
    import aiosqlite

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT chat_id FROM daily_revenue ORDER BY chat_id"
        )
        rows = await cursor.fetchall()

    for (chat_id,) in rows:
        try:
            report = await handle_report_command(chat_id=chat_id, text="/отчет прошлая")
            await telegram_client.send_message(chat_id=chat_id, text=report)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Weekly report failed for %s: %s", chat_id, exc)

# Persist jobs in a dedicated SQLite file so reminders survive restarts.
_JOBSTORE_URL = "sqlite:///scheduler_jobs.db"

_jobstores = {
    "default": SQLAlchemyJobStore(url=_JOBSTORE_URL),
}

scheduler = AsyncIOScheduler(
    jobstores=_jobstores,
    timezone=ZoneInfo(settings.morning_brief_timezone),
)


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

    # Weekly finance report — every Monday at 09:00
    scheduler.add_job(
        _send_weekly_finance_report,
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        timezone=ZoneInfo(settings.morning_brief_timezone),
        id="weekly_finance_report",
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


async def send_task_reminder(chat_id: int, task_id: int) -> None:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None or task["status"] in {"done", "cancelled"} or not task.get("reminder_at"):
        return

    await telegram_client.send_message(
        chat_id=chat_id,
        text=(
            f"Напоминание по задаче #{task_id}: {task['title']}\n\n"
            "Открыть список: /today\n"
            f"Закрыть: /done {task_id}"
        ),
    )
    await mark_task_reminder_sent(chat_id=chat_id, task_id=task_id)


def schedule_task_reminder(chat_id: int, task_id: int, reminder_at: str) -> bool:
    if not scheduler.running:
        start_scheduler()

    run_date = _parse_reminder_at(reminder_at)
    if run_date is None:
        return False

    now = datetime.now(ZoneInfo(settings.morning_brief_timezone))
    if run_date < now:
        run_date = now + timedelta(seconds=5)

    scheduler.add_job(
        send_task_reminder,
        trigger="date",
        run_date=run_date,
        args=[chat_id, task_id],
        id=f"task_reminder_{chat_id}_{task_id}",
        replace_existing=True,
    )
    return True


async def schedule_pending_task_reminders() -> None:
    now = datetime.now(ZoneInfo(settings.morning_brief_timezone)).strftime("%Y-%m-%d %H:%M")
    tasks = await list_pending_reminder_tasks(now=now)
    for task in tasks:
        schedule_task_reminder(
            chat_id=task["chat_id"],
            task_id=task["id"],
            reminder_at=task["reminder_at"],
        )


def _parse_reminder_at(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=ZoneInfo(settings.morning_brief_timezone))
        except ValueError:
            continue
    return None
