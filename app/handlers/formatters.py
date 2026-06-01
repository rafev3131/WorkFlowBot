"""Pure formatting helpers — no I/O, no DB, no async."""
from __future__ import annotations

from datetime import date
from typing import Any

STATUS_EMOJI = {
    "in_progress": "🔄",
    "todo": "📋",
    "planned": "📋",
    "done": "✅",
    "cancelled": "❌",
    "inbox": "📥",
}

PRIORITY_LABEL = {
    "critical": "🔴 Критично",
    "high": "🟠 Высокий",
    "medium": "🟡 Средний",
    "low": "⚪️ Низкий",
}


def status_emoji(status: str) -> str:
    return STATUS_EMOJI.get(status, "•")


def format_deadline_short(task: dict[str, Any], today: date) -> str:
    due = task.get("due_date")
    if not due:
        if task.get("planning_period") == "week":
            return "на неделю"
        return ""
    try:
        d = date.fromisoformat(due)
    except ValueError:
        return due
    diff = (d - today).days
    if diff < 0:
        return f"просрочено {abs(diff)} дн."
    if diff == 0:
        return "сегодня"
    if diff == 1:
        return "завтра"
    months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{d.day} {months[d.month - 1]}"


def format_deadline_full(task: dict[str, Any]) -> str:
    due = task.get("due_date")
    if not due:
        if task.get("planning_period") == "week":
            return "на эту неделю"
        return "без дедлайна"
    try:
        d = date.fromisoformat(due)
    except ValueError:
        return due
    months_full = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    return f"{d.day} {months_full[d.month - 1]} {d.year}"


def build_task_list_keyboard(tasks: list[dict[str, Any]]) -> dict:
    """One button per task, each opens the detail view."""
    today = date.today()
    rows = []
    for task in tasks:
        emoji = status_emoji(task["status"])
        deadline = format_deadline_short(task, today)
        label = f"{emoji} {task['title']}"
        if deadline:
            label += f" — {deadline}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([{"text": label, "callback_data": f"tv:{task['id']}"}])
    return {"inline_keyboard": rows}


def build_task_detail_text(task: dict[str, Any]) -> str:
    emoji = status_emoji(task["status"])
    lines = [f"{emoji} {task['title']}"]

    project = task.get("project_name") or task.get("project_id")
    if project:
        lines.append(f"\nПроект: {project}")

    deadline = format_deadline_full(task)
    lines.append(f"Дедлайн: {deadline}")

    priority = PRIORITY_LABEL.get(task.get("priority", ""), "")
    if priority:
        lines.append(f"Приоритет: {priority}")

    est = task.get("estimated_minutes")
    if est:
        lines.append(f"Оценка: {est} мин")

    description = task.get("user_text", "")
    title = task.get("title", "")
    if description and description.strip().lower() != title.strip().lower():
        short = description[:200].replace("\n", " ")
        if len(description) > 200:
            short += "…"
        lines.append(f"\n{short}")

    return "\n".join(lines)


def build_task_detail_keyboard(task: dict[str, Any]) -> dict:
    task_id = task["id"]
    status = task.get("status", "")

    action_rows: list[list[dict]] = []

    if status not in ("in_progress",):
        action_rows.append([{"text": "▶️ Начать", "callback_data": f"ts:{task_id}"}])

    row2 = []
    if status not in ("done",):
        row2.append({"text": "✅ Завершить", "callback_data": f"td:{task_id}"})
    if status not in ("cancelled",):
        row2.append({"text": "❌ Отказаться", "callback_data": f"tc:{task_id}"})
    if row2:
        action_rows.append(row2)

    action_rows.append([{"text": "← Назад к задачам", "callback_data": "tb"}])
    return {"inline_keyboard": action_rows}


# ── Legacy helpers (still used elsewhere) ─────────────────────────────────────

def format_task_time(task: dict[str, Any]) -> str:
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
    return f", {', '.join(parts)}" if parts else ""


def format_task_timing(task: dict[str, Any], today: date) -> str:
    due_date = task.get("due_date")
    if due_date:
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            return f", срок: {due_date}"
        days_left = (due - today).days
        if days_left < 0:
            return f", просрочено на {abs(days_left)} дн."
        if days_left == 0:
            return ", срок сегодня"
        return f", осталось {days_left} дн."
    if task.get("planning_period") == "week":
        days_left = days_until_week_end(today)
        return f", на неделю, осталось {days_left} дн."
    return ", без даты"


def days_until_week_end(today: date) -> int:
    days_left = 6 - today.weekday()
    return days_left if days_left > 0 else 7


def build_task_actions_keyboard(tasks: list[dict[str, Any]]) -> dict:
    """Legacy keyboard — replaced by build_task_list_keyboard in list views."""
    rows = []
    for task in tasks[:5]:
        task_id = task["id"]
        rows.append(
            [
                {"text": f"Готово #{task_id}", "callback_data": f"done:{task_id}"},
                {"text": f"Отмена #{task_id}", "callback_data": f"cancel:{task_id}"},
                {"text": f"План #{task_id}", "callback_data": f"plan:{task_id}"},
                {"text": f"Шаги #{task_id}", "callback_data": f"subtasks:{task_id}"},
            ]
        )
    return {"inline_keyboard": rows}


def build_subtask_actions_keyboard(subtasks: list[dict[str, Any]]) -> dict:
    rows = []
    for subtask in subtasks[:8]:
        if subtask["status"] == "done":
            continue
        subtask_id = subtask["id"]
        rows.append(
            [
                {
                    "text": f"Готово подзадача #{subtask_id}",
                    "callback_data": f"subdone:{subtask_id}",
                }
            ]
        )
    return {"inline_keyboard": rows} if rows else {}


def format_subtasks_reply(task: dict[str, Any], subtasks: list[dict[str, Any]]) -> str:
    today = date.today()
    lines = [f"📋 {task['title']}", ""]
    done_count = sum(1 for s in subtasks if s["status"] == "done")
    lines.append(f"Выполнено {done_count}/{len(subtasks)}:")
    lines.append("")
    for subtask in subtasks:
        marker = "✅" if subtask["status"] == "done" else "☐"
        line = f"{marker} {subtask['title']}"
        meta = []
        due = subtask.get("due_date")
        if due:
            meta.append(format_deadline_short(subtask, today))
        est = subtask.get("estimated_minutes")
        if est:
            meta.append(f"{est} мин")
        if meta:
            line += f" — {', '.join(meta)}"
        lines.append(line)
    return "\n".join(lines)


def format_subtasks_today(subtasks_by_task: list[dict[str, Any]]) -> str:
    """Format subtasks due today for the daily focus view."""
    lines = ["📌 Подзадачи на сегодня:", ""]
    for s in subtasks_by_task:
        marker = "☐"
        line = f"{marker} {s['title']}"
        if s.get("parent_title"):
            line += f"  ·  {s['parent_title']}"
        est = s.get("estimated_minutes")
        if est:
            line += f" — {est} мин"
        lines.append(line)
    return "\n".join(lines)


def build_memory_reply(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return (
            "Долговременная память пока пустая или ChromaDB недоступен. "
            "После вечерних ретроспектив и Planner-планов здесь появятся записи."
        )
    lines = ["Последние записи памяти:"]
    for index, memory in enumerate(memories, start=1):
        metadata = memory.get("metadata") or {}
        source = metadata.get("source", "memory")
        created_at = metadata.get("created_at", "без даты")
        text = memory.get("text", "").replace("\n", " ")
        if len(text) > 180:
            text = f"{text[:177]}..."
        lines.append(f"{index}. [{source}, {created_at}] {text}")
    return "\n".join(lines)
