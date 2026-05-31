from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Request
import traceback

from app.agent_memory import (
    build_planner_memory_text,
    format_memory_context,
    list_recent_memory,
    remember,
    search_memory,
)
from app.briefing import send_morning_brief
from app.database import (
    all_subtasks_done,
    get_project,
    get_subtask,
    get_task,
    init_database,
    list_active_tasks,
    list_next_task_candidates,
    list_planner_context_tasks,
    list_project_context,
    list_project_tasks,
    list_projects,
    list_recent_retrospectives,
    list_recent_tasks,
    list_subtasks,
    list_tasks_for_notion_sync,
    list_today_focus_tasks,
    list_tasks_by_planning_period,
    list_tasks_by_due_date,
    mark_subtask_done,
    mark_task_cancelled,
    mark_task_done,
    mark_task_done_with_time,
    replace_subtasks,
    save_task,
    update_task_priority,
    update_task_reminder,
    update_task_title,
    update_task_notion_page_id,
    update_task_plan,
    update_task_due_date,
    update_task_status,
)
from app.ai_client import ai_client
from app.message_formatter import format_analysis, format_planner_result
from app.notion_client import notion_client
from app.retrospective import (
    handle_retrospective_callback,
    handle_retrospective_response,
    send_evening_retro,
)
from app.scheduler import (
    schedule_morning_brief_snooze,
    schedule_pending_task_reminders,
    schedule_task_reminder,
    shutdown_scheduler,
    start_scheduler,
)
from app.supervisor import supervise_analysis
from app.task_intents import find_matching_task, parse_task_intent
from app.telegram_client import telegram_client
from app.workflow_context import (
    format_project_context,
    format_retrospective_context,
    format_task_context,
    load_workflow_context,
)

app = FastAPI(title="Personal AI Workflow Hub")


@app.on_event("startup")
async def startup() -> None:
    await init_database()
    start_scheduler()
    await schedule_pending_task_reminders()


