from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.agent_memory import build_retrospective_memory_text, remember
from app.ai_client import ai_client
from app.config import settings
from app.database import (
    create_or_update_daily_retrospective,
    get_pending_retrospective,
    list_chat_ids_for_retrospective,
    list_today_focus_tasks,
    save_retrospective_response,
    update_retrospective_status,
)
from app.telegram_client import telegram_client


async def evening_retro() -> None:
    chat_ids = await list_chat_ids_for_retrospective()
    for chat_id in chat_ids:
        await send_evening_retro(chat_id=chat_id)


async def send_evening_retro(chat_id: int) -> None:
    today = datetime.now(ZoneInfo(settings.evening_retro_timezone)).date()
    tasks = await list_today_focus_tasks(
        chat_id=chat_id,
        today=today.isoformat(),
        limit=12,
    )
    text = _build_evening_retro_text(tasks=tasks)
    await create_or_update_daily_retrospective(
        chat_id=chat_id,
        retro_date=today.isoformat(),
        prompt_text=text,
    )
    await telegram_client.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_evening_retro_keyboard(),
    )


async def handle_retrospective_response(chat_id: int, text: str) -> str | None:
    pending = await get_pending_retrospective(chat_id=chat_id)
    if pending is None:
        return None

    tasks = await list_today_focus_tasks(
        chat_id=chat_id,
        today=pending["retro_date"],
        limit=12,
    )
    summary = await ai_client.summarize_retrospective(
        retro_date=pending["retro_date"],
        response_text=text,
        task_context=_format_tasks_for_prompt(tasks),
    )
    await save_retrospective_response(
        chat_id=chat_id,
        retro_id=pending["id"],
        response_text=text,
        summary=summary,
    )
    await remember(
        chat_id=chat_id,
        text=build_retrospective_memory_text(
            retro_date=pending["retro_date"],
            response_text=text,
            summary=summary,
        ),
        source="retrospective",
        metadata={
            "retro_id": pending["id"],
            "retro_date": pending["retro_date"],
        },
    )
    return _build_retrospective_saved_reply(summary=summary)


async def handle_retrospective_callback(
    callback_query_id: str,
    chat_id: int,
    action: str,
) -> None:
    pending = await get_pending_retrospective(chat_id=chat_id)
    if pending is None:
        text = "Активной вечерней ретроспективы сейчас нет. Можно запустить вручную: /retro"
    elif action == "write":
        text = (
            "Напиши одним сообщением:\n"
            "1. Что сделал?\n"
            "2. Что не сделал?\n"
            "3. Что пошло не так?\n"
            "4. Где времени не хватило или было больше, чем ожидал?"
        )
    elif action == "skip":
        await update_retrospective_status(
            chat_id=chat_id,
            retro_id=pending["id"],
            status="skipped",
        )
        text = "Ок, пропустил ретроспективу на сегодня."
    else:
        text = "Неизвестное действие для ретроспективы."

    await telegram_client.answer_callback_query(
        callback_query_id=callback_query_id,
        text=text,
    )
    await telegram_client.send_message(chat_id=chat_id, text=text)


def _build_evening_retro_text(tasks: list[dict[str, Any]]) -> str:
    lines = [
        "Вечерняя ретроспектива.",
        "",
        "Давай коротко закроем день, чтобы завтра я точнее оценивал время и порядок задач.",
    ]

    if tasks:
        lines.extend(["", "Сегодня в фокусе были:"])
        for task in tasks[:8]:
            due = task.get("due_date") or task.get("planning_period") or "без срока"
            estimate = task.get("estimated_minutes") or "нет оценки"
            lines.append(f"- #{task['id']} {task['title']} ({task['priority']}, {due}, оценка: {estimate} мин)")
    else:
        lines.extend(["", "Фокусных задач в базе на сегодня не было."])

    lines.extend(
        [
            "",
            "Ответь одним сообщением:",
            "1. Что сделал?",
            "2. Что не сделал?",
            "3. Что пошло не так?",
            "4. Где оценка времени была неверной?",
        ]
    )
    return "\n".join(lines)


def _format_tasks_for_prompt(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "Фокусных задач не было."

    lines = []
    for task in tasks:
        due = task.get("due_date") or task.get("planning_period") or "без срока"
        lines.append(
            f"- #{task['id']} {task['title']} "
            f"[{task['priority']}, {task['status']}]. "
            f"Срок/период: {due}. "
            f"Оценка: {task.get('estimated_minutes') or 'нет'} мин. "
            f"Факт: {task.get('actual_minutes') or 'нет'} мин."
        )
    return "\n".join(lines)


def _build_retrospective_saved_reply(summary: dict[str, Any]) -> str:
    time_notes = summary.get("time_estimation_notes") or []
    planning_rules = summary.get("planning_rules") or []

    lines = [
        "Ретроспектива сохранена.",
        "Я буду учитывать это в следующих планах и утренних брифах.",
    ]

    if time_notes:
        lines.extend(["", "Что учту по времени:"])
        lines.extend(f"- {note}" for note in time_notes[:3])

    if planning_rules:
        lines.extend(["", "Правила для следующих планов:"])
        lines.extend(f"- {rule}" for rule in planning_rules[:3])

    return "\n".join(lines)


def _evening_retro_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Записать ретро", "callback_data": "retro:write"},
                {"text": "Пропустить", "callback_data": "retro:skip"},
            ]
        ]
    }
