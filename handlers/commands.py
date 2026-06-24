"""
Обработчики команд Telegram бота.
Реализует все команды из main.py с использованием SQL базы данных.
"""
import os
import html
from typing import Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.document_service import DocumentService
from services.file_service import FileService
from utils.logger import logger
from utils.validators import Validators
from config import Config


async def import_folder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Импорт всех файлов из папки хранения в индекс документов без использования бота."""
    folder = context.args[0] if context.args else Config.UPLOAD_DIR
    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    await update.message.reply_text(f"📦 Сканирую папку {folder}...")
    imported = await service.import_documents_from_folder(folder)
    await update.message.reply_text(
        f"✅ Импорт завершён. Добавлено документов: {imported}"
    )

# Состояния для ConversationHandler (мастер добавления документа)
(
    ADD_NAME, ADD_TYPE, ADD_NUMBER, ADD_VERSION,
    ADD_TECH_PROCESS, ADD_TAGS, ADD_DESCRIPTION, ADD_FILE, CONFIRM
) = range(9)

# Временное хранилище данных для мастера добавления
_add_data: dict = {}


def _escape_html(text: Optional[str]) -> str:
    """Экранирует текст для Telegram HTML parse mode."""
    return html.escape(text or "", quote=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start.
    Приветствие и инструкция по использованию бота.
    """
    user = update.effective_user
    first_name = _escape_html(user.first_name or user.username or "пользователь")
    welcome_text = (
        f"👋 Добро пожаловать, {first_name}!\n\n"
        "Я — бот системы документооборота машиностроительного предприятия. "
        "Помогаю искать, добавлять и управлять технической документацией.\n\n"
        "📋 <b>Основные команды:</b>\n"
        "/menu — Главное меню\n"
        "/search &lt;текст&gt; — Поиск документов\n"
        "/find &lt;текст&gt; — Умный поиск с ИИ\n"
        "/filter — Фильтрация документов\n"
        "/get &lt;doc_id&gt; — Информация о документе\n"
        "/download &lt;doc_id&gt; — Скачать файл\n"
        "/list — Список всех документов\n"
        "/add — Добавить новый документ\n"
        "/status &lt;doc_id&gt; &lt;статус&gt; — Изменить статус\n"
        "/stats — Статистика архива\n"
        "/help — Справка\n\n"
        "💡 <i>Просто отправьте текст — я найду документы через ИИ!</i>"
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=await _get_main_menu_keyboard()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /menu.
    Показывает главное меню с кнопками.
    """
    await update.message.reply_text(
        "📋 <b>Главное меню</b>\n\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=await _get_main_menu_keyboard()
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /search.
    Простой поиск по названию, описанию и тегам + отправка файлов.
    """
    query = " ".join(context.args) if context.args else ""

    if not query:
        await update.message.reply_text(
            "❌ Укажите текст для поиска.\n"
            "Пример: /search вал приводной"
        )
        return

    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    await update.message.reply_text(
        f"🔍 Ищу документы по запросу: <b>{_escape_html(query)}</b>...",
        parse_mode=ParseMode.HTML,
    )

    docs = await service.search_documents(query)

    if not docs:
        await update.message.reply_text(
            f"❌ По запросу \"{query}\" ничего не найдено.\n"
            "Попробуйте /find для умного поиска с ИИ."
        )
        return

    # Отправляем список
    await _send_document_list(update, docs, f"✅ Найдено {len(docs)} документов:")

    # Отправляем файлы всех найденных документов
    await _send_document_files(update, docs, service)


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /find.
    Умный поиск с использованием LLM.
    """
    query = " ".join(context.args) if context.args else ""

    if not query:
        await update.message.reply_text(
            "❌ Укажите текст для поиска.\n"
            "Пример: /find вал с шпоночным пазом"
        )
        return

    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    await update.message.reply_text(
        f"🔍 Выполняю умный поиск: <b>{_escape_html(query)}</b>...",
        parse_mode=ParseMode.HTML,
    )

    result = await service.smart_search(query)

    if not result["all_results"]:
        await update.message.reply_text(
            f"❌ По запросу \"{query}\" ничего не найдено.\n"
            "Попробуйте изменить формулировку."
        )
        return

    # Формирование ответа
    parts = [f"<b>{result['message']}</b>\n"]

    if result["llm_suggestions"]:
        parts.append(
            "💡 <b>ИИ предлагает синонимы:</b> "
            f"{', '.join(result['llm_suggestions'])}\n"
        )

    for i, doc in enumerate(result["all_results"][:5], 1):
        parts.append(
            f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
            f"   📌 Тип: {doc.doc_type or 'Не указан'} | "
            f"📊 Статус: {doc.status}\n"
            f"   🔧 Техпроцесс: {doc.tech_process or 'Не указан'}"
        )

    if len(result["all_results"]) > 5:
        parts.append(f"\n... и ещё {len(result['all_results']) - 5} документов.")

    if result["best_match"]:
        doc = result["best_match"]
        parts.append(
            f"\n🏆 <b>Наиболее релевантный:</b> {doc.doc_id} — {doc.title}\n"
            f"/get {doc.doc_id} — подробнее"
        )

    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)

    # Отправляем файл наиболее релевантного документа
    if result["best_match"] and result["best_match"].file_path:
        file_data = await service.download_document(result["best_match"].doc_id)
        if file_data:
            content, file_name = file_data
            try:
                await update.message.reply_document(
                    document=content,
                    filename=file_name,
                    caption=f"🏆 {result['best_match'].doc_id} — {result['best_match'].title}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки best_match: {e}")


async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /filter.
    Показывает inline-кнопки для фильтрации документов.
    """
    keyboard = [
        [InlineKeyboardButton("📄 По типу", callback_data="filter_type")],
        [InlineKeyboardButton("📊 По статусу", callback_data="filter_status")],
        [InlineKeyboardButton("🔧 По техпроцессу", callback_data="filter_tech")],
        [InlineKeyboardButton("❌ Отмена", callback_data="filter_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🔍 <b>Фильтрация документов</b>\n\nВыберите критерий:",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /get.
    Получение полной информации о документе + отправка файла.
    """
    doc_id = " ".join(context.args) if context.args else ""

    if not doc_id:
        await update.message.reply_text(
            "❌ Укажите ID документа.\n"
            "Пример: /get DOC-2024-001"
        )
        return

    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    info = await service.get_document_info(doc_id)

    if not info:
        await update.message.reply_text(
            f"❌ Документ {doc_id} не найден.\n"
            "Попробуйте /search для поиска."
        )
        return

    # Формирование карточки документа
    card = (
        f"📄 <b>Документ: {_escape_html(info['doc_id'])}</b>\n"
        f"{'━' * 30}\n"
        f"📌 <b>Название:</b> {_escape_html(info.get('title', 'Не указано'))}\n"
        f"📂 <b>Тип:</b> {_escape_html(info.get('doc_type', 'Не указан'))}\n"
        f"🔢 <b>Номер чертежа:</b> {_escape_html(info.get('drawing_number', 'Не указан'))}\n"
        f"📊 <b>Версия:</b> {_escape_html(info.get('version', 'Не указана'))}\n"
        f"🔧 <b>Техпроцесс:</b> {_escape_html(info.get('tech_process', 'Не указан'))}\n"
        f"📊 <b>Статус:</b> {_escape_html(info.get('status', 'Не указан'))}\n"
        f"🏷️ <b>Теги:</b> {_escape_html(info.get('tags', 'Нет тегов'))}\n"
        f"📝 <b>Описание:</b> {_escape_html(info.get('description', 'Нет описания'))}\n"
        f"👤 <b>Создал:</b> {_escape_html(info.get('created_by', 'Неизвестно'))}\n"
        f"📅 <b>Создан:</b> {_escape_html(info.get('created_at', 'Неизвестно'))}\n"
        f"📅 <b>Обновлён:</b> {_escape_html(info.get('updated_at', 'Неизвестно'))}\n"
    )

    if info.get("file_size"):
        card += f"📎 <b>Размер файла:</b> {_escape_html(str(info['file_size']))}\n"

    # Сначала отправляем карточку
    await update.message.reply_text(card, parse_mode=ParseMode.HTML)

    # Отправляем файл документа если есть
    if info.get("file_path"):
        file_data = await service.download_document(doc_id)
        if file_data:
            content, file_name = file_data
            try:
                await update.message.reply_document(
                    document=content,
                    filename=file_name,
                    caption=f"📄 {doc_id} — {file_name}"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки файла: {e}")
                await update.message.reply_text(
                    "❌ Не удалось отправить файл. Возможно, он слишком большой."
                )
        else:
            await update.message.reply_text(
                "⚠️ Файл документа указан в БД, но не найден на диске."
            )
    else:
        await update.message.reply_text(
            "📎 К документу не прикреплён файл."
        )


async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /download.
    Скачивание файла документа.
    """
    doc_id = " ".join(context.args) if context.args else ""

    if not doc_id:
        await update.message.reply_text(
            "❌ Укажите ID документа.\n"
            "Пример: /download DOC-2024-001"
        )
        return

    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    await update.message.reply_text(f"📎 Загружаю файл документа {doc_id}...")

    file_data = await service.download_document(doc_id)

    if not file_data:
        await update.message.reply_text(
            f"❌ Файл для документа {doc_id} не найден."
        )
        return

    content, file_name = file_data

    try:
        await update.message.reply_document(
            document=content,
            filename=file_name,
            caption=f"📄 {doc_id} — {file_name}"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        await update.message.reply_text(
            "❌ Ошибка при отправке файла. Возможно, файл слишком большой."
        )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /list.
    Список всех документов с пагинацией.
    """
    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    # Получаем номер страницы из аргументов
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])

    docs, total = await service.get_document_list(page=page, per_page=10)

    if not docs:
        await update.message.reply_text(
            "📋 В архиве пока нет документов.\n"
            "Используйте /add для добавления."
        )
        return

    total_pages = (total + 9) // 10

    parts = [f"📋 <b>Список документов</b> (стр. {page}/{total_pages}, всего: {total})\n"]

    for i, doc in enumerate(docs, 1):
        parts.append(
            f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
            f"   📌 {doc.doc_type or 'Не указан'} | "
            f"📊 {doc.status} | "
            f"🔧 {doc.tech_process or 'Не указан'}"
        )

    # Кнопки пагинации
    keyboard = []
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Назад", callback_data=f"list_{page - 1}")
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton("Вперёд ➡️", callback_data=f"list_{page + 1}")
        )
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await update.message.reply_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /status.
    Изменение статуса документа.
    """
    args = context.args if context.args else []

    if len(args) < 2:
        await update.message.reply_text(
            "❌ Укажите ID документа и новый статус.\n"
            "Пример: /status DOC-2024-001 Архивный\n\n"
            "Допустимые статусы: Активен, Архивный, В работе, Отменен"
        )
        return

    doc_id = args[0]
    new_status = " ".join(args[1:])

    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    user = update.effective_user.full_name or update.effective_user.username
    success, message = await service.change_status(doc_id, new_status, user)

    await update.message.reply_text(message)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /add.
    Запуск мастера добавления нового документа.
    """
    user_id = update.effective_user.id
    _add_data[user_id] = {}

    await update.message.reply_text(
        "📄 <b>Добавление нового документа</b>\n\n"
        "Шаг 1 из 8: Введите <b>название документа</b>\n"
        "(или отправьте /cancel для отмены)\n\n"
        "💡 Для прямой загрузки файлов в папку хранения используйте /import_folder",
        parse_mode=ParseMode.HTML
    )

    return ADD_NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Получение названия документа."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    is_valid, error = Validators.validate_title(text)
    if not is_valid:
        await update.message.reply_text(f"❌ {error}\nПопробуйте снова:")
        return ADD_NAME

    _add_data[user_id]["title"] = text

    await update.message.reply_text(
        "✅ Название сохранено!\n\n"
        "Шаг 2 из 8: Выберите <b>тип документа</b>:\n"
        "Чертеж, Техпроцесс, Спецификация, Инструкция, Схема, Расчет\n"
        "(или отправьте '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_TYPE


async def add_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: Получение типа документа."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text != "-":
        is_valid, error = Validators.validate_doc_type(text)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nПопробуйте снова:")
            return ADD_TYPE
        _add_data[user_id]["doc_type"] = text
    else:
        _add_data[user_id]["doc_type"] = None

    await update.message.reply_text(
        "✅ Тип сохранён!\n\n"
        "Шаг 3 из 8: Введите <b>номер чертежа по ЕСКД</b>\n"
        "(или отправьте '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_NUMBER


async def add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Получение номера чертежа."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    _add_data[user_id]["drawing_number"] = text if text != "-" else None

    await update.message.reply_text(
        "✅ Номер чертежа сохранён!\n\n"
        "Шаг 4 из 8: Введите <b>версию документа</b>\n"
        "(например: 1.0, 2.1; или '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_VERSION


async def add_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: Получение версии документа."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    _add_data[user_id]["version"] = text if text != "-" else "1.0"

    await update.message.reply_text(
        "✅ Версия сохранена!\n\n"
        "Шаг 5 из 8: Выберите <b>техпроцесс</b>:\n"
        "Токарная, Фрезерная, Сверлильная, Шлифовальная,\n"
        "Сварочная, Сборочная, Термическая, Гальваническая\n"
        "(или отправьте '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_TECH_PROCESS


async def add_tech_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 5: Получение техпроцесса."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text != "-":
        is_valid, error = Validators.validate_tech_process(text)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nПопробуйте снова:")
            return ADD_TECH_PROCESS
        _add_data[user_id]["tech_process"] = text
    else:
        _add_data[user_id]["tech_process"] = None

    await update.message.reply_text(
        "✅ Техпроцесс сохранён!\n\n"
        "Шаг 6 из 8: Введите <b>теги</b> через запятую\n"
        "(например: вал, привод, сталь45; или '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_TAGS


async def add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 6: Получение тегов."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    _add_data[user_id]["tags"] = text if text != "-" else None

    await update.message.reply_text(
        "✅ Теги сохранены!\n\n"
        "Шаг 7 из 8: Введите <b>описание документа</b>\n"
        "(или отправьте '-' чтобы пропустить)",
        parse_mode=ParseMode.HTML
    )
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 7: Получение описания."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    _add_data[user_id]["description"] = text if text != "-" else None

    await update.message.reply_text(
        "✅ Описание сохранено!\n\n"
        "Шаг 8 из 8: Отправьте <b>файл документа</b>\n"
        "(.docx, .pdf, .dwg; макс. 50 МБ)\n"
        "или отправьте '-' чтобы пропустить",
        parse_mode=ParseMode.HTML
    )
    return ADD_FILE


async def add_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 8: Получение файла документа."""
    user_id = update.effective_user.id
    data = _add_data.get(user_id, {})

    # Проверка, отправил ли пользователь файл
    if update.message.document:
        file = update.message.document
        file_name = file.file_name or "document.bin"

        # Валидация файла
        is_valid, error = Validators.validate_file(file_name, file.file_size)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nПопробуйте другой файл или отправьте '-'")
            return ADD_FILE

        # Скачивание файла
        try:
            file_obj = await file.get_file()
            file_content = await file_obj.download_as_bytearray()
            data["file_content"] = bytes(file_content)
            data["file_name"] = file_name
        except Exception as e:
            logger.error(f"Ошибка скачивания файла: {e}")
            await update.message.reply_text("❌ Ошибка при загрузке файла. Попробуйте снова.")
            return ADD_FILE
    elif update.message.text and update.message.text.strip() == "-":
        data["file_content"] = None
        data["file_name"] = None
    else:
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте файл или '-' для пропуска."
        )
        return ADD_FILE

    # Показ подтверждения
    await _show_confirmation(update, data)
    return CONFIRM


async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и сохранение документа."""
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()

    if text == "да":
        data = _add_data.get(user_id, {})
        service: DocumentService = context.bot_data.get("document_service")

        if not service:
            await update.message.reply_text("❌ Сервис недоступен.")
            return ConversationHandler.END

        user_name = update.effective_user.full_name or update.effective_user.username

        await update.message.reply_text("⏳ Сохраняю документ...")

        doc = await service.add_new_document(
            data=data,
            file_content=data.get("file_content"),
            user=user_name
        )

        if doc:
            await update.message.reply_text(
                f"✅ <b>Документ успешно создан!</b>\n"
                f"ID: {doc.doc_id}\n"
                f"Название: {doc.title}\n\n"
                f"/get {doc.doc_id} — просмотреть",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text("❌ Ошибка при создании документа.")

        # Очистка временных данных
        _add_data.pop(user_id, None)
        return ConversationHandler.END

    elif text == "нет":
        _add_data.pop(user_id, None)
        await update.message.reply_text(
            "❌ Добавление отменено.\n"
            "Используйте /add чтобы начать заново."
        )
        return ConversationHandler.END

    else:
        await update.message.reply_text(
            "Пожалуйста, ответьте <b>Да</b> или <b>Нет</b>",
            parse_mode=ParseMode.HTML
        )
        return CONFIRM


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущей операции."""
    user_id = update.effective_user.id
    _add_data.pop(user_id, None)

    await update.message.reply_text(
        "❌ Операция отменена.",
        reply_markup=await _get_main_menu_keyboard()
    )
    return ConversationHandler.END


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /stats.
    Статистика архива документов.
    """
    service: DocumentService = context.bot_data.get("document_service")
    if not service:
        await update.message.reply_text("❌ Сервис недоступен.")
        return

    await update.message.reply_text("📊 Загружаю статистику...")

    stats = await service.get_statistics()

    parts = [
        "📊 <b>Статистика архива документов</b>\n",
        f"📦 <b>Всего документов:</b> {stats.get('total', 0)}\n",
    ]

    # По типам
    by_type = stats.get("by_type", {})
    if by_type:
        parts.append(f"\n📂 <b>По типам:</b>")
        for doc_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            parts.append(f"  • {doc_type}: {count}")

    # По статусам
    by_status = stats.get("by_status", {})
    if by_status:
        parts.append(f"\n📊 <b>По статусам:</b>")
        for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
            parts.append(f"  • {status}: {count}")

    # По техпроцессам
    by_tp = stats.get("by_tech_process", {})
    if by_tp:
        parts.append(f"\n🔧 <b>По техпроцессам:</b>")
        for tp, count in sorted(by_tp.items(), key=lambda x: -x[1]):
            parts.append(f"  • {tp}: {count}")

    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /help.
    Справка по всем командам.
    """
    help_text = (
        "📋 <b>Справка по командам</b>\n\n"
        "<b>Основные:</b>\n"
        "/start — Приветствие и инструкция\n"
        "/menu — Главное меню\n"
        "/help — Эта справка\n\n"
        "<b>Поиск:</b>\n"
        "/search <текст> — Поиск по названию/описанию\n"
        "/find <текст> — Умный поиск с ИИ (синонимы, ранжирование)\n"
        "/filter — Фильтрация по типу, статусу, техпроцессу\n\n"
        "<b>Работа с документами:</b>\n"
        "/get <doc_id> — Информация о документе\n"
        "/download <doc_id> — Скачать файл\n"
        "/list [страница] — Список всех документов\n"
        "/add — Мастер добавления документа\n"
        "/status <doc_id> <статус> — Изменить статус\n\n"
        "<b>Прочее:</b>\n"
        "/stats — Статистика архива\n\n"
        "💡 <i>Просто отправьте текст — я найду документы через ИИ!</i>"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


# ========== Вспомогательные функции ==========

async def _send_document_files(
    update: Update, docs: list, service: DocumentService
):
    """Отправка файлов найденных документов."""
    sent_count = 0
    for doc in docs:
        if doc.file_path:
            file_data = await service.download_document(doc.doc_id)
            if file_data:
                content, file_name = file_data
                try:
                    await update.message.reply_document(
                        document=content,
                        filename=file_name,
                        caption=f"📄 {doc.doc_id} — {doc.title}"
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Ошибка отправки {doc.doc_id}: {e}")
            if sent_count >= 5:  # Отправляем максимум 5 файлов за раз
                break
    
    if sent_count > 0:
        await update.message.reply_text(
            f"📎 Отправлено файлов: {sent_count}"
        )


async def _get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры главного меню."""
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📄 Добавить документ", callback_data="menu_add")],
        [InlineKeyboardButton("📋 Показать все документы", callback_data="menu_list")],
        [InlineKeyboardButton("🔧 Фильтр", callback_data="menu_filter")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu_stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _send_document_list(
    update: Update, docs: list, header: str
):
    """Отправка списка документов пользователю."""
    parts = [f"<b>{_escape_html(header)}</b>\n"]

    for i, doc in enumerate(docs[:10], 1):
        parts.append(
            f"{i}. <b>{_escape_html(doc.doc_id)}</b> — {_escape_html(doc.title)}\n"
            f"   📌 {_escape_html(doc.doc_type or 'Не указан')} | "
            f"📊 {_escape_html(doc.status)} | "
            f"🔧 {_escape_html(doc.tech_process or 'Не указан')}"
        )

    if len(docs) > 10:
        parts.append(f"\n... и ещё {len(docs) - 10} документов.")
        parts.append("Используйте /list для полного списка.")

    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def _show_confirmation(update: Update, data: dict):
    """Показ подтверждения перед сохранением документа."""
    text = (
        "📄 <b>Проверьте данные документа:</b>\n\n"
        f"📌 <b>Название:</b> {_escape_html(data.get('title', 'Не указано'))}\n"
        f"📂 <b>Тип:</b> {_escape_html(data.get('doc_type', 'Не указан'))}\n"
        f"🔢 <b>Номер чертежа:</b> {_escape_html(data.get('drawing_number', 'Не указан'))}\n"
        f"📊 <b>Версия:</b> {_escape_html(data.get('version', '1.0'))}\n"
        f"🔧 <b>Техпроцесс:</b> {_escape_html(data.get('tech_process', 'Не указан'))}\n"
        f"🏷️ <b>Теги:</b> {_escape_html(data.get('tags', 'Нет тегов'))}\n"
        f"📝 <b>Описание:</b> {_escape_html(data.get('description', 'Нет описания'))}\n"
        f"📎 <b>Файл:</b> {_escape_html('Прикреплён' if data.get('file_content') else 'Нет файла')}\n\n"
        "Всё верно? Отправьте <b>Да</b> для сохранения или <b>Нет</b> для отмены."
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)