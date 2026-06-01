"""Finance report formatters."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.finance.db import expense_summary, revenue_summary


WEEKDAY_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
CATEGORY_EMOJI = {
    "продукты": "🥩",
    "напитки": "🍾",
    "зарплата": "👥",
    "аренда": "🏠",
    "хозтовары": "🧹",
    "маркетинг": "📣",
    "ремонт": "🔧",
    "коммунальные": "💡",
    "прочее": "📦",
}


def fmt_money(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"{amount:,}".replace(",", " ") + " ₸"


def fmt_pct(part: int, total: int) -> str:
    if not total:
        return "—"
    return f"{round(part / total * 100)}%"


async def build_today_finance_summary(chat_id: int, today: str) -> str:
    rev = await revenue_summary(chat_id, today, today)
    exp = await expense_summary(chat_id, today, today)

    if not rev["days"] and not exp["entries"]:
        return (
            f"📊 Финансов за {today} нет.\n"
            "Введи данные: «выручка 380к нал 210к карта 170к расходы продукты 85к»"
        )

    lines = [f"📊 Финансы за {today}"]

    if rev["days"]:
        r = rev["days"][0]
        lines.append(f"\nВыручка: {fmt_money(r['total'])}")
        if r.get("cash") or r.get("card"):
            lines.append(f"  Нал: {fmt_money(r['cash'])}  Карта: {fmt_money(r['card'])}")

    if exp["entries"]:
        lines.append(f"\nРасходы: {fmt_money(exp['total'])}")
        for cat, amt in exp["by_category"].items():
            emoji = CATEGORY_EMOJI.get(cat, "•")
            lines.append(f"  {emoji} {cat}: {fmt_money(amt)}")

    if rev["days"] and exp["entries"]:
        profit = rev["total"] - exp["total"]
        margin = fmt_pct(profit, rev["total"])
        lines.append(f"\nПрибыль: {fmt_money(profit)} (маржа {margin})")

    return "\n".join(lines)


async def build_week_report(
    chat_id: int,
    week_start: date,
    prev_week_start: date,
) -> str:
    week_end = week_start + timedelta(days=6)
    prev_end = prev_week_start + timedelta(days=6)

    rev = await revenue_summary(chat_id, week_start.isoformat(), week_end.isoformat())
    exp = await expense_summary(chat_id, week_start.isoformat(), week_end.isoformat())
    prev_rev = await revenue_summary(chat_id, prev_week_start.isoformat(), prev_end.isoformat())
    prev_exp = await expense_summary(chat_id, prev_week_start.isoformat(), prev_end.isoformat())

    lines = [
        f"📊 Финансовый отчёт",
        f"{week_start.strftime('%d.%m')} — {week_end.strftime('%d.%m.%Y')}",
    ]

    # Revenue block
    if rev["total"]:
        rev_vs = _vs_prev(rev["total"], prev_rev["total"])
        lines.append(f"\n💰 Выручка: {fmt_money(rev['total'])} {rev_vs}")

        if rev.get("cash") or rev.get("card"):
            lines.append(f"   Нал: {fmt_money(rev['cash'])}  Карта: {fmt_money(rev['card'])}")

        if rev["best_day"]:
            bd = rev["best_day"]
            wd = _weekday(bd["date"])
            lines.append(f"   Лучший день: {wd} {bd['date'][5:]} — {fmt_money(bd['total'])}")
        if rev["worst_day"] and rev["worst_day"]["date"] != rev["best_day"]["date"]:
            wd_row = rev["worst_day"]
            wd = _weekday(wd_row["date"])
            lines.append(f"   Слабый день: {wd} {wd_row['date'][5:]} — {fmt_money(wd_row['total'])}")

        # Revenue per day of week table (compact)
        if len(rev["days"]) > 1:
            lines.append("\n   По дням:")
            for r in rev["days"]:
                wd = _weekday(r["date"])
                lines.append(f"   {wd} {r['date'][5:]}: {fmt_money(r['total'])}")
    else:
        lines.append("\n💰 Выручка не внесена.")

    # Expenses block
    if exp["total"]:
        exp_vs = _vs_prev(exp["total"], prev_exp["total"])
        lines.append(f"\n💸 Расходы: {fmt_money(exp['total'])} {exp_vs}")
        for cat, amt in exp["by_category"].items():
            emoji = CATEGORY_EMOJI.get(cat, "•")
            pct = fmt_pct(amt, exp["total"])
            lines.append(f"   {emoji} {cat}: {fmt_money(amt)} ({pct})")
    else:
        lines.append("\n💸 Расходы не внесены.")

    # Profit
    if rev["total"] and exp["total"]:
        profit = rev["total"] - exp["total"]
        margin = fmt_pct(profit, rev["total"])
        prev_profit = prev_rev["total"] - prev_exp["total"]
        profit_vs = _vs_prev(profit, prev_profit)
        lines.append(f"\n✅ Прибыль: {fmt_money(profit)} (маржа {margin}) {profit_vs}")

    return "\n".join(lines)


def build_payroll_summary(
    payroll_rows: list[dict[str, Any]],
    period_start: str,
    period_end: str,
) -> str:
    if not payroll_rows:
        return "📋 Сотрудников нет. Добавь через /сотрудник_добавить Имя Бармен 15000"

    lines = [f"📋 Зарплатный расчёт", f"{period_start} — {period_end}", ""]
    total = 0
    for row in payroll_rows:
        shifts = row["shift_count"] or 0
        salary = row["total_salary"] or 0
        total += salary
        lines.append(
            f"👤 {row['name']} ({row['role'] or '—'})\n"
            f"   Смен: {shifts} × {fmt_money(row['rate_per_shift'])} = {fmt_money(salary)}"
        )
    lines.append(f"\nИтого к выплате: {fmt_money(total)}")
    lines.append("\nВыплатить: /выплатить Имя Сумма")
    return "\n".join(lines)


def build_staff_list(staff: list[dict[str, Any]]) -> str:
    if not staff:
        return "👥 Сотрудников нет.\nДобавить: /сотрудник_добавить Иван Бармен 15000"
    lines = ["👥 Сотрудники:"]
    for s in staff:
        lines.append(
            f"  {s['id']}. {s['name']} — {s['role'] or 'должность не указана'}"
            f", ставка {fmt_money(s['rate_per_shift'])}/смену"
        )
    lines.append("\nДобавить смену: /смена Имя")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vs_prev(current: int, prev: int) -> str:
    if not prev:
        return ""
    diff = current - prev
    pct = round(diff / prev * 100)
    arrow = "📈" if diff >= 0 else "📉"
    sign = "+" if diff >= 0 else ""
    return f"{arrow} {sign}{pct}% vs пред. нед."


def _weekday(date_str: str) -> str:
    try:
        d = date.fromisoformat(date_str)
        return WEEKDAY_RU[d.weekday()]
    except ValueError:
        return date_str
