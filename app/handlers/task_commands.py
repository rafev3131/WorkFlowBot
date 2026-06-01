"""Mutation command handlers for tasks and subtasks."""
from __future__ import annotations

import json
from typing import Any

from app.agent_memory import (
    build_planner_memory_text,
    format_memory_context,
    remember,
    search_memory,
)
from app.ai_client import ai_client
from app.database import (
    all_subtasks_done,
    get_subtask,
    get_task,
    list_planner_context_tasks,
    list_project_context,
    list_recent_retrospectives,
    list_subtasks,
    mark_subtask_done,
    mark_task_cancelled,
    mark_task_done,
    mark_task_done_with_time,
    replace_subtasks,
    update_task_due_date,
    update_task_plan,
    update_task_priority,
    update_task_reminder,
    update_task_title,
)
from app.handlers.formatters import (
    build_subtask_actions_keyboard,
    build_task_actions_keyboard,
    format_subtasks_reply,
)
from app.handlers.notion import try_sync_task_to_notion
from app.message_formatter import format_planner_result
from app.scheduler import schedule_task_reminder
from app.workflow_context import (
    format_project_context,
    format_retrospective_context,
    format_task_context,
    load_workflow_context,
)


# ---------------------------------------------------------------------------
# Done / delete / rename / priority / remind / deadline
# ---------------------------------------------------------------------------

async def handle_status_command(
    text: str,
    chat_id: int,
    action,
    success_text: str,
    usage_text: str,
) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return usage_text

    task_id = int(parts[1])
    updated = await action(chat_id=chat_id, task_id=task_id)
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return success_text


async def handle_done_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) not in {2, 3} or not parts[1].isdigit():
        return "Напиши так: /done 1 или /done 1 120, где 120 — фактические минуты."

    task_id = int(parts[1])
    actual_minutes = None
    if len(parts) == 3:
        if not parts[2].isdigit() or int(parts[2]) <= 0:
            return "Фактическое время должно быть числом минут, например: /done 1 120"
        actual_minutes = int(parts[2])

    task_before = await get_task(chat_id=chat_id, task_id=task_id)
    if task_before is None:
        return f"Не нашел задачу #{task_id}."

    updated = await mark_task_done_with_time(
        chat_id=chat_id,
        task_id=task_id,
        actual_minutes=actual_minutes,
    )
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)

    task_after = await get_task(chat_id=chat_id, task_id=task_id)
    if actual_minutes is not None and task_after:
        await remember(
            chat_id=chat_id,
            text=_build_time_feedback_memory(task_after),
            source="time_feedback",
            metadata={
                "task_id": task_id,
                "task_title": task_after.get("title", ""),
                "estimated_minutes": task_after.get("estimated_minutes") or "",
                "actual_minutes": task_after.get("actual_minutes") or "",
                "time_estimation_accuracy": task_after.get("time_estimation_accuracy") or "",
            },
        )

    if actual_minutes is None:
        return "Готово, задача закрыта. Если хочешь обучить оценку времени, в следующий раз можно так: /done 1 120"

    estimate = task_after.get("estimated_minutes") if task_after else task_before.get("estimated_minutes")
    accuracy = task_after.get("time_estimation_accuracy") if task_after else None
    if estimate and accuracy is not None:
        return (
            f"Готово, задача закрыта. "
            f"Оценка: {estimate} мин, факт: {actual_minutes} мин, точность: {accuracy}%."
        )
    return f"Готово, задача закрыта. Фактическое время: {actual_minutes} мин."


async def handle_delete_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /delete 1"

    task_id = int(parts[1])
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    await mark_task_cancelled(chat_id=chat_id, task_id=task_id)
    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Убрал задачу #{task_id} «{task['title']}» из активных."


