from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class NotionClient:
    @property
    def is_configured(self) -> bool:
        return bool(settings.notion_token and settings.notion_tasks_data_source_id)

    async def sync_task(self, task: dict[str, Any], subtasks: list[dict[str, Any]]) -> str | None:
        if not self.is_configured:
            return None

        payload = {
            "properties": _build_task_properties(task),
            "children": _build_task_children(task, subtasks),
        }

        page_id = task.get("notion_page_id")
        if page_id:
            await self._request(
                method="PATCH",
                path=f"/v1/pages/{page_id}",
                json={"properties": payload["properties"]},
            )
            return page_id

        payload["parent"] = {
            "type": "database_id",
            "database_id": settings.notion_tasks_data_source_id,
        }
        data = await self._request(
            method="POST",
            path="/v1/pages",
            json=payload,
        )
        return data.get("id")

    async def get_task_status(self, page_id: str) -> str:
        if not self.is_configured:
            raise RuntimeError("Notion не настроен.")

        try:
            data = await self._request(
                method="GET",
                path=f"/v1/pages/{page_id}",
            )
        except NotionNotFoundError:
            return "cancelled"

        if data.get("archived") or data.get("in_trash"):
            return "cancelled"

        props = data.get("properties", {})
        # Support both new Russian schema and legacy English schema
        notion_status = (
            props.get("Статус", {}).get("select", {}).get("name")
            or props.get("Status", {}).get("select", {}).get("name")
        )
        return _local_status(notion_status)

    async def create_tasks_data_source(self) -> str:
        if not settings.notion_token:
            raise RuntimeError("Добавь NOTION_TOKEN в .env.")
        if not settings.notion_parent_page_id:
            raise RuntimeError("Добавь NOTION_PARENT_PAGE_ID в .env.")

        data = await self._request(
            method="POST",
            path="/v1/databases",
            json={
                "parent": {
                    "type": "page_id",
                    "page_id": settings.notion_parent_page_id,
                },
                "title": [{"type": "text", "text": {"content": "Tasks"}}],
                "is_inline": True,
                "initial_data_source": {
                    "title": [{"type": "text", "text": {"content": "Tasks"}}],
                    "properties": _build_tasks_data_source_properties(),
                },
            },
        )
        data_sources = data.get("data_sources", [])
        if data_sources:
            return data_sources[0]["id"]
        return data["id"]

    async def create_child_page(self, title: str, children: list[dict[str, Any]]) -> str:
        if not settings.notion_token:
            raise RuntimeError("Добавь NOTION_TOKEN в .env.")
        if not settings.notion_parent_page_id:
            raise RuntimeError("Добавь NOTION_PARENT_PAGE_ID в .env.")

        data = await self._request(
            method="POST",
            path="/v1/pages",
            json={
                "parent": {
                    "type": "page_id",
                    "page_id": settings.notion_parent_page_id,
                },
                "properties": {
                    "title": {
                        "title": [{"type": "text", "text": {"content": title}}],
                    }
                },
                "children": children,
            },
        )
        return data["id"]

    async def append_page_blocks(self, page_id: str, children: list[dict[str, Any]]) -> None:
        if not settings.notion_token:
            raise RuntimeError("Добавь NOTION_TOKEN в .env.")

        await self._request(
            method="PATCH",
            path=f"/v1/blocks/{page_id}/children",
            json={"children": children},
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method=method,
                url=f"https://api.notion.com{path}",
                headers={
                    "Authorization": f"Bearer {settings.notion_token}",
                    "Content-Type": "application/json",
                    "Notion-Version": settings.notion_version,
                },
                json=json,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 404:
                    raise NotionNotFoundError(_format_notion_error(error.response)) from error
                raise RuntimeError(_format_notion_error(error.response)) from error

        return response.json()


def _build_task_properties(task: dict[str, Any]) -> dict[str, Any]:
    """Build Notion page properties for the new Russian-schema planner database."""
    status = _notion_status_new(task.get("status", "in_progress"))
    urgency, importance = _priority_to_eisenhower(task.get("priority", "medium"))

    properties: dict[str, Any] = {
        "Задача": {
            "title": [{"text": {"content": task.get("title", "Без названия")}}],
        },
        "Статус": {"select": {"name": status}},
        "Срочность": {"select": {"name": urgency}},
        "Важность": {"select": {"name": importance}},
        "Bot ID": {"number": task.get("id")},
    }

    due_date = task.get("due_date")
    if due_date:
        properties["Дедлайн"] = {"date": {"start": due_date}}

    # Energy: map estimated minutes to energy level
    estimated = task.get("estimated_minutes")
    if estimated:
        if estimated <= 15:
            energy = "⚡ Быстро · до 15 мин"
        elif estimated <= 60:
            energy = "🔆 Средне · до 1 ч"
        else:
            energy = "🔋 Глубокая работа · 2+ ч"
        properties["Энергия"] = {"select": {"name": energy}}

    # Notes: include summary and agent
    notes_parts = []
    summary = task.get("result") or task.get("summary") or ""
    if summary:
        notes_parts.append(summary[:1000])
    if task.get("assigned_agent"):
        notes_parts.append(f"Agent: {task['assigned_agent']}")
    if notes_parts:
        properties["Заметки"] = {
            "rich_text": [{"text": {"content": "\n".join(notes_parts)[:2000]}}]
        }

    return properties


def _build_tasks_data_source_properties() -> dict[str, Any]:
    return {
        "Name": {"title": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "In Progress", "color": "blue"},
                    {"name": "Done", "color": "green"},
                    {"name": "Cancelled", "color": "gray"},
                ]
            }
        },
        "Priority": {
            "select": {
                "options": [
                    {"name": "high", "color": "red"},
                    {"name": "medium", "color": "yellow"},
                    {"name": "low", "color": "gray"},
                ]
            }
        },
        "Due": {"date": {}},
        "Project": {"rich_text": {}},
        "Period": {
            "select": {
                "options": [
                    {"name": "week", "color": "purple"},
                ]
            }
        },
        "Agent": {
            "select": {
                "options": [
                    {"name": "planner_agent", "color": "blue"},
                    {"name": "inbox_agent", "color": "gray"},
                    {"name": "writer_agent", "color": "green"},
                    {"name": "research_agent", "color": "orange"},
                    {"name": "automation_agent", "color": "purple"},
                    {"name": "reminder_agent", "color": "red"},
                ]
            }
        },
        "Type": {
            "select": {
                "options": [
                    {"name": "task", "color": "blue"},
                    {"name": "idea", "color": "yellow"},
                    {"name": "note", "color": "gray"},
                    {"name": "reminder", "color": "red"},
                    {"name": "research", "color": "orange"},
                    {"name": "document", "color": "purple"},
                    {"name": "automation", "color": "green"},
                ]
            }
        },
        "Local ID": {"number": {"format": "number"}},
        "Estimated Minutes": {"number": {"format": "number"}},
        "Actual Minutes": {"number": {"format": "number"}},
        "Time Accuracy": {"number": {"format": "percent"}},
    }


