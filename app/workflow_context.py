from __future__ import annotations

from pathlib import Path
import json
from typing import Any


WORKFLOW_CONTEXT_PATH = Path("WORKFLOW_CONTEXT.md")


def load_workflow_context() -> str:
    if not WORKFLOW_CONTEXT_PATH.exists():
        return ""

    return WORKFLOW_CONTEXT_PATH.read_text(encoding="utf-8").strip()


def format_task_context(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "Активных или недавних задач пока нет."

    lines = []
    for task in tasks:
        project = task.get("project_name") or "без проекта"
        lines.append(
            "- "
            f"#{task['id']} {task['title']} "
            f"[{task['status']}, {task['priority']}, {task['assigned_agent']}]. "
            f"Проект: {project}. "
            f"Тип: {task['task_type']}. "
            f"Оценка: {_format_time_fields(task)}. "
            f"Создана: {task['created_at']}."
        )

    return "\n".join(lines)


def format_project_context(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "Проекты пока не заведены."

    lines = []
    for project in projects:
        description = project.get("description") or "без описания"
        lines.append(
            "- "
            f"#{project['id']} {project['name']} "
            f"[{project['status']}]. "
            f"Активных задач: {project['active_task_count'] or 0}. "
            f"Всего задач: {project['task_count'] or 0}. "
            f"Описание: {description}."
        )

    return "\n".join(lines)


def format_retrospective_context(retrospectives: list[dict[str, Any]]) -> str:
    if not retrospectives:
        return "Ретроспектив пока нет."

    lines = []
    for retro in retrospectives:
        try:
            summary = json.loads(retro.get("summary_json") or "{}")
        except json.JSONDecodeError:
            summary = {}

        done = _join_summary_list(summary.get("done"))
        not_done = _join_summary_list(summary.get("not_done"))
        blockers = _join_summary_list(summary.get("blockers"))
        time_notes = _join_summary_list(summary.get("time_estimation_notes"))
        rules = _join_summary_list(summary.get("planning_rules"))

        lines.append(
            "- "
            f"{retro['retro_date']}: "
            f"сделано: {done}; "
            f"не сделано: {not_done}; "
            f"помешало: {blockers}; "
            f"оценки времени: {time_notes}; "
            f"правила: {rules}."
        )

    return "\n".join(lines)


def _join_summary_list(value: Any) -> str:
    if isinstance(value, list) and value:
        return ", ".join(str(item) for item in value[:4])
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "нет данных"


def _format_time_fields(task: dict[str, Any]) -> str:
    estimated = task.get("estimated_minutes")
    actual = task.get("actual_minutes")
    accuracy = task.get("time_estimation_accuracy")
    parts = []
    if estimated:
        parts.append(f"план {estimated} мин")
    if actual:
        parts.append(f"факт {actual} мин")
    if accuracy is not None:
        parts.append(f"точность {accuracy}%")
    return ", ".join(parts) if parts else "нет оценки"
