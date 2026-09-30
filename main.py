"""Запуск системы документооборота через VK Callback API."""
import os
import asyncio
from contextlib import suppress

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
        logger.warning("LM Studio недоступен по адресу %s; бот будет работать без ИИ.", Config.LLM_API_URL)

    # Ициализация сервиса документов
    document_service = DocumentService(db=db, llm=llm)

    return db, document_service


async def schedule_folder_import(document_service: DocumentService):
    """Периодически импортирует новые файлы из папки хранения."""
    while True:
        try:
            await document_service.import_documents_from_folder(Config.UPLOAD_DIR)
        except Exception as exc:
            logger.error(f"Ошибка автоимпорта: {exc}")
        await asyncio.sleep(300)


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
    import_task = None
    try:
        await runner.setup()
        site = web.TCPSite(runner, Config.HOST, Config.PORT)
        await site.start()
        public_path = Config.VK_CALLBACK_PATH.rstrip("/") or ""
        callback_url = f"{public_path}/" if public_path else "/"
        logger.info("VK Callback endpoint слушает %s:%s%s", Config.HOST, Config.PORT, callback_url)
        print(f"VK Callback-бот запущен на {Config.HOST}:{Config.PORT}{callback_url}")
        import_task = asyncio.create_task(schedule_folder_import(document_service))
        await asyncio.Event().wait()
    finally:
        if import_task:
            import_task.cancel()
            with suppress(asyncio.CancelledError):
                await import_task
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