@app.on_event("shutdown")
async def shutdown() -> None:
    shutdown_scheduler()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    update = await request.json()
    callback_query = update.get("callback_query")
    if callback_query:
        await _handle_callback_query(callback_query)
        return {"ok": True}

    message = update.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")
    voice = message.get("voice")

    if chat_id is None:
        return {"ok": True}

    if text in {"/health", "/статус"}:
        await telegram_client.send_message(
            chat_id=chat_id,
            text="Backend работает. Память задач включена: SQLite workflow.db.",
        )
        return {"ok": True}

    if text in {"/sync_notion", "/ноушен"}:
        reply = await _handle_notion_sync_command(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/sync_from_notion", "/из_ноушен"}:
        reply = await _handle_notion_pull_command(chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/brief", "/бриф"}:
        await send_morning_brief(chat_id=chat_id)
        return {"ok": True}

    if text in {"/retro", "/ретро"}:
        await send_evening_retro(chat_id=chat_id)
        return {"ok": True}

    if text in {"/memory", "/память"}:
        memories = await list_recent_memory(chat_id=chat_id, limit=8)
        reply = _build_memory_reply(memories)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text in {"/tasks", "/задачи"}:
        tasks = await list_recent_tasks(chat_id=chat_id)
        if not tasks:
            reply = "Пока нет сохраненных задач. Отправь новую задачу обычным сообщением, потом снова напиши /задачи."
            reply_markup = None
        else:
            lines = ["Последние задачи:"]
            for task in tasks:
                project = f", {task['project_name']}" if task.get("project_name") else ""
                due = f", {task['due_date']}" if task.get("due_date") else ""
                time_info = _format_task_time(task)
                lines.append(
                    f"{task['id']}. {task['title']} "
                    f"({task['status']}, {task['assigned_agent']}{project}{due}{time_info})"
                )
            reply = "\n".join(lines)
            reply_markup = _build_task_actions_keyboard(tasks)

        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/today", "/сегодня"}:
        reply, reply_markup = await _build_today_focus_reply(chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/tomorrow", "/завтра"}:
        reply, reply_markup = await _build_day_tasks_reply(
            chat_id=chat_id,
            target_date=date.today() + timedelta(days=1),
            empty_text="На завтра задач нет. Можешь добавить задачу обычным сообщением, например: `Завтра созвониться с подрядчиком`.",
            title="Задачи на завтра:",
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/week", "/неделя"}:
        reply, reply_markup = await _build_week_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/active", "/активные"}:
        reply, reply_markup = await _build_active_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/next", "/дальше"}:
        reply, reply_markup = await _build_next_task_reply(chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text in {"/projects", "/проекты"}:
        projects = await list_projects(chat_id=chat_id)
        if not projects:
            reply = "Пока нет проектов. Отправь задачу с понятным направлением, и бот заведет проект автоматически."
        else:
            lines = ["Проекты:"]
            for project in projects:
                lines.append(
                    f"{project['id']}. {project['name']} "
                    f"(активных: {project['active_task_count'] or 0}, всего: {project['task_count'] or 0})"
                )
            lines.extend(["", "Открыть проект: /project 1"])
            reply = "\n".join(lines)

        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/project") or text.startswith("/проект")):
        reply, reply_markup = await _handle_project_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text and (text.startswith("/done") or text.startswith("/готово")):
        reply = await _handle_done_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/delete") or text.startswith("/удалить")):
        reply = await _handle_delete_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/cancel") or text.startswith("/отмена")):
        reply = await _handle_status_command(
            text=text,
            chat_id=chat_id,
            action=mark_task_cancelled,
            success_text="Задача отменена.",
            usage_text="Напиши так: /отмена 1",
        )
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/rename") or text.startswith("/переименовать")):
        reply = await _handle_rename_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/priority") or text.startswith("/приоритет")):
        reply = await _handle_priority_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/remind") or text.startswith("/напомни")):
        reply = await _handle_remind_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/deadline") or text.startswith("/срок")):
        reply = await _handle_deadline_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/subtasks") or text.startswith("/подзадачи")):
        reply, reply_markup = await _handle_subtasks_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text and (text.startswith("/subdone") or text.startswith("/подготово")):
        reply = await _handle_subtask_done_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and (text.startswith("/plan") or text.startswith("/план")):
        reply = await _handle_plan_command(text=text, chat_id=chat_id)
        await telegram_client.send_message(chat_id=chat_id, text=reply)
        return {"ok": True}

    if text and _is_tomorrow_overview_request(text):
        reply, reply_markup = await _build_day_tasks_reply(
            chat_id=chat_id,
            target_date=date.today() + timedelta(days=1),
            empty_text="На завтра задач нет. Хочешь добавить задачу? Просто напиши ее сообщением, например: `Завтра разобрать входящие`.",
            title="Задачи на завтра:",
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text and _is_week_overview_request(text):
        reply, reply_markup = await _build_week_tasks_reply(chat_id=chat_id)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return {"ok": True}

    if text:
        retro_reply = await handle_retrospective_response(chat_id=chat_id, text=text)
        if retro_reply:
            await telegram_client.send_message(chat_id=chat_id, text=retro_reply)
            return {"ok": True}

        intent_reply = await _try_handle_task_intent(chat_id=chat_id, text=text)
        if intent_reply:
            await telegram_client.send_message(chat_id=chat_id, text=intent_reply)
            return {"ok": True}

    if voice:
        try:
            file_path = await telegram_client.get_file_path(voice["file_id"])
            audio_bytes = await telegram_client.download_file(file_path)
            transcribed_text = await ai_client.transcribe_audio(
                audio_bytes=audio_bytes,
                filename=file_path.split("/")[-1],
            )
            if not transcribed_text:
                reply = "Я получил голосовое, но не смог распознать текст."
            else:
                reply = await _process_text_message(
                    chat_id=chat_id,
                    text=transcribed_text,
                    prefix=f"Распознал голосовое:\n{transcribed_text}\n\n",
                )
        except Exception as error:
            traceback.print_exc()
            reply = f"Получил голосовое, но обработка не сработала: {error}"
    elif text:
        try:
            reply = await _process_text_message(chat_id=chat_id, text=text)
        except Exception as error:
            traceback.print_exc()
            reply = f"Принял текст, но обработка не сработала: {error}"
    else:
        reply = "Пока я умею принимать текст и голосовые сообщения."

    await telegram_client.send_message(chat_id=chat_id, text=reply)
    return {"ok": True}


async def _process_text_message(chat_id: int, text: str, prefix: str = "") -> str:
    analysis = await ai_client.analyze_message(text)
    analysis = supervise_analysis(text=text, analysis=analysis)
    _normalize_analysis_reminder(analysis)
    plan = None
    if analysis.get("assigned_agent") == "planner_agent":
        planner_tasks = await list_planner_context_tasks(chat_id=chat_id)
        projects = await list_project_context(chat_id=chat_id)
        retrospectives = await list_recent_retrospectives(chat_id=chat_id, limit=5)
        memories = await search_memory(chat_id=chat_id, query=text, limit=6)
        plan = await ai_client.run_planner(
            text=text,
            analysis=analysis,
            workflow_context=load_workflow_context(),
            task_context=format_task_context(planner_tasks),
            project_context=format_project_context(projects),
            retrospective_context=format_retrospective_context(retrospectives),
            memory_context=format_memory_context(memories),
        )
        result = format_planner_result(analysis=analysis, plan=plan)
        reply = result
    else:
        result = analysis.get("summary", "")
        reply = format_analysis(analysis)

    task_id = await save_task(
        chat_id=chat_id,
        user_text=text,
        analysis=analysis,
        result=result,
    )
    if plan:
        await replace_subtasks(
            chat_id=chat_id,
            task_id=task_id,
            titles=_extract_subtask_titles(plan),
        )
        await remember(
            chat_id=chat_id,
            text=build_planner_memory_text(
                task_id=task_id,
                title=analysis.get("title", "Без названия"),
                plan=plan,
            ),
            source="planner_advice",
            metadata={
                "task_id": task_id,
                "task_title": analysis.get("title", ""),
                "priority": analysis.get("priority", ""),
                "project": analysis.get("project", ""),
            },
        )
    reminder_note = await _try_schedule_task_reminder(
        chat_id=chat_id,
        task_id=task_id,
        reminder_at=analysis.get("reminder_at"),
    )
    notion_note = await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"{prefix}Задача #{task_id} сохранена.{reminder_note}{notion_note}\n\n{reply}"


def _normalize_analysis_reminder(analysis: dict) -> None:
    reminder_at = _normalize_reminder_at(str(analysis.get("reminder_at") or ""))
    if reminder_at:
        analysis["reminder_at"] = reminder_at
        return

    if analysis.get("type") == "reminder" or analysis.get("assigned_agent") == "reminder_agent":
        due_date = analysis.get("due_date")
        if due_date:
            analysis["reminder_at"] = f"{due_date} 10:00"


def _normalize_reminder_at(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


async def _try_schedule_task_reminder(chat_id: int, task_id: int, reminder_at: str | None) -> str:
    if not reminder_at:
        return ""

    scheduled = schedule_task_reminder(
        chat_id=chat_id,
        task_id=task_id,
        reminder_at=reminder_at,
    )
    if not scheduled:
        return f"\nНапоминание: время не распознано ({reminder_at})."
    return f"\nНапоминание: {reminder_at}."


async def _try_handle_task_intent(chat_id: int, text: str) -> str | None:
    intent = parse_task_intent(text)
    if intent is None:
        return None

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    task = None
    if intent.get("task_id"):
        task = await get_task(chat_id=chat_id, task_id=intent["task_id"])
    if task is None:
        alias = intent.get("alias")
        task = find_matching_task(tasks=tasks, alias=alias) if alias else None
    if task is None:
        return _build_unclear_task_reference_reply(intent=intent, tasks=tasks)

    if intent["intent"] == "update_due_date":
        await update_task_due_date(
            chat_id=chat_id,
            task_id=task["id"],
            due_date=intent["due_date"],
        )
        await _try_sync_task_to_notion(chat_id=chat_id, task_id=task["id"])
        return f"Обновил срок задачи #{task['id']} «{task['title']}»: {intent['due_date']}."

    if intent["intent"] == "cancel_task":
        await mark_task_cancelled(chat_id=chat_id, task_id=task["id"])
        await _try_sync_task_to_notion(chat_id=chat_id, task_id=task["id"])
        return f"Отменил задачу #{task['id']} «{task['title']}»."

    return None


def _build_unclear_task_reference_reply(intent: dict, tasks: list[dict]) -> str:
    if intent["intent"] == "update_due_date":
        action = f"поставить срок {intent['due_date']}"
    elif intent["intent"] == "cancel_task":
        action = "отменить задачу"
    else:
        action = "изменить задачу"

    active_tasks = [task for task in tasks if task.get("status") not in {"done", "cancelled"}]
    lines = [
        f"Я понял, что нужно {action}, но не уверен, какую именно задачу ты имеешь в виду.",
        "",
        "Напиши номер задачи, например:",
    ]

    if intent["intent"] == "update_due_date":
        lines.append(f"/deadline 7 {intent['due_date']}")
    else:
        lines.append("/cancel 7")

    if active_tasks:
        lines.extend(["", "Похожие активные задачи:"])
        for task in active_tasks[:8]:
            lines.append(f"{task['id']}. {task['title']} ({task['priority']}, {task['status']})")

    lines.extend(["", "Если это новая задача, напиши ее как отдельное действие без слов про редактирование существующей задачи."])
    return "\n".join(lines)


async def _handle_status_command(
    text: str,
    chat_id: int,
    action,
    success_text: str,
    usage_text: str,
) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return usage_text

    task_id = int(parts[1])
    updated = await action(chat_id=chat_id, task_id=task_id)

    if not updated:
        return f"Не нашел задачу #{task_id}."

    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return success_text


async def _handle_done_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) not in {2, 3} or not parts[1].isdigit():
        return "Напиши так: /done 1 или /done 1 120, где 120 — фактические минуты."

    task_id = int(parts[1])
    actual_minutes = None
    if len(parts) == 3:
        if not parts[2].isdigit() or int(parts[2]) <= 0:
            return "Фактическое время должно быть числом минут, например: /done 1 120"
        actual_minutes = int(parts[2])

    task_before = await get_task(chat_id=chat_id, task_id=task_id)
    if task_before is None:
        return f"Не нашел задачу #{task_id}."

    updated = await mark_task_done_with_time(
        chat_id=chat_id,
        task_id=task_id,
        actual_minutes=actual_minutes,
    )
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)

    task_after = await get_task(chat_id=chat_id, task_id=task_id)
    if actual_minutes is not None and task_after:
        await remember(
            chat_id=chat_id,
            text=_build_time_feedback_memory(task_after),
            source="time_feedback",
            metadata={
                "task_id": task_id,
                "task_title": task_after.get("title", ""),
                "estimated_minutes": task_after.get("estimated_minutes") or "",
                "actual_minutes": task_after.get("actual_minutes") or "",
                "time_estimation_accuracy": task_after.get("time_estimation_accuracy") or "",
            },
        )

    if actual_minutes is None:
        return "Готово, задача закрыта. Если хочешь обучить оценку времени, в следующий раз можно так: /done 1 120"

    estimate = task_after.get("estimated_minutes") if task_after else task_before.get("estimated_minutes")
    accuracy = task_after.get("time_estimation_accuracy") if task_after else None
    if estimate and accuracy is not None:
        return (
            f"Готово, задача закрыта. "
            f"Оценка: {estimate} мин, факт: {actual_minutes} мин, точность: {accuracy}%."
        )
    return f"Готово, задача закрыта. Фактическое время: {actual_minutes} мин."


async def _handle_delete_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /delete 1"

    task_id = int(parts[1])
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    await mark_task_cancelled(chat_id=chat_id, task_id=task_id)
    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Убрал задачу #{task_id} «{task['title']}» из активных."


async def _handle_rename_command(text: str, chat_id: int) -> str:
    parts = text.split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].strip():
        return "Напиши так: /rename 1 Новое название задачи"

    task_id = int(parts[1])
    title = parts[2].strip()
    updated = await update_task_title(chat_id=chat_id, task_id=task_id, title=title)
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Переименовал задачу #{task_id}: «{title}»."


async def _handle_priority_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        return "Напиши так: /priority 1 high"

    priority = parts[2].lower()
    if priority not in {"high", "medium", "low"}:
        return "Приоритет должен быть high, medium или low."

    task_id = int(parts[1])
    updated = await update_task_priority(chat_id=chat_id, task_id=task_id, priority=priority)
    if not updated:
        return f"Не нашел задачу #{task_id}."

    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Обновил приоритет задачи #{task_id}: {priority}."


async def _handle_remind_command(text: str, chat_id: int) -> str:
    parts = text.split(maxsplit=3)
    if len(parts) < 3 or not parts[1].isdigit():
        return "Напиши так: /remind 1 2026-06-02 14:30 или /remind 1 off"

    task_id = int(parts[1])
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    value = " ".join(parts[2:]).strip()
    if value.lower() in {"off", "нет", "убрать", "disable"}:
        await update_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=None)
        await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
        return f"Убрал напоминание у задачи #{task_id}."

    reminder_at = _normalize_reminder_at(value)
    if reminder_at is None:
        return "Время напоминания должно быть в формате YYYY-MM-DD HH:MM, например: /remind 1 2026-06-02 14:30"

    await update_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=reminder_at)
    scheduled = schedule_task_reminder(chat_id=chat_id, task_id=task_id, reminder_at=reminder_at)
    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    if not scheduled:
        return f"Сохранил напоминание для задачи #{task_id}, но не смог поставить его в scheduler: {reminder_at}."
    return f"Напоминание для задачи #{task_id} поставлено на {reminder_at}."


async def _handle_deadline_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        return "Напиши так: /deadline 7 2026-06-15"

    task_id = int(parts[1])
    due_date = parts[2]
    try:
        date.fromisoformat(due_date)
    except ValueError:
        return "Дата должна быть в формате YYYY-MM-DD, например: /deadline 7 2026-06-15"

    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    await update_task_due_date(chat_id=chat_id, task_id=task_id, due_date=due_date)
    await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    return f"Обновил срок задачи #{task_id} «{task['title']}»: {due_date}."


async def _build_day_tasks_reply(
    chat_id: int,
    target_date: date,
    empty_text: str,
    title: str,
) -> tuple[str, dict | None]:
    tasks = await list_tasks_by_due_date(
        chat_id=chat_id,
        due_date=target_date.isoformat(),
    )
    if not tasks:
        return empty_text, None

    lines = [title]
    for task in tasks:
        project = f", {task['project_name']}" if task.get("project_name") else ""
        time_info = _format_task_time(task)
        lines.append(
            f"{task['id']}. {task['title']} "
            f"({task['priority']}, {task['assigned_agent']}{project}{time_info})"
        )

    return "\n".join(lines), _build_task_actions_keyboard(tasks)


async def _build_today_focus_reply(chat_id: int) -> tuple[str, dict | None]:
    today = date.today()
    tasks = await list_today_focus_tasks(
        chat_id=chat_id,
        today=today.isoformat(),
    )
    if not tasks:
        return (
            "На сегодня нет задач и срочных фокусов. Можешь добавить задачу обычным сообщением, например: `Срочно проверить документы СЭС`.",
            None,
        )

    lines = ["Фокус на сегодня:"]
    for task in tasks:
        project = f", {task['project_name']}" if task.get("project_name") else ""
        timing = _format_task_timing(task=task, today=today)
        time_info = _format_task_time(task)
        lines.append(
            f"{task['id']}. {task['title']} "
            f"({task['priority']}, {task['assigned_agent']}{project}{timing}{time_info})"
        )

    return "\n".join(lines), _build_task_actions_keyboard(tasks)


async def _build_next_task_reply(chat_id: int) -> tuple[str, dict | None]:
    today = date.today()
    tasks = await list_next_task_candidates(chat_id=chat_id, today=today.isoformat(), limit=5)
    if not tasks:
        return "Активных задач нет. Можно добавить новую задачу обычным сообщением.", None

    task = tasks[0]
    project = f"\nПроект: {task['project_name']}" if task.get("project_name") else ""
    timing = _format_task_timing(task=task, today=today)
    time_info = _format_task_time(task)
    reminder = f"\nНапоминание: {task['reminder_at']}" if task.get("reminder_at") else ""

    lines = [
        "Следующий лучший шаг:",
        "",
        f"Задача #{task['id']}: {task['title']}",
        f"Приоритет: {task['priority']}{timing}{time_info}",
    ]
    if project:
        lines.append(project.lstrip())
    if task.get("next_subtask_title"):
        lines.extend(
            [
                "",
                f"Начни с подзадачи #{task['next_subtask_id']}: {task['next_subtask_title']}",
                f"Закрыть шаг: /subdone {task['next_subtask_id']}",
            ]
        )
    else:
        lines.extend(["", f"Закрыть задачу: /done {task['id']}"])
    if reminder:
        lines.append(reminder.lstrip())

    if len(tasks) > 1:
        lines.extend(["", "Дальше в очереди:"])
        for next_task in tasks[1:4]:
            lines.append(f"{next_task['id']}. {next_task['title']} ({next_task['priority']})")

    return "\n".join(lines), _build_task_actions_keyboard([task])


async def _build_week_tasks_reply(chat_id: int) -> tuple[str, dict | None]:
    tasks = await list_tasks_by_planning_period(
        chat_id=chat_id,
        planning_period="week",
    )
    if not tasks:
        return (
            "На неделю пока нет задач без точной даты. Можешь добавить задачу обычным сообщением, например: `На неделю проверить документы СЭС`.",
            None,
        )

    lines = ["Задачи на неделю:"]
    for task in tasks:
        project = f", {task['project_name']}" if task.get("project_name") else ""
        time_info = _format_task_time(task)
        lines.append(
            f"{task['id']}. {task['title']} "
            f"({task['priority']}, {task['assigned_agent']}{project}{time_info})"
        )

    return "\n".join(lines), _build_task_actions_keyboard(tasks)


def _format_task_timing(task: dict, today: date) -> str:
    due_date = task.get("due_date")
    if due_date:
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            return f", срок: {due_date}"

        days_left = (due - today).days
        if days_left < 0:
            return f", просрочено на {abs(days_left)} дн."
        if days_left == 0:
            return ", срок сегодня"
        return f", осталось {days_left} дн."

    if task.get("planning_period") == "week":
        days_left = _days_until_week_end(today)
        return f", на неделю, осталось {days_left} дн."

    return ", без даты"


def _format_task_time(task: dict) -> str:
    estimated = task.get("estimated_minutes")
    actual = task.get("actual_minutes")
    accuracy = task.get("time_estimation_accuracy")

    parts = []
    if estimated:
        parts.append(f"оценка {estimated} мин")
    if actual:
        parts.append(f"факт {actual} мин")
    if accuracy is not None:
        parts.append(f"точность {accuracy}%")

    return f", {', '.join(parts)}" if parts else ""


def _build_time_feedback_memory(task: dict) -> str:
    return "\n".join(
        [
            f"Факт времени по задаче #{task['id']}: {task['title']}.",
            f"Оценка: {task.get('estimated_minutes') or 'нет'} мин.",
            f"Факт: {task.get('actual_minutes') or 'нет'} мин.",
            f"Точность оценки: {task.get('time_estimation_accuracy') or 'нет'}%.",
            "Используй это для будущих оценок похожих задач.",
        ]
    )


def _days_until_week_end(today: date) -> int:
    days_left = 6 - today.weekday()
    if days_left <= 0:
        return 7
    return days_left


async def _build_active_tasks_reply(chat_id: int) -> tuple[str, dict | None]:
    tasks = await list_active_tasks(chat_id=chat_id)
    if not tasks:
        return "Активных задач нет. Можно добавить новую задачу обычным сообщением.", None

    lines = ["Все активные задачи:"]
    for task in tasks:
        project = f", {task['project_name']}" if task.get("project_name") else ""
        due = f", {task['due_date']}" if task.get("due_date") else ""
        period = ", на неделю" if task.get("planning_period") == "week" else ""
        time_info = _format_task_time(task)
        lines.append(
            f"{task['id']}. {task['title']} "
            f"({task['priority']}, {task['assigned_agent']}{project}{due}{period}{time_info})"
        )

    return "\n".join(lines), _build_task_actions_keyboard(tasks)


def _is_tomorrow_overview_request(text: str) -> bool:
    normalized = text.lower().strip()
    if normalized.startswith("/"):
        return False

    overview_prefixes = (
        "план на завтра",
        "задачи на завтра",
        "дела на завтра",
        "что на завтра",
        "список задач на завтра",
        "список дел на завтра",
        "покажи задачи на завтра",
        "покажи план на завтра",
        "какие задачи на завтра",
        "какой план на завтра",
    )
    return any(normalized.startswith(prefix) for prefix in overview_prefixes)


def _is_week_overview_request(text: str) -> bool:
    normalized = text.lower().strip()
    if normalized.startswith("/"):
        return False

    overview_prefixes = (
        "план на неделю",
        "задачи на неделю",
        "дела на неделю",
        "что на неделю",
        "список задач на неделю",
        "список дел на неделю",
        "покажи задачи на неделю",
        "покажи план на неделю",
        "какие задачи на неделю",
        "какой план на неделю",
    )
    return any(normalized.startswith(prefix) for prefix in overview_prefixes)


async def _handle_plan_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /plan 1"

    task_id = int(parts[1])
    return await _build_plan_for_saved_task(chat_id=chat_id, task_id=task_id)


async def _handle_subtasks_command(text: str, chat_id: int) -> tuple[str, dict | None]:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /subtasks 1", None

    task_id = int(parts[1])
    return await _build_subtasks_for_task(chat_id=chat_id, task_id=task_id)


async def _handle_subtask_done_command(text: str, chat_id: int) -> str:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /subdone 1"

    subtask_id = int(parts[1])
    updated = await mark_subtask_done(chat_id=chat_id, subtask_id=subtask_id)
    if not updated:
        return f"Не нашел подзадачу #{subtask_id}."

    reply = await _build_subtask_done_reply(chat_id=chat_id, subtask_id=subtask_id)
    subtask = await get_subtask(chat_id=chat_id, subtask_id=subtask_id)
    if subtask:
        await _try_sync_task_to_notion(chat_id=chat_id, task_id=subtask["task_id"])
    return reply


async def _handle_project_command(text: str, chat_id: int) -> tuple[str, dict | None]:
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return "Напиши так: /project 1", None

    project_id = int(parts[1])
    project = await get_project(chat_id=chat_id, project_id=project_id)
    if project is None:
        return f"Не нашел проект #{project_id}.", None

    tasks = await list_project_tasks(chat_id=chat_id, project_id=project_id)
    description = project.get("description") or "описание пока не задано"
    lines = [
        f"Проект #{project['id']}: {project['name']}",
        f"Статус: {project['status']}",
        f"Активных задач: {project['active_task_count'] or 0}",
        f"Всего задач: {project['task_count'] or 0}",
        f"Описание: {description}",
    ]

    if tasks:
        lines.extend(["", "Задачи:"])
        for task in tasks:
            lines.append(
                f"{task['id']}. {task['title']} "
                f"({task['status']}, {task['priority']}, {task['assigned_agent']}{_format_task_time(task)})"
            )
        next_task = next(
            (task for task in tasks if task["status"] not in {"done", "cancelled"}),
            None,
        )
        if next_task:
            lines.extend(["", f"Следующий план: /plan {next_task['id']}"])
    else:
        lines.extend(["", "В этом проекте пока нет задач."])

    return "\n".join(lines), _build_task_actions_keyboard(tasks) if tasks else None


async def _build_plan_for_saved_task(chat_id: int, task_id: int) -> str:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}."

    try:
        analysis = json.loads(task["analysis_json"])
    except json.JSONDecodeError:
        analysis = {
            "type": task["task_type"],
            "title": task["title"],
            "summary": task["user_text"],
            "priority": task["priority"],
            "assigned_agent": "planner_agent",
            "can_be_automated": False,
            "needs_clarification": True,
            "next_action": "Пересобрать план по сохраненной задаче",
        }

    analysis["assigned_agent"] = "planner_agent"
    planner_tasks = await list_planner_context_tasks(chat_id=chat_id)
    projects = await list_project_context(chat_id=chat_id)
    memories = await search_memory(
        chat_id=chat_id,
        query=f"{task['title']}\n{task['user_text']}",
        limit=6,
    )
    plan = await ai_client.run_planner(
        text=task["user_text"],
        analysis=analysis,
        workflow_context=load_workflow_context(),
        task_context=format_task_context(planner_tasks),
        project_context=format_project_context(projects),
        retrospective_context=format_retrospective_context(
            await list_recent_retrospectives(chat_id=chat_id, limit=5)
        ),
        memory_context=format_memory_context(memories),
    )
    result = format_planner_result(analysis=analysis, plan=plan)
    await update_task_plan(
        chat_id=chat_id,
        task_id=task_id,
        analysis=analysis,
        result=result,
    )
    await replace_subtasks(
        chat_id=chat_id,
        task_id=task_id,
        titles=_extract_subtask_titles(plan),
    )
    await remember(
        chat_id=chat_id,
        text=build_planner_memory_text(
            task_id=task_id,
            title=task["title"],
            plan=plan,
        ),
        source="planner_advice",
        metadata={
            "task_id": task_id,
            "task_title": task["title"],
            "priority": task["priority"],
            "project_id": task.get("project_id") or "",
        },
    )
    notion_note = await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)

    return f"План для задачи #{task_id} обновлен.{notion_note}\n\n{result}"


