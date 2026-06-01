"""Telegram inline-keyboard callback handlers."""
from __future__ import annotations

from app.database import (
    get_task,
    mark_task_cancelled,
    mark_task_done,
    mark_subtask_done,
    get_subtask,
    update_task_status,
)
from app.handlers.formatters import build_task_detail_keyboard, build_task_detail_text
from app.handlers.task_commands import (
    build_plan_for_saved_task,
    build_subtask_done_reply,
    build_subtasks_for_task,
)
from app.handlers.task_views import build_active_tasks_reply
from app.handlers.notion import try_sync_task_to_notion
from app.retrospective import handle_retrospective_callback
from app.scheduler import schedule_morning_brief_snooze
from app.telegram_client import telegram_client


async def handle_callback_query(callback_query: dict) -> None:
    callback_query_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if chat_id is None:
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text="Не понял, к какому чату относится действие.",
        )
        return

    message_id = message.get("message_id")
    action, _, task_id_text = data.partition(":")

    # ── New task-detail UI ────────────────────────────────────────────────────
    if action == "tv":
        await _handle_task_view(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            message_id=message_id,
            task_id_text=task_id_text,
        )
        return

    if data == "tb":
        await _handle_task_back(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        return

    if action in ("ts", "td", "tc"):
        await _handle_task_status_action(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            message_id=message_id,
            action=action,
            task_id_text=task_id_text,
        )
        return
    # ─────────────────────────────────────────────────────────────────────────

    if action == "brief":
        await _handle_brief_callback(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            action=task_id_text,
        )
        return

    if action == "retro":
        await handle_retrospective_callback(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            action=task_id_text,
        )
        return

    if not task_id_text.isdigit():
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text="Не понял номер задачи.",
        )
        return

    task_id = int(task_id_text)

    if action == "done":
        updated = await mark_task_done(chat_id=chat_id, task_id=task_id)
        text = f"Задача #{task_id} закрыта." if updated else f"Не нашел задачу #{task_id}."
        if updated:
            await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)

    elif action == "cancel":
        updated = await mark_task_cancelled(chat_id=chat_id, task_id=task_id)
        text = f"Задача #{task_id} отменена." if updated else f"Не нашел задачу #{task_id}."
        if updated:
            await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)

    elif action == "plan":
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Готовлю план для задачи #{task_id}...",
        )
        text = await build_plan_for_saved_task(chat_id=chat_id, task_id=task_id)
        await telegram_client.send_message(chat_id=chat_id, text=text)
        return

    elif action == "subtasks":
        reply, reply_markup = await build_subtasks_for_task(chat_id=chat_id, task_id=task_id)
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Открываю шаги задачи #{task_id}.",
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return

    elif action == "subdone":
        updated = await mark_subtask_done(chat_id=chat_id, subtask_id=task_id)
        if updated:
            text = await build_subtask_done_reply(chat_id=chat_id, subtask_id=task_id)
            subtask = await get_subtask(chat_id=chat_id, subtask_id=task_id)
            if subtask:
                await try_sync_task_to_notion(chat_id=chat_id, task_id=subtask["task_id"])
        else:
            text = f"Не нашел подзадачу #{task_id}."

    else:
        text = "Неизвестное действие."

    await telegram_client.answer_callback_query(
        callback_query_id=callback_query_id,
        text=text,
    )
    await telegram_client.send_message(chat_id=chat_id, text=text)


async def _handle_task_view(
    callback_query_id: str,
    chat_id: int,
    message_id: int | None,
    task_id_text: str,
) -> None:
    if not task_id_text.isdigit():
        await telegram_client.answer_callback_query(callback_query_id=callback_query_id, text="Ошибка.")
        return
    task_id = int(task_id_text)
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id, text="Задача не найдена."
        )
        return
    text = build_task_detail_text(task)
    keyboard = build_task_detail_keyboard(task)
    await telegram_client.answer_callback_query(callback_query_id=callback_query_id, text="")
    if message_id:
        await telegram_client.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
        )
    else:
        await telegram_client.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def _handle_task_back(
    callback_query_id: str,
    chat_id: int,
    message_id: int | None,
) -> None:
    text, keyboard = await build_active_tasks_reply(chat_id=chat_id)
    await telegram_client.answer_callback_query(callback_query_id=callback_query_id, text="")
    if message_id and keyboard:
        await telegram_client.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
        )
    else:
        await telegram_client.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def _handle_task_status_action(
    callback_query_id: str,
    chat_id: int,
    message_id: int | None,
    action: str,
    task_id_text: str,
) -> None:
    if not task_id_text.isdigit():
        await telegram_client.answer_callback_query(callback_query_id=callback_query_id, text="Ошибка.")
        return
    task_id = int(task_id_text)

    if action == "ts":
        updated = await update_task_status(chat_id=chat_id, task_id=task_id, status="in_progress")
        toast = "Задача взята в работу." if updated else "Не удалось обновить."
    elif action == "td":
        updated = await mark_task_done(chat_id=chat_id, task_id=task_id)
        if updated:
            await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
        toast = "Задача завершена ✅" if updated else "Не удалось обновить."
    elif action == "tc":
        updated = await mark_task_cancelled(chat_id=chat_id, task_id=task_id)
        if updated:
            await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
        toast = "Задача отменена." if updated else "Не удалось обновить."
    else:
        toast = "Неизвестное действие."
        updated = False

    await telegram_client.answer_callback_query(callback_query_id=callback_query_id, text=toast)

    if updated:
        task = await get_task(chat_id=chat_id, task_id=task_id)
        if task and message_id:
            text = build_task_detail_text(task)
            keyboard = build_task_detail_keyboard(task)
            await telegram_client.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
            )


async def _handle_brief_callback(
    callback_query_id: str,
    chat_id: int,
    action: str,
) -> None:
    if action == "accept":
        text = "План принят. Держим фокус и закрываем по шагам."
    elif action == "edit":
        text = "Напиши, что изменить в плане: например, «сначала ревизия, потом P&L»."
    elif action == "snooze":
        schedule_morning_brief_snooze(chat_id=chat_id, minutes=60)
        text = "Ок, напомню через час."
    else:
        text = "Неизвестное действие для брифа."

    await telegram_client.answer_callback_query(
        callback_query_id=callback_query_id,
        text=text,
    )
    await telegram_client.send_message(chat_id=chat_id, text=text)
