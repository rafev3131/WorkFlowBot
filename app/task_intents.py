from __future__ import annotations

import re
from datetime import date
from typing import Any


MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

TASK_ALIASES = {
    "pl": ("p&l", "pl", "pnl", "пиэль", "пл"),
    "p&l": ("p&l", "pl", "pnl", "пиэль", "пл"),
    "документац": ("документац", "сэс", "пожар", "охрана труда", "трудовые"),
    "вакууматор": ("вакууматор",),
    "кладов": ("кладов", "склад"),
    "мусор": ("мусор", "подвал"),
    "зарплат": ("зарплат", "выплат"),
    "ревизи": ("ревизи", "инвентаризац"),
}

DELETE_WORDS = ("удали", "удалить", "убери", "убрать", "отмени", "отменить")
DEADLINE_WORDS = ("дедлайн", "срок", "до")


def parse_task_intent(text: str) -> dict[str, Any] | None:
    normalized = text.lower().strip()

    explicit_task_id = _extract_task_id(normalized)
    delete_alias = _extract_delete_alias(normalized)
    if any(word in normalized for word in DELETE_WORDS):
        return {
            "intent": "cancel_task",
            "alias": delete_alias,
            "task_id": explicit_task_id,
        }

    due_date = _extract_due_date(normalized)
    if due_date and any(word in normalized for word in DEADLINE_WORDS):
        alias = _extract_known_alias(normalized)
        return {
            "intent": "update_due_date",
            "alias": alias,
            "due_date": due_date,
            "task_id": explicit_task_id,
        }

    return None


def find_matching_task(tasks: list[dict[str, Any]], alias: str) -> dict[str, Any] | None:
    needles = TASK_ALIASES.get(alias, (alias,))
    active_tasks = sorted(
        [task for task in tasks if task.get("status") not in {"done", "cancelled"}],
        key=lambda task: task.get("id", 0),
    )

    for task in active_tasks:
        title = task.get("title", "").lower()
        user_text = task.get("user_text", "").lower()
        haystack = f"{title} {user_text}"
        if any(needle in haystack for needle in needles):
            return task

    return None


def _extract_delete_alias(text: str) -> str | None:
    if not any(word in text for word in DELETE_WORDS):
        return None

    return _extract_known_alias(text)


def _extract_known_alias(text: str) -> str | None:
    for alias, needles in TASK_ALIASES.items():
        if any(needle in text for needle in needles):
            return alias
    return None


def _extract_due_date(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2})\s+([а-яё]+)\b", text)
    if not match:
        return None

    day = int(match.group(1))
    month_name = match.group(2)
    month = MONTHS.get(month_name)
    if month is None:
        return None

    today = date.today()
    year = today.year
    parsed = date(year, month, day)
    if parsed < today:
        parsed = date(year + 1, month, day)

    return parsed.isoformat()


def _extract_task_id(text: str) -> int | None:
    match = re.search(r"(?:задач[ауи]?\s*#?|#)(\d+)", text)
    if not match:
        return None
    return int(match.group(1))