async def _handle_callback_query(callback_query: dict) -> None:
    callback_query_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if chat_id is None:
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text="Не понял, к какому чату относится действие.",
        )
        return

    action, _, task_id_text = data.partition(":")

    if action == "brief":
        await _handle_brief_callback(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            action=task_id_text,
        )
        return

    if action == "retro":
        await handle_retrospective_callback(
            callback_query_id=callback_query_id,
            chat_id=chat_id,
            action=task_id_text,
        )
        return

    if not task_id_text.isdigit():
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text="Не понял номер задачи.",
        )
        return

    task_id = int(task_id_text)
    if action == "done":
        updated = await mark_task_done(chat_id=chat_id, task_id=task_id)
        text = f"Задача #{task_id} закрыта." if updated else f"Не нашел задачу #{task_id}."
        if updated:
            await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    elif action == "cancel":
        updated = await mark_task_cancelled(chat_id=chat_id, task_id=task_id)
        text = f"Задача #{task_id} отменена." if updated else f"Не нашел задачу #{task_id}."
        if updated:
            await _try_sync_task_to_notion(chat_id=chat_id, task_id=task_id)
    elif action == "plan":
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Готовлю план для задачи #{task_id}...",
        )
        text = await _build_plan_for_saved_task(chat_id=chat_id, task_id=task_id)
        await telegram_client.send_message(chat_id=chat_id, text=text)
        return
    elif action == "subtasks":
        reply, reply_markup = await _build_subtasks_for_task(
            chat_id=chat_id,
            task_id=task_id,
        )
        await telegram_client.answer_callback_query(
            callback_query_id=callback_query_id,
            text=f"Открываю шаги задачи #{task_id}.",
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )
        return
    elif action == "subdone":
        updated = await mark_subtask_done(chat_id=chat_id, subtask_id=task_id)
        if updated:
            text = await _build_subtask_done_reply(chat_id=chat_id, subtask_id=task_id)
            subtask = await get_subtask(chat_id=chat_id, subtask_id=task_id)
            if subtask:
                await _try_sync_task_to_notion(chat_id=chat_id, task_id=subtask["task_id"])
        else:
            text = f"Не нашел подзадачу #{task_id}."
    else:
        text = "Неизвестное действие."

    await telegram_client.answer_callback_query(
        callback_query_id=callback_query_id,
        text=text,
    )
    await telegram_client.send_message(chat_id=chat_id, text=text)


