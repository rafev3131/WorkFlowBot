"""Finance command handlers."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.ai_client import ai_client
from app.finance.db import (
    add_expense,
    add_shift,
    add_staff,
    count_shifts_by_staff,
    deactivate_staff,
    delete_expense,
    get_revenue,
    get_staff_by_name,
    list_payments,
    list_staff,
    record_payment,
    upsert_revenue,
)
from app.finance.reports import (
    build_payroll_summary,
    build_staff_list,
    build_today_finance_summary,
    build_week_report,
    fmt_money,
)

# ---------------------------------------------------------------------------
# Free-text finance input (main entry point from the bot)
# ---------------------------------------------------------------------------

FINANCE_KEYWORDS = (
    "выручка", "нал", "карта", "безнал", "расход", "расходы",
    "продажи", "касса", "баланс",
)


def is_finance_message(text: str) -> bool:
    lower = text.lower()
    if lower.startswith("/"):
        return False
    return any(kw in lower for kw in FINANCE_KEYWORDS)


async def handle_finance_input(chat_id: int, text: str) -> str:
    today = date.today().isoformat()
    parsed = await ai_client.parse_finance(text=text, today=today)

    entry_date = parsed.get("date") or today
    messages = []

    # Save revenue
    revenue_data = parsed.get("revenue")
    if revenue_data and any(v is not None for v in revenue_data.values()):
        total = _resolve_total(revenue_data)
        if total and total > 0:
            await upsert_revenue(
                chat_id=chat_id,
                date=entry_date,
                total=total,
                cash=revenue_data.get("cash"),
                card=revenue_data.get("card"),
                notes=parsed.get("notes", ""),
            )
            cash_str = f", нал {fmt_money(revenue_data.get('cash'))}" if revenue_data.get("cash") else ""
            card_str = f", карта {fmt_money(revenue_data.get('card'))}" if revenue_data.get("card") else ""
            messages.append(f"💰 Выручка {entry_date}: {fmt_money(total)}{cash_str}{card_str}")

    # Save expenses
    expenses = parsed.get("expenses") or []
    for exp in expenses:
        amount = exp.get("amount")
        category = exp.get("category", "прочее")
        if amount and amount > 0:
            await add_expense(
                chat_id=chat_id,
                date=entry_date,
                category=category,
                amount=int(amount),
                description=exp.get("description", ""),
            )
            messages.append(f"💸 Расход ({category}): {fmt_money(int(amount))}")

    if not messages:
        return (
            "Не смог распознать финансовые данные. Попробуй так:\n"
            "«выручка 380000 нал 210000 карта 170000 расходы продукты 85000»"
        )

    return "\n".join(messages) + f"\n\n/финансы — посмотреть итог за {entry_date}"


# ---------------------------------------------------------------------------
# /финансы — today summary
# ---------------------------------------------------------------------------

async def handle_finances_command(chat_id: int, text: str) -> str:
    parts = text.split()
    # /финансы or /финансы 2026-06-01
    target = parts[1] if len(parts) == 2 else date.today().isoformat()
    try:
        date.fromisoformat(target)
    except ValueError:
        return "Формат: /финансы или /финансы 2026-06-01"
    return await build_today_finance_summary(chat_id=chat_id, today=target)


# ---------------------------------------------------------------------------
# /выручка — manual revenue entry
# ---------------------------------------------------------------------------

async def handle_revenue_command(chat_id: int, text: str) -> str:
    """
    /выручка 380000
    /выручка 380000 нал 210000 карта 170000
    """
    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return "Формат: /выручка 380000\nили: /выручка 380000 нал 210000 карта 170000"

    total = int(parts[1])
    cash = card = None
    if len(parts) >= 6 and parts[2] == "нал" and parts[4] == "карта":
        try:
            cash = int(parts[3])
            card = int(parts[5])
        except (ValueError, IndexError):
            pass

    today = date.today().isoformat()
    await upsert_revenue(chat_id=chat_id, date=today, total=total, cash=cash, card=card)

    cash_str = f", нал {fmt_money(cash)}" if cash else ""
    card_str = f", карта {fmt_money(card)}" if card else ""
    return f"💰 Выручка {today}: {fmt_money(total)}{cash_str}{card_str}\n\n/финансы — итог дня"


# ---------------------------------------------------------------------------
# /расход — manual expense entry
# ---------------------------------------------------------------------------

async def handle_expense_command(chat_id: int, text: str) -> str:
    """
    /расход продукты 85000
    /расход продукты 85000 мясо
    """
    parts = text.split(maxsplit=3)
    if len(parts) < 3 or not parts[2].isdigit():
        return (
            "Формат: /расход категория сумма\n"
            "Категории: продукты, напитки, зарплата, аренда, хозтовары, маркетинг, ремонт, коммунальные, прочее\n"
            "Пример: /расход продукты 85000"
        )

    category = parts[1].lower()
    amount = int(parts[2])
    description = parts[3] if len(parts) > 3 else ""

    today = date.today().isoformat()
    expense_id = await add_expense(
        chat_id=chat_id,
        date=today,
        category=category,
        amount=amount,
        description=description,
    )
    return (
        f"💸 Расход #{expense_id} сохранён.\n"
        f"  {category}: {fmt_money(amount)}"
        f"{' — ' + description if description else ''}\n\n"
        f"/финансы — итог дня"
    )


# ---------------------------------------------------------------------------
# /отчет — weekly report
# ---------------------------------------------------------------------------

async def handle_report_command(chat_id: int, text: str) -> str:
    """
    /отчет         — текущая неделя
    /отчет прошлая — прошлая неделя
    """
    today = date.today()
    # Current Monday
    this_monday = today - timedelta(days=today.weekday())
    prev_monday = this_monday - timedelta(weeks=1)

    parts = text.split()
    if len(parts) > 1 and "прошл" in parts[1].lower():
        week_start = prev_monday
        prev_week_start = prev_monday - timedelta(weeks=1)
    else:
        week_start = this_monday
        prev_week_start = prev_monday

    report_text = await build_week_report(
        chat_id=chat_id,
        week_start=week_start,
        prev_week_start=prev_week_start,
    )

    # Add AI insight
    try:
        insight = await ai_client.generate_finance_insight(report_text)
        if insight:
            report_text += f"\n\n💡 {insight}"
    except Exception:
        pass

    return report_text


# ---------------------------------------------------------------------------
# Staff commands
# ---------------------------------------------------------------------------

async def handle_staff_command(chat_id: int) -> str:
    staff = await list_staff(chat_id=chat_id)
    return build_staff_list(staff)


async def handle_staff_add_command(chat_id: int, text: str) -> str:
    """
    /сотрудник_добавить Иван Бармен 15000
    /сотрудник_добавить "Иван Петров" Менеджер 20000
    """
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        return (
            "Формат: /сотрудник_добавить Имя Должность Ставка\n"
            "Пример: /сотрудник_добавить Иван Бармен 15000"
        )

    name = parts[1]
    role = parts[2]
    rate = 0
    if len(parts) >= 4 and parts[3].isdigit():
        rate = int(parts[3])

    await add_staff(chat_id=chat_id, name=name, role=role, rate_per_shift=rate)
    return (
        f"👤 Сотрудник добавлен: {name} ({role}), ставка {fmt_money(rate)}/смену\n\n"
        "/смена Иван — поставить смену сегодня\n"
        "/расчет — посмотреть зарплаты"
    )


async def handle_staff_remove_command(chat_id: int, text: str) -> str:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return "Формат: /сотрудник_убрать Иван"

    name = parts[1].strip()
    staff = await get_staff_by_name(chat_id=chat_id, name=name)
    if not staff:
        return f"Не нашёл сотрудника «{name}». Проверь /сотрудники"

    await deactivate_staff(chat_id=chat_id, staff_id=staff["id"])
    return f"👤 {staff['name']} переведён в архив."


# ---------------------------------------------------------------------------
# Shift commands
# ---------------------------------------------------------------------------

async def handle_shift_command(chat_id: int, text: str) -> str:
    """
    /смена Иван            — сегодня
    /смена Иван 2026-06-01 — конкретная дата
    """
    parts = text.split()
    if len(parts) < 2:
        return "Формат: /смена Имя или /смена Имя 2026-06-01"

    name = parts[1]
    work_date = date.today().isoformat()
    if len(parts) >= 3:
        try:
            date.fromisoformat(parts[2])
            work_date = parts[2]
        except ValueError:
            return "Дата должна быть в формате YYYY-MM-DD"

    staff = await get_staff_by_name(chat_id=chat_id, name=name)
    if not staff:
        return (
            f"Не нашёл сотрудника «{name}».\n"
            "/сотрудники — список\n"
            f"/сотрудник_добавить {name} Бармен 15000 — добавить"
        )

    added = await add_shift(
        chat_id=chat_id,
        staff_id=staff["id"],
        work_date=work_date,
    )
    if not added:
        return f"Смена {staff['name']} на {work_date} уже записана."

    rate = fmt_money(staff["rate_per_shift"])
    return f"✅ Смена записана: {staff['name']}, {work_date} ({rate})"


async def handle_shift_remove_command(chat_id: int, text: str) -> str:
    parts = text.split()
    if len(parts) < 2:
        return "Формат: /смена_убрать Имя или /смена_убрать Имя 2026-06-01"

    name = parts[1]
    work_date = date.today().isoformat()
    if len(parts) >= 3:
        work_date = parts[2]

    staff = await get_staff_by_name(chat_id=chat_id, name=name)
    if not staff:
        return f"Не нашёл сотрудника «{name}»."

    deleted = await delete_shift(
        chat_id=chat_id,
        staff_id=staff["id"],
        work_date=work_date,
    )
    return f"Смена {staff['name']} на {work_date} {'удалена' if deleted else 'не найдена'}."


# ---------------------------------------------------------------------------
# Payroll commands
# ---------------------------------------------------------------------------

async def handle_payroll_command(chat_id: int, text: str) -> str:
    """
    /расчет           — текущий месяц
    /расчет 2026-06   — конкретный месяц
    """
    parts = text.split()
    today = date.today()
    if len(parts) >= 2 and "-" in parts[1]:
        try:
            year, month = map(int, parts[1].split("-"))
            period_start = date(year, month, 1)
        except ValueError:
            return "Формат: /расчет или /расчет 2026-06"
    else:
        period_start = date(today.year, today.month, 1)

    # Last day of month
    if period_start.month == 12:
        period_end = date(period_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(period_start.year, period_start.month + 1, 1) - timedelta(days=1)

    rows = await count_shifts_by_staff(
        chat_id=chat_id,
        date_from=period_start.isoformat(),
        date_to=period_end.isoformat(),
    )
    return build_payroll_summary(rows, period_start.isoformat(), period_end.isoformat())


async def handle_pay_command(chat_id: int, text: str) -> str:
    """
    /выплатить Иван 45000
    """
    parts = text.split()
    if len(parts) < 3 or not parts[2].isdigit():
        return "Формат: /выплатить Имя Сумма\nПример: /выплатить Иван 45000"

    name = parts[1]
    amount = int(parts[2])

    staff = await get_staff_by_name(chat_id=chat_id, name=name)
    if not staff:
        return f"Не нашёл сотрудника «{name}»."

    today = date.today()
    period_start = date(today.year, today.month, 1)
    rows = await count_shifts_by_staff(
        chat_id=chat_id,
        date_from=period_start.isoformat(),
        date_to=today.isoformat(),
    )
    staff_row = next((r for r in rows if r["staff_id"] == staff["id"]), None)
    shifts_this_month = staff_row["shift_count"] if staff_row else 0

    await record_payment(
        chat_id=chat_id,
        staff_id=staff["id"],
        period_start=period_start.isoformat(),
        period_end=today.isoformat(),
        amount=amount,
        shift_count=shifts_this_month,
    )

    return (
        f"✅ Выплата записана: {staff['name']}\n"
        f"   Сумма: {fmt_money(amount)}\n"
        f"   Смен в этом месяце: {shifts_this_month}\n\n"
        "/расчет — обновлённый расчёт"
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _resolve_total(revenue: dict[str, Any]) -> int | None:
    if revenue.get("total"):
        return int(revenue["total"])
    cash = revenue.get("cash") or 0
    card = revenue.get("card") or 0
    if cash or card:
        return int(cash) + int(card)
    return None
