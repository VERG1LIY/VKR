"""
Обработчики произвольных текстовых сообщений.
Реализует RAG (Retrieval-Augmented Generation) для ответов на вопросы пользователя.
"""
import re

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from services.document_service import DocumentService
from utils.logger import logger


_SEARCH_WORDS = (
    "найди", "найти", "ищи", "поиск", "поискать", "дай", "покажи",
    "показать", "открой", "посмотри", "документ", "документы", "чертёж",
    "чертеж", "техпроцесс", "спецификацию", "инструкцию", "файл", "файлы",
    "схему", "чертежи", "спецификации"
)

_SEARCH_HINTS = (
    "документ", "документы", "чертеж", "чертёж", "техпроцесс", "спецификация",
    "инструкция", "схема", "файл", "файлы", "архив"
)


def _looks_like_search_request(text: str) -> bool:
    """Определяет, выглядит ли обычный текст как запрос на поиск."""
    normalized = re.sub(r"[^а-яa-z0-9]+", " ", text.lower()).strip()
    if not normalized:
        return False

    words = set(normalized.split())
    if any(word in words for word in _SEARCH_WORDS):
        return True

    if len(words) <= 3:
        return False

    return any(word in normalized for word in _SEARCH_HINTS)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик произвольных текстовых сообщений.
    Использует LLM с RAG для ответа на запрос пользователя.

    Анализирует текст и ищет релевантные документы в базе данных,
    затем формирует ответ с помощью локальной LLM.
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    service: DocumentService = context.bot_data.get("document_service")

    if not service:
        await update.message.reply_text("❌ Сервис недоступен. Попробуйте позже.")
        return

    # Показываем индатор "печатает"
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    if _looks_like_search_request(text):
        status_msg = await update.message.reply_text(
            "🔍 <i>Анализирую запрос и ищу документы...</i>",
            parse_mode=ParseMode.HTML
        )
        try:
            response = await service.process_free_text(text)
            await status_msg.edit_text(
                response[:4000] if len(response) > 4000 else response,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            await status_msg.edit_text(
                "❌ Не удалось обработать запрос. Попробуйте /find или /search."
            )
        return

    # Обычный текст без явного поиска — пробуем ответить через LLM как помощник
    status_msg = await update.message.reply_text(
        "💬 <i>Обрабатываю ваш текст...</i>",
        parse_mode=ParseMode.HTML
    )

    try:
        response = await service.process_free_text(text)
        await status_msg.edit_text(
            response[:4000] if len(response) > 4000 else response,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

        # Fallback: базовый поиск без LLM
        docs = await service.search_documents(text)
        if docs:
            parts = [f"🔍 <b>Найденные документы по запросу:</b>\n"]
            for i, doc in enumerate(docs[:5], 1):
                parts.append(
                    f"{i}. <b>{doc.doc_id}</b> — {doc.title}\n"
                    f"   📌 {doc.doc_type or 'Не указан'} | "
                    f"📊 {doc.status}"
                )
            parts.append(
                "\n💡 <i>Используйте /find для умного поиска с ИИ</i>"
            )
            await status_msg.edit_text(
                "\n".join(parts),
                parse_mode=ParseMode.HTML
            )
        else:
            await status_msg.edit_text(
                "❌ По вашему запросу ничего не найдено.\n"
                "Попробуйте:\n"
                "• /search <текст> — поиск по документам\n"
                "• /find <текст> — умный поиск с ИИ\n"
                "• /filter — фильтрация по критериям"
            )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик голосовых сообщений.
    (Заглушка — голосовые сообщения не поддерживаются)
    """
    await update.message.reply_text(
        "🎤 Голосовые сообщения пока не поддерживаются.\n"
        "Пожалуйста, отправьте текстовый запрос."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик фотографий.
    (Заглушка — изображения не поддерживаются)
    """
    await update.message.reply_text(
        "🖼️ Обработка изображений пока не поддерживается.\n"
        "Пожалуйста, отправьте текстовый запрос или файл документа."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик файлов, отправленных вне мастера добавления.
    Предлагает использовать /add для добавления документа.
    """
    await update.message.reply_text(
        "📄 Вы отправили файл. Чтобы добавить его как документ:\n"
        "• Используйте /add — мастер добавления документа\n"
        "• Отправьте /add прямо сейчас, чтобы начать"
    )