async def _handle_brief_callback(callback_query_id: str, chat_id: int, action: str) -> None:
    if action == "accept":
        text = "План принят. Держим фокус и закрываем по шагам."
    elif action == "edit":
        text = "Напиши, что изменить в плане: например, «сначала ревизия, потом P&L»."
    elif action == "snooze":
        schedule_morning_brief_snooze(chat_id=chat_id, minutes=60)
        text = "Ок, напомню через час."
    else:
        text = "Неизвестное действие для брифа."

    await telegram_client.answer_callback_query(
        callback_query_id=callback_query_id,
        text=text,
    )
    await telegram_client.send_message(chat_id=chat_id, text=text)


def _build_task_actions_keyboard(tasks: list[dict]) -> dict:
    rows = []
    for task in tasks[:5]:
        task_id = task["id"]
        rows.append(
            [
                {
                    "text": f"Готово #{task_id}",
                    "callback_data": f"done:{task_id}",
                },
                {
                    "text": f"Отмена #{task_id}",
                    "callback_data": f"cancel:{task_id}",
                },
                {
                    "text": f"План #{task_id}",
                    "callback_data": f"plan:{task_id}",
                },
                {
                    "text": f"Шаги #{task_id}",
                    "callback_data": f"subtasks:{task_id}",
                },
            ]
        )

    return {"inline_keyboard": rows}


