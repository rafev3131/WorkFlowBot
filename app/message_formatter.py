from typing import Any


def format_analysis(analysis: dict[str, Any]) -> str:
    automated = "да" if analysis.get("can_be_automated") else "нет"
    clarification = "да" if analysis.get("needs_clarification") else "нет"

    return "\n".join(
        [
            "Разобрал сообщение:",
            "",
            f"Тип: {analysis.get('type', 'unknown')}",
            f"Название: {analysis.get('title', 'Без названия')}",
            f"Проект: {analysis.get('project') or 'не указан'}",
            f"Дата: {analysis.get('due_date') or 'не указана'}",
            f"Приоритет: {analysis.get('priority', 'medium')}",
            f"Оценка времени: {_format_minutes(analysis.get('estimated_minutes'))}",
            f"Агент: {analysis.get('assigned_agent', 'inbox_agent')}",
            f"Можно автоматизировать: {automated}",
            f"Нужно уточнение: {clarification}",
            "",
            f"Кратко: {analysis.get('summary', '')}",
            "",
            f"Следующее действие: {analysis.get('next_action', '')}",
        ]
    )


def format_agent_result(analysis: dict[str, Any], result: str) -> str:
    title = analysis.get("title", "Без названия")
    agent = analysis.get("assigned_agent", "inbox_agent")

    return "\n".join(
        [
            f"Задача: {title}",
            f"Агент: {agent}",
            "",
            result,
        ]
    )


def format_planner_result(analysis: dict[str, Any], plan: dict[str, Any]) -> str:
    title = analysis.get("title", "Без названия")
    objective = plan.get("objective") or analysis.get("summary", "")
    raw_plan = plan.get("raw_plan")

    lines = [
        f"Задача: {title}",
        "Агент: planner_agent",
        f"Оценка времени: {_format_minutes(analysis.get('estimated_minutes'))}",
        "",
        f"Цель: {objective}",
    ]

    if raw_plan:
        lines.extend(["", raw_plan])
        return "\n".join(lines)

    assumptions = _as_list(plan.get("assumptions"))
    if assumptions:
        lines.extend(["", "Допущения:"])
        lines.extend(f"- {item}" for item in assumptions)

    phases = _as_list(plan.get("phases"))
    if phases:
        lines.extend(["", "План:"])
        for index, phase in enumerate(phases, start=1):
            if isinstance(phase, dict):
                phase_title = phase.get("title", f"Этап {index}")
                steps = _as_list(phase.get("steps"))
            else:
                phase_title = f"Этап {index}"
                steps = [str(phase)]

            lines.append(f"{index}. {phase_title}")
            lines.extend(f"   - {step}" for step in steps)

    materials = _as_list(plan.get("materials"))
    if materials:
        lines.extend(["", "Подготовить:"])
        lines.extend(f"- {item}" for item in materials)

    risks = _as_list(plan.get("risks"))
    if risks:
        lines.extend(["", "Риски:"])
        lines.extend(f"- {item}" for item in risks)

    questions = _as_list(plan.get("clarifying_questions"))
    if questions:
        lines.extend(["", "Уточнить:"])
        lines.extend(f"- {item}" for item in questions)

    next_step = plan.get("next_step") or analysis.get("next_action", "")
    if next_step:
        lines.extend(["", f"Первый шаг: {next_step}"])

    return "\n".join(lines)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _format_minutes(value: Any) -> str:
    if value in (None, ""):
        return "не указана"
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return "не указана"
    if minutes <= 0:
        return "не указана"
    hours = minutes // 60
    remainder = minutes % 60
    if hours and remainder:
        return f"{hours} ч {remainder} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"
