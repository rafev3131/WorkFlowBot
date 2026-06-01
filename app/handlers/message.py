"""Incoming message processing: classify → plan → save → respond."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.agent_memory import (
    build_planner_memory_text,
    format_memory_context,
    remember,
    search_memory,
)
from app.ai_client import ai_client
from app.database import (
    get_task,
    list_planner_context_tasks,
    list_project_context,
    list_recent_retrospectives,
    list_tasks_for_notion_sync,
    replace_subtasks,
    save_task,
)
from app.handlers.formatters import build_task_actions_keyboard
from app.handlers.notion import try_sync_task_to_notion
from app.handlers.task_commands import extract_subtasks, _normalize_reminder_at
from app.message_formatter import format_analysis, format_planner_result
from app.scheduler import schedule_task_reminder
from app.supervisor import supervise_analysis
from app.task_intents import find_matching_task, parse_task_intent
from app.workflow_context import (
    format_project_context,
    format_retrospective_context,
    format_task_context,
    load_workflow_context,
)


async def process_text_message(chat_id: int, text: str, prefix: str = "") -> str:
    analysis = await ai_client.analyze_message(text)
    analysis = supervise_analysis(text=text, analysis=analysis)
    _normalize_analysis_reminder(analysis)

    plan = None
    if analysis.get("assigned_agent") == "planner_agent":
        planner_tasks = await list_planner_context_tasks(chat_id=chat_id)
        projects = await list_project_context(chat_id=chat_id)
        retrospectives = await list_recent_retrospectives(chat_id=chat_id, limit=5)
        memories = await search_memory(chat_id=chat_id, query=text, limit=6)
        plan = await ai_client.run_planner(
            text=text,
            analysis=analysis,
            workflow_context=load_workflow_context(),
            task_context=format_task_context(planner_tasks),
            project_context=format_project_context(projects),
            retrospective_context=format_retrospective_context(retrospectives),
            memory_context=format_memory_context(memories),
        )
        result = format_planner_result(analysis=analysis, plan=plan)
        reply = result
    else:
        result = analysis.get("summary", "")
        reply = format_analysis(analysis)

    task_id = await save_task(
        chat_id=chat_id,
        user_text=text,
        analysis=analysis,
        result=result,
    )
    if plan:
        await replace_subtasks(
            chat_id=chat_id,
            task_id=task_id,
            subtasks=extract_subtasks(plan),
        )
        await remember(
            chat_id=chat_id,
            text=build_planner_memory_text(
                task_id=task_id,
                title=analysis.get("title", "Без названия"),
                plan=plan,
            ),
            source="planner_advice",
            metadata={
                "task_id": task_id,
                "task_title": analysis.get("title", ""),
                "priority": analysis.get("priority", ""),
                "project": analysis.get("project", ""),
            },
        )

    reminder_note = await _try_schedule_task_reminder(
        chat_id=chat_id,
        task_id=task_id,
        reminder_at=analysis.get("reminder_at"),
    )
    notion_note = await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"{prefix}Задача #{task_id} сохранена.{reminder_note}{notion_note}\n\n{reply}"


async def try_handle_task_intent(chat_id: int, text: str) -> str | None:
    intent = parse_task_intent(text)
    if intent is None:
        return None

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    task = None
    if intent.get("task_id"):
        task = await get_task(chat_id=chat_id, task_id=intent["task_id"])
    if task is None:
        alias = intent.get("alias")
        task = find_matching_task(tasks=tasks, alias=alias) if alias else None
    if task is None:
        return _build_unclear_task_reference_reply(intent=intent, tasks=tasks)

    if intent["intent"] == "update_due_date":
        from app.database import update_task_due_date

        await update_task_due_date(
            chat_id=chat_id,
            task_id=task["id"],
            due_date=intent["due_date"],
        )
        await try_sync_task_to_notion(chat_id=chat_id, task_id=task["id"])
        return f"Обновил срок задачи #{task['id']} «{task['title']}»: {intent['due_date']}."

    if intent["intent"] == "cancel_task":
        from app.database import mark_task_cancelled

        await mark_task_cancelled(chat_id=chat_id, task_id=task["id"])
        await try_sync_task_to_notion(chat_id=chat_id, task_id=task["id"])
        return f"Отменил задачу #{task['id']} «{task['title']}»."

    return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalize_analysis_reminder(analysis: dict[str, Any]) -> None:
    reminder_at = _normalize_reminder_at(str(analysis.get("reminder_at") or ""))
    if reminder_at:
        analysis["reminder_at"] = reminder_at
        return

    if analysis.get("type") == "reminder" or analysis.get("assigned_agent") == "reminder_agent":
        due_date = analysis.get("due_date")
        if due_date:
            analysis["reminder_at"] = f"{due_date} 10:00"


async def _try_schedule_task_reminder(
    chat_id: int,
    task_id: int,
    reminder_at: str | None,
) -> str:
    if not reminder_at:
        return ""

    scheduled = schedule_task_reminder(
        chat_id=chat_id,
        task_id=task_id,
        reminder_at=reminder_at,
    )
    if not scheduled:
        return f"\nНапоминание: время не распознано ({reminder_at})."
    return f"\nНапоминание: {reminder_at}."


def _build_unclear_task_reference_reply(intent: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    if intent["intent"] == "update_due_date":
        action = f"поставить срок {intent['due_date']}"
    elif intent["intent"] == "cancel_task":
        action = "отменить задачу"
    else:
        action = "изменить задачу"

    active_tasks = [task for task in tasks if task.get("status") not in {"done", "cancelled"}]
    lines = [
        f"Я понял, что нужно {action}, но не уверен, какую именно задачу ты имеешь в виду.",
        "",
        "Напиши номер задачи, например:",
    ]

    if intent["intent"] == "update_due_date":
        lines.append(f"/deadline 7 {intent['due_date']}")
    else:
        lines.append("/cancel 7")

    if active_tasks:
        lines.extend(["", "Похожие активные задачи:"])
        for task in active_tasks[:8]:
            lines.append(f"{task['id']}. {task['title']} ({task['priority']}, {task['status']})")

    lines.extend(
        [
            "",
            "Если это новая задача, напиши ее как отдельное действие "
            "без слов про редактирование существующей задачи.",
        ]
    )
    return "\n".join(lines)