def _build_memory_reply(memories: list[dict]) -> str:
    if not memories:
        return (
            "Долговременная память пока пустая или ChromaDB недоступен. "
            "После вечерних ретроспектив и Planner-планов здесь появятся записи."
        )

    lines = ["Последние записи памяти:"]
    for index, memory in enumerate(memories, start=1):
        metadata = memory.get("metadata") or {}
        source = metadata.get("source", "memory")
        created_at = metadata.get("created_at", "без даты")
        text = memory.get("text", "").replace("\n", " ")
        if len(text) > 180:
            text = f"{text[:177]}..."
        lines.append(f"{index}. [{source}, {created_at}] {text}")

    return "\n".join(lines)


async def _build_subtasks_for_task(chat_id: int, task_id: int) -> tuple[str, dict | None]:
    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return f"Не нашел задачу #{task_id}.", None

    subtasks = await list_subtasks(chat_id=chat_id, task_id=task_id)
    if not subtasks:
        return (
            f"У задачи #{task_id} пока нет подзадач. Нажми `План #{task_id}` или напиши /plan {task_id}, чтобы Planner разложил ее на шаги.",
            None,
        )

    return _format_subtasks_reply(task=task, subtasks=subtasks), _build_subtask_actions_keyboard(subtasks)


async def _build_subtask_done_reply(chat_id: int, subtask_id: int) -> str:
    subtask = await get_subtask(chat_id=chat_id, subtask_id=subtask_id)
    if subtask is None:
        return f"Готово, подзадача #{subtask_id} закрыта."

    task_id = subtask["task_id"]
    if await all_subtasks_done(chat_id=chat_id, task_id=task_id):
        await mark_task_done(chat_id=chat_id, task_id=task_id)
        return (
            f"Готово, подзадача #{subtask_id} закрыта.\n"
            f"Все подзадачи выполнены, задача #{task_id} тоже закрыта."
        )

    return f"Готово, подзадача #{subtask_id} закрыта."


