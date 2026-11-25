"""Запуск системы документооборота через VK Callback API."""
import os
import asyncio

from aiohttp import web

from config import Config
from database.repository import DocumentDatabase
from services.llm_service import LLMProcessor
from services.vk_api import VKAPIClient
from utils.logger import logger
from services.document_service import DocumentService
from handlers.vk_callback import create_vk_app


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
    if not await llm.is_available():
        logger.warning(
            "Начальная проверка LLM не прошла; бот повторит подключение при обработке запросов."
        )

    # Ициализация сервиса документов
    document_service = DocumentService(db=db, llm=llm)
    repaired_files = await document_service.repair_missing_file_paths(Config.UPLOAD_DIR)
    if repaired_files:
        logger.info("Восстановлены пути к файлам документов: %s", repaired_files)
    repaired_imports = await document_service.repair_missing_file_paths(Config.IMPORT_DIR)
    if repaired_imports:
        logger.info("Восстановлены пути к файлам из папки импорта: %s", repaired_imports)
    imported_documents = await document_service.import_documents_from_folder(Config.IMPORT_DIR)
    if imported_documents:
        logger.info("Импортированы документы из папки импорта: %s", imported_documents)

    return db, document_service


async def main():
    """Запускает HTTP Callback endpoint и фоновые задачи."""
    logger.info("Запуск VK Callback-бота документооборота...")

    missing = [
        name for name, value in (
            ("VK_ACCESS_TOKEN", Config.VK_ACCESS_TOKEN),
            ("VK_CALLBACK_SECRET", Config.VK_CALLBACK_SECRET),
            ("VK_CONFIRMATION_CODE", Config.VK_CONFIRMATION_CODE),
        ) if not value
    ]
    if missing:
        logger.error("Не заданы настройки: %s", ", ".join(missing))
        print("Заполните в .env: " + ", ".join(missing))
        return

    db, document_service = await init_services()
    vk_client = VKAPIClient(Config.VK_ACCESS_TOKEN, Config.VK_API_VERSION)
    app = create_vk_app(db, document_service, vk_client)
    runner = web.AppRunner(app)
    try:
        await runner.setup()
        site = web.TCPSite(runner, Config.HOST, Config.PORT)
        await site.start()
        public_path = Config.VK_CALLBACK_PATH.rstrip("/") or ""
        callback_url = f"{public_path}/" if public_path else "/"
        logger.info("VK Callback endpoint слушает %s:%s%s", Config.HOST, Config.PORT, callback_url)
        print(f"VK Callback-бот запущен на {Config.HOST}:{Config.PORT}{callback_url}")
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await vk_client.close()
        await db.close()
        await document_service.llm.close()
        logger.info("VK Callback-бот остановлен")


if __name__ == "__main__":
    # Создание необходимых директорий
    os.makedirs("logs", exist_ok=True)
    os.makedirs(Config.UPLOAD_DIR, exist_ok=True)

    # Запуск
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем.")