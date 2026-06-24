"""
Конфигурация приложения.
Загружает настройки из .env файла и предоставляет доступ к ним.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Класс конфигурации приложения."""

    # Telegram
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")

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