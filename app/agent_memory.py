from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import os
from typing import Any
from uuid import uuid4

from app.ai_client import ai_client
from app.config import settings


_COLLECTION = None


async def remember(
    chat_id: int,
    text: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    memory_id: str | None = None,
) -> str | None:
    if not settings.agent_memory_enabled or not text.strip():
        return None

    try:
        collection = _get_collection()
        embedding = await ai_client.create_embedding(text)
        memory_id = memory_id or f"{chat_id}:{source}:{uuid4().hex}"
        clean_metadata = _normalize_metadata(
            {
                "chat_id": chat_id,
                "source": source,
                "created_at": datetime.utcnow().isoformat(timespec="seconds"),
                **(metadata or {}),
            }
        )

        await asyncio.to_thread(
            collection.upsert,
            ids=[memory_id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[clean_metadata],
        )
        return memory_id
    except Exception as error:
        print(f"Agent memory write skipped: {error}")
        return None


async def search_memory(chat_id: int, query: str, limit: int = 6) -> list[dict[str, Any]]:
    if not settings.agent_memory_enabled or not query.strip():
        return []

    try:
        collection = _get_collection()
        embedding = await ai_client.create_embedding(query)
        result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[embedding],
            n_results=limit,
            where={"chat_id": str(chat_id)},
            include=["documents", "metadatas", "distances"],
        )
        return _format_query_result(result)
    except Exception as error:
        print(f"Agent memory search skipped: {error}")
        return []


async def list_recent_memory(chat_id: int, limit: int = 8) -> list[dict[str, Any]]:
    if not settings.agent_memory_enabled:
        return []

    try:
        collection = _get_collection()
        result = await asyncio.to_thread(
            collection.get,
            where={"chat_id": str(chat_id)},
            limit=limit,
            include=["documents", "metadatas"],
        )
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        memories = []
        for index, document in enumerate(documents):
            memories.append(
                {
                    "text": document,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "distance": None,
                }
            )
        return memories
    except Exception as error:
        print(f"Agent memory list skipped: {error}")
        return []


def format_memory_context(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "Релевантной долговременной памяти пока нет."

    lines = []
    for memory in memories:
        metadata = memory.get("metadata") or {}
        source = metadata.get("source", "memory")
        created_at = metadata.get("created_at", "без даты")
        distance = memory.get("distance")
        score = "" if distance is None else f", distance={distance:.3f}"
        lines.append(f"- [{source}, {created_at}{score}] {memory['text']}")

    return "\n".join(lines)


def build_retrospective_memory_text(
    retro_date: str,
    response_text: str,
    summary: dict[str, Any],
) -> str:
    return "\n".join(
        [
            f"Ретроспектива за {retro_date}.",
            f"Ответ пользователя: {response_text}",
            f"Сделано: {_join_items(summary.get('done'))}",
            f"Не сделано: {_join_items(summary.get('not_done'))}",
            f"Помешало: {_join_items(summary.get('blockers'))}",
            f"Уроки по оценке времени: {_join_items(summary.get('time_estimation_notes'))}",
            f"Правила планирования: {_join_items(summary.get('planning_rules'))}",
            f"Предложения на завтра: {_join_items(summary.get('tomorrow_suggestions'))}",
        ]
    )


def build_planner_memory_text(
    task_id: int,
    title: str,
    plan: dict[str, Any],
) -> str:
    steps: list[str] = []
    for phase in plan.get("phases", []):
        if not isinstance(phase, dict):
            continue
        for step in phase.get("steps", []):
            if isinstance(step, str):
                steps.append(step)

    return "\n".join(
        [
            f"Planner Agent дал план для задачи #{task_id}: {title}.",
            f"Цель: {plan.get('objective', '')}",
            f"Первый шаг: {plan.get('next_step', '')}",
            f"Шаги: {_join_items(steps[:12])}",
            f"Риски: {_join_items(plan.get('risks'))}",
            f"Вопросы: {_join_items(plan.get('clarifying_questions'))}",
        ]
    )


def _get_collection():
    global _COLLECTION
    if _COLLECTION is not None:
        return _COLLECTION

    if settings.agent_memory_backend != "chromadb":
        raise RuntimeError(f"Unsupported memory backend: {settings.agent_memory_backend}")

    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    os.environ.setdefault("CHROMA_TELEMETRY", "False")
    logging.getLogger("chromadb.telemetry.product.posthog").disabled = True

    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as error:
        raise RuntimeError("ChromaDB не установлен. Запусти: pip install -r requirements.txt") from error

    client = chromadb.PersistentClient(
        path=settings.agent_memory_path,
        settings=Settings(anonymized_telemetry=False),
    )
    _COLLECTION = client.get_or_create_collection(
        name=settings.agent_memory_collection,
        metadata={"hnsw:space": "cosine"},
    )
    return _COLLECTION


def _format_query_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    memories = []
    for index, document in enumerate(documents):
        memories.append(
            {
                "text": document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
        )
    return memories


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    normalized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            normalized[key] = str(value) if key == "chat_id" else value
        elif value is None:
            normalized[key] = ""
        else:
            normalized[key] = json.dumps(value, ensure_ascii=False)
    return normalized


def _join_items(value: Any) -> str:
    if isinstance(value, list) and value:
        return "; ".join(str(item) for item in value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "нет данных"
