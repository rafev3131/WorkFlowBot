from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Telegram message length limit
_MAX_MESSAGE_LENGTH = 4096


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
    ) -> bool:
        """Send a message. Returns True on success, False on failure (never raises)."""
        if self.base_url is None:
            logger.error("send_message: TELEGRAM_BOT_TOKEN is not configured")
            return False

        # Telegram hard limit — truncate gracefully
        if len(text) > _MAX_MESSAGE_LENGTH:
            text = text[: _MAX_MESSAGE_LENGTH - 3] + "…"

        payload: dict = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                )
                if response.status_code == 400:
                    # Bad request — likely invalid chat_id or blocked bot
                    logger.warning(
                        "send_message 400 for chat_id=%s: %s",
                        chat_id,
                        response.json().get("description", ""),
                    )
                    return False
                response.raise_for_status()
                return True
        except httpx.HTTPStatusError as exc:
            logger.error("send_message HTTP error for chat_id=%s: %s", chat_id, exc)
            return False
        except httpx.RequestError as exc:
            logger.error("send_message network error for chat_id=%s: %s", chat_id, exc)
            return False

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> bool:
        if self.base_url is None:
            return False
        if len(text) > _MAX_MESSAGE_LENGTH:
            text = text[: _MAX_MESSAGE_LENGTH - 3] + "…"
        payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/editMessageText",
                    json=payload,
                )
                if response.status_code == 400:
                    logger.warning(
                        "edit_message_text 400 for chat_id=%s msg=%s: %s",
                        chat_id,
                        message_id,
                        response.json().get("description", ""),
                    )
                    return False
                response.raise_for_status()
                return True
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.error("edit_message_text error: %s", exc)
            return False

    async def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        if self.base_url is None:
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id, "text": text},
                )
                response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("answer_callback_query failed: %s", exc)

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

        last_error: Exception | None = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(
                        f"{self.base_url}/getFile",
                        json={"file_id": file_id},
                    )
                    response.raise_for_status()
                return response.json()["result"]["file_path"]
            except httpx.RequestError as error:
                last_error = error
                await asyncio.sleep(1)

        raise RuntimeError(f"Не смог получить файл из Telegram: {last_error}")

    async def download_file(self, file_path: str) -> bytes:
        if settings.telegram_bot_token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        file_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
        last_error: Exception | None = None
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
