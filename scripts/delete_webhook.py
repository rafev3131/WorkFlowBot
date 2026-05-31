from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("TELEGRAM_BOT_TOKEN is missing in .env")
        sys.exit(1)

    if token == "put_your_telegram_bot_token_here":
        print("TELEGRAM_BOT_TOKEN still contains the placeholder value.")
        print("Open .env and replace it with the real token from BotFather.")
        sys.exit(1)

    response = httpx.post(
        f"https://api.telegram.org/bot{token}/deleteWebhook",
        timeout=15,
    )
    response.raise_for_status()

    print("Webhook deleted")
    print(response.json())


if __name__ == "__main__":
    main()
