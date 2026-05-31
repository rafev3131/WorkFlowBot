from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_audio_model: str = "whisper-1"
    app_url: Optional[str] = None
    notion_token: Optional[str] = None
    notion_parent_page_id: Optional[str] = None
    notion_tasks_data_source_id: Optional[str] = None
    notion_version: str = "2026-03-11"
    morning_brief_enabled: bool = True
    morning_brief_timezone: str = "Asia/Almaty"
    morning_brief_hour: int = 10
    morning_brief_minute: int = 0
    evening_retro_enabled: bool = True
    evening_retro_timezone: str = "Asia/Almaty"
    evening_retro_hour: int = 21
    evening_retro_minute: int = 0
    agent_memory_enabled: bool = True
    agent_memory_backend: str = "chromadb"
    agent_memory_path: str = ".chroma"
    agent_memory_collection: str = "agent_memory"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
