from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_SCHEMA_VERSION = 5


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    return _pool


async def init_database() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_schema_version_table(conn)
            current_version = await _get_schema_version(conn)
            await _run_migrations(conn, current_version)


# ---------------------------------------------------------------------------
# Migration engine
# ---------------------------------------------------------------------------

async def _ensure_schema_version_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """
    )
    count = await conn.fetchval("SELECT COUNT(*) FROM schema_version")
    if count == 0:
        await conn.execute("INSERT INTO schema_version (version) VALUES (0)")


async def _get_schema_version(conn: asyncpg.Connection) -> int:
    val = await conn.fetchval("SELECT version FROM schema_version LIMIT 1")
    return int(val) if val is not None else 0


async def _set_schema_version(conn: asyncpg.Connection, version: int) -> None:
    await conn.execute("UPDATE schema_version SET version = $1", version)


async def _run_migrations(conn: asyncpg.Connection, current_version: int) -> None:
    migrations = {
        1: _migrate_v1_initial_schema,
        2: _migrate_v2_add_columns,
        3: _migrate_v3_add_indices,
        4: _migrate_v4_finance_tables,
        5: _migrate_v5_subtask_fields,
    }
    for version in range(current_version + 1, _SCHEMA_VERSION + 1):
        migrate_fn = migrations.get(version)
        if migrate_fn:
            await migrate_fn(conn)
            await _set_schema_version(conn, version)


# ---------------------------------------------------------------------------
# Individual migration steps
# ---------------------------------------------------------------------------

async def _migrate_v1_initial_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(chat_id, name)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
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
            time_estimation_accuracy DOUBLE PRECISION,
            reminder_at TEXT,
            reminder_sent_at TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subtasks (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL,
            chat_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            position INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_retrospectives (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            retro_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested',
            prompt_text TEXT NOT NULL DEFAULT '',
            response_text TEXT NOT NULL DEFAULT '',
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            answered_at TIMESTAMPTZ,
            UNIQUE(chat_id, retro_date)
        )
        """
    )


async def _migrate_v2_add_columns(conn: asyncpg.Connection) -> None:
    columns = await _get_table_columns(conn, "tasks")
    optional: dict[str, str] = {
        "project_id": "ALTER TABLE tasks ADD COLUMN project_id INTEGER",
        "due_date": "ALTER TABLE tasks ADD COLUMN due_date TEXT",
        "planning_period": "ALTER TABLE tasks ADD COLUMN planning_period TEXT NOT NULL DEFAULT ''",
        "notion_page_id": "ALTER TABLE tasks ADD COLUMN notion_page_id TEXT",
        "estimated_minutes": "ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER",
        "actual_minutes": "ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER",
        "time_estimation_accuracy": "ALTER TABLE tasks ADD COLUMN time_estimation_accuracy DOUBLE PRECISION",
        "reminder_at": "ALTER TABLE tasks ADD COLUMN reminder_at TEXT",
        "reminder_sent_at": "ALTER TABLE tasks ADD COLUMN reminder_sent_at TEXT",
    }
    for col, sql in optional.items():
        if col not in columns:
            await conn.execute(sql)


