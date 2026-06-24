"""
Обработчики inline-кнопок (callback data) для Telegram бота.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from services.document_service import DocumentService
from utils.logger import logger


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный обработчик всех callback-запросов от inline-кнопок.
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    service: DocumentService = context.bot_data.get("document_service")

    if not service:
        await query.edit_message_text("❌ Сервис недоступен.")
        return

    # ===== Меню =====
    if data == "menu_add":
        # Перенаправление на команду /add
        await query.edit_message_text(
            "📄 Используйте команду /add для добавления документа."
        )
        return

    elif data == "menu_list":
        docs, total = await service.get_document_list(page=1, per_page=10)
        if not docs:
            await query.edit_message_text("📋 В архиве пока нет документов.")
            return

        parts = [f"📋 <b>Показать все документы</b> (всего: {total})\n"]
        for i, doc in enumerate(docs[:10], 1):
            parts.append(
                f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
                f"   📌 {doc.doc_type or 'Не указан'} | 📊 {doc.status}"
            )

        keyboard = [[InlineKeyboardButton("➡️ Следующая страница", callback_data="list_2")], [InlineKeyboardButton("❌ Закрыть", callback_data="close")]]
        await query.edit_message_text(
            "\n".join(parts),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "menu_filter":
        # Показ фильтров
        keyboard = [
            [InlineKeyboardButton("📄 По типу", callback_data="filter_type")],
            [InlineKeyboardButton("📊 По статусу", callback_data="filter_status")],
            [InlineKeyboardButton("🔧 По техпроцессу", callback_data="filter_tech")],
            [InlineKeyboardButton("❌ Закрыть", callback_data="close")],
        ]
        await query.edit_message_text(
            "🔍 <b>Фильтрация документов</b>\n\nВыберите критерий:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "menu_stats":
        # Показ статистики
        stats = await service.get_statistics()
        parts = [
            "📊 <b>Статистика архива</b>\n",
            f"📦 Всего: {stats.get('total', 0)}\n",
        ]
        by_type = stats.get("by_type", {})
        if by_type:
            parts.append("\n📂 <b>По типам:</b>")
            for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
                parts.append(f"  • {t}: {c}")
        by_status = stats.get("by_status", {})
        if by_status:
            parts.append("\n📊 <b>По статусам:</b>")
            for s, c in sorted(by_status.items(), key=lambda x: -x[1]):
                parts.append(f"  • {s}: {c}")

        keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data="close")]]
        await query.edit_message_text(
            "\n".join(parts),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "menu_help":
        keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data="close")]]
        await query.edit_message_text(
            "📋 Используйте команду /help для получения справки.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ===== Фильтрация =====
    elif data == "filter_type":
        types = await service.get_available_types()
        keyboard = [
            [InlineKeyboardButton(t, callback_data=f"sel_type_{t}")]
            for t in types
        ]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="filter_cancel")])
        await query.edit_message_text(
            "📂 <b>Выберите тип документа:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "filter_status":
        statuses = await service.get_available_statuses()
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sel_status_{s}")]
            for s in statuses
        ]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="filter_cancel")])
        await query.edit_message_text(
            "📊 <b>Выберите статус:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "filter_tech":
        processes = await service.get_available_tech_processes()
        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"sel_tech_{p}")]
            for p in processes
        ]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="filter_cancel")])
        await query.edit_message_text(
            "🔧 <b>Выберите техпроцесс:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "filter_cancel":
        await query.edit_message_text("❌ Фильтрация отменена.")

    elif data.startswith("sel_type_"):
        doc_type = data.replace("sel_type_", "")
        docs = await service.filter_documents(doc_type=doc_type)
        await _show_filter_results(query, docs, f"📂 Тип: {doc_type}")
        # Отправляем файлы найденных документов
        await _send_callback_files(query, docs, service)

    elif data.startswith("sel_status_"):
        status = data.replace("sel_status_", "")
        docs = await service.filter_documents(status=status)
        await _show_filter_results(query, docs, f"📊 Статус: {status}")
        await _send_callback_files(query, docs, service)

    elif data.startswith("sel_tech_"):
        tech = data.replace("sel_tech_", "")
        docs = await service.filter_documents(tech_process=tech)
        await _show_filter_results(query, docs, f"🔧 Техпроцесс: {tech}")
        await _send_callback_files(query, docs, service)

    # ===== Скачивание =====
    elif data.startswith("download_"):
        doc_id = data.replace("download_", "")
        file_data = await service.download_document(doc_id)
        if file_data:
            content, file_name = file_data
            await query.message.reply_document(
                document=content,
                filename=file_name,
                caption=f"📄 {doc_id} — {file_name}"
            )
            await query.edit_message_reply_markup(None)
        else:
            await query.edit_message_text(
                f"❌ Файл для документа {doc_id} не найден."
            )

    # ===== Изменение статуса =====
    elif data.startswith("status_"):
        doc_id = data.replace("status_", "")
        statuses = ["Активен", "Архивный", "В работе", "Отменен"]
        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"set_status_{doc_id}_{s}")]
            for s in statuses
        ]
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="close")])
        await query.edit_message_text(
            f"📊 <b>Выберите новый статус для {doc_id}:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("set_status_"):
        parts = data.split("_", 3)
        if len(parts) == 4:
            _, _, doc_id, new_status = parts
            user = (update.effective_user.full_name
                    or update.effective_user.username
                    or "unknown")
            success, message = await service.change_status(doc_id, new_status, user)
            await query.edit_message_text(message)

    # ===== Пагинация =====
    elif data.startswith("list_"):
        page = int(data.replace("list_", ""))
        docs, total = await service.get_document_list(page=page, per_page=10)
        total_pages = (total + 9) // 10

        if not docs:
            await query.edit_message_text("📋 Нет документов на этой странице.")
            return

        parts = [
            f"📋 <b>Список документов</b> "
            f"(стр. {page}/{total_pages}, всего: {total})\n"
        ]
        for i, doc in enumerate(docs, 1):
            parts.append(
                f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
                f"   📌 {doc.doc_type or 'Не указан'} | "
                f"📊 {doc.status}"
            )

        keyboard = []
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton("⬅️", callback_data=f"list_{page - 1}")
            )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("➡️", callback_data=f"list_{page + 1}")
            )
        if nav_buttons:
            keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="close")])

        await query.edit_message_text(
            "\n".join(parts),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ===== Закрытие =====
    elif data == "close":
        await query.delete_message()


async def _send_callback_files(query, docs, service):
    """Отправка файлов найденных документов через callback."""
    sent_count = 0
    for doc in docs:
        if doc.file_path:
            file_data = await service.download_document(doc.doc_id)
            if file_data:
                content, file_name = file_data
                try:
                    await query.message.reply_document(
                        document=content,
                        filename=file_name,
                        caption=f"📄 {doc.doc_id} — {doc.title}"
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Ошибка отправки {doc.doc_id}: {e}")
            if sent_count >= 5:
                break
    if sent_count > 0:
        await query.message.reply_text(f"📎 Отправлено файлов: {sent_count}")


async def _show_filter_results(query, docs, header: str):
    """
    Отображение результатов фильтрации.

    Args:
        query: CallbackQuery объект.
        docs: Список документов.
        header: Заголовок результата.
    """
    if not docs:
        await query.edit_message_text(
            f"❌ {header}\n\nДокументов не найдено."
        )
        return

    parts = [f"✅ <b>{header}</b>\nНайдено: {len(docs)}\n"]
    for i, doc in enumerate(docs[:10], 1):
        parts.append(
            f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
            f"   📊 {doc.status} | 🔧 {doc.tech_process or 'Не указан'}"
        )

    if len(docs) > 10:
        parts.append(f"\n... и ещё {len(docs) - 10}")

    keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data="close")]]
    await query.edit_message_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )