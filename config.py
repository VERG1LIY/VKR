"""
Конфигурация приложения.
Загружает настройки из .env файла и предоставляет доступ к ним.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Класс конфигурации приложения."""

    # VK Callback API
    VK_ACCESS_TOKEN: str = os.getenv("VK_ACCESS_TOKEN", "")
    VK_CALLBACK_SECRET: str = os.getenv("VK_CALLBACK_SECRET", "")
    VK_CONFIRMATION_CODE: str = os.getenv("VK_CONFIRMATION_CODE", "")
    VK_API_VERSION: str = os.getenv("VK_API_VERSION", "5.199")
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "3000"))
    VK_CALLBACK_PATH: str = os.getenv("VK_CALLBACK_PATH", "/")
    # Список администраторов, которым разрешены только специальные операции.
    # Для загрузки документов всем пользователям текущее поведение: VK_ADMIN_IDS не блокирует open_upload.
    VK_ADMIN_IDS: tuple[int, ...] = tuple(
        int(item.strip()) for item in os.getenv("VK_ADMIN_IDS", "").split(",") if item.strip()
    )

    # База данных
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///documents.db"
    )

    # LLM (LM Studio)
    LLM_API_URL: str = os.getenv("LLM_API_URL", "http://localhost:1234/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-3-4b")

    # Файлы
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", 52428800))  # 50MB
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads/documents")

    # Допустимые расширения файлов
    ALLOWED_EXTENSIONS: tuple = (".docx", ".pdf", ".dwg")

    # Параметры поиска
    SEARCH_LIMIT: int = 20
    MIN_SEMANTIC_RESULTS: int = 2