async def _migrate_v3_add_indices(conn: asyncpg.Connection) -> None:
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_tasks_chat_id ON tasks(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_chat_status ON tasks(chat_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_chat_due ON tasks(chat_id, due_date)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_chat_period ON tasks(chat_id, planning_period)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_reminder ON tasks(reminder_at) WHERE reminder_at IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_subtasks_task_id ON subtasks(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_subtasks_chat_id ON subtasks(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_retro_chat_date ON daily_retrospectives(chat_id, retro_date)",
        "CREATE INDEX IF NOT EXISTS idx_projects_chat_id ON projects(chat_id)",
    ]:
        await conn.execute(stmt)


async def _migrate_v4_finance_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_revenue (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            date TEXT NOT NULL,
            cash INTEGER,
            card INTEGER,
            total INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(chat_id, date)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expense_entries (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_members (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            rate_per_shift INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(chat_id, name)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shifts (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            staff_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            rate_override INTEGER,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(chat_id, staff_id, work_date)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS salary_payments (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            staff_id INTEGER NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            amount INTEGER NOT NULL,
            shift_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            paid_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_revenue_chat_date ON daily_revenue(chat_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_expenses_chat_date ON expense_entries(chat_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_expenses_chat_cat ON expense_entries(chat_id, category)",
        "CREATE INDEX IF NOT EXISTS idx_shifts_chat_staff ON shifts(chat_id, staff_id)",
        "CREATE INDEX IF NOT EXISTS idx_shifts_chat_date ON shifts(chat_id, work_date)",
        "CREATE INDEX IF NOT EXISTS idx_staff_chat ON staff_members(chat_id)",
    ]:
        await conn.execute(stmt)


async def _migrate_v5_subtask_fields(conn: asyncpg.Connection) -> None:
    columns = await _get_table_columns(conn, "subtasks")
    if "due_date" not in columns:
        await conn.execute("ALTER TABLE subtasks ADD COLUMN due_date TEXT")
    if "estimated_minutes" not in columns:
        await conn.execute("ALTER TABLE subtasks ADD COLUMN estimated_minutes INTEGER")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subtasks_due ON subtasks(due_date) WHERE due_date IS NOT NULL"
    )


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------

async def save_task(
    chat_id: int,
    user_text: str,
    analysis: dict[str, Any],
    result: str,
    status: str = "in_progress",
) -> int:
    project_id = await _resolve_project_id(chat_id=chat_id, analysis=analysis)
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO tasks (
                chat_id, project_id, due_date, planning_period,
                user_text, title, task_type, priority, assigned_agent,
                status, analysis_json, result, estimated_minutes, reminder_at
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING id
            """,
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
        )
        return int(new_id)


async def list_recent_tasks(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.due_date, tasks.planning_period, tasks.estimated_minutes,
                tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.reminder_at, tasks.reminder_sent_at, tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1
            ORDER BY tasks.id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def list_active_tasks(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.due_date, tasks.planning_period, tasks.estimated_minutes,
                tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1 AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY tasks.id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def list_planner_context_tasks(chat_id: int, limit: int = 12) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.due_date, tasks.planning_period, tasks.estimated_minutes,
                tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1
            ORDER BY
                CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 0 ELSE 1 END,
                tasks.id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def get_task(chat_id: int, task_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                tasks.id, tasks.chat_id, tasks.project_id, tasks.due_date,
                tasks.planning_period, tasks.user_text, tasks.title, tasks.task_type,
                tasks.priority, tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.analysis_json, tasks.result, tasks.estimated_minutes,
                tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.reminder_at, tasks.reminder_sent_at, tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1 AND tasks.id = $2
            """,
            chat_id, task_id,
        )
    return dict(row) if row else None


async def list_projects(chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                projects.id, projects.name, projects.description,
                projects.status, projects.created_at,
                COUNT(tasks.id) AS task_count,
                SUM(CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 1 ELSE 0 END) AS active_task_count
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            WHERE projects.chat_id = $1
            GROUP BY projects.id
            ORDER BY active_task_count DESC NULLS LAST, projects.id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def list_project_context(chat_id: int, limit: int = 8) -> list[dict[str, Any]]:
    return await list_projects(chat_id=chat_id, limit=limit)


async def list_tasks_by_due_date(
    chat_id: int,
    due_date: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.due_date, tasks.estimated_minutes, tasks.actual_minutes,
                tasks.time_estimation_accuracy, tasks.reminder_at,
                tasks.reminder_sent_at, tasks.created_at,
                projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1
                AND tasks.due_date = $2
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                tasks.id DESC
            LIMIT $3
            """,
            chat_id, due_date, limit,
        )
    return [dict(r) for r in rows]


async def list_today_focus_tasks(
    chat_id: int,
    today: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id,
                tasks.due_date, tasks.planning_period, tasks.estimated_minutes,
                tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                tasks.chat_id = $1
                AND tasks.status NOT IN ('done', 'cancelled')
                AND (
                    tasks.due_date = $2
                    OR tasks.priority = 'high'
                    OR tasks.planning_period = 'week'
                )
            ORDER BY
                CASE
                    WHEN tasks.due_date = $2 THEN 0
                    WHEN tasks.priority = 'high' THEN 1
                    WHEN tasks.planning_period = 'week' THEN 2
                    ELSE 3
                END,
                CASE tasks.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                tasks.id DESC
            LIMIT $3
            """,
            chat_id, today, limit,
        )
    return [dict(r) for r in rows]


async def list_subtasks_due_today(chat_id: int, today: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                subtasks.id, subtasks.task_id, subtasks.title, subtasks.status,
                subtasks.position, subtasks.due_date, subtasks.estimated_minutes,
                tasks.title AS parent_title, projects.name AS project_name
            FROM subtasks
            JOIN tasks ON tasks.id = subtasks.task_id
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                subtasks.chat_id = $1
                AND subtasks.due_date = $2
                AND subtasks.status != 'done'
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY subtasks.position ASC
            """,
            chat_id, today,
        )
    return [dict(r) for r in rows]


async def list_chat_ids_for_morning_brief() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT chat_id FROM tasks
            WHERE status NOT IN ('done', 'cancelled')
            ORDER BY chat_id
            """
        )
    return [int(r["chat_id"]) for r in rows]


async def list_chat_ids_for_retrospective() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT chat_id FROM tasks ORDER BY chat_id")
    return [int(r["chat_id"]) for r in rows]


async def list_open_subtasks_for_brief(chat_id: int, limit: int = 20) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                subtasks.id, subtasks.task_id, subtasks.title, subtasks.status, subtasks.position,
                tasks.title AS task_title, tasks.priority AS task_priority,
                tasks.estimated_minutes AS task_estimated_minutes,
                tasks.actual_minutes AS task_actual_minutes,
                tasks.time_estimation_accuracy AS task_time_estimation_accuracy,
                projects.name AS project_name
            FROM subtasks
            JOIN tasks ON tasks.id = subtasks.task_id
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE
                subtasks.chat_id = $1
                AND subtasks.status != 'done'
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                tasks.id DESC,
                subtasks.position ASC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def create_or_update_daily_retrospective(
    chat_id: int,
    retro_date: str,
    prompt_text: str,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO daily_retrospectives (chat_id, retro_date, status, prompt_text)
            VALUES ($1, $2, 'requested', $3)
            ON CONFLICT(chat_id, retro_date) DO UPDATE SET
                status = CASE
                    WHEN daily_retrospectives.status = 'answered' THEN daily_retrospectives.status
                    ELSE 'requested'
                END,
                prompt_text = EXCLUDED.prompt_text
            """,
            chat_id, retro_date, prompt_text,
        )
        row_id = await conn.fetchval(
            "SELECT id FROM daily_retrospectives WHERE chat_id = $1 AND retro_date = $2",
            chat_id, retro_date,
        )
    return int(row_id) if row_id else 0


async def get_pending_retrospective(chat_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, chat_id, retro_date, status, prompt_text, response_text,
                   summary_json, created_at, answered_at
            FROM daily_retrospectives
            WHERE chat_id = $1 AND status = 'requested'
            ORDER BY retro_date DESC, id DESC
            LIMIT 1
            """,
            chat_id,
        )
    return dict(row) if row else None


async def save_retrospective_response(
    chat_id: int,
    retro_id: int,
    response_text: str,
    summary: dict[str, Any],
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            UPDATE daily_retrospectives
            SET status = 'answered', response_text = $1, summary_json = $2, answered_at = NOW()
            WHERE chat_id = $3 AND id = $4
            """,
            response_text,
            json.dumps(summary, ensure_ascii=False),
            chat_id,
            retro_id,
        )
    return _rowcount(status) > 0


async def update_retrospective_status(chat_id: int, retro_id: int, status: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE daily_retrospectives SET status = $1, answered_at = NOW() WHERE chat_id = $2 AND id = $3",
            status, chat_id, retro_id,
        )
    return _rowcount(result) > 0


async def list_recent_retrospectives(chat_id: int, limit: int = 7) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, retro_date, status, response_text, summary_json, created_at, answered_at
            FROM daily_retrospectives
            WHERE chat_id = $1 AND status IN ('answered', 'partial')
            ORDER BY retro_date DESC, id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


async def list_tasks_by_planning_period(
    chat_id: int,
    planning_period: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.due_date, tasks.planning_period,
                tasks.estimated_minutes, tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1
                AND tasks.planning_period = $2
                AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE tasks.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                tasks.id DESC
            LIMIT $3
            """,
            chat_id, planning_period, limit,
        )
    return [dict(r) for r in rows]


async def get_project(chat_id: int, project_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                projects.id, projects.name, projects.description,
                projects.status, projects.created_at,
                COUNT(tasks.id) AS task_count,
                SUM(CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 1 ELSE 0 END) AS active_task_count
            FROM projects
            LEFT JOIN tasks ON tasks.project_id = projects.id
            WHERE projects.chat_id = $1 AND projects.id = $2
            GROUP BY projects.id
            """,
            chat_id, project_id,
        )
    return dict(row) if row else None


async def list_project_tasks(chat_id: int, project_id: int, limit: int = 10) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.due_date, tasks.planning_period,
                tasks.estimated_minutes, tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1 AND tasks.project_id = $2
            ORDER BY
                CASE WHEN tasks.status NOT IN ('done', 'cancelled') THEN 0 ELSE 1 END,
                tasks.id DESC
            LIMIT $3
            """,
            chat_id, project_id, limit,
        )
    return [dict(r) for r in rows]


async def update_task_plan(
    chat_id: int,
    task_id: int,
    analysis: dict[str, Any],
    result: str,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            UPDATE tasks
            SET assigned_agent = 'planner_agent',
                analysis_json = $1,
                result = $2,
                estimated_minutes = COALESCE($3, estimated_minutes)
            WHERE chat_id = $4 AND id = $5
            """,
            json.dumps(analysis, ensure_ascii=False),
            result,
            _normalize_minutes(analysis.get("estimated_minutes")),
            chat_id,
            task_id,
        )
    return _rowcount(status) > 0


async def update_task_notion_page_id(chat_id: int, task_id: int, notion_page_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE tasks SET notion_page_id = $1 WHERE chat_id = $2 AND id = $3",
            notion_page_id, chat_id, task_id,
        )
    return _rowcount(status) > 0


async def update_task_status(chat_id: int, task_id: int, status: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET status = $1 WHERE chat_id = $2 AND id = $3",
            status, chat_id, task_id,
        )
    return _rowcount(result) > 0


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
    accuracy = _calculate_time_estimation_accuracy(estimated_minutes, actual_minutes)

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tasks
            SET status = 'done',
                actual_minutes = COALESCE($1, actual_minutes),
                time_estimation_accuracy = COALESCE($2, time_estimation_accuracy)
            WHERE chat_id = $3 AND id = $4
            """,
            actual_minutes, accuracy, chat_id, task_id,
        )
    return _rowcount(result) > 0


async def update_task_due_date(chat_id: int, task_id: int, due_date: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET due_date = $1, planning_period = '' WHERE chat_id = $2 AND id = $3",
            due_date, chat_id, task_id,
        )
    return _rowcount(result) > 0


async def update_task_title(chat_id: int, task_id: int, title: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET title = $1 WHERE chat_id = $2 AND id = $3",
            title, chat_id, task_id,
        )
    return _rowcount(result) > 0


async def update_task_priority(chat_id: int, task_id: int, priority: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET priority = $1 WHERE chat_id = $2 AND id = $3",
            priority, chat_id, task_id,
        )
    return _rowcount(result) > 0


async def update_task_reminder(chat_id: int, task_id: int, reminder_at: str | None) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET reminder_at = $1, reminder_sent_at = NULL WHERE chat_id = $2 AND id = $3",
            reminder_at, chat_id, task_id,
        )
    return _rowcount(result) > 0


async def mark_task_reminder_sent(chat_id: int, task_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET reminder_sent_at = NOW()::TEXT WHERE chat_id = $1 AND id = $2",
            chat_id, task_id,
        )
    return _rowcount(result) > 0


async def list_next_task_candidates(chat_id: int, today: str, limit: int = 12) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.due_date, tasks.planning_period,
                tasks.estimated_minutes, tasks.actual_minutes, tasks.time_estimation_accuracy,
                tasks.reminder_at, projects.name AS project_name,
                (
                    SELECT subtasks.id FROM subtasks
                    WHERE subtasks.task_id = tasks.id
                        AND subtasks.chat_id = tasks.chat_id
                        AND subtasks.status != 'done'
                    ORDER BY subtasks.position ASC, subtasks.id ASC
                    LIMIT 1
                ) AS next_subtask_id,
                (
                    SELECT subtasks.title FROM subtasks
                    WHERE subtasks.task_id = tasks.id
                        AND subtasks.chat_id = tasks.chat_id
                        AND subtasks.status != 'done'
                    ORDER BY subtasks.position ASC, subtasks.id ASC
                    LIMIT 1
                ) AS next_subtask_title
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1 AND tasks.status NOT IN ('done', 'cancelled')
            ORDER BY
                CASE
                    WHEN tasks.due_date IS NOT NULL AND tasks.due_date < $2 THEN 0
                    WHEN tasks.due_date = $2 THEN 1
                    WHEN tasks.priority = 'high' THEN 2
                    WHEN tasks.due_date IS NOT NULL THEN 3
                    WHEN tasks.planning_period = 'week' THEN 4
                    ELSE 5
                END,
                CASE tasks.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                tasks.due_date ASC NULLS LAST,
                tasks.id DESC
            LIMIT $3
            """,
            chat_id, today, limit,
        )
    return [dict(r) for r in rows]


async def list_pending_reminder_tasks(now: str, limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, chat_id, title, priority, status, due_date, reminder_at, reminder_sent_at
            FROM tasks
            WHERE
                reminder_at IS NOT NULL
                AND reminder_at != ''
                AND reminder_sent_at IS NULL
                AND status NOT IN ('done', 'cancelled')
            ORDER BY reminder_at ASC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def list_tasks_for_notion_sync(chat_id: int, limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                tasks.id, tasks.user_text, tasks.title, tasks.task_type, tasks.priority,
                tasks.assigned_agent, tasks.status, tasks.notion_page_id, tasks.due_date,
                tasks.planning_period, tasks.estimated_minutes, tasks.actual_minutes,
                tasks.time_estimation_accuracy, tasks.reminder_at, tasks.reminder_sent_at,
                tasks.created_at, projects.name AS project_name
            FROM tasks
            LEFT JOIN projects ON projects.id = tasks.project_id
            WHERE tasks.chat_id = $1
            ORDER BY tasks.id DESC
            LIMIT $2
            """,
            chat_id, limit,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Subtask operations
# ---------------------------------------------------------------------------

async def replace_subtasks(
    chat_id: int,
    task_id: int,
    subtasks: list[dict[str, Any]],
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM subtasks WHERE chat_id = $1 AND task_id = $2",
                chat_id, task_id,
            )
            for position, item in enumerate(subtasks, start=1):
                await conn.execute(
                    """
                    INSERT INTO subtasks (task_id, chat_id, title, position, due_date, estimated_minutes)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    """,
                    task_id, chat_id, item["title"], position,
                    item.get("due_date"), item.get("estimated_minutes"),
                )


async def list_subtasks(chat_id: int, task_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task_id, title, status, position, due_date, estimated_minutes, created_at
            FROM subtasks
            WHERE chat_id = $1 AND task_id = $2
            ORDER BY position ASC, id ASC
            """,
            chat_id, task_id,
        )
    return [dict(r) for r in rows]


async def mark_subtask_done(chat_id: int, subtask_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE subtasks SET status = 'done' WHERE chat_id = $1 AND id = $2",
            chat_id, subtask_id,
        )
    return _rowcount(result) > 0


async def get_subtask(chat_id: int, subtask_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, task_id, title, status, position, created_at FROM subtasks WHERE chat_id = $1 AND id = $2",
            chat_id, subtask_id,
        )
    return dict(row) if row else None


async def all_subtasks_done(chat_id: int, task_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status != 'done' THEN 1 ELSE 0 END) AS open_count
            FROM subtasks
            WHERE chat_id = $1 AND task_id = $2
            """,
            chat_id, task_id,
        )
    total = row["total_count"] or 0
    open_count = row["open_count"] or 0
    return total > 0 and open_count == 0


async def mark_task_done(chat_id: int, task_id: int) -> bool:
    return await mark_task_done_with_time(chat_id=chat_id, task_id=task_id)


async def mark_task_cancelled(chat_id: int, task_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE tasks SET status = 'cancelled' WHERE chat_id = $1 AND id = $2",
            chat_id, task_id,
        )
    return _rowcount(result) > 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _resolve_project_id(chat_id: int, analysis: dict[str, Any]) -> int | None:
    project_name = analysis.get("project") or analysis.get("project_name")
    if not isinstance(project_name, str):
        return None
    project_name = project_name.strip()
    if not project_name:
        return None

    description = analysis.get("project_description", "") or ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO projects (chat_id, name, description)
            VALUES ($1, $2, $3)
            ON CONFLICT(chat_id, name) DO NOTHING
            """,
            chat_id, project_name, description,
        )
        row_id = await conn.fetchval(
            "SELECT id FROM projects WHERE chat_id = $1 AND name = $2",
            chat_id, project_name,
        )
    return int(row_id) if row_id else None


async def _get_table_columns(conn: asyncpg.Connection, table_name: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
        table_name,
    )
    return {r["column_name"] for r in rows}


def _rowcount(status: str) -> int:
    """Parse asyncpg status string like 'UPDATE 3' → 3."""
    try:
        return int(status.split()[-1])
    except (IndexError, ValueError):
        return 0


def _normalize_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def _calculate_time_estimation_accuracy(
    estimated_minutes: int | None,
    actual_minutes: int | None,
) -> float | None:
    if not estimated_minutes or not actual_minutes:
        return None
    smaller = min(estimated_minutes, actual_minutes)
    bigger = max(estimated_minutes, actual_minutes)
    return round((smaller / bigger) * 100, 1)
