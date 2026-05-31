from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.agent_memory import format_memory_context, search_memory
from app.ai_client import ai_client
from app.config import settings
from app.database import (
    list_chat_ids_for_morning_brief,
    list_open_subtasks_for_brief,
    list_recent_retrospectives,
    list_today_focus_tasks,
)
from app.telegram_client import telegram_client
from app.workflow_context import format_retrospective_context, load_workflow_context


async def morning_brief() -> None:
    chat_ids = await list_chat_ids_for_morning_brief()
    for chat_id in chat_ids:
        await send_morning_brief(chat_id=chat_id)


async def send_morning_brief(chat_id: int) -> None:
    today = datetime.now(ZoneInfo(settings.morning_brief_timezone)).date()
    tasks = await list_today_focus_tasks(
        chat_id=chat_id,
        today=today.isoformat(),
        limit=12,
    )
    subtasks = await list_open_subtasks_for_brief(chat_id=chat_id, limit=12)
    retrospectives = await list_recent_retrospectives(chat_id=chat_id, limit=5)
    memory_query = "\n".join(
        [
            f"Утренний бриф {today.isoformat()}",
            _format_tasks_for_prompt(tasks),
            _format_subtasks_for_prompt(subtasks),
        ]
    )
    memories = await search_memory(chat_id=chat_id, query=memory_query, limit=6)

    brief = await ai_client.build_morning_brief(
        today=today.isoformat(),
        task_context=_format_tasks_for_prompt(tasks),
        subtask_context=_format_subtasks_for_prompt(subtasks),
        workflow_context=load_workflow_context(),
        retrospective_context=format_retrospective_context(retrospectives),
        memory_context=format_memory_context(memories),
    )

    await telegram_client.send_message(
        chat_id=chat_id,
        text=brief,
        reply_markup=_morning_brief_keyboard(),
    )


def _format_tasks_for_prompt(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "Фокусных задач нет."

    lines = []
    for task in tasks:
        project = task.get("project_name") or "без проекта"
        due = task.get("due_date") or task.get("planning_period") or "без срока"
        time_info = _format_task_time(task)
        lines.append(
            f"- #{task['id']} {task['title']} "
            f"[{task['priority']}, {task['status']}]. "
            f"Проект: {project}. Срок/период: {due}. {time_info}"
        )
    return "\n".join(lines)


def _format_subtasks_for_prompt(subtasks: list[dict[str, Any]]) -> str:
    if not subtasks:
        return "Открытых подзадач нет."

    lines = []
    for subtask in subtasks:
        project = subtask.get("project_name") or "без проекта"
        lines.append(
            f"- #{subtask['id']} {subtask['title']} "
            f"(задача #{subtask['task_id']}: {subtask['task_title']}; "
            f"проект: {project}; приоритет: {subtask['task_priority']}; "
            f"оценка задачи: {subtask.get('task_estimated_minutes') or 'нет'} мин)"
        )
    return "\n".join(lines)


def _morning_brief_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Принять план", "callback_data": "brief:accept"},
                {"text": "📝 Изменить", "callback_data": "brief:edit"},
            ],
            [
                {"text": "⏰ Отложить напоминание", "callback_data": "brief:snooze"},
            ],
        ]
    }


def _format_task_time(task: dict[str, Any]) -> str:
    estimated = task.get("estimated_minutes")
    actual = task.get("actual_minutes")
    accuracy = task.get("time_estimation_accuracy")
    parts = []
    if estimated:
        parts.append(f"оценка {estimated} мин")
    if actual:
        parts.append(f"факт {actual} мин")
    if accuracy is not None:
        parts.append(f"точность {accuracy}%")
    return "Время: " + ", ".join(parts) + "." if parts else "Время не оценено."
