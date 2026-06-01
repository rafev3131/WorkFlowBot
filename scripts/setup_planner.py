#!/usr/bin/env python3
"""
🎯 Командный центр — Notion Planner Setup

Создаёт полноценный планировщик в Notion:
  1. Главная страница "🎯 Командный центр" с обложкой
  2. База данных "📁 Проекты" с цветовыми метками
  3. База данных "✅ Задачи" с 13 свойствами + формулы
  4. Страница-инструкция по настройке видов

Usage:
    python scripts/setup_planner.py

После запуска скрипт выведет IDs, которые нужно добавить в .env.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.notion_client import notion_client


# ---------------------------------------------------------------------------
# Color palette for projects
# ---------------------------------------------------------------------------
PROJECT_COLORS = {
    "🍺 Бар 127.1": "orange",
    "💰 Финансы": "green",
    "👤 Личное развитие": "purple",
    "🏠 Быт / Семья": "pink",
    "🔧 Разное": "gray",
}

# Unsplash cover image — dark, dramatic, inspiring
COVER_URL = "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=1920&q=80"

# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def heading1(text: str, color: str = "default") -> dict:
    return {
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "color": color,
        },
    }


def heading2(text: str, color: str = "default") -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "color": color,
        },
    }


def heading3(text: str, color: str = "default") -> dict:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "color": color,
        },
    }


def paragraph(text: str, bold: bool = False, color: str = "default") -> dict:
    rich = {"type": "text", "text": {"content": text}}
    if bold:
        rich["annotations"] = {"bold": True}
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [rich], "color": color},
    }


def callout(text: str, emoji: str = "💡", color: str = "gray_background") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": color,
        },
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def bulleted_item(text: str, bold_prefix: str = "") -> dict:
    rich_text = []
    if bold_prefix:
        rich_text.append({
            "type": "text",
            "text": {"content": bold_prefix},
            "annotations": {"bold": True},
        })
    rich_text.append({"type": "text", "text": {"content": text}})
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text},
    }


def numbered_item(text: str) -> dict:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def toggle(title: str, children: list[dict]) -> dict:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": title}}],
            "children": children,
        },
    }


# ---------------------------------------------------------------------------
# Database schema builders
# ---------------------------------------------------------------------------

def build_projects_schema() -> dict:
    return {
        "Название": {"title": {}},
        "Статус": {
            "select": {
                "options": [
                    {"name": "🟢 Активный", "color": "green"},
                    {"name": "⏸ Пауза", "color": "yellow"},
                    {"name": "✅ Завершён", "color": "blue"},
                    {"name": "❌ Архив", "color": "red"},
                ]
            }
        },
        "Цвет": {
            "select": {
                "options": [
                    {"name": "🍺 Бар", "color": "orange"},
                    {"name": "💰 Финансы", "color": "green"},
                    {"name": "👤 Развитие", "color": "purple"},
                    {"name": "🏠 Быт", "color": "pink"},
                    {"name": "🔧 Разное", "color": "gray"},
                ]
            }
        },
        "Описание": {"rich_text": {}},
        "Создан": {"created_time": {}},
    }


def build_tasks_schema(projects_db_id: str) -> dict:
    return {
        "Задача": {"title": {}},

        # Project relation
        "Проект": {
            "relation": {
                "database_id": projects_db_id,
                "single_property": {},
            }
        },

        # Status
        "Статус": {
            "select": {
                "options": [
                    {"name": "📥 Входящие", "color": "gray"},
                    {"name": "🔄 В работе", "color": "blue"},
                    {"name": "⏸ Ожидание", "color": "yellow"},
                    {"name": "✅ Готово", "color": "green"},
                    {"name": "❌ Отменено", "color": "red"},
                ]
            }
        },

        # Urgency / Importance (Eisenhower)
        "Срочность": {
            "select": {
                "options": [
                    {"name": "🔴 Срочно", "color": "red"},
                    {"name": "🟡 Несрочно", "color": "yellow"},
                ]
            }
        },
        "Важность": {
            "select": {
                "options": [
                    {"name": "⭐ Важно", "color": "orange"},
                    {"name": "○ Неважно", "color": "gray"},
                ]
            }
        },

        # Quadrant formula (Eisenhower matrix)
        "Квадрант": {
            "formula": {
                "expression": (
                    'if(and(prop("Срочность") == "🔴 Срочно", prop("Важность") == "⭐ Важно"), '
                    '"🔥 Q1 · Делай сейчас", '
                    'if(and(prop("Срочность") == "🟡 Несрочно", prop("Важность") == "⭐ Важно"), '
                    '"📅 Q2 · Запланируй", '
                    'if(and(prop("Срочность") == "🔴 Срочно", prop("Важность") == "○ Неважно"), '
                    '"⚡ Q3 · Делегируй", '
                    '"🗂 Q4 · Исключи")))'
                )
            }
        },

        # Deadline
        "Дедлайн": {"date": {}},

        # Overdue formula — nested ifs (Notion API doesn't allow 4+ args in and())
        "Просрочено": {
            "formula": {
                "expression": (
                    'if(not(empty(prop("Дедлайн"))), '
                    'if(dateBetween(prop("Дедлайн"), now(), "days") < 0, '
                    'if(prop("Статус") != "✅ Готово", '
                    'if(prop("Статус") != "❌ Отменено", "🚨 Просрочено", ""), '
                    '""), ""), "")'
                )
            }
        },

        # Energy / size
        "Энергия": {
            "select": {
                "options": [
                    {"name": "⚡ Быстро · до 15 мин", "color": "green"},
                    {"name": "🔆 Средне · до 1 ч", "color": "yellow"},
                    {"name": "🔋 Глубокая работа · 2+ ч", "color": "red"},
                ]
            }
        },

        # Tags
        "Теги": {
            "multi_select": {
                "options": [
                    {"name": "СЭС", "color": "red"},
                    {"name": "Документы", "color": "orange"},
                    {"name": "Переговоры", "color": "yellow"},
                    {"name": "Финансы", "color": "green"},
                    {"name": "Персонал", "color": "blue"},
                    {"name": "Личное", "color": "purple"},
                    {"name": "Дом", "color": "pink"},
                ]
            }
        },

        # Notes
        "Заметки": {"rich_text": {}},

        # Bot sync ID (for Telegram bot integration)
        "Bot ID": {"number": {}},

        # Metadata
        "Создано": {"created_time": {}},
    }


# ---------------------------------------------------------------------------
# Dashboard page content
# ---------------------------------------------------------------------------

def build_dashboard_blocks(projects_db_id: str, tasks_db_id: str) -> list[dict]:
    return [
        callout(
            "Открывай эту страницу каждое утро. Три вопроса: что сделать СЕЙЧАС, что ГОРИТ, что в РАБОТЕ.",
            emoji="☀️",
            color="yellow_background",
        ),
        divider(),

        heading2("🎯 КАК ЧИТАТЬ ЭТОТ ДАШБОРД", color="gray"),
        bulleted_item(" Начни с блока «🔥 Фокус сегодня» — там твои 3 приоритета.", bold_prefix="1. "),
        bulleted_item(" Проверь «🚨 Просрочено» — если есть, сначала туда.", bold_prefix="2. "),
        bulleted_item(" Посмотри «📅 Эта неделя» — планируй блоки времени.", bold_prefix="3. "),
        bulleted_item(" Канбан — для контроля общего потока задач.", bold_prefix="4. "),
        divider(),

        heading2("🔥 ФОКУС СЕГОДНЯ", color="red"),
        callout(
            f"Создай вид → Linked view of database → Задачи (ID: {tasks_db_id[:8]}…)\n"
            "Фильтр: Статус = «🔄 В работе»  ИЛИ  Квадрант = «🔥 Q1 · Делай сейчас»\n"
            "Сортировка: Дедлайн ↑ | Лимит: 5 задач | Вид: Gallery или List",
            emoji="📌",
            color="red_background",
        ),
        divider(),

        heading2("🚨 ПРОСРОЧЕНО", color="red"),
        callout(
            f"Создай вид → Linked view → Задачи (ID: {tasks_db_id[:8]}…)\n"
            "Фильтр: Просрочено = «🚨 Просрочено»\n"
            "Сортировка: Дедлайн ↑ | Вид: List",
            emoji="🚨",
            color="red_background",
        ),
        divider(),

        heading2("📅 ЭТА НЕДЕЛЯ", color="blue"),
        callout(
            f"Создай вид → Linked view → Задачи (ID: {tasks_db_id[:8]}…)\n"
            "Фильтр: Дедлайн = This week  AND  Статус ≠ «✅ Готово»\n"
            "Вид: Timeline (по Дедлайн) или Calendar",
            emoji="📅",
            color="blue_background",
        ),
        divider(),

        heading2("🗂 КАНБАН ПО ПРОЕКТАМ", color="orange"),
        callout(
            f"Создай вид → Linked view → Задачи (ID: {tasks_db_id[:8]}…)\n"
            "Фильтр: Статус ≠ «✅ Готово»  AND  Статус ≠ «❌ Отменено»\n"
            "Вид: Board | Группировка: по Проект | Карточки: Дедлайн + Квадрант",
            emoji="🗂",
            color="orange_background",
        ),
        divider(),

        heading2("📁 ПРОЕКТЫ", color="purple"),
        callout(
            f"Создай вид → Linked view → Проекты (ID: {projects_db_id[:8]}…)\n"
            "Фильтр: Статус = «🟢 Активный»\n"
            "Вид: Gallery | Карточки: показать Описание + Статус",
            emoji="📁",
            color="purple_background",
        ),
        divider(),

        toggle("⚙️ IDs баз данных (для бота и интеграций)", [
            paragraph(f"📁 Проекты DB:  {projects_db_id}"),
            paragraph(f"✅ Задачи DB:   {tasks_db_id}"),
            paragraph("Добавь в .env:"),
            paragraph(f"NOTION_TASKS_DATA_SOURCE_ID={tasks_db_id}"),
        ]),
    ]


def build_setup_guide_blocks(projects_db_id: str, tasks_db_id: str) -> list[dict]:
    """Detailed step-by-step guide for setting up views."""
    return [
        callout(
            "Следуй шагам по порядку. На всё уйдёт около 10 минут.",
            emoji="⏱",
            color="gray_background",
        ),
        divider(),

        heading2("ШАГ 1 · Вид «🔥 Фокус сегодня»"),
        numbered_item("Открой страницу «🎯 Командный центр»"),
        numbered_item("Кликни «+» в разделе «🔥 ФОКУС СЕГОДНЯ»"),
        numbered_item("Выбери «Linked view of database» → Задачи"),
        numbered_item("Вид: List → настрой фильтр: Статус = «🔄 В работе»"),
        numbered_item("Добавь второй фильтр (OR): Квадрант = «🔥 Q1 · Делай сейчас»"),
        numbered_item("Сортировка: Дедлайн → по возрастанию"),
        numbered_item("Свойства: показать Проект, Дедлайн, Энергия"),
        numbered_item("Лимит: Load more → ограничь до 5"),
        divider(),

        heading2("ШАГ 2 · Вид «🚨 Просрочено»"),
        numbered_item("Кликни «+» в разделе «🚨 ПРОСРОЧЕНО»"),
        numbered_item("Выбери «Linked view of database» → Задачи"),
        numbered_item("Вид: List"),
        numbered_item("Фильтр: Просрочено = «🚨 Просрочено»"),
        numbered_item("Свойства: Проект, Дедлайн, Квадрант"),
        divider(),

        heading2("ШАГ 3 · Вид «📅 Эта неделя»"),
        numbered_item("Кликни «+» в разделе «📅 ЭТА НЕДЕЛЯ»"),
        numbered_item("Выбери «Linked view» → Задачи"),
        numbered_item("Вид: Timeline → Date property: Дедлайн"),
        numbered_item("Фильтр: Дедлайн → is within → this week"),
        numbered_item("Добавь фильтр: Статус ≠ «✅ Готово»"),
        divider(),

        heading2("ШАГ 4 · Канбан"),
        numbered_item("Кликни «+» в разделе «🗂 КАНБАН»"),
        numbered_item("Выбери «Linked view» → Задачи"),
        numbered_item("Вид: Board"),
        numbered_item("Group by: Статус"),
        numbered_item("Фильтр: Статус ≠ «✅ Готово», Статус ≠ «❌ Отменено»"),
        numbered_item("На карточке: Проект, Дедлайн, Квадрант, Энергия"),
        divider(),

        heading2("ШАГ 5 · Проекты Gallery"),
        numbered_item("Кликни «+» в разделе «📁 ПРОЕКТЫ»"),
        numbered_item("Выбери «Linked view» → Проекты"),
        numbered_item("Вид: Gallery"),
        numbered_item("Фильтр: Статус = «🟢 Активный»"),
        numbered_item("Добавь обложки: открой каждый проект → Cover → выбери цвет/фото"),
        divider(),

        heading2("ШАГ 6 · Синхронизация с Telegram-ботом"),
        numbered_item("Скопируй ID Задачи DB:"),
        paragraph(f"    {tasks_db_id}", bold=False),
        numbered_item("Добавь в .env файл бота:"),
        paragraph(f"    NOTION_TASKS_DATA_SOURCE_ID={tasks_db_id}"),
        numbered_item("Перезапусти бота"),
        numbered_item("Напиши боту любую задачу → она появится в Notion"),

        divider(),
        callout(
            "Готово! Теперь каждая задача из бота автоматически попадает в Notion "
            "и синхронизируется при изменении статуса.",
            emoji="✅",
            color="green_background",
        ),
    ]


# ---------------------------------------------------------------------------
# Sample tasks for initial population
# ---------------------------------------------------------------------------

SAMPLE_TASKS = [
    {
        "title": "Проверить документы СЭС",
        "status": "📥 Входящие",
        "urgency": "🔴 Срочно",
        "importance": "⭐ Важно",
        "energy": "🔆 Средне · до 1 ч",
        "tags": ["СЭС", "Документы"],
        "project": "🍺 Бар 127.1",
    },
    {
        "title": "Внести P&L за прошлый месяц",
        "status": "📥 Входящие",
        "urgency": "🟡 Несрочно",
        "importance": "⭐ Важно",
        "energy": "🔋 Глубокая работа · 2+ ч",
        "tags": ["Финансы"],
        "project": "💰 Финансы",
    },
    {
        "title": "Провести собеседование с барменом",
        "status": "📥 Входящие",
        "urgency": "🟡 Несрочно",
        "importance": "⭐ Важно",
        "energy": "🔆 Средне · до 1 ч",
        "tags": ["Персонал"],
        "project": "🍺 Бар 127.1",
    },
    {
        "title": "Прочитать книгу по управлению — 30 стр",
        "status": "📥 Входящие",
        "urgency": "🟡 Несрочно",
        "importance": "⭐ Важно",
        "energy": "🔆 Средне · до 1 ч",
        "tags": ["Личное"],
        "project": "👤 Личное развитие",
    },
    {
        "title": "Ответить поставщику по счёту",
        "status": "🔄 В работе",
        "urgency": "🔴 Срочно",
        "importance": "⭐ Важно",
        "energy": "⚡ Быстро · до 15 мин",
        "tags": ["Переговоры"],
        "project": "🍺 Бар 127.1",
    },
]


# ---------------------------------------------------------------------------
# Main setup function
# ---------------------------------------------------------------------------

async def main() -> None:
    if not settings.notion_token:
        print("❌ NOTION_TOKEN не настроен. Добавь в .env и перезапусти.")
        sys.exit(1)
    if not settings.notion_parent_page_id:
        print("❌ NOTION_PARENT_PAGE_ID не настроен. Добавь в .env и перезапусти.")
        sys.exit(1)

    print("🚀 Создаю планировщик в Notion...\n")

    # ----- 1. Create main dashboard page -----
    print("📄 Создаю страницу «🎯 Командный центр»...")
    dashboard_page = await notion_client._request(
        "POST",
        "/v1/pages",
        json={
            "parent": {"type": "page_id", "page_id": settings.notion_parent_page_id},
            "icon": {"type": "emoji", "emoji": "🎯"},
            "cover": {"type": "external", "external": {"url": COVER_URL}},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": "🎯 Командный центр"}}]
                }
            },
            "children": [heading1("Командный центр", color="default")],
        },
    )
    dashboard_id = dashboard_page["id"]
    print(f"   ✓ ID: {dashboard_id}")

    # ----- 2. Create Projects database -----
    print("\n📁 Создаю базу данных «Проекты»...")
    projects_db = await notion_client._request(
        "POST",
        "/v1/databases",
        json={
            "parent": {"type": "page_id", "page_id": dashboard_id},
            "icon": {"type": "emoji", "emoji": "📁"},
            "title": [{"type": "text", "text": {"content": "📁 Проекты"}}],
            "properties": build_projects_schema(),
        },
    )
    projects_db_id = projects_db["id"]
    print(f"   ✓ ID: {projects_db_id}")

    # ----- 3. Populate Projects -----
    print("\n   Добавляю проекты...")
    project_ids: dict[str, str] = {}
    for name, color_tag in PROJECT_COLORS.items():
        # Map project name to color select option
        color_map = {
            "🍺 Бар 127.1": "🍺 Бар",
            "💰 Финансы": "💰 Финансы",
            "👤 Личное развитие": "👤 Развитие",
            "🏠 Быт / Семья": "🏠 Быт",
            "🔧 Разное": "🔧 Разное",
        }
        page = await notion_client._request(
            "POST",
            "/v1/pages",
            json={
                "parent": {"type": "database_id", "database_id": projects_db_id},
                "icon": {"type": "emoji", "emoji": name.split()[0]},
                "properties": {
                    "Название": {
                        "title": [{"type": "text", "text": {"content": name}}]
                    },
                    "Статус": {"select": {"name": "🟢 Активный"}},
                    "Цвет": {"select": {"name": color_map.get(name, "🔧 Разное")}},
                },
            },
        )
        project_ids[name] = page["id"]
        print(f"   ✓ {name}")

    # ----- 4. Create Tasks database -----
    print("\n✅ Создаю базу данных «Задачи»...")
    tasks_db = await notion_client._request(
        "POST",
        "/v1/databases",
        json={
            "parent": {"type": "page_id", "page_id": dashboard_id},
            "icon": {"type": "emoji", "emoji": "✅"},
            "title": [{"type": "text", "text": {"content": "✅ Задачи"}}],
            "properties": build_tasks_schema(projects_db_id),
        },
    )
    tasks_db_id = tasks_db["id"]
    print(f"   ✓ ID: {tasks_db_id}")

    # ----- 5. Populate sample tasks -----
    print("\n   Добавляю примеры задач...")
    for task in SAMPLE_TASKS:
        props: dict = {
            "Задача": {
                "title": [{"type": "text", "text": {"content": task["title"]}}]
            },
            "Статус": {"select": {"name": task["status"]}},
            "Срочность": {"select": {"name": task["urgency"]}},
            "Важность": {"select": {"name": task["importance"]}},
            "Энергия": {"select": {"name": task["energy"]}},
            "Теги": {
                "multi_select": [{"name": tag} for tag in task["tags"]]
            },
        }
        # Add project relation
        project_name = task.get("project")
        if project_name and project_name in project_ids:
            props["Проект"] = {"relation": [{"id": project_ids[project_name]}]}

        await notion_client._request(
            "POST",
            "/v1/pages",
            json={
                "parent": {"type": "database_id", "database_id": tasks_db_id},
                "properties": props,
            },
        )
        print(f"   ✓ {task['title']}")

    # ----- 6. Add dashboard content -----
    print("\n🎨 Добавляю контент дашборда...")
    await notion_client.append_page_blocks(
        page_id=dashboard_id,
        children=build_dashboard_blocks(projects_db_id, tasks_db_id),
    )
    print("   ✓ Блоки добавлены")

    # ----- 7. Create setup guide page -----
    print("\n📖 Создаю страницу-инструкцию...")
    guide_page = await notion_client._request(
        "POST",
        "/v1/pages",
        json={
            "parent": {"type": "page_id", "page_id": dashboard_id},
            "icon": {"type": "emoji", "emoji": "📖"},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": "📖 Инструкция по настройке видов"}}]
                }
            },
            "children": [heading1("Настройка видов — пошаговая инструкция")],
        },
    )
    await notion_client.append_page_blocks(
        page_id=guide_page["id"],
        children=build_setup_guide_blocks(projects_db_id, tasks_db_id),
    )
    print(f"   ✓ ID: {guide_page['id']}")

    # ----- Done — print summary -----
    print("\n" + "=" * 60)
    print("✅ ПЛАНИРОВЩИК СОЗДАН!")
    print("=" * 60)
    print(f"\n🎯 Дашборд:  https://notion.so/{dashboard_id.replace('-', '')}")
    print(f"📁 Проекты:  {projects_db_id}")
    print(f"✅ Задачи:   {tasks_db_id}")
    print(f"📖 Гид:      https://notion.so/{guide_page['id'].replace('-', '')}")

    print("\n📌 Добавь в .env файл бота:")
    print(f"   NOTION_TASKS_DATA_SOURCE_ID={tasks_db_id}")

    print("\n📌 Следующие шаги:")
    print("   1. Открой страницу 🎯 Командный центр в Notion")
    print("   2. Следуй инструкции 📖 — настрой 5 видов (займёт ~10 мин)")
    print("   3. Добавь NOTION_TASKS_DATA_SOURCE_ID в .env и перезапусти бота")
    print("   4. Напиши боту любую задачу — она появится в Notion автоматически")
    print()


if __name__ == "__main__":
    asyncio.run(main())
