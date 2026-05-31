from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.agent_memory import build_retrospective_memory_text, remember
from app.database import DATABASE_PATH

import aiosqlite


async def main() -> None:
    indexed_count = 0
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        task_rows = await (
            await db.execute(
                """
                SELECT id, chat_id, title, priority, result, analysis_json, created_at
                FROM tasks
                WHERE assigned_agent = 'planner_agent' AND result != ''
                ORDER BY id ASC
                """
            )
        ).fetchall()
        retro_rows = await (
            await db.execute(
                """
                SELECT id, chat_id, retro_date, response_text, summary_json
                FROM daily_retrospectives
                WHERE status = 'answered'
                ORDER BY id ASC
                """
            )
        ).fetchall()

    for row in task_rows:
        await remember(
            chat_id=row["chat_id"],
            text="\n".join(
                [
                    f"Сохраненный совет Planner Agent по задаче #{row['id']}: {row['title']}.",
                    f"Приоритет: {row['priority']}.",
                    f"План/ответ: {row['result']}",
                ]
            ),
            source="planner_advice",
            metadata={
                "task_id": row["id"],
                "task_title": row["title"],
                "priority": row["priority"],
                "created_at": row["created_at"],
            },
            memory_id=f"{row['chat_id']}:planner_advice:task:{row['id']}",
        )
        indexed_count += 1

    for row in retro_rows:
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except json.JSONDecodeError:
            summary = {}

        await remember(
            chat_id=row["chat_id"],
            text=build_retrospective_memory_text(
                retro_date=row["retro_date"],
                response_text=row["response_text"],
                summary=summary,
            ),
            source="retrospective",
            metadata={
                "retro_id": row["id"],
                "retro_date": row["retro_date"],
            },
            memory_id=f"{row['chat_id']}:retrospective:{row['id']}",
        )
        indexed_count += 1

    print(f"Indexed {indexed_count} memory records")


if __name__ == "__main__":
    asyncio.run(main())
