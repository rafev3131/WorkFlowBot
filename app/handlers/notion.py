"""Notion sync helpers."""
from __future__ import annotations

from app.database import (
    list_subtasks,
    list_tasks_for_notion_sync,
    update_task_notion_page_id,
    update_task_status,
    get_task,
)
from app.notion_client import notion_client


async def try_sync_task_to_notion(chat_id: int, task_id: int) -> str:
    """Sync a single task to Notion; return a status note (empty string if Notion is not configured)."""
    if not notion_client.is_configured:
        return ""

    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return ""

    try:
        page_id = await notion_client.sync_task(
            task=task,
            subtasks=await list_subtasks(chat_id=chat_id, task_id=task_id),
        )
        if page_id:
            await update_task_notion_page_id(
                chat_id=chat_id,
                task_id=task_id,
                notion_page_id=page_id,
            )
        return "\nNotion: синхронизировано."
    except Exception as error:
        return f"\nNotion: не синхронизировано: {error}"


async def handle_notion_sync_command(chat_id: int) -> str:
    if not notion_client.is_configured:
        return (
            "Notion пока не настроен. Добавь в .env NOTION_TOKEN и "
            "NOTION_TASKS_DATA_SOURCE_ID, а затем перезапусти backend."
        )

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    if not tasks:
        return "Нет задач для синхронизации с Notion."

    synced = 0
    failed = 0
    for task in tasks:
        try:
            page_id = await notion_client.sync_task(
                task=task,
                subtasks=await list_subtasks(chat_id=chat_id, task_id=task["id"]),
            )
            if page_id:
                await update_task_notion_page_id(
                    chat_id=chat_id,
                    task_id=task["id"],
                    notion_page_id=page_id,
                )
            synced += 1
        except Exception:
            failed += 1

    if failed:
        return f"Notion sync завершен частично: синхронизировано {synced}, ошибок {failed}."
    return f"Notion sync готов: синхронизировано {synced} задач."


async def handle_notion_pull_command(chat_id: int) -> str:
    if not notion_client.is_configured:
        return (
            "Notion пока не настроен. Добавь в .env NOTION_TOKEN и "
            "NOTION_TASKS_DATA_SOURCE_ID, а затем перезапусти backend."
        )

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    tasks = [task for task in tasks if task.get("notion_page_id")]
    if not tasks:
        return "Пока нет задач, связанных с Notion. Сначала запусти /sync_notion."

    updated = 0
    unchanged = 0
    failed = 0
    for task in tasks:
        try:
            notion_status = await notion_client.get_task_status(task["notion_page_id"])
            if notion_status != task["status"]:
                await update_task_status(
                    chat_id=chat_id,
                    task_id=task["id"],
                    status=notion_status,
                )
                updated += 1
            else:
                unchanged += 1
        except Exception:
            failed += 1

    parts = [f"Из Notion обновлено: {updated}", f"без изменений: {unchanged}"]
    if failed:
        parts.append(f"ошибок: {failed}")
    return ". ".join(parts) + "."