async def handle_rename_command(text: str, chat_id: int) -> str:
    parts = text.split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].strip():
        return "Напиши так: /rename 1 Новое название задачи"

    task_id = int(parts[1])
    title = parts[2].strip()
    updated = await update_task_title(chat_id=chat_id, task_id=task_id, title=title)
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Переименовал задачу #{task_id}: «{title}»."


async def handle_priority_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        return "Напиши так: /priority 1 high"

    priority = parts[2].lower()
    if priority not in {"high", "medium", "low"}:
        return "Приоритет должен быть high, medium или low."

    task_id = int(parts[1])
    updated = await update_task_priority(chat_id=chat_id, task_id=task_id, priority=priority)
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Обновил приоритет задачи #{task_id}: {priority}."


async def handle_remind_command(text: str, chat_id: int) -> str:
    parts = text.split(maxsplit=3)
    if len(parts) < 3 or not parts[1].isdigit():
        return "Напиши так: /remind 1 2026-06-02 14:30 или /remind 1 off"

    task_id = int(parts[1])
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    value = " ".join(parts[2:]).strip()
    if value.lower() in {"off", "нет", "убрать", "disable"}:
        await update_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=None)
        await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
        return f"Убрал напоминание у задачи #{task_id}."

    reminder_at = _normalize_reminder_at(value)
    if reminder_at is None:
        return "Время напоминания должно быть в формате YYYY-MM-DD HH:MM, например: /remind 1 2026-06-02 14:30"

    await update_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=reminder_at)
    scheduled = schedule_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=reminder_at)
    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    if not scheduled:
        return f"Сохранил напоминание для задачи #{task_id}, но не смог поставить его в scheduler: {reminder_at}."
    return f"Напоминание для задачи #{task_id} поставлено на {reminder_at}."


async def handle_deadline_command(text: str, chat_id: int) -> str:
    from datetime import date

    parts = text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        return "Напиши так: /deadline 7 2026-06-15"

    task_id = int(parts[1])
    due_date = parts[2]
    try:
        date.fromisoformat(due_date)
    except ValueError:
        return "Дата должна быть в формате YYYY-MM-DD, например: /deadline 7 2026-06-15"

    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    await update_task_due_date(chat_id=chat_id, task_id=task_id, due_date=due_date)
    await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Обновил срок задачи #{task_id} «{task['title']}»: {due_date}."


# ---------------------------------------------------------------------------
# Plan / subtasks
# ---------------------------------------------------------------------------

async def handle_plan_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /plan 1"

    task_id = int(parts[1])
    return await build_plan_for_saved_task(chat_id=chat_id, task_id=task_id)


async def handle_subtasks_command(text: str, chat_id: int) -> tuple[str, dict | None]:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /subtasks 1", None

    task_id = int(parts[1])
    return await build_subtasks_for_task(chat_id=chat_id, task_id=task_id)


async def handle_subtask_done_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /subdone 1"

    subtask_id = int(parts[1])
    updated = await mark_subtask_done(chat_id=chat_id, subtask_id=subtask_id)
    if not updated:
        return f"Не нашел подзадачу #{subtask_id}."

    reply = await build_subtask_done_reply(chat_id=chat_id, subtask_id=subtask_id)
    subtask = await get_subtask(chat_id=chat_id, subtask_id=subtask_id)
    if subtask:
        await try_sync_task_to_notion(chat_id=chat_id, task_id=subtask["task_id"])
    return reply


