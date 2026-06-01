"""Finance module — database operations."""
from __future__ import annotations

from typing import Any

from app.database import _rowcount, get_pool


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

async def upsert_revenue(
    chat_id: int,
    date: str,
    total: int,
    cash: int | None = None,
    card: int | None = None,
    notes: str = "",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO daily_revenue (chat_id, date, cash, card, total, notes)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT(chat_id, date) DO UPDATE SET
                cash = EXCLUDED.cash,
                card = EXCLUDED.card,
                total = EXCLUDED.total,
                notes = EXCLUDED.notes
            """,
            chat_id, date, cash, card, total, notes,
        )


async def get_revenue(chat_id: int, date: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM daily_revenue WHERE chat_id = $1 AND date = $2",
            chat_id, date,
        )
    return dict(row) if row else None


async def list_revenue(chat_id: int, date_from: str, date_to: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM daily_revenue
            WHERE chat_id = $1 AND date >= $2 AND date <= $3
            ORDER BY date ASC
            """,
            chat_id, date_from, date_to,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

async def add_expense(
    chat_id: int,
    date: str,
    category: str,
    amount: int,
    description: str = "",
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO expense_entries (chat_id, date, category, amount, description)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            chat_id, date, category, amount, description,
        )
    return int(new_id)


async def list_expenses(chat_id: int, date_from: str, date_to: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM expense_entries
            WHERE chat_id = $1 AND date >= $2 AND date <= $3
            ORDER BY date ASC, id ASC
            """,
            chat_id, date_from, date_to,
        )
    return [dict(r) for r in rows]


async def delete_expense(chat_id: int, expense_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM expense_entries WHERE id = $1 AND chat_id = $2",
            expense_id, chat_id,
        )
    return _rowcount(result) > 0


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

async def add_staff(
    chat_id: int,
    name: str,
    role: str = "",
    rate_per_shift: int = 0,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO staff_members (chat_id, name, role, rate_per_shift)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT(chat_id, name) DO UPDATE SET
                role = EXCLUDED.role,
                rate_per_shift = EXCLUDED.rate_per_shift,
                status = 'active'
            RETURNING id
            """,
            chat_id, name, role, rate_per_shift,
        )
    return int(new_id)


async def list_staff(chat_id: int, status: str = "active") -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM staff_members WHERE chat_id = $1 AND status = $2 ORDER BY name",
            chat_id, status,
        )
    return [dict(r) for r in rows]


async def get_staff_by_name(chat_id: int, name: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM staff_members
            WHERE chat_id = $1 AND status = 'active'
              AND (name = $2 OR lower(name) LIKE lower($3))
            LIMIT 1
            """,
            chat_id, name, f"%{name}%",
        )
    return dict(row) if row else None


async def deactivate_staff(chat_id: int, staff_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE staff_members SET status = 'inactive' WHERE id = $1 AND chat_id = $2",
            staff_id, chat_id,
        )
    return _rowcount(result) > 0


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

async def add_shift(
    chat_id: int,
    staff_id: int,
    work_date: str,
    rate_override: int | None = None,
    notes: str = "",
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO shifts (chat_id, staff_id, work_date, rate_override, notes)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT(chat_id, staff_id, work_date) DO NOTHING
            """,
            chat_id, staff_id, work_date, rate_override, notes,
        )
    return _rowcount(result) > 0


async def delete_shift(chat_id: int, staff_id: int, work_date: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM shifts WHERE chat_id = $1 AND staff_id = $2 AND work_date = $3",
            chat_id, staff_id, work_date,
        )
    return _rowcount(result) > 0


async def list_shifts(chat_id: int, date_from: str, date_to: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.*, sm.name AS staff_name, sm.role, sm.rate_per_shift
            FROM shifts s
            JOIN staff_members sm ON sm.id = s.staff_id
            WHERE s.chat_id = $1 AND s.work_date >= $2 AND s.work_date <= $3
            ORDER BY s.work_date ASC, sm.name ASC
            """,
            chat_id, date_from, date_to,
        )
    return [dict(r) for r in rows]


async def count_shifts_by_staff(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                sm.id AS staff_id, sm.name, sm.role, sm.rate_per_shift,
                COUNT(s.id) AS shift_count,
                SUM(COALESCE(s.rate_override, sm.rate_per_shift)) AS total_salary
            FROM staff_members sm
            LEFT JOIN shifts s ON s.staff_id = sm.id
                AND s.chat_id = sm.chat_id
                AND s.work_date >= $1
                AND s.work_date <= $2
            WHERE sm.chat_id = $3 AND sm.status = 'active'
            GROUP BY sm.id
            ORDER BY sm.name
            """,
            date_from, date_to, chat_id,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Salary payments
# ---------------------------------------------------------------------------

async def record_payment(
    chat_id: int,
    staff_id: int,
    period_start: str,
    period_end: str,
    amount: int,
    shift_count: int = 0,
    notes: str = "",
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            """
            INSERT INTO salary_payments
                (chat_id, staff_id, period_start, period_end, amount, shift_count, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            chat_id, staff_id, period_start, period_end, amount, shift_count, notes,
        )
    return int(new_id)


async def list_payments(chat_id: int, date_from: str, date_to: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sp.*, sm.name AS staff_name, sm.role
            FROM salary_payments sp
            JOIN staff_members sm ON sm.id = sp.staff_id
            WHERE sp.chat_id = $1 AND sp.paid_at >= $2 AND sp.paid_at <= $3
            ORDER BY sp.paid_at DESC
            """,
            chat_id, date_from, date_to,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

async def revenue_summary(chat_id: int, date_from: str, date_to: str) -> dict[str, Any]:
    rows = await list_revenue(chat_id, date_from, date_to)
    total = sum(r["total"] for r in rows)
    cash = sum(r["cash"] or 0 for r in rows)
    card = sum(r["card"] or 0 for r in rows)
    return {
        "total": total,
        "cash": cash,
        "card": card,
        "days": rows,
        "best_day": max(rows, key=lambda r: r["total"]) if rows else None,
        "worst_day": min(rows, key=lambda r: r["total"]) if rows else None,
    }


async def expense_summary(chat_id: int, date_from: str, date_to: str) -> dict[str, Any]:
    rows = await list_expenses(chat_id, date_from, date_to)
    total = sum(r["amount"] for r in rows)
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    return {
        "total": total,
        "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
        "entries": rows,
    }
