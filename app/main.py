from __future__ import annotations

import logging
import traceback
from datetime import date, timedelta

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

from app.briefing import send_morning_brief
from app.config import settings
from app.database import init_database, list_recent_tasks
from app.handlers.callbacks import handle_callback_query
from app.handlers.message import process_text_message, try_handle_task_intent
from app.handlers.notion import handle_notion_pull_command, handle_notion_sync_command
from app.handlers.task_commands import (
    handle_deadline_command,
    handle_delete_command,
    handle_done_command,
    handle_plan_command,
    handle_priority_command,
    handle_remind_command,
    handle_rename_command,
    handle_status_command,
    handle_subtask_done_command,
    handle_subtasks_command,
)
from app.handlers.task_views import (
    build_active_tasks_reply,
    build_day_tasks_reply,
    build_memory_overview,
    build_next_task_reply,
    build_projects_reply,
    build_tasks_reply,
    build_today_focus_reply,
    build_week_tasks_reply,
    handle_project_command,
    is_tomorrow_overview_request,
    is_week_overview_request,
)
from app.agent_memory import list_recent_memory
from app.database import mark_task_cancelled
from app.finance.handlers import (
    handle_expense_command,
    handle_finances_command,
    handle_finance_input,
    handle_pay_command,
    handle_payroll_command,
    handle_report_command,
    handle_revenue_command,
    handle_shift_command,
    handle_shift_remove_command,
    handle_staff_add_command,
    handle_staff_command,
    handle_staff_remove_command,
    is_finance_message,
)
from app.retrospective import handle_retrospective_response, send_evening_retro
from app.scheduler import (
    schedule_pending_task_reminders,
    shutdown_scheduler,
    start_scheduler,
)
from app.telegram_client import telegram_client
from app.utils.rate_limiter import rate_limiter

app = FastAPI(title="Personal AI Workflow Hub")


@app.on_event("startup")
async def startup() -> None:
    # Apply rate limit from settings.
    rate_limiter._max = settings.rate_limit_per_minute

    await init_database()
    start_scheduler()
    await schedule_pending_task_reminders()


@app.on_event("shutdown")
async def shutdown() -> None:
    shutdown_scheduler()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    try:
        return await _process_update(request)
    except Exception:
        # Never return 5xx to Telegram — it would stop delivering updates.
        logger.exception("Unhandled error in telegram_webhook")
        return {"ok": True}