def _build_subtask_actions_keyboard(subtasks: list[dict]) -> dict:
    rows = []
    for subtask in subtasks[:8]:
        if subtask["status"] == "done":
            continue
        subtask_id = subtask["id"]
        rows.append(
            [
                {
                    "text": f"Готово подзадача #{subtask_id}",
                    "callback_data": f"subdone:{subtask_id}",
                }
            ]
        )

    return {"inline_keyboard": rows} if rows else {}


def _format_subtasks_reply(task: dict, subtasks: list[dict]) -> str:
    lines = [f"Подзадачи для #{task['id']}: {task['title']}"]
    for subtask in subtasks:
        marker = "x" if subtask["status"] == "done" else " "
        lines.append(f"[{marker}] {subtask['id']}. {subtask['title']}")
    return "\n".join(lines)


def _extract_subtask_titles(plan: dict) -> list[str]:
    titles: list[str] = []
    for phase in plan.get("phases", []):
        if isinstance(phase, dict):
            steps = phase.get("steps", [])
        else:
            steps = [phase]

        for step in steps:
            title = str(step).strip()
            if title:
                titles.append(title)

    return titles[:20]


async def _handle_notion_sync_command(chat_id: int) -> str:
    if not notion_client.is_configured:
        return (
            "Notion пока не настроен. Добавь в .env NOTION_TOKEN и "
            "NOTION_TASKS_DATA_SOURCE_ID, а затем перезапусти backend."
        )

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    if not tasks:
        return "Нет задач для синхронизации с Notion."

    synced = 0
    failed = 0
    for task in tasks:
        try:
            page_id = await notion_client.sync_task(
                task=task,
                subtasks=await list_subtasks(chat_id=chat_id, task_id=task["id"]),
            )
            if page_id:
                await update_task_notion_page_id(
                    chat_id=chat_id,
                    task_id=task["id"],
                    notion_page_id=page_id,
                )
            synced += 1
        except Exception:
            failed += 1

    if failed:
        return f"Notion sync завершен частично: синхронизировано {synced}, ошибок {failed}."

    return f"Notion sync готов: синхронизировано {synced} задач."


