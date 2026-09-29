"""VK Callback API endpoint and text-command router."""
import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from config import Config
from services.document_service import DocumentService
from services.vk_api import VKAPIClient


logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Добро пожаловать! Я бот архива технической документации.\n\n"
    "Команды для управления:\n"
    "помощь — полный список команд\n"
    "поиск <текст> — найти документ\n"
    "умный поиск <текст> — поиск с подбором синонимов\n"
    "список [страница] — список документов\n"
    "инфо <ID> — карточка документа\n"
    "скачать <ID> — получить файл\n"
    "фильтр тип|статус|техпроцесс <значение>\n"
    "статистика — сводка архива\n"
    "статус <ID> <новый статус> — изменить статус (для администратора)\n"
    "добавить Название | Тип | Номер | Версия | Техпроцесс | Теги | Описание\n\n"
    "Можно также написать запрос обычными словами, например: «найди чертеж вала»."
)

HELP_TEXT = WELCOME_TEXT.replace("Добро пожаловать! Я бот архива технической документации.\n\n", "")


def parse_text_command(text: str) -> Tuple[str, str]:
    """Выделяет команду из slash-команды или русской текстовой фразы."""
    normalized = text.strip()
    if not normalized:
        return "", ""

    if normalized.startswith("/"):
        parts = normalized[1:].split(maxsplit=1)
        command = parts[0].split("@", maxsplit=1)[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
    else:
        parts = normalized.split(maxsplit=1)
        command = parts[0].lower().strip("!?.,:")
        argument = parts[1].strip() if len(parts) > 1 else ""

    aliases = {
        "команды": "help", "помощь": "help", "справка": "help",
        "меню": "help", "найди": "search", "найти": "search",
        "поиск": "search", "покажи": "search", "умный": "smart",
        "инфо": "get", "документ": "get", "скачать": "download",
        "список": "list", "фильтр": "filter", "статистика": "stats",
        "статус": "status", "добавить": "add", "начать": "start",
        "start": "start", "help": "help", "menu": "help",
        "search": "search", "find": "smart", "get": "get",
        "download": "download", "list": "list", "filter": "filter",
        "stats": "stats", "status": "status", "add": "add",
    }

    if command == "умный" and argument.lower().startswith("поиск"):
        argument = argument[5:].strip()
        return "smart", argument
    return aliases.get(command, ""), argument


def create_vk_app(
    db: Any, document_service: DocumentService, vk_client: VKAPIClient
) -> web.Application:
    app = web.Application()
    app["db"] = db
    app["document_service"] = document_service
    app["vk_client"] = vk_client
    app["tasks"] = set()
    callback_path = Config.VK_CALLBACK_PATH or "/"
    app.router.add_post(callback_path, handle_callback)
    app.router.add_get("/health", health_check)
    app.on_cleanup.append(cancel_background_tasks)
    return app


async def health_check(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_callback(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (ValueError, web.HTTPException):
        return web.Response(status=400, text="invalid json")

    secret = Config.VK_CALLBACK_SECRET
    if secret and payload.get("secret") != secret:
        return web.Response(status=403, text="forbidden")

    event_type = payload.get("type")
    if event_type == "confirmation":
        return web.Response(text=Config.VK_CONFIRMATION_CODE)
    if event_type == "message_new":
        event_object = payload.get("object", {})
        message = event_object.get("message", event_object)
        sender_id = message.get("from_id")
        peer_id = message.get("peer_id")
        if sender_id and peer_id and sender_id > 0:
            task = asyncio.create_task(
                process_message(request.app, message, int(sender_id), int(peer_id))
            )
            request.app["tasks"].add(task)
            task.add_done_callback(request.app["tasks"].discard)
    return web.Response(text="ok")


async def process_message(
    app: web.Application, message: Dict[str, Any], sender_id: int, peer_id: int
) -> None:
    vk_client: VKAPIClient = app["vk_client"]
    try:
        is_first_message = await app["db"].register_vk_user(sender_id)
        text = str(message.get("text", "")).strip()
        command, argument = parse_text_command(text)
        if is_first_message:
            await vk_client.send_message(peer_id, WELCOME_TEXT)
            if command in {"", "start", "help"}:
                return
        if command == "start":
            await vk_client.send_message(peer_id, WELCOME_TEXT)
            return
        response = await dispatch_text_command(
            app["document_service"], vk_client, peer_id, sender_id,
            command, argument, text
        )
        await vk_client.send_message(peer_id, response)
    except Exception:
        logger.exception("Ошибка обработки VK-сообщения от %s", sender_id)
        try:
            await vk_client.send_message(
                peer_id, "Не удалось обработать запрос. Попробуйте позже или отправьте «помощь»."
            )
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке в VK")


async def dispatch_text_command(
    service: DocumentService,
    vk_client: VKAPIClient,
    peer_id: int,
    sender_id: int,
    command: str,
    argument: str,
    original_text: str,
) -> str:
    if command in {"help", ""}:
        return HELP_TEXT
    if command == "search":
        if not argument:
            return "Укажите запрос: поиск вал приводной"
        docs = await service.search_documents(argument)
        return _format_documents(docs, f"Результаты поиска: {len(docs)}")
    if command == "smart":
        if not argument:
            return "Укажите запрос: умный поиск вал с пазом"
        result = await service.smart_search(argument)
        return _format_documents(
            result["all_results"], result["message"], result.get("llm_suggestions")
        )
    if command == "list":
        page = int(argument) if argument.isdigit() else 1
        docs, total = await service.get_document_list(page=max(page, 1), per_page=10)
        return _format_documents(docs, f"Документы, страница {max(page, 1)}; всего: {total}")
    if command == "get":
        if not argument:
            return "Укажите ID документа: инфо DOC-2024-0001"
        info = await service.get_document_info(argument)
        if not info:
            return f"Документ {argument} не найден."
        return (
            f"{info['doc_id']} — {info.get('title', 'Без названия')}\n"
            f"Тип: {info.get('doc_type') or 'не указан'}\n"
            f"Номер: {info.get('drawing_number') or 'не указан'}\n"
            f"Версия: {info.get('version') or 'не указана'}\n"
            f"Техпроцесс: {info.get('tech_process') or 'не указан'}\n"
            f"Статус: {info.get('status') or 'не указан'}\n"
            f"Теги: {info.get('tags') or 'нет'}\n"
            f"Описание: {info.get('description') or 'нет'}"
        )
    if command == "download":
        if not argument:
            return "Укажите ID документа: скачать DOC-2024-0001"
        file_data = await service.download_document(argument)
        if not file_data:
            return f"Файл документа {argument} не найден."
        content, file_name = file_data
        await vk_client.send_document(peer_id, content, file_name, f"{argument} — {file_name}")
        return f"Файл документа {argument} отправлен."
    if command == "filter":
        parts = argument.split(maxsplit=1)
        if len(parts) != 2:
            return "Формат: фильтр тип Чертеж | фильтр статус Активен | фильтр техпроцесс Токарная"
        key, value = parts[0].lower(), parts[1]
        filter_names = {
            "тип": "doc_type", "статус": "status", "техпроцесс": "tech_process",
            "type": "doc_type", "status": "status", "tech": "tech_process",
        }
        field = filter_names.get(key)
        if not field:
            return "Критерий должен быть: тип, статус или техпроцесс."
        docs = await service.filter_documents(**{field: value})
        return _format_documents(docs, f"Фильтр {key}: {value}; найдено: {len(docs)}")
    if command == "stats":
        stats = await service.get_statistics()
        return (
            f"Документов в архиве: {stats.get('total', 0)}\n"
            f"По типам: {_format_counts(stats.get('by_type', {}))}\n"
            f"По статусам: {_format_counts(stats.get('by_status', {}))}"
        )
    if command == "status":
        parts = argument.split(maxsplit=1)
        if len(parts) != 2:
            return "Формат: статус DOC-2024-0001 Архивный"
        success, result = await service.change_status(parts[0], parts[1], str(sender_id))
        return result
    if command == "add":
        fields = [value.strip() for value in argument.split("|")]
        if len(fields) != 7 or not fields[0]:
            return (
                "Формат: добавить Название | Тип | Номер | Версия | "
                "Техпроцесс | Теги | Описание\nДля пропуска поля укажите -"
            )
        values = [None if value == "-" else value for value in fields]
        data = dict(zip(
            ("title", "doc_type", "drawing_number", "version", "tech_process", "tags", "description"),
            values,
        ))
        document = await service.add_new_document(data, user=str(sender_id))
        return f"Документ добавлен: {document.doc_id} — {document.title}" if document else "Не удалось добавить документ. Проверьте название и тип."

    response = await service.process_free_text(original_text)
    return response[:3500]


def _format_documents(docs: list, title: str, suggestions: Optional[list] = None) -> str:
    lines = [title]
    if suggestions:
        lines.append("Синонимы: " + ", ".join(suggestions))
    if not docs:
        lines.append("Документов не найдено.")
    for index, doc in enumerate(docs[:10], 1):
        lines.append(
            f"{index}. {doc.doc_id} — {doc.title} "
            f"({doc.doc_type or 'тип не указан'}, {doc.status})"
        )
    if len(docs) > 10:
        lines.append(f"Показаны первые 10 из {len(docs)}. Используйте «список <страница>».")
    return "\n".join(lines)[:3500]


def _format_counts(values: Dict[str, int]) -> str:
    return ", ".join(f"{name}: {count}" for name, count in values.items()) or "нет данных"


async def cancel_background_tasks(app: web.Application) -> None:
    tasks = list(app["tasks"])
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)