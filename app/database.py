from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite


DATABASE_PATH = Path("workflow.db")


async def init_database() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, name)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                project_id INTEGER,
                due_date TEXT,
                planning_period TEXT NOT NULL DEFAULT '',
                user_text TEXT NOT NULL,
                title TEXT NOT NULL,
                task_type TEXT NOT NULL,
                priority TEXT NOT NULL,
                assigned_agent TEXT NOT NULL,
                status TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                result TEXT NOT NULL,
                notion_page_id TEXT,
                estimated_minutes INTEGER,
                actual_minutes INTEGER,
                time_estimation_accuracy REAL,
                reminder_at TEXT,
                reminder_sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = await _get_table_columns(db, "tasks")
        if "project_id" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN project_id INTEGER")
        if "due_date" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        if "planning_period" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN planning_period TEXT NOT NULL DEFAULT ''")
        if "notion_page_id" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN notion_page_id TEXT")
        if "estimated_minutes" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER")
        if "actual_minutes" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER")
        if "time_estimation_accuracy" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN time_estimation_accuracy REAL")
        if "reminder_at" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN reminder_at TEXT")
        if "reminder_sent_at" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN reminder_sent_at TEXT")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_retrospectives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                retro_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'requested',
                prompt_text TEXT NOT NULL DEFAULT '',
                response_text TEXT NOT NULL DEFAULT '',
                summary_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                answered_at TEXT,
                UNIQUE(chat_id, retro_date)
            )
            """
        )
        await db.commit()


async def save_task(
    chat_id: int,
    user_text: str,
    analysis: dict[str, Any],
    result: str,
    status: str = "in_progress",
) -> int:
    project_id = await _resolve_project_id(chat_id=chat_id, analysis=analysis)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO tasks (
                chat_id,
                project_id,
                due_date,
                planning_period,
                user_text,
                title,
                task_type,
                priority,
                assigned_agent,
                status,
                analysis_json,
                result,
                estimated_minutes,
                reminder_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                project_id,
                analysis.get("due_date") or None,
                analysis.get("planning_period", ""),
                user_text,
                analysis.get("title", "Без названия"),
                analysis.get("type", "task"),
                analysis.get("priority", "medium"),
                analysis.get("assigned_agent", "inbox_agent"),
                status,
                json.dumps(analysis, ensure_ascii=False),
                result,
                _normalize_minutes(analysis.get("estimated_minutes")),
                analysis.get("reminder_at") or None,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_recent_tasks(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.reminder_at,
                tasks.reminder_sent_at,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ?
            ORDER BY tasks.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_active_tasks(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ? AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY tasks.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_planner_context_tasks(chat_id: int, limit: int = 12) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ?
            ORDER BY
                CASE
                    WHEN tasks.status NOT IN ('done', 'cancelled') THEN 0
                    ELSE 1
                END,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_task(chat_id: int, task_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                id,
                chat_id,
                project_id,
                due_date,
                planning_period,
                user_text,
                title,
                task_type,
                priority,
                assigned_agent,
                status,
                notion_page_id,
                analysis_json,
                result,
                estimated_minutes,
                actual_minutes,
                time_estimation_accuracy,
                reminder_at,
                reminder_sent_at,
                created_at
            FROM tasks
            WHERE chat_id = ? AND id = ?
            """,
            (chat_id, task_id),
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    return dict(row)


