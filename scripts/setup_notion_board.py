from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.notion_client import notion_client


async def main() -> None:
    data_source_id = await notion_client.create_tasks_data_source()
    print("Notion Tasks data source created.")
    print("Add this to .env:")
    print(f"NOTION_TASKS_DATA_SOURCE_ID={data_source_id}")


if __name__ == "__main__":
    asyncio.run(main())

