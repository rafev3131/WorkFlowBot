"""Finance module — database operations."""
from __future__ import annotations

from typing import Any

import aiosqlite

from app.database import DATABASE_PATH


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
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO daily_revenue (chat_id, date, cash, card, total, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, date) DO UPDATE SET
                cash = excluded.cash,
                card = excluded.card,
                total = excluded.total,
                notes = excluded.notes
            """,
            (chat_id, date, cash, card, total, notes),
        )
        await db.commit()


async def get_revenue(chat_id: int, date: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM daily_revenue WHERE chat_id = ? AND date = ?",
            (chat_id, date),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def list_revenue(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM daily_revenue
            WHERE chat_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
            """,
            (chat_id, date_from, date_to),
        )
        rows = await cursor.fetchall()
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
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO expense_entries (chat_id, date, category, amount, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, date, category, amount, description),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_expenses(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM expense_entries
            WHERE chat_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC, id ASC
            """,
            (chat_id, date_from, date_to),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def delete_expense(chat_id: int, expense_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM expense_entries WHERE id = ? AND chat_id = ?",
            (expense_id, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

async def add_staff(
    chat_id: int,
    name: str,
    role: str = "",
    rate_per_shift: int = 0,
) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO staff_members (chat_id, name, role, rate_per_shift)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, name) DO UPDATE SET
                role = excluded.role,
                rate_per_shift = excluded.rate_per_shift,
                status = 'active'
            """,
            (chat_id, name, role, rate_per_shift),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_staff(chat_id: int, status: str = "active") -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM staff_members WHERE chat_id = ? AND status = ? ORDER BY name",
            (chat_id, status),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_staff_by_name(chat_id: int, name: str) -> dict[str, Any] | None:
    """Find staff member by exact or partial name match."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM staff_members
            WHERE chat_id = ? AND status = 'active'
              AND (name = ? OR lower(name) LIKE lower(?))
            LIMIT 1
            """,
            (chat_id, name, f"%{name}%"),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def deactivate_staff(chat_id: int, staff_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "UPDATE staff_members SET status = 'inactive' WHERE id = ? AND chat_id = ?",
            (staff_id, chat_id),
        )
        await db.commit()
        return cursor.rowcount > 0


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
    """Return True if inserted, False if already exists (upsert)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO shifts (chat_id, staff_id, work_date, rate_override, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, staff_id, work_date, rate_override, notes),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_shift(chat_id: int, staff_id: int, work_date: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM shifts WHERE chat_id = ? AND staff_id = ? AND work_date = ?",
            (chat_id, staff_id, work_date),
        )
        await db.commit()
        return cursor.rowcount > 0


async def list_shifts(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*, sm.name AS staff_name, sm.role, sm.rate_per_shift
            FROM shifts s
            JOIN staff_members sm ON sm.id = s.staff_id
            WHERE s.chat_id = ? AND s.work_date >= ? AND s.work_date <= ?
            ORDER BY s.work_date ASC, sm.name ASC
            """,
            (chat_id, date_from, date_to),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def count_shifts_by_staff(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    """Return shift count and calculated salary per staff member for a period."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                sm.id AS staff_id,
                sm.name,
                sm.role,
                sm.rate_per_shift,
                COUNT(s.id) AS shift_count,
                SUM(COALESCE(s.rate_override, sm.rate_per_shift)) AS total_salary
            FROM staff_members sm
            LEFT JOIN shifts s ON s.staff_id = sm.id
                AND s.chat_id = sm.chat_id
                AND s.work_date >= ?
                AND s.work_date <= ?
            WHERE sm.chat_id = ? AND sm.status = 'active'
            GROUP BY sm.id
            ORDER BY sm.name
            """,
            (date_from, date_to, chat_id),
        )
        rows = await cursor.fetchall()
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
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO salary_payments
                (chat_id, staff_id, period_start, period_end, amount, shift_count, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, staff_id, period_start, period_end, amount, shift_count, notes),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_payments(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT sp.*, sm.name AS staff_name, sm.role
            FROM salary_payments sp
            JOIN staff_members sm ON sm.id = sp.staff_id
            WHERE sp.chat_id = ? AND sp.paid_at >= ? AND sp.paid_at <= ?
            ORDER BY sp.paid_at DESC
            """,
            (chat_id, date_from, date_to),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Aggregates (used by reports)
# ---------------------------------------------------------------------------

async def revenue_summary(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """Return totals and per-day list for a period."""
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


async def expense_summary(
    chat_id: int,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """Return total and by-category breakdown."""
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
