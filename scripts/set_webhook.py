from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app_url = os.getenv("APP_URL")

    if not token:
        print("TELEGRAM_BOT_TOKEN is missing in .env")
        sys.exit(1)

    if token == "put_your_telegram_bot_token_here":
        print("TELEGRAM_BOT_TOKEN still contains the placeholder value.")
        print("Open .env and replace it with the real token from BotFather.")
        sys.exit(1)

    if not app_url:
        print("APP_URL is missing in .env")
        print("Example: APP_URL=https://example.ngrok-free.app")
        sys.exit(1)

    webhook_url = f"{app_url.rstrip('/')}/telegram/webhook"
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={"url": webhook_url},
        timeout=15,
    )
    response.raise_for_status()

    print(f"Webhook set to: {webhook_url}")
    print(response.json())


if __name__ == "__main__":
    main()