async def build_plan_for_saved_task(chat_id: int, task_id: int) -> str:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    try:
        analysis = json.loads(task["analysis_json"])
    except json.JSONDecodeError:
        analysis = {
            "type": task["task_type"],
            "title": task["title"],
            "summary": task["user_text"],
            "priority": task["priority"],
            "assigned_agent": "planner_agent",
            "can_be_automated": False,
            "needs_clarification": True,
            "next_action": "Пересобрать план по сохраненной задаче",
        }

    analysis["assigned_agent"] = "planner_agent"
    planner_tasks = await list_planner_context_tasks(chat_id=chat_id)
    projects = await list_project_context(chat_id=chat_id)
    memories = await search_memory(
        chat_id=chat_id,
        query=f"{task['title']}\n{task['user_text']}",
        limit=6,
    )
    plan = await ai_client.run_planner(
        text=task["user_text"],
        analysis=analysis,
        workflow_context=load_workflow_context(),
        task_context=format_task_context(planner_tasks),
        project_context=format_project_context(projects),
        retrospective_context=format_retrospective_context(
            await list_recent_retrospectives(chat_id=chat_id, limit=5)
        ),
        memory_context=format_memory_context(memories),
    )
    result = format_planner_result(analysis=analysis, plan=plan)
    await update_task_plan(
        chat_id=chat_id,
        task_id=task_id,
        analysis=analysis,
        result=result,
    )
    await replace_subtasks(
        chat_id=chat_id,
        task_id=task_id,
        subtasks=extract_subtasks(plan),
    )
    await remember(
        chat_id=chat_id,
        text=build_planner_memory_text(
            task_id=task_id,
            title=task["title"],
            plan=plan,
        ),
        source="planner_advice",
        metadata={
            "task_id": task_id,
            "task_title": task["title"],
            "priority": task["priority"],
            "project_id": task.get("project_id") or "",
        },
    )
    notion_note = await try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"План для задачи #{task_id} обновлен.{notion_note}\n\n{result}"


async def build_subtasks_for_task(chat_id: int, task_id: int) -> tuple[str, dict | None]:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}.", None

    subtasks = await list_subtasks(chat_id=chat_id, task_id=task_id)
    if not subtasks:
        return (
            f"У задачи #{task_id} пока нет подзадач. "
            f"Нажми `План #{task_id}` или напиши /plan {task_id}, чтобы Planner разложил ее на шаги.",
            None,
        )
    return format_subtasks_reply(task=task, subtasks=subtasks), build_subtask_actions_keyboard(subtasks)


async def build_subtask_done_reply(chat_id: int, subtask_id: int) -> str:
    subtask = await get_subtask(chat_id=chat_id, subtask_id=subtask_id)
    if subtask is None:
        return f"Готово, подзадача #{subtask_id} закрыта."

    task_id = subtask["task_id"]
    if await all_subtasks_done(chat_id=chat_id, task_id=task_id):
        await mark_task_done(chat_id=chat_id, task_id=task_id)
        return (
            f"Готово, подзадача #{subtask_id} закрыта.\n"
            f"Все подзадачи выполнены, задача #{task_id} тоже закрыта."
        )
    return f"Готово, подзадача #{subtask_id} закрыта."


def extract_subtasks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract subtask dicts with title, due_date, estimated_minutes from planner output."""
    result: list[dict[str, Any]] = []
    for phase in plan.get("phases", []):
        steps = phase.get("steps", []) if isinstance(phase, dict) else [phase]
        for step in steps:
            if isinstance(step, dict):
                title = str(step.get("title", "")).strip()
                if not title:
                    continue
                result.append(
                    {
                        "title": title,
                        "due_date": step.get("due_date") or None,
                        "estimated_minutes": step.get("estimated_minutes") or None,
                    }
                )
            else:
                title = str(step).strip()
                if title:
                    result.append({"title": title, "due_date": None, "estimated_minutes": None})
    return result[:15]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_time_feedback_memory(task: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Факт времени по задаче #{task['id']}: {task['title']}.",
            f"Оценка: {task.get('estimated_minutes') or 'нет'} мин.",
            f"Факт: {task.get('actual_minutes') or 'нет'} мин.",
            f"Точность оценки: {task.get('time_estimation_accuracy') or 'нет'}%.",
            "Используй это для будущих оценок похожих задач.",
        ]
    )


def _normalize_reminder_at(value: str) -> str | None:
    from datetime import datetime

    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None
