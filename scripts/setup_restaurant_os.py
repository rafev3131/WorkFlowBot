from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.notion_client import notion_client


SECTIONS = [
    (
        "Сегодня / Фокус",
        [
            "Утренний фокус: что горит, что влияет на людей, продукты и оборудование.",
            "Открывай Telegram-команду /today, чтобы синхронизировать фактический фокус.",
            "Здесь можно вручную держать короткие заметки дня.",
        ],
    ),
    (
        "Документация и безопасность",
        [
            "СЭС, трудовые документы, пожарная безопасность, охрана труда.",
            "Главный текущий приоритет: найти пробелы и закрывать их по порядку.",
            "Связанная задача в боте: Проверить документацию ресторана.",
        ],
    ),
    (
        "Финансы / Ревизии",
        [
            "P&L, баланс, инвентаризации, ревизии и разбор расхождений.",
            "Используй для подготовки закрытия месяца и контроля ревизий.",
        ],
    ),
    (
        "Персонал",
        [
            "Зарплаты, графики, коммуникация с командой, кадровые документы.",
            "Высокий приоритет: все, что влияет на выплаты и безопасность людей.",
        ],
    ),
    (
        "Оборудование",
        [
            "Ремонт, обслуживание и критичные поломки.",
            "Текущий фокус: вакууматор.",
        ],
    ),
    (
        "Кладовка / Склад",
        [
            "Договор новой кладовки, переезд, складские процессы.",
            "Отдельно фиксируй, что уже перевезено и что осталось.",
        ],
    ),
    (
        "Ивенты / Коммерческие предложения",
        [
            "Мероприятия, митапы, спикеры, коммерческие предложения для компаний.",
            "Здесь удобно собирать лиды, идеи и статусы переговоров.",
        ],
    ),
]


async def main() -> None:
    if not settings.notion_parent_page_id:
        raise RuntimeError("Добавь NOTION_PARENT_PAGE_ID в .env.")

    section_pages = []
    for title, bullets in SECTIONS:
        page_id = await notion_client.create_child_page(
            title=f"127.1 · {title}",
            children=[
                _paragraph("Рабочий раздел Restaurant OS для бара 127.1."),
                _heading("Как использовать"),
                *[_bulleted(item) for item in bullets],
            ],
        )
        section_pages.append((title, page_id))

    await notion_client.append_page_blocks(
        page_id=settings.notion_parent_page_id,
        children=[
            _heading("127.1 Restaurant OS"),
            _paragraph(
                "Операционная панель бара 127.1: задачи, документы, финансы, ревизии, персонал, оборудование, склад и ивенты."
            ),
            _callout(
                "Правило приоритета: человек -> продукты -> оборудование. "
                "Telegram остается быстрым входом, Notion — визуальная панель управления."
            ),
            _heading("Быстрый доступ"),
            *[_page_link(title=f"127.1 · {title}", page_id=page_id) for title, page_id in section_pages],
            _heading("Как работать"),
            _bulleted("Утром смотри /today в Telegram и сверяйся с разделом Сегодня / Фокус."),
            _bulleted("Большие задачи дроби через /plan, затем закрывай маленькие шаги."),
            _bulleted("После изменений запускай /sync_notion или /sync_from_notion."),
            _bulleted("В Notion не удаляй задачи без необходимости: лучше ставить Status = Done или Cancelled."),
        ],
    )

    print("Restaurant OS dashboard created.")
    print("Created sections:")
    for title, page_id in section_pages:
        print(f"- {title}: {page_id}")


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _heading(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _bulleted(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _callout(text: str) -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _page_link(title: str, page_id: str) -> dict:
    return {
        "object": "block",
        "type": "link_to_page",
        "link_to_page": {
            "type": "page_id",
            "page_id": page_id,
        },
    }


if __name__ == "__main__":
    asyncio.run(main())
