from __future__ import annotations

from typing import Any


HIGH_PRIORITY_KEYWORDS = (
    "важно",
    "очень важно",
    "экстренно",
    "срочно",
    "как можно быстрее",
    "как можно скорей",
    "чем раньше тем лучше",
    "горит",
    "критично",
    "немедленно",
    "сегодня обязательно",
)

WEEK_KEYWORDS = (
    "на неделю",
    "на этой неделе",
    "на следующую неделю",
    "в течение недели",
)


def supervise_analysis(text: str, analysis: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(analysis)
    lowered = text.lower()
    notes: list[str] = []

    if _has_any_keyword(lowered, HIGH_PRIORITY_KEYWORDS):
        normalized["priority"] = "high"
        notes.append("Повышен приоритет из-за срочной формулировки.")

    if _has_any_keyword(lowered, WEEK_KEYWORDS) and not normalized.get("due_date"):
        normalized["planning_period"] = "week"
        notes.append("Задача отнесена к недельному плану.")

    if normalized.get("priority") == "high" and normalized.get("type") == "task":
        normalized["assigned_agent"] = "planner_agent"

    if notes:
        normalized["supervisor_notes"] = notes

    return normalized


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)

