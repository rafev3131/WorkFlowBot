import json
import asyncio
from datetime import date
import hashlib
from typing import Any

import httpx

from app.config import settings


SYSTEM_INSTRUCTIONS = """
Ты классифицируешь входящие сообщения пользователя для персонального AI workflow.
Верни только валидный JSON без markdown.

Маршрутизация агентов:
- supervisor_agent: диспетчерский слой, который проверяет приоритет, сроки, проект и кому передать задачу дальше.
- planner_agent: задачи, проекты, цели, запуск чего-либо, подготовка, обучение, переезд, покупка, процесс из нескольких шагов.
- writer_agent: тексты, письма, посты, документы, формулировки.
- research_agent: поиск, сравнение, изучение темы, подбор вариантов.
- automation_agent: повторяемые действия, интеграции, скрипты, workflow.
- reminder_agent: напоминания с датой или временем.
- inbox_agent: заметки, идеи и сообщения без явного следующего действия.

Схема:
{
  "type": "task | idea | reminder | question | note | research | document | automation",
  "title": "короткое название",
  "summary": "краткое описание",
  "project": "название проекта или направления, если понятно из контекста; иначе пустая строка",
  "project_description": "краткое описание проекта, если project не пустой",
  "due_date": "дата выполнения в формате YYYY-MM-DD, если пользователь указал сегодня/завтра/дату; иначе пустая строка",
  "reminder_at": "дата и время напоминания в формате YYYY-MM-DD HH:MM, если пользователь явно просит напомнить; иначе пустая строка",
  "planning_period": "week, если задача на неделю без точной даты; иначе пустая строка",
  "estimated_minutes": 60,
  "priority": "low | medium | high",
  "assigned_agent": "inbox_agent | planner_agent | writer_agent | research_agent | automation_agent | reminder_agent",
  "can_be_automated": true,
  "needs_clarification": false,
  "next_action": "что сделать дальше"
}

Правила приоритета:
- high: важно, очень важно, экстренно, срочно, как можно быстрее, чем раньше тем лучше, критично, горит, безопасность, зарплата, СЭС, пожарная безопасность, охрана труда.
- medium: обычная рабочая задача без срочного дедлайна.
- low: идея или улучшение без срока и без влияния на людей, продукты, оборудование, финансы или документы.

Правила оценки времени:
- estimated_minutes — реалистичная оценка длительности в минутах.
- Если пользователь явно указал длительность, используй ее.
- Если длительность не указана, оцени сам по рабочему контексту.
- Для коротких звонков/сообщений обычно 15-30 минут.
- Для разборов, документов, отчетов, ревизий и коммерческих предложений обычно 60-180 минут.
- Если задача крупная и расплывчатая, ставь оценку первого рабочего блока, а не всего проекта целиком.
"""


PLANNER_INSTRUCTIONS = """
Ты Planner Agent для персонального AI workflow.
Твоя задача — превратить входящую задачу в практичный план, который можно начать выполнять сразу.

Правила:
- Пиши по-русски.
- Будь конкретным: шаги должны начинаться с глагола.
- Разбивай большую задачу на маленькие подзадачи, которые можно закрывать по одной.
- В каждом этапе делай 2-5 коротких шага. Не пиши абстрактные шаги вроде "разобраться" без конкретного действия.
- Опирайся на рабочий контекст и список задач, если они переданы.
- Не утверждай, что задач нет, если в контексте есть активные или недавние задачи.
- Если данных не хватает, сделай разумные предположения и отдельно перечисли вопросы.
- Не обещай автоматические действия вне Telegram-бота.
- Верни только валидный JSON без markdown.

Схема:
{
  "objective": "какой результат должен получить пользователь",
  "assumptions": ["предположение 1", "предположение 2"],
  "phases": [
    {
      "title": "название этапа",
      "steps": ["конкретный шаг 1", "конкретный шаг 2"]
    }
  ],
  "materials": ["что подготовить"],
  "risks": ["что может помешать"],
  "clarifying_questions": ["что стоит уточнить"],
  "next_step": "один самый первый конкретный шаг"
}
"""