def _build_task_children(task: dict[str, Any], subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    children = [
        _paragraph(f"Telegram task #{task.get('id')}"),
        _paragraph(_format_task_time(task)),
    ]

    if subtasks:
        children.append(_heading("Подзадачи"))
        for subtask in subtasks[:50]:
            children.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": subtask["title"]}}],
                        "checked": subtask["status"] == "done",
                    },
                }
            )

    return children


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"text": {"content": text}}]},
    }


def _format_task_time(task: dict[str, Any]) -> str:
    parts = []
    if task.get("estimated_minutes"):
        parts.append(f"estimated {task['estimated_minutes']} min")
    if task.get("actual_minutes"):
        parts.append(f"actual {task['actual_minutes']} min")
    if task.get("time_estimation_accuracy") is not None:
        parts.append(f"accuracy {task['time_estimation_accuracy']}%")
    return "Time: " + ", ".join(parts) if parts else "Time: not estimated"


def _heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": text}}]},
    }


def _notion_status(status: str) -> str:
    """Legacy schema status mapping."""
    if status == "done":
        return "Done"
    if status == "cancelled":
        return "Cancelled"
    return "In Progress"


def _notion_status_new(status: str) -> str:
    """New planner schema status mapping."""
    mapping = {
        "done": "✅ Готово",
        "cancelled": "❌ Отменено",
        "in_progress": "🔄 В работе",
        "inbox": "📥 Входящие",
        "waiting": "⏸ Ожидание",
    }
    return mapping.get(status, "📥 Входящие")


def _priority_to_eisenhower(priority: str) -> tuple[str, str]:
    """Map bot priority to Eisenhower urgency + importance."""
    if priority == "high":
        return "🔴 Срочно", "⭐ Важно"
    if priority == "medium":
        return "🟡 Несрочно", "⭐ Важно"
    return "🟡 Несрочно", "○ Неважно"


def _local_status(status: str | None) -> str:
    if status in {"Done", "✅ Готово"}:
        return "done"
    if status in {"Cancelled", "❌ Отменено"}:
        return "cancelled"
    return "in_progress"


class NotionNotFoundError(RuntimeError):
    pass


def _format_notion_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}

    message = body.get("message")
    if response.status_code == 401:
        return "Notion token не принят. Проверь NOTION_TOKEN в .env."
    if response.status_code == 403:
        return "Notion вернул 403. Проверь, что integration имеет доступ к базе и право Insert/Update content."
    if response.status_code == 404:
        return "Notion не нашел data source. Проверь NOTION_TASKS_DATA_SOURCE_ID и доступ integration к базе."
    if response.status_code == 400 and message and "collection_view" in message:
        return (
            "NOTION_PARENT_PAGE_ID указывает на database/table view, а не на обычную страницу. "
            "Создай обычную пустую страницу-контейнер, дай integration доступ и вставь ID этой страницы."
        )
    if message:
        return f"Notion API вернул ошибку {response.status_code}: {message}"
    return f"Notion API вернул ошибку {response.status_code}."


notion_client = NotionClient()
