"""
Точка входа в приложение Telegram бота для системы документооборота.
Инициализирует базу данных, сервисы и запускает бота.
"""
import os
import asyncio
import signal
import sys
from contextlib import suppress

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

from config import Config
from database.repository import DocumentDatabase
from services.llm_service import LLMProcessor
from utils.logger import logger

from handlers.commands import (
    start, menu, search_command, find_command, filter_command,
    get_command, download_command, list_command, status_command,
    add_command, add_name, add_type, add_number, add_version,
    add_tech_process, add_tags, add_description, add_file,
    add_confirm, cancel, stats_command, help_command, import_folder_command,
    ADD_NAME, ADD_TYPE, ADD_NUMBER, ADD_VERSION,
    ADD_TECH_PROCESS, ADD_TAGS, ADD_DESCRIPTION, ADD_FILE, CONFIRM,
)
from handlers.callbacks import handle_callback
from handlers.messages import handle_message, handle_voice, handle_photo, handle_document
from services.document_service import DocumentService


async def init_services():
    """
    Инициализация всех сервисов приложения.

    Returns:
        Кортеж (DocumentDatabase, DocumentService).
    """
    # Инициализация базы данных
    db = DocumentDatabase()
    await db.initialize()

    # Инициализация LLM
    llm = LLMProcessor(
        api_url=Config.LLM_API_URL,
        model=Config.LLM_MODEL
    )

    # Инициализация сервиса документов
    document_service = DocumentService(db=db, llm=llm)

    return db, document_service


async def setup_handlers(app: Application):
    """
    Настройка всех обработчиков команд и сообщений.

    Args:
        app: Экземпляр приложения Telegram бота.
    """
    # ===== Команды =====
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("filter", filter_command))
    app.add_handler(CommandHandler("get", get_command))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("import_folder", import_folder_command))

    # ===== Мастер добавления документа (ConversationHandler) =====
    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_command)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_type)],
            ADD_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number)],
            ADD_VERSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_version)],
            ADD_TECH_PROCESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_tech_process)
            ],
            ADD_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tags)],
            ADD_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)
            ],
            ADD_FILE: [
                MessageHandler(filters.Document.ALL, add_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_file),
            ],
            CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_confirm)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(add_conv_handler)

    # ===== Callback-запросы (inline-кнопки) =====
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ===== Обработчики сообщений =====
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info("✅ Все обработчики настроены")


async def shutdown(app: Application, db: DocumentDatabase, document_service: DocumentService):
    """Корректное завершение работы всех сервисов."""
    logger.info("🛑 Завершение работы...")
    try:
        await db.close()
    except Exception as e:
        logger.error(f"Ошибка закрытия БД: {e}")
    try:
        if hasattr(document_service.llm, 'close'):
            await document_service.llm.close()
    except Exception as e:
        logger.error(f"Ошибка закрытия LLM: {e}")
    try:
        await app.stop()
        await app.shutdown()
    except Exception as e:
        logger.error(f"Ошибка остановки бота: {e}")
    logger.info("✅ Бот остановлен")


async def schedule_folder_import(document_service: DocumentService):
    """Периодически импортирует новые файлы из папки хранения."""
    while True:
        try:
            await document_service.import_documents_from_folder(Config.UPLOAD_DIR)
        except Exception as exc:
            logger.error(f"Ошибка автоимпорта: {exc}")
        await asyncio.sleep(300)


async def main():
    """Главная функция запуска бота."""
    logger.info("🤖 Запуск бота системы документооборота...")

    # Проверка токена
    if not Config.TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN не задан в .env файле!")
        print(
            "❌ Ошибка: TELEGRAM_TOKEN не задан!\n"
            "Пожалуйста, укажите токен бота в файле .env:\n"
            "TELEGRAM_TOKEN=ваш_токен_бота"
        )
        return

    # Инициализация сервисов
    db, document_service = await init_services()

    # Создание приложения Telegram бота
    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()

    # Сохранение сервисов в bot_data для доступа из обработчиков
    app.bot_data["document_service"] = document_service
    app.bot_data["db"] = db

    # Настройка обработчиков
    await setup_handlers(app)

    # Инициализация приложения
    await app.initialize()

    logger.info("✅ Бот запущен и готов к работе!")
    print("🤖 Бот запущен! Нажмите Ctrl+C для остановки.")

    import_task = asyncio.create_task(schedule_folder_import(document_service))

    # Запуск поллинга
    try:
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "callback_query"])
        # Бесконечное ожидание (блокируем main)
        stop_signal = asyncio.Future()
        await stop_signal
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        print(f"❌ Критическая ошибка: {e}")
    finally:
        import_task.cancel()
        with suppress(asyncio.CancelledError):
            await import_task
        await shutdown(app, db, document_service)


if __name__ == "__main__":
    # Создание необходимых директорий
    os.makedirs("logs", exist_ok=True)
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

    # Запуск
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем.")