"""Read-only view builders for task lists and overviews."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.agent_memory import list_recent_memory
from app.database import (
    get_project,
    list_active_tasks,
    list_next_task_candidates,
    list_project_tasks,
    list_projects,
    list_recent_tasks,
    list_subtasks_due_today,
    list_tasks_by_due_date,
    list_tasks_by_planning_period,
    list_today_focus_tasks,
)
from app.handlers.formatters import (
    build_memory_reply,
    build_task_list_keyboard,
    days_until_week_end,
    format_subtasks_today,
    format_task_time,
    format_task_timing,
)


async def build_tasks_reply(chat_id: int) -> tuple[str, dict | None]:
    tasks = await list_recent_tasks(chat_id=chat_id)
    if not tasks:
        return (
            "Пока нет сохраненных задач. "
            "Отправь новую задачу обычным сообщением, потом снова напиши /задачи.",
            None,
        )
    header = f"Последние задачи — {len(tasks)} шт. Нажми, чтобы открыть:"
    return header, build_task_list_keyboard(tasks)


async def build_today_focus_reply(chat_id: int) -> tuple[str, dict | None]:
    today = date.today()
    tasks = await list_today_focus_tasks(chat_id=chat_id, today=today.isoformat())
    subtasks = await list_subtasks_due_today(chat_id=chat_id, today=today.isoformat())

    if not tasks and not subtasks:
        return (
            "На сегодня нет задач и срочных фокусов. "
            "Можешь добавить задачу обычным сообщением, например: `Срочно проверить документы СЭС`.",
            None,
        )

    parts = []
    if tasks:
        parts.append(f"Фокус на сегодня — {len(tasks)} задач:")
    if subtasks:
        parts.append(format_subtasks_today(subtasks))

    header = "\n\n".join(parts)
    keyboard = build_task_list_keyboard(tasks) if tasks else None
    return header, keyboard


async def build_day_tasks_reply(
    chat_id: int,
    target_date: date,
    empty_text: str,
    title: str,
) -> tuple[str, dict | None]:
    tasks = await list_tasks_by_due_date(chat_id=chat_id, due_date=target_date.isoformat())
    if not tasks:
        return empty_text, None
    return title, build_task_list_keyboard(tasks)


async def build_week_tasks_reply(chat_id: int) -> tuple[str, dict | None]:
    tasks = await list_tasks_by_planning_period(chat_id=chat_id, planning_period="week")
    if not tasks:
        return (
            "На неделю пока нет задач без точной даты. "
            "Можешь добавить задачу обычным сообщением, например: `На неделю проверить документы СЭС`.",
            None,
        )
    return f"Задачи на неделю — {len(tasks)} шт.:", build_task_list_keyboard(tasks)


async def build_active_tasks_reply(chat_id: int) -> tuple[str, dict | None]:
    tasks = await list_active_tasks(chat_id=chat_id)
    if not tasks:
        return "Активных задач нет. Можно добавить новую задачу обычным сообщением.", None
    return f"Активные задачи — {len(tasks)} шт.:", build_task_list_keyboard(tasks)


async def build_next_task_reply(chat_id: int) -> tuple[str, dict | None]:
    today = date.today()
    tasks = await list_next_task_candidates(chat_id=chat_id, today=today.isoformat(), limit=5)
    if not tasks:
        return "Активных задач нет. Можно добавить новую задачу обычным сообщением.", None

    task = tasks[0]
    project = f"\nПроект: {task['project_name']}" if task.get("project_name") else ""
    timing = format_task_timing(task=task, today=today)
    time_info = format_task_time(task)
    reminder = f"\nНапоминание: {task['reminder_at']}" if task.get("reminder_at") else ""

    lines = [
        "Следующий лучший шаг:",
        "",
        f"Задача #{task['id']}: {task['title']}",
        f"Приоритет: {task['priority']}{timing}{time_info}",
    ]
    if project:
        lines.append(project.lstrip())
    if task.get("next_subtask_title"):
        lines.extend(
            [
                "",
                f"Начни с подзадачи #{task['next_subtask_id']}: {task['next_subtask_title']}",
                f"Закрыть шаг: /subdone {task['next_subtask_id']}",
            ]
        )
    else:
        lines.extend(["", f"Закрыть задачу: /done {task['id']}"])
    if reminder:
        lines.append(reminder.lstrip())

    if len(tasks) > 1:
        lines.extend(["", "Дальше в очереди:"])
        for next_task in tasks[1:4]:
            lines.append(f"{next_task['id']}. {next_task['title']} ({next_task['priority']})")

    return "\n".join(lines), build_task_actions_keyboard([task])


async def build_projects_reply(chat_id: int) -> str:
    projects = await list_projects(chat_id=chat_id)
    if not projects:
        return (
            "Пока нет проектов. "
            "Отправь задачу с понятным направлением, и бот заведет проект автоматически."
        )
    lines = ["Проекты:"]
    for project in projects:
        lines.append(
            f"{project['id']}. {project['name']} "
            f"(активных: {project['active_task_count'] or 0}, всего: {project['task_count'] or 0})"
        )
    lines.extend(["", "Открыть проект: /project 1"])
    return "\n".join(lines)


async def handle_project_command(text: str, chat_id: int) -> tuple[str, dict | None]:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /project 1", None

    project_id = int(parts[1])
    project = await get_project(chat_id=chat_id, project_id=project_id)
    if project is None:
        return f"Не нашел проект #{project_id}.", None

    tasks = await list_project_tasks(chat_id=chat_id, project_id=project_id)
    description = project.get("description") or "описание пока не задано"
    lines = [
        f"Проект #{project['id']}: {project['name']}",
        f"Статус: {project['status']}",
        f"Активных задач: {project['active_task_count'] or 0}",
        f"Всего задач: {project['task_count'] or 0}",
        f"Описание: {description}",
    ]

    if tasks:
        lines.append("")
        return "\n".join(lines), build_task_list_keyboard(tasks)

    lines.extend(["", "В этом проекте пока нет задач."])
    return "\n".join(lines), None


async def build_memory_overview(chat_id: int) -> str:
    memories = await list_recent_memory(chat_id=chat_id, limit=8)
    return build_memory_reply(memories)


def is_tomorrow_overview_request(text: str) -> bool:
    normalized = text.lower().strip()
    if normalized.startswith("/"):
        return False
    prefixes = (
        "план на завтра",
        "задачи на завтра",
        "дела на завтра",
        "что на завтра",
        "список задач на завтра",
        "список дел на завтра",
        "покажи задачи на завтра",
        "покажи план на завтра",
        "какие задачи на завтра",
        "какой план на завтра",
    )
    return any(normalized.startswith(p) for p in prefixes)


def is_week_overview_request(text: str) -> bool:
    normalized = text.lower().strip()
    if normalized.startswith("/"):
        return False
    prefixes = (
        "план на неделю",
        "задачи на неделю",
        "дела на неделю",
        "что на неделю",
        "список задач на неделю",
        "список дел на неделю",
        "покажи задачи на неделю",
        "покажи план на неделю",
        "какие задачи на неделю",
        "какой план на неделю",
    )
    return any(normalized.startswith(p) for p in prefixes)