async def list_projects(chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                projects.id,
                projects.name,
                projects.description,
                projects.status,
                projects.created_at,
                COUNT(tasks.id) AS task_count,
                SUM(CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 1 ELSE 0 END) AS active_task_count
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            WHERE projects.chat_id = ?
            GROUP BY projects.id
            ORDER BY active_task_count DESC, projects.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_project_context(chat_id: int, limit: int = 8) -> list[dict[str, Any]]:
    return await list_projects(chat_id=chat_id, limit=limit)


async def list_tasks_by_due_date(
    chat_id: int,
    due_date: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.reminder_at,
                tasks.reminder_sent_at,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                tasks.chat_id = ?
                AND tasks.due_date = ?
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, due_date, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_today_focus_tasks(
    chat_id: int,
    today: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                tasks.chat_id = ?
                AND tasks.status NOT IN ('done', 'cancelled')
                AND (
                    tasks.due_date = ?
                    OR tasks.priority = 'high'
                    OR tasks.planning_period = 'week'
                )
            ORDER BY
                CASE
                    WHEN tasks.due_date = ? THEN 0
                    WHEN tasks.priority = 'high' THEN 1
                    WHEN tasks.planning_period = 'week' THEN 2
                    ELSE 3
                END,
                CASE tasks.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, today, today, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_chat_ids_for_morning_brief() -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT DISTINCT chat_id
            FROM tasks
            WHERE status NOT IN ('done', 'cancelled')
            ORDER BY chat_id
            """
        )
        rows = await cursor.fetchall()

    return [int(row[0]) for row in rows]


async def list_chat_ids_for_retrospective() -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT DISTINCT chat_id
            FROM tasks
            ORDER BY chat_id
            """
        )
        rows = await cursor.fetchall()

    return [int(row[0]) for row in rows]


async def list_open_subtasks_for_brief(chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                subtasks.id,
                subtasks.task_id,
                subtasks.title,
                subtasks.status,
                subtasks.position,
                tasks.title AS task_title,
                tasks.priority AS task_priority,
                tasks.estimated_minutes AS task_estimated_minutes,
                tasks.actual_minutes AS task_actual_minutes,
                tasks.time_estimation_accuracy AS task_time_estimation_accuracy,
                projects.name AS project_name
            FROM subtasks
            JOIN tasks ON tasks.id = subtasks.task_id
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                subtasks.chat_id = ?
                AND subtasks.status != 'done'
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                tasks.id DESC,
                subtasks.position ASC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def create_or_update_daily_retrospective(
    chat_id: int,
    retro_date: str,
    prompt_text: str,
) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO daily_retrospectives (chat_id, retro_date, status, prompt_text)
            VALUES (?, ?, 'requested', ?)
            ON CONFLICT(chat_id, retro_date) DO UPDATE SET
                status = CASE
                    WHEN daily_retrospectives.status = 'answered' THEN daily_retrospectives.status
                    ELSE 'requested'
                END,
                prompt_text = excluded.prompt_text
            """,
            (chat_id, retro_date, prompt_text),
        )
        cursor = await db.execute(
            """
            SELECT id
            FROM daily_retrospectives
            WHERE chat_id = ? AND retro_date = ?
            """,
            (chat_id, retro_date),
        )
        row = await cursor.fetchone()
        await db.commit()

    return int(row[0]) if row else 0


async def get_pending_retrospective(chat_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, chat_id, retro_date, status, prompt_text, response_text, summary_json, created_at, answered_at
            FROM daily_retrospectives
            WHERE chat_id = ? AND status = 'requested'
            ORDER BY retro_date DESC, id DESC
            LIMIT 1
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()

    return dict(row) if row else None


async def save_retrospective_response(
    chat_id: int,
    retro_id: int,
    response_text: str,
    summary: dict[str, Any],
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE daily_retrospectives
            SET
                status = 'answered',
                response_text = ?,
                summary_json = ?,
                answered_at = CURRENT_TIMESTAMP
            WHERE chat_id = ? AND id = ?
            """,
            (
                response_text,
                json.dumps(summary, ensure_ascii=False),
                chat_id,
                retro_id,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_retrospective_status(
    chat_id: int,
    retro_id: int,
    status: str,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE daily_retrospectives
            SET status = ?, answered_at = CURRENT_TIMESTAMP
            WHERE chat_id = ? AND id = ?
            """,
            (status, chat_id, retro_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def list_recent_retrospectives(chat_id: int, limit: int = 7) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, retro_date, status, response_text, summary_json, created_at, answered_at
            FROM daily_retrospectives
            WHERE chat_id = ? AND status IN ('answered', 'partial')
            ORDER BY retro_date DESC, id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_tasks_by_planning_period(
    chat_id: int,
    planning_period: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                tasks.chat_id = ?
                AND tasks.planning_period = ?
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, planning_period, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_project(chat_id: int, project_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                projects.id,
                projects.name,
                projects.description,
                projects.status,
                projects.created_at,
                COUNT(tasks.id) AS task_count,
                SUM(CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 1 ELSE 0 END) AS active_task_count
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            WHERE projects.chat_id = ? AND projects.id = ?
            GROUP BY projects.id
            """,
            (chat_id, project_id),
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    return dict(row)


async def list_project_tasks(
    chat_id: int,
    project_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ? AND tasks.project_id = ?
            ORDER BY
                CASE
                    WHEN tasks.status NOT IN ('done', 'cancelled') THEN 0
                    ELSE 1
                END,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, project_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def update_task_plan(
    chat_id: int,
    task_id: int,
    analysis: dict[str, Any],
    result: str,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET
                assigned_agent = 'planner_agent',
                analysis_json = ?,
                result = ?,
                estimated_minutes = COALESCE(?, estimated_minutes)
            WHERE chat_id = ? AND id = ?
            """,
            (
                json.dumps(analysis, ensure_ascii=False),
                result,
                _normalize_minutes(analysis.get("estimated_minutes")),
                chat_id,
                task_id,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_notion_page_id(
    chat_id: int,
    task_id: int,
    notion_page_id: str,
) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET notion_page_id = ?
            WHERE chat_id = ? AND id = ?
            """,
            (notion_page_id, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_status(chat_id: int, task_id: int, status: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET status = ?
            WHERE chat_id = ? AND id = ?
            """,
            (status, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_task_done_with_time(
    chat_id: int,
    task_id: int,
    actual_minutes: int | None = None,
) -> bool:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return False

    estimated_minutes = _normalize_minutes(task.get("estimated_minutes"))
    actual_minutes = _normalize_minutes(actual_minutes)
    accuracy = _calculate_time_estimation_accuracy(
        estimated_minutes=estimated_minutes,
        actual_minutes=actual_minutes,
    )

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET
                status = 'done',
                actual_minutes = COALESCE(?, actual_minutes),
                time_estimation_accuracy = COALESCE(?, time_estimation_accuracy)
            WHERE chat_id = ? AND id = ?
            """,
            (actual_minutes, accuracy, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_due_date(chat_id: int, task_id: int, due_date: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET due_date = ?, planning_period = ''
            WHERE chat_id = ? AND id = ?
            """,
            (due_date, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_title(chat_id: int, task_id: int, title: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET title = ?
            WHERE chat_id = ? AND id = ?
            """,
            (title, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_priority(chat_id: int, task_id: int, priority: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET priority = ?
            WHERE chat_id = ? AND id = ?
            """,
            (priority, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_task_reminder(chat_id: int, task_id: int, reminder_at: str | None) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET reminder_at = ?, reminder_sent_at = NULL
            WHERE chat_id = ? AND id = ?
            """,
            (reminder_at, chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_task_reminder_sent(chat_id: int, task_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET reminder_sent_at = CURRENT_TIMESTAMP
            WHERE chat_id = ? AND id = ?
            """,
            (chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def list_next_task_candidates(chat_id: int, today: str, limit: int = 12) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.reminder_at,
                projects.name AS project_name,
                (
                    SELECT subtasks.id
                    FROM subtasks
                    WHERE subtasks.task_id = tasks.id
                        AND subtasks.chat_id = tasks.chat_id
                        AND subtasks.status != 'done'
                    ORDER BY subtasks.position ASC, subtasks.id ASC
                    LIMIT 1
                ) AS next_subtask_id,
                (
                    SELECT subtasks.title
                    FROM subtasks
                    WHERE subtasks.task_id = tasks.id
                        AND subtasks.chat_id = tasks.chat_id
                        AND subtasks.status != 'done'
                    ORDER BY subtasks.position ASC, subtasks.id ASC
                    LIMIT 1
                ) AS next_subtask_title
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ? AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE
                    WHEN tasks.due_date IS NOT NULL AND tasks.due_date < ? THEN 0
                    WHEN tasks.due_date = ? THEN 1
                    WHEN tasks.priority = 'high' THEN 2
                    WHEN tasks.due_date IS NOT NULL THEN 3
                    WHEN tasks.planning_period = 'week' THEN 4
                    ELSE 5
                END,
                CASE tasks.priority
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                tasks.due_date ASC,
                tasks.id DESC
            LIMIT ?
            """,
            (chat_id, today, today, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_pending_reminder_tasks(now: str, limit: int = 100) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                id,
                chat_id,
                title,
                priority,
                status,
                due_date,
                reminder_at,
                reminder_sent_at
            FROM tasks
            WHERE
                reminder_at IS NOT NULL
                AND reminder_at != ''
                AND reminder_sent_at IS NULL
                AND status NOT IN ('done', 'cancelled')
            ORDER BY reminder_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def list_tasks_for_notion_sync(chat_id: int, limit: int = 100) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tasks.id,
                tasks.user_text,
                tasks.title,
                tasks.task_type,
                tasks.priority,
                tasks.assigned_agent,
                tasks.status,
                tasks.notion_page_id,
                tasks.due_date,
                tasks.planning_period,
                tasks.estimated_minutes,
                tasks.actual_minutes,
                tasks.time_estimation_accuracy,
                tasks.reminder_at,
                tasks.reminder_sent_at,
                tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = ?
            ORDER BY tasks.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def replace_subtasks(
    chat_id: int,
    task_id: int,
    titles: list[str],
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            DELETE FROM subtasks
            WHERE chat_id = ? AND task_id = ?
            """,
            (chat_id, task_id),
        )
        for position, title in enumerate(titles, start=1):
            await db.execute(
                """
                INSERT INTO subtasks (task_id, chat_id, title, position)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, chat_id, title, position),
            )
        await db.commit()


async def list_subtasks(chat_id: int, task_id: int) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, title, status, position, created_at
            FROM subtasks
            WHERE chat_id = ? AND task_id = ?
            ORDER BY position ASC, id ASC
            """,
            (chat_id, task_id),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def mark_subtask_done(chat_id: int, subtask_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE subtasks
            SET status = 'done'
            WHERE chat_id = ? AND id = ?
            """,
            (chat_id, subtask_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_subtask(chat_id: int, subtask_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, title, status, position, created_at
            FROM subtasks
            WHERE chat_id = ? AND id = ?
            """,
            (chat_id, subtask_id),
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    return dict(row)


async def all_subtasks_done(chat_id: int, task_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status != 'done' THEN 1 ELSE 0 END) AS open_count
            FROM subtasks
            WHERE chat_id = ? AND task_id = ?
            """,
            (chat_id, task_id),
        )
        row = await cursor.fetchone()

    total_count = row[0] or 0
    open_count = row[1] or 0
    return total_count > 0 and open_count == 0


async def _resolve_project_id(chat_id: int, analysis: dict[str, Any]) -> int | None:
    project_name = analysis.get("project")
    if not project_name:
        project_name = analysis.get("project_name")

    if not isinstance(project_name, str):
        return None

    project_name = project_name.strip()
    if not project_name:
        return None

    project_description = analysis.get("project_description", "")
    if not isinstance(project_description, str):
        project_description = ""

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO projects (chat_id, name, description)
            VALUES (?, ?, ?)
            """,
            (chat_id, project_name, project_description),
        )
        cursor = await db.execute(
            """
            SELECT id
            FROM projects
            WHERE chat_id = ? AND name = ?
            """,
            (chat_id, project_name),
        )
        row = await cursor.fetchone()
        await db.commit()

    return int(row[0]) if row else None


async def _get_table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def mark_task_done(chat_id: int, task_id: int) -> bool:
    return await mark_task_done_with_time(chat_id=chat_id, task_id=task_id)


async def mark_task_cancelled(chat_id: int, task_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE tasks
            SET status = 'cancelled'
            WHERE chat_id = ? AND id = ?
            """,
            (chat_id, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


def _normalize_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return minutes


def _calculate_time_estimation_accuracy(
    estimated_minutes: int | None,
    actual_minutes: int | None,
) -> float | None:
    if not estimated_minutes or not actual_minutes:
        return None
    smaller = min(estimated_minutes, actual_minutes)
    bigger = max(estimated_minutes, actual_minutes)
    return round((smaller / bigger) * 100, 1)