async def _process_update(request: Request) -> dict[str, bool]:
    update = await request.json()

    # ---- Callback queries ----
    callback_query = update.get("callback_query")
    if callback_query:
        cb_chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
        if cb_chat_id and not _is_chat_allowed(cb_chat_id):
            return {"ok": True}
        await handle_callback_query(callback_query)
        return {"ok": True}

    # ---- Regular messages ----
    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")
    voice = message.get("voice")

    if chat_id is None:
        return {"ok": True}

    # Security: reject unknown chats when ALLOWED_CHAT_IDS is set.
    if not _is_chat_allowed(chat_id):
        return {"ok": True}

    # Rate limiting.
    if not rate_limiter.is_allowed(chat_id):
        await telegram_client.send_message(
            chat_id=chat_id,
            text="Слишком много запросов. Подожди минуту.",
        )
        return {"ok": True}

    # ---- Commands (exact match) ----
    if text in {"/health", "/статус"}:
        await telegram_client.send_message(
            chat_id=chat_id,
            text="Backend работает. Память задач включена: SQLite workflow.db.",
        )
        return {"ok": True}

    if text in {"/sync_notion", "/ноушен"}:
        reply = await handle_notion_sync_command(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/sync_from_notion", "/из_ноушен"}:
        reply = await handle_notion_pull_command(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/brief", "/бриф"}:
        await send_morning_brief(chat_id=chat_id)
        return {"ok": True}

    if text in {"/retro", "/ретро"}:
        await send_evening_retro(chat_id=chat_id)
        return {"ok": True}

    if text in {"/memory", "/память"}:
        reply = await build_memory_overview(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/tasks", "/задачи"}:
        reply, reply_markup = await build_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/today", "/сегодня"}:
        reply, reply_markup = await build_today_focus_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/tomorrow", "/завтра"}:
        reply, reply_markup = await build_day_tasks_reply(
            chat_id=chat_id,
            target_date=date.today() + timedelta(days=1),
            empty_text="На завтра задач нет. Можешь добавить задачу обычным сообщением.",
            title="Задачи на завтра:",
        )
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/week", "/неделя"}:
        reply, reply_markup = await build_week_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/active", "/активные"}:
        reply, reply_markup = await build_active_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/next", "/дальше"}:
        reply, reply_markup = await build_next_task_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text in {"/projects", "/проекты"}:
        reply = await build_projects_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    # ---- Commands (prefix match) ----
    if text and (text.startswith("/project") or text.startswith("/проект")):
        reply, reply_markup = await handle_project_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text and (text.startswith("/done") or text.startswith("/готово")):
        reply = await handle_done_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/delete") or text.startswith("/удалить")):
        reply = await handle_delete_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/cancel") or text.startswith("/отмена")):
        reply = await handle_status_command(
            text=text,
            chat_id=chat_id,
            action=mark_task_cancelled,
            success_text="Задача отменена.",
            usage_text="Напиши так: /отмена 1",
        )
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/rename") or text.startswith("/переименовать")):
        reply = await handle_rename_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/priority") or text.startswith("/приоритет")):
        reply = await handle_priority_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/remind") or text.startswith("/напомни")):
        reply = await handle_remind_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/deadline") or text.startswith("/срок")):
        reply = await handle_deadline_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/subtasks") or text.startswith("/подзадачи")):
        reply, reply_markup = await handle_subtasks_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text and (text.startswith("/subdone") or text.startswith("/подготово")):
        reply = await handle_subtask_done_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/plan") or text.startswith("/план")):
        reply = await handle_plan_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    # ---- Finance commands ----
    if text and (text.startswith("/финансы") or text.startswith("/finance")):
        reply = await handle_finances_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/выручка") or text.startswith("/revenue")):
        reply = await handle_revenue_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/расход") or text.startswith("/expense")):
        reply = await handle_expense_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/отчет") or text.startswith("/report")):
        reply = await handle_report_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/сотрудники", "/staff"}:
        reply = await handle_staff_command(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/сотрудник_добавить") or text.startswith("/staff_add")):
        reply = await handle_staff_add_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/сотрудник_убрать") or text.startswith("/staff_remove")):
        reply = await handle_staff_remove_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/смена ") or text.startswith("/shift ")):
        reply = await handle_shift_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/смена_убрать") or text.startswith("/shift_remove")):
        reply = await handle_shift_remove_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/расчет") or text.startswith("/payroll")):
        reply = await handle_payroll_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/выплатить") or text.startswith("/pay ")):
        reply = await handle_pay_command(chat_id=chat_id, text=text)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    # ---- Natural language overviews ----
    if text and is_tomorrow_overview_request(text):
        reply, reply_markup = await build_day_tasks_reply(
            chat_id=chat_id,
            target_date=date.today() + timedelta(days=1),
            empty_text="На завтра задач нет. Хочешь добавить задачу? Просто напиши ее сообщением.",
            title="Задачи на завтра:",
        )
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    if text and is_week_overview_request(text):
        reply, reply_markup = await build_week_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply, reply_markup=reply_markup)
        return {"ok": True}

    # ---- Retrospective answer, task intent, or finance free-text ----
    if text:
        retro_reply = await handle_retrospective_response(chat_id=chat_id, text=text)
        if retro_reply:
            await telegram_client.send_message(chat_id=chat_id, text=retro_reply)
            return {"ok": True}

        intent_reply = await try_handle_task_intent(chat_id=chat_id, text=text)
        if intent_reply:
            await telegram_client.send_message(chat_id=chat_id, text=intent_reply)
            return {"ok": True}

        # Finance keywords take priority over generic AI classification
        if is_finance_message(text):
            reply = await handle_finance_input(chat_id=chat_id, text=text)
            await telegram_client.send_message(chat_id=chat_id, text=reply)
            return {"ok": True}

    # ---- Voice or free-form text → AI classify ----
    if voice:
        try:
            from app.ai_client import ai_client

            file_path = await telegram_client.get_file_path(voice["file_id"])
            audio_bytes = await telegram_client.download_file(file_path)
            transcribed_text = await ai_client.transcribe_audio(
                audio_bytes=audio_bytes,
                filename=file_path.split("/")[-1],
            )
            if not transcribed_text:
                reply = "Я получил голосовое, но не смог распознать текст."
            elif is_finance_message(transcribed_text):
                finance_reply = await handle_finance_input(chat_id=chat_id, text=transcribed_text)
                reply = f"Распознал голосовое:\n{transcribed_text}\n\n{finance_reply}"
            else:
                reply = await process_text_message(
                    chat_id=chat_id,
                    text=transcribed_text,
                    prefix=f"Распознал голосовое:\n{transcribed_text}\n\n",
                )
        except Exception as error:
            traceback.print_exc()
            reply = f"Получил голосовое, но обработка не сработала: {error}"
    elif text:
        try:
            reply = await process_text_message(chat_id=chat_id, text=text)
        except Exception as error:
            traceback.print_exc()
            reply = f"Принял текст, но обработка не сработала: {error}"
    else:
        reply = "Пока я умею принимать текст и голосовые сообщения."

    await telegram_client.send_message(chat_id=chat_id, text=reply)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_chat_allowed(chat_id: int) -> bool:
    """Return True if chat_id is permitted.

    If ALLOWED_CHAT_IDS is empty (default), all chats are allowed.
    Set it in .env to restrict access:  ALLOWED_CHAT_IDS=123456789
    """
    if not settings.allowed_chat_ids:
        return True
    return chat_id in settings.allowed_chat_ids