async def _handle_notion_pull_command(chat_id: int) -> str:
    if not notion_client.is_configured:
        return (
            "Notion пока не настроен. Добавь в .env NOTION_TOKEN и "
            "NOTION_TASKS_DATA_SOURCE_ID, а затем перезапусти backend."
        )

    tasks = await list_tasks_for_notion_sync(chat_id=chat_id)
    tasks = [task for task in tasks if task.get("notion_page_id")]
    if not tasks:
        return "Пока нет задач, связанных с Notion. Сначала запусти /sync_notion."

    updated = 0
    unchanged = 0
    failed = 0
    for task in tasks:
        try:
            notion_status = await notion_client.get_task_status(task["notion_page_id"])
            if notion_status != task["status"]:
                await update_task_status(
                    chat_id=chat_id,
                    task_id=task["id"],
                    status=notion_status,
                )
                updated += 1
            else:
                unchanged += 1
        except Exception:
            failed += 1

    parts = [
        f"Из Notion обновлено: {updated}",
        f"без изменений: {unchanged}",
    ]
    if failed:
        parts.append(f"ошибок: {failed}")

    return ". ".join(parts) + "."


async def _try_sync_task_to_notion(chat_id: int, task_id: int) -> str:
    if not notion_client.is_configured:
        return ""

    task = await get_task(chat_id=chat_id, task_id=task_id)
    if task is None:
        return ""

    try:
        page_id = await notion_client.sync_task(
            task=task,
            subtasks=await list_subtasks(chat_id=chat_id, task_id=task_id),
        )
        if page_id:
            await update_task_notion_page_id(
                chat_id=chat_id,
                task_id=task_id,
                notion_page_id=page_id,
            )
        return "\nNotion: синхронизировано."
    except Exception as error:
        return f"\nNotion: не синхронизировано: {error}"
