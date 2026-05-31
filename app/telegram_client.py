import httpx
import asyncio
from typing import Optional

from app.config import settings


class TelegramClient:
    def __init__(self) -> None:
        self.base_url = None
        if settings.telegram_bot_token:
            self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> None:
        if self.base_url is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.base_url}/sendMessage",
                json=payload,
            )
            response.raise_for_status()

    async def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        if self.base_url is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.base_url}/answerCallbackQuery",
                json={
                    "callback_query_id": callback_query_id,
                    "text": text,
                },
            )
            response.raise_for_status()

    async def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        if self.base_url is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.base_url}/setMyCommands",
                json={"commands": commands},
            )
            response.raise_for_status()

    async def get_file_path(self, file_id: str) -> str:
        if self.base_url is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        last_error = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(
                        f"{self.base_url}/getFile",
                        json={"file_id": file_id},
                    )
                    response.raise_for_status()
                data = response.json()
                return data["result"]["file_path"]
            except httpx.RequestError as error:
                last_error = error
                await asyncio.sleep(1)

        raise RuntimeError(f"Не смог получить файл из Telegram: {last_error}")

    async def download_file(self, file_path: str) -> bytes:
        if settings.telegram_bot_token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        file_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
        last_error = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(file_url)
                    response.raise_for_status()
                    return response.content
            except httpx.RequestError as error:
                last_error = error
                await asyncio.sleep(1)

        raise RuntimeError(f"Не смог скачать голосовой файл из Telegram: {last_error}")


telegram_client = TelegramClient()
