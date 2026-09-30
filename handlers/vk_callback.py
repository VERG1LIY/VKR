"""VK Callback API endpoint and text-command router."""
import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web

from config import Config
from services.document_service import DocumentService
from services.file_service import FileService
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


class NavStateManager:
    """Хранит стек навигации по экранам для каждого пользователя VK."""

    def __init__(self):
        self._states: Dict[int, List[str]] = {}

    def get(self, user_id: int) -> List[str]:
        return self._states.setdefault(user_id, ["main"])

    def current(self, user_id: int) -> str:
        path = self.get(user_id)
        return path[-1] if path else "main"

    def push(self, user_id: int, screen: str) -> List[str]:
        path = self.get(user_id)[:]
        if path and path[-1] == screen:
            return path
        path.append(screen)
        self._states[user_id] = path
        return path

    def back(self, user_id: int) -> str:
        path = self.get(user_id)
        if len(path) <= 1:
            self._states[user_id] = ["main"]
            return "main"
        self._states[user_id] = path[:-1]
        return self._states[user_id][-1]

    def reset(self, user_id: int) -> List[str]:
        self._states[user_id] = ["main"]
        return self._states[user_id]


def build_payload(action: str, **kwargs: Any) -> str:
    payload: Dict[str, Any] = {"action": action}
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_payload(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        if text.startswith("{"):
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return {"action": text}
        return {"action": text}
    return {"action": str(raw)}


def _button(label: str, action: str, **kwargs: Any) -> Dict[str, Any]:
    return {
        "action": {
            "type": "text",
            "label": label,
            "payload": build_payload(action, **kwargs),
        }
    }


def build_main_menu_keyboard() -> Dict[str, Any]:
    buttons = [
        [_button("🔎 Поиск", "open_search"), _button("🧠 Умный поиск", "open_smart_search")],
        [_button("🗂 Фильтр", "open_filters"), _button("📋 Список", "open_document_list")],
        [_button("📤 Загрузить", "open_upload"), _button("🏠 Главное меню", "main_menu")],
    ]
    return {"one_time": False, "buttons": buttons}


def build_navigation_keyboard() -> Dict[str, Any]:
    buttons = [
        [_button("◀️ Назад", "back"), _button("🏠 Главное меню", "main_menu")],
    ]
    return {"one_time": False, "buttons": buttons}


def build_filter_menu_keyboard() -> Dict[str, Any]:
    buttons = [
        [_button("🏷 Все теги", "filter_mode", filter_name="tags")],
        [_button("◀️ Назад", "back"), _button("🏠 Главное меню", "main_menu")],
    ]
    return {"one_time": False, "buttons": buttons}


def build_document_list_keyboard(page: int, total_pages: int, docs: Optional[List[Any]] = None) -> Dict[str, Any]:
    buttons: List[List[Dict[str, Any]]] = []
    if docs:
        for doc in docs:
            buttons.append([
                _button(f"{doc.doc_id}", "open_document", doc_id=doc.doc_id),
            ])
    nav = []
    if page > 1:
        nav.append(_button("⬅️", "list_page", page=page - 1))
    if page < total_pages:
        nav.append(_button("➡️", "list_page", page=page + 1))
    if nav:
        buttons.append(nav)
    buttons.append([_button("◀️ Назад", "back"), _button("🏠 Главное меню", "main_menu")])
    return {"one_time": False, "buttons": buttons}


def build_confirm_upload_keyboard() -> Dict[str, Any]:
    return {
        "one_time": False,
        "buttons": [
            [_button("✅ Сохранить", "confirm_upload"), _button("❌ Отмена", "cancel_upload")],
            [_button("🏠 Главное меню", "main_menu")],
        ],
    }


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


async def dispatch_text_command(
    service: DocumentService,
    vk_client: VKAPIClient,
    peer_id: int,
    sender_id: int,
    command: str,
    argument: str,
    text: str,
) -> str:
    """Обработка текстовых команд бота в обычном чате VK."""
    normalized_text = (text or argument or "").strip()

    if command in {"help", "menu"}:
        return HELP_TEXT
    if command == "start":
        return WELCOME_TEXT
    if command == "search":
        query = (argument or text).strip()
        if not query:
            return "Введите текст поиска. Пример: поиск вал редуктора"
        docs = await service.search_documents(query)
        return _format_documents(docs, f"Результаты поиска: {len(docs)}")
    if command == "smart":
        query = (argument or text).strip()
        if not query:
            return "Введите запрос для умного поиска."
        result = await service.smart_search(query)
        return _format_documents(
            result.get("all_results", []),
            result.get("message", "Результаты поиска"),
            result.get("llm_suggestions"),
        )
    if command == "list":
        page = 1
        if argument and argument.strip().isdigit():
            page = max(int(argument.strip()), 1)
        docs, total = await service.get_document_list(page=page, per_page=10)
        total_pages = max((total + 9) // 10, 1)
        if not docs:
            return "В архиве пока нет документов."
        lines = [f"📋 Список документов {page}/{total_pages} (всего: {total})"]
        for index, doc in enumerate(docs, 1):
            lines.append(f"{index}. {doc.doc_id} — {doc.title} ({doc.status or 'без статуса'})")
        return "\n".join(lines)
    if command in {"get", "info"}:
        doc_id = (argument or text).strip()
        if not doc_id:
            return "Укажите ID документа. Пример: /info DOC-2024-001"
        info = await service.get_document_info(doc_id)
        if not info:
            return f"Документ {doc_id} не найден."
        return (
            f"Название: {info.get('title') or 'Без названия'}\n"
            f"ID: {info.get('doc_id')}\n"
            f"Тип: {info.get('doc_type') or 'не указан'}\n"
            f"Статус: {info.get('status') or 'не указан'}\n"
            f"Техпроцесс: {info.get('tech_process') or 'не указан'}\n"
            f"Версия: {info.get('version') or 'не указана'}\n"
            f"Теги: {info.get('tags') or 'нет'}\n"
            f"Описание: {info.get('description') or 'нет'}"
        )
    if command == "download":
        doc_id = (argument or text).strip()
        if not doc_id:
            return "Укажите ID документа. Пример: /download DOC-2024-001"
        file_data = await service.download_document(doc_id)
        if not file_data:
            return f"Файл документа {doc_id} не найден."
        content, file_name = file_data
        await vk_client.send_document(peer_id, content, file_name, f"{doc_id} — {file_name}")
        return "Файл отправлен."
    if command == "filter":
        filter_text = argument.strip() if argument else ""
        if not filter_text:
            tags = await service.get_available_tags()
            if not tags:
                return "В базе пока нет тегов у документов."
            return "Доступные теги:\n- " + "\n- ".join(tags)

        docs = await service.filter_documents(tags=filter_text)
        if not docs:
            return f"По тегу '{filter_text}' документов не найдено."
        return _format_documents(docs, f"Документы по тегу '{filter_text}': {len(docs)}")
    if command == "stats":
        stats = await service.get_statistics()
        return _format_counts(stats)
    if command == "status":
        parts = argument.split(maxsplit=1)
        if len(parts) < 2:
            return "Формат: /status DOC-2024-001 Активен"
        admin_ids = set(Config.VK_ADMIN_IDS)
        if admin_ids and str(sender_id) not in {str(item) for item in admin_ids}:
            return "Изменение статуса доступно только администраторам."
        success, message = await service.change_status(parts[0], parts[1], str(sender_id))
        return message
    if command == "add":
        raw_fields = [part.strip() for part in (argument or text).split("|")]
        if len(raw_fields) < 7:
            return (
                "Формат: добавить Название | Тип | Номер | Версия | Техпроцесс | Теги | Описание"
            )
        title, doc_type, drawing_number, version, tech_process, tags, description = raw_fields[:7]
        document = await service.add_new_document(
            {
                "title": title,
                "doc_type": doc_type or None,
                "drawing_number": drawing_number or "",
                "version": version or "1.0",
                "tech_process": tech_process or None,
                "tags": tags or "",
                "description": description or "",
                "status": "Активен",
            },
            file_content=None,
            user=str(sender_id),
        )
        if not document:
            return "❌ Не удалось добавить документ. Проверьте обязательные поля."
        return f"✅ Документ добавлен: {document.doc_id} — {document.title}"

    if normalized_text:
        return (
            "Неизвестная команда. Используйте:\n"
            "поиск <текст> — поиск по документам\n"
            "умный поиск <текст> — поиск через LM Studio\n"
            "фильтр — список тегов\n"
            "список — список документов\n"
            "загрузить — добавить документ\n"
            "меню — главное меню"
        )
    return "Введите команду или запрос."


def create_vk_app(
    db: Any, document_service: DocumentService, vk_client: VKAPIClient
) -> web.Application:
    app = web.Application()
    app["db"] = db
    app["document_service"] = document_service
    app["vk_client"] = vk_client
    app["menu_state"] = NavStateManager()
    app["tasks"] = set()
    app["pending_uploads"] = {}
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
    if event_type == "message_event":
        event_object = payload.get("object", {})
        payload_data = parse_payload(event_object.get("payload"))
        action = payload_data.get("action")
        user_id = event_object.get("user_id")
        peer_id = event_object.get("peer_id") or user_id
        if action and user_id and peer_id:
            task = asyncio.create_task(
                handle_vk_action(request.app, int(user_id), int(peer_id), action, payload_data)
            )
            request.app["tasks"].add(task)
            task.add_done_callback(request.app["tasks"].discard)
        return web.Response(text="ok")
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
        state = app["menu_state"]
        text = str(message.get("text", "")).strip()
        attachments = message.get("attachments") or []
        current = state.current(sender_id)

        if current == "upload_waiting" and attachments:
            response = await prepare_upload_document(app, sender_id, peer_id, attachments[0])
            if response["status"] == "pending":
                state.push(sender_id, "upload_confirm")
                await vk_client.send_message(
                    peer_id,
                    response["text"],
                    keyboard=build_confirm_upload_keyboard(),
                )
            else:
                state.reset(sender_id)
                await vk_client.send_message(peer_id, response["text"], keyboard=build_main_menu_keyboard())
            return

        is_first_message = await app["db"].register_vk_user(sender_id)
        command, argument = parse_text_command(text)
        if is_first_message:
            await vk_client.send_message(peer_id, WELCOME_TEXT, keyboard=build_main_menu_keyboard())
            if command in {"", "start", "help"}:
                return
        if command == "start":
            await vk_client.send_message(peer_id, WELCOME_TEXT, keyboard=build_main_menu_keyboard())
            return
        if command in {"search", "smart"} and text:
            if command == "search":
                docs = await app["document_service"].search_documents(text)
            else:
                result = await app["document_service"].smart_search(text)
                docs = result.get("all_results") or []
            if docs and len(docs) == 1:
                sent = await _send_document_by_doc(app, vk_client, peer_id, docs[0])
                if sent:
                    await vk_client.send_message(
                        peer_id,
                        f"Найден документ: {docs[0].doc_id} — {docs[0].title}",
                        keyboard=build_navigation_keyboard(),
                    )
                    return

        if current in {"search", "smart_search"} and text:
            if current == "search":
                docs = await app["document_service"].search_documents(text)
                await vk_client.send_message(
                    peer_id,
                    _format_documents(docs, f"Результаты поиска: {len(docs)}"),
                    keyboard=build_navigation_keyboard(),
                )
                return
            result = await app["document_service"].smart_search(text)
            await vk_client.send_message(
                peer_id,
                _format_documents(result["all_results"], result["message"], result.get("llm_suggestions")),
                keyboard=build_navigation_keyboard(),
            )
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


async def handle_vk_action(
    app: web.Application,
    sender_id: int,
    peer_id: int,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    state = app["menu_state"]
    payload = payload or {}
    vk_client: VKAPIClient = app["vk_client"]
    service: DocumentService = app["document_service"]

    if action == "main_menu":
        state.reset(sender_id)
        await vk_client.send_message(peer_id, "Главное меню", keyboard=build_main_menu_keyboard())
        return

    if action == "back":
        previous = state.back(sender_id)
        await _show_screen(app, sender_id, peer_id, previous, payload)
        return

    if action == "open_search":
        state.push(sender_id, "search")
        await vk_client.send_message(peer_id, "Введите название документа, тег или ключевые слова.", keyboard=build_navigation_keyboard())
        return

    if action == "open_smart_search":
        state.push(sender_id, "smart_search")
        await vk_client.send_message(peer_id, "Введите запрос для умного поиска.", keyboard=build_navigation_keyboard())
        return

    if action == "open_filters":
        state.push(sender_id, "filters")
        await vk_client.send_message(peer_id, "Выберите критерий фильтрации:", keyboard=build_filter_menu_keyboard())
        return

    if action == "filter_mode":
        filter_name = payload.get("filter_name")
        state.push(sender_id, f"filter:{filter_name}")
        if filter_name == "tags":
            tags = await service.get_available_tags()
            if not tags:
                await vk_client.send_message(peer_id, "В базе пока нет тегов у документов.", keyboard=build_navigation_keyboard())
                return
            text = "Доступные теги:\n- " + "\n- ".join(tags)
            await vk_client.send_message(peer_id, text, keyboard=build_navigation_keyboard())
            return
        await vk_client.send_message(peer_id, f"Для фильтрации по {filter_name} введите значение после команды или просто напишите его в чат.", keyboard=build_navigation_keyboard())
        return

    if action == "open_document_list":
        state.push(sender_id, "document_list")
        await _show_document_list(service, vk_client, peer_id, page=1)
        return

    if action == "list_page":
        page = int(payload.get("page", 1))
        await _show_document_list(service, vk_client, peer_id, page=page)
        return

    if action == "open_upload":
        state.push(sender_id, "upload_waiting")
        await vk_client.send_message(
            peer_id,
            "Отправьте один файл документа. Я проверю формат, сохраню и добавлю в архив.",
            keyboard=build_navigation_keyboard(),
        )
        return

    if action == "confirm_upload":
        pending = app.get("pending_uploads", {}).get(sender_id)
        if not pending:
            await vk_client.send_message(peer_id, "Нет ожидающего файла для сохранения.")
            state.reset(sender_id)
            return
        result = await persist_pending_upload(app, sender_id, peer_id)
        await vk_client.send_message(peer_id, result, keyboard=build_main_menu_keyboard())
        state.reset(sender_id)
        return

    if action == "cancel_upload":
        app.get("pending_uploads", {}).pop(sender_id, None)
        state.reset(sender_id)
        await vk_client.send_message(peer_id, "Загрузка отменена.", keyboard=build_main_menu_keyboard())
        return

    if action == "open_document":
        doc_id = payload.get("doc_id")
        if doc_id:
            await _show_document_card(service, vk_client, peer_id, doc_id)
        return

    if action == "download_document":
        doc_id = payload.get("doc_id")
        if not doc_id:
            return
        file_data = await service.download_document(doc_id)
        if not file_data:
            await vk_client.send_message(peer_id, f"Файл документа {doc_id} не найден.")
            return
        content, file_name = file_data
        await vk_client.send_document(peer_id, content, file_name, f"{doc_id} — {file_name}")
        await vk_client.send_message(peer_id, "Файл отправлен.", keyboard=build_navigation_keyboard())
        return


async def _show_screen(
    app: web.Application,
    sender_id: int,
    peer_id: int,
    screen: str,
    payload: Optional[Dict[str, Any]],
) -> None:
    if screen == "main":
        await app["vk_client"].send_message(peer_id, "Главное меню", keyboard=build_main_menu_keyboard())
        return
    if screen == "search":
        await app["vk_client"].send_message(peer_id, "Введите название документа, тег или ключевые слова.", keyboard=build_navigation_keyboard())
        return
    if screen == "smart_search":
        await app["vk_client"].send_message(peer_id, "Введите запрос для умного поиска.", keyboard=build_navigation_keyboard())
        return
    if screen == "document_list":
        await _show_document_list(app["document_service"], app["vk_client"], peer_id, page=1)
        return
    if screen == "filters":
        await app["vk_client"].send_message(peer_id, "Выберите критерий фильтрации:", keyboard=build_filter_menu_keyboard())
        return
    if screen.startswith("filter:"):
        filter_name = screen.split(":", 1)[1]
        await app["vk_client"].send_message(peer_id, f"Параметр: {filter_name}. Введите значение для фильтра.", keyboard=build_navigation_keyboard())
        return
    if screen == "upload_waiting":
        await app["vk_client"].send_message(peer_id, "Отправьте файл документа.", keyboard=build_navigation_keyboard())
        return
    if screen == "upload_confirm":
        await app["vk_client"].send_message(peer_id, "Нажмите подтвердить, чтобы сохранить документ.", keyboard=build_confirm_upload_keyboard())
        return


async def _show_document_list(
    service: DocumentService,
    vk_client: VKAPIClient,
    peer_id: int,
    page: int = 1,
) -> None:
    docs, total = await service.get_document_list(page=max(page, 1), per_page=10)
    total_pages = max((total + 9) // 10, 1)
    title = f"Документы {page}/{total_pages} из {total}"
    if not docs:
        text = "В архиве пока нет документов."
    else:
        lines = [title]
        for index, doc in enumerate(docs, 1):
            lines.append(f"{(page - 1) * 10 + index}. {doc.doc_id} — {doc.title}")
        text = "\n".join(lines)
    await vk_client.send_message(
        peer_id,
        text,
        keyboard=build_document_list_keyboard(page, total_pages, docs),
    )


async def _send_document_by_doc(
    app: web.Application,
    vk_client: VKAPIClient,
    peer_id: int,
    doc: Any,
) -> bool:
    if not doc or not getattr(doc, "file_path", None):
        return False
    file_data = await app["document_service"].db.get_document_file(doc.doc_id)
    if not file_data:
        return False
    file_name = getattr(doc, "file_name", None) or f"{doc.doc_id}.pdf"
    await vk_client.send_document(peer_id, file_data, file_name, f"{doc.doc_id} — {doc.title}")
    return True


async def _show_document_card(
    service: DocumentService,
    vk_client: VKAPIClient,
    peer_id: int,
    doc_id: str,
) -> None:
    info = await service.get_document_info(doc_id)
    if not info:
        await vk_client.send_message(peer_id, f"Документ {doc_id} не найден.")
        return

    text = (
        f"Название: {info.get('title') or 'Без названия'}\n"
        f"ID: {info.get('doc_id')}\n"
        f"Тип: {info.get('doc_type') or 'не указан'}\n"
        f"Статус: {info.get('status') or 'не указан'}\n"
        f"Техпроцесс: {info.get('tech_process') or 'не указан'}\n"
        f"Версия: {info.get('version') or 'не указана'}\n"
        f"Теги: {info.get('tags') or 'нет'}\n"
        f"Описание: {info.get('description') or 'нет'}"
    )
    file_data = await service.download_document(doc_id)
    if file_data:
        content, file_name = file_data
        await vk_client.send_document(peer_id, content, file_name, f"{doc_id} — {file_name}")
    keyboard = {
        "one_time": False,
        "buttons": [
            [_button("📥 Получить файл", "download_document", doc_id=doc_id)],
            [_button("◀️ Назад", "back"), _button("🏠 Главное меню", "main_menu")],
        ],
    }
    await vk_client.send_message(peer_id, text, keyboard=keyboard)


async def prepare_upload_document(
    app: web.Application,
    sender_id: int,
    peer_id: int,
    attachment: Dict[str, Any],
) -> Dict[str, Any]:
    vk_client: VKAPIClient = app["vk_client"]
    service: DocumentService = app["document_service"]

    try:
        file_bytes = await vk_client.download_attachment(attachment)
    except Exception as exc:
        logger.exception("Ошибка скачивания вложения VK от %s", sender_id)
        return {"status": "error", "text": f"Не удалось скачать файл: {exc}"}

    doc = attachment.get("doc") if isinstance(attachment, dict) else None
    file_name = (doc or attachment).get("title") or (doc or attachment).get("file_name") or f"upload_{sender_id}.bin"
    _, ext = os.path.splitext(file_name)
    if not FileService.validate_file_extension(file_name):
        return {"status": "error", "text": "Недопустимый формат файла. Поддерживаются: .docx, .pdf, .dwg"}
    if not FileService.validate_file_size(len(file_bytes)):
        return {"status": "error", "text": "Файл слишком большой. Максимальный размер — 50 МБ."}

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    duplicate = await service.find_duplicate_document(file_name, file_hash)
    app.setdefault("pending_uploads", {})[sender_id] = {
        "file_name": file_name,
        "file_bytes": file_bytes,
        "file_hash": file_hash,
        "duplicate": duplicate,
    }

    if duplicate:
        return {
            "status": "pending",
            "text": (
                f"Возможно, такой документ уже существует: {duplicate.doc_id} — {duplicate.title}\n"
                f"Файл: {file_name}\n\n"
                "Проверьте данные и нажмите «Сохранить», чтобы добавить новый экземпляр в архив."
            ),
        }

    return {
        "status": "pending",
        "text": (
            f"Документ подготовлен к добавлению:\n"
            f"Название: {os.path.splitext(os.path.basename(file_name))[0]}\n"
            f"Формат: {ext.lower()}\n\n"
            "Нажмите «Сохранить», чтобы добавить в базу документов."
        ),
    }


async def persist_pending_upload(app: web.Application, sender_id: int, peer_id: int) -> str:
    pending = app.get("pending_uploads", {}).pop(sender_id)
    file_name = pending["file_name"]
    file_bytes = pending["file_bytes"]
    file_hash = pending["file_hash"]
    service: DocumentService = app["document_service"]

    safe_path = FileService.save_file(file_bytes, file_name)
    if not safe_path:
        return "Не удалось сохранить файл на сервере."

    doc_data = {
        "title": os.path.splitext(os.path.basename(file_name))[0],
        "doc_type": "Загруженный документ",
        "drawing_number": "",
        "version": "1.0",
        "tech_process": "",
        "status": "Активен",
        "file_path": safe_path,
        "file_name": os.path.basename(file_name),
        "tags": "uploaded,vk",
        "description": "Загружен через VK бот",
        "metadata_json": {
            "source": "vk_upload",
            "uploaded_by": sender_id,
            "sha256": file_hash,
            "extension": os.path.splitext(file_name)[1].lower(),
        },
    }

    document = await service.add_new_document(doc_data, file_content=file_bytes, user=str(sender_id))
    if not document:
        return "Файл сохранён, но не удалось добавить запись в БД. Проверьте данные документа."
    return f"✅ Документ сохранён: {document.doc_id} — {document.title}"


async def cancel_background_tasks(app: web.Application) -> None:
    tasks = list(app.get("tasks", set()))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


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