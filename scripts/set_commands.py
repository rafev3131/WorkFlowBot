from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.telegram_client import telegram_client


COMMANDS = [
    {"command": "tasks", "description": "Показать все последние задачи"},
    {"command": "today", "description": "Показать задачи на сегодня"},
    {"command": "tomorrow", "description": "Показать задачи на завтра"},
    {"command": "week", "description": "Показать задачи на неделю"},
    {"command": "active", "description": "Показать все активные задачи"},
    {"command": "next", "description": "Показать следующий лучший шаг"},
    {"command": "projects", "description": "Показать проекты"},
    {"command": "project", "description": "Открыть проект: /project 1"},
    {"command": "plan", "description": "Построить план для задачи: /plan 1"},
    {"command": "subtasks", "description": "Показать подзадачи: /subtasks 1"},
    {"command": "subdone", "description": "Закрыть подзадачу: /subdone 1"},
    {"command": "sync_notion", "description": "Синхронизировать задачи с Notion"},
    {"command": "sync_from_notion", "description": "Забрать статусы из Notion"},
    {"command": "brief", "description": "Отправить утренний бриф сейчас"},
    {"command": "retro", "description": "Запустить вечернюю ретроспективу"},
    {"command": "memory", "description": "Показать последние записи памяти"},
    {"command": "deadline", "description": "Поставить срок: /deadline 7 2026-06-15"},
    {"command": "remind", "description": "Поставить напоминание: /remind 7 2026-06-02 14:30"},
    {"command": "rename", "description": "Переименовать задачу: /rename 7 Название"},
    {"command": "priority", "description": "Сменить приоритет: /priority 7 high"},
    {"command": "delete", "description": "Убрать задачу из активных: /delete 7"},
    {"command": "done", "description": "Закрыть задачу: /done 1 120"},
    {"command": "cancel", "description": "Отменить задачу: /cancel 1"},
    {"command": "health", "description": "Проверить backend"},
]


async def main() -> None:
    await telegram_client.set_my_commands(COMMANDS)
    print("Bot command menu updated")


if __name__ == "__main__":
    asyncio.run(main())