MORNING_BRIEF_INSTRUCTIONS = """
Ты Operations Supervisor для управляющего бара 127.1 в Алматы.
Составь короткий утренний бриф на русском языке.

Правила:
- Начни с "Доброе утро."
- Скажи, что сегодня важнее всего.
- Дай правильную очередность действий.
- Укажи 1-2 рекомендуемых временных блока, если это уместно.
- Не выдумывай факты, суммы, людей или события.
- Если задач мало или нет, скажи это спокойно и предложи добавить задачи.
- Пиши компактно, чтобы сообщение удобно читалось в Telegram.
"""


RETROSPECTIVE_SUMMARY_INSTRUCTIONS = """
Ты анализируешь вечернюю ретроспективу управляющего бара 127.1.
Верни только валидный JSON без markdown.

Задача:
- выделить, что было сделано;
- что осталось;
- что пошло не так;
- где оценка времени была неверной;
- какие правила учесть в будущих планах.

Схема:
{
  "done": ["что сделано"],
  "not_done": ["что не сделано"],
  "blockers": ["что помешало"],
  "time_estimation_notes": ["что учесть в оценках времени"],
  "planning_rules": ["короткие правила для будущего планирования"],
  "tomorrow_suggestions": ["что стоит поставить в фокус завтра"]
}
"""


class AIClient:
    async def analyze_message(self, text: str) -> dict[str, Any]:
        if not settings.openai_api_key:
            return {
                "type": "note",
                "title": "AI key is not configured",
                "summary": text,
                "priority": "medium",
                "assigned_agent": "inbox_agent",
                "due_date": "",
                "estimated_minutes": 30,
                "can_be_automated": False,
                "needs_clarification": True,
                "next_action": "Добавить OPENAI_API_KEY в .env",
            }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "instructions": SYSTEM_INSTRUCTIONS,
                    "input": (
                        f"Текущая дата: {date.today().isoformat()}\n\n"
                        f"Сообщение пользователя:\n{text}"
                    ),
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error

        data = response.json()
        output_text = data.get("output_text", "")

        if not output_text:
            output_text = _extract_output_text(data)

        return json.loads(output_text)

    async def run_planner(
        self,
        text: str,
        analysis: dict[str, Any],
        workflow_context: str = "",
        task_context: str = "",
        project_context: str = "",
        retrospective_context: str = "",
        memory_context: str = "",
    ) -> dict[str, Any]:
        if not settings.openai_api_key:
            return {
                "objective": "Запустить Planner Agent",
                "assumptions": [],
                "phases": [
                    {
                        "title": "Настройка",
                        "steps": ["Добавить OPENAI_API_KEY в .env"],
                    }
                ],
                "materials": [".env файл", "OpenAI API key"],
                "risks": ["Без ключа Planner Agent не сможет обращаться к OpenAI"],
                "clarifying_questions": [],
                "next_step": "Добавить OPENAI_API_KEY в .env",
            }

        prompt = f"""
Задача пользователя:
{text}

Разбор задачи:
{json.dumps(analysis, ensure_ascii=False)}

Контекст рабочего процесса:
{workflow_context or "Не задан."}

Контекст задач из базы:
{task_context or "Активных или недавних задач пока нет."}

Контекст проектов:
{project_context or "Проекты пока не заведены."}

Последние ретроспективы и уроки по времени:
{retrospective_context or "Пока нет ретроспектив."}

Долговременная память агента:
{memory_context or "Релевантных воспоминаний пока нет."}

Составь план по указанной JSON-схеме.
"""

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "instructions": PLANNER_INSTRUCTIONS,
                    "input": prompt,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error

        data = response.json()
        output_text = data.get("output_text", "")
        if not output_text:
            output_text = _extract_output_text(data)

        try:
            return json.loads(output_text)
        except json.JSONDecodeError:
            return {
                "objective": analysis.get("title", "Выполнить задачу"),
                "assumptions": [],
                "phases": [],
                "materials": [],
                "risks": ["Planner Agent вернул неструктурированный ответ"],
                "clarifying_questions": [],
                "next_step": analysis.get("next_action", "Уточнить задачу"),
                "raw_plan": output_text.strip(),
            }

    async def build_morning_brief(
        self,
        today: str,
        task_context: str,
        subtask_context: str,
        workflow_context: str,
        retrospective_context: str = "",
        memory_context: str = "",
    ) -> str:
        if not settings.openai_api_key:
            return (
                "Доброе утро.\n\n"
                "OpenAI API key не настроен, поэтому я не могу собрать умный бриф. "
                "Проверь /today и /week вручную."
            )

        prompt = f"""
Дата: {today}

Рабочий контекст:
{workflow_context or "Не задан."}

Фокусные задачи:
{task_context or "Нет задач."}

Открытые подзадачи:
{subtask_context or "Нет открытых подзадач."}

Последние ретроспективы:
{retrospective_context or "Пока нет ретроспектив."}

Долговременная память агента:
{memory_context or "Релевантных воспоминаний пока нет."}
"""

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "instructions": MORNING_BRIEF_INSTRUCTIONS,
                    "input": prompt,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error

        data = response.json()
        output_text = data.get("output_text", "")
        if not output_text:
            output_text = _extract_output_text(data)

        return output_text.strip()

    async def create_embedding(self, text: str) -> list[float]:
        if not settings.openai_api_key:
            return _fallback_embedding(text)

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_embedding_model,
                    "input": text,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error

        data = response.json()
        return data["data"][0]["embedding"]

    async def summarize_retrospective(
        self,
        retro_date: str,
        response_text: str,
        task_context: str,
    ) -> dict[str, Any]:
        if not settings.openai_api_key:
            return {
                "done": [],
                "not_done": [],
                "blockers": [],
                "time_estimation_notes": ["OpenAI API key не настроен, ретро сохранено без AI-разбора."],
                "planning_rules": [],
                "tomorrow_suggestions": [],
            }

        prompt = f"""
Дата ретроспективы: {retro_date}

Фокусные задачи дня:
{task_context or "Задачи не переданы."}

Ответ пользователя:
{response_text}
"""

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "instructions": RETROSPECTIVE_SUMMARY_INSTRUCTIONS,
                    "input": prompt,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error

        data = response.json()
        output_text = data.get("output_text", "")
        if not output_text:
            output_text = _extract_output_text(data)

        try:
            return json.loads(output_text)
        except json.JSONDecodeError:
            return {
                "done": [],
                "not_done": [],
                "blockers": ["AI вернул неструктурированную ретроспективу."],
                "time_estimation_notes": [],
                "planning_rules": [],
                "tomorrow_suggestions": [],
                "raw_summary": output_text.strip(),
            }

    async def transcribe_audio(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        last_error = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={
                            "Authorization": f"Bearer {settings.openai_api_key}",
                        },
                        data={
                            "model": settings.openai_audio_model,
                            "language": "ru",
                        },
                        files={
                            "file": (filename, audio_bytes, "audio/ogg"),
                        },
                    )
                    response.raise_for_status()

                data = response.json()
                return data.get("text", "").strip()
            except httpx.HTTPStatusError as error:
                raise RuntimeError(_format_openai_error(error.response)) from error
            except httpx.RequestError as error:
                last_error = error
                await asyncio.sleep(1)

        raise RuntimeError(f"Не смог отправить аудио в OpenAI: {last_error}")


def _extract_output_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts)


ai_client = AIClient()


def _fallback_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    words = text.lower().split()
    for word in words:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0

    norm = sum(value * value for value in vector) ** 0.5
    if not norm:
        return vector
    return [value / norm for value in vector]


def _format_openai_error(response: httpx.Response) -> str:
    try:
        error_body = response.json()
    except ValueError:
        error_body = {}

    message = error_body.get("error", {}).get("message")

    if response.status_code == 401:
        return "OpenAI API key не принят. Проверь OPENAI_API_KEY в .env."

    if response.status_code == 429:
        return (
            "OpenAI вернул 429: лимит или billing. Проверь баланс и лимиты в OpenAI Platform. "
            "Для классификации уже выбрана более легкая модель gpt-4.1-mini."
        )

    if response.status_code == 400:
        if message:
            return f"OpenAI не принял запрос: {message}"
        return (
            "OpenAI не принял запрос. Проверь OPENAI_MODEL "
            f"({settings.openai_model}) и OPENAI_AUDIO_MODEL ({settings.openai_audio_model})."
        )

    if message:
        return f"OpenAI API вернул ошибку {response.status_code}: {message}"

    return f"OpenAI API вернул ошибку {response.status_code}."
