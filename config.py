"""
Конфигурация приложения.
Загружает настройки из .env файла и предоставляет доступ к ним.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent


def _resolve_project_path(raw_path: str, default_rel_path: str) -> str:
    """Возвращает абсолютный путь относительно корня проекта."""
    value = (raw_path or default_rel_path).strip()
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((BASE_DIR / path).resolve())


def _resolve_database_url(raw_url: str) -> str:
    """Нормализует относительный SQLite URL к абсолютному пути проекта."""
    default_url = f"sqlite+aiosqlite:///{_resolve_project_path('documents.db', 'documents.db')}"
    if not raw_url:
        return default_url

    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if raw_url.startswith(prefix):
            db_path = raw_url[len(prefix):]
            if db_path and not os.path.isabs(db_path):
                db_path = _resolve_project_path(db_path, "documents.db")
            return f"sqlite+aiosqlite:///{db_path}"

    return raw_url


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
    DATABASE_URL: str = _resolve_database_url(
        os.getenv("DATABASE_URL", "sqlite+aiosqlite:///documents.db")
    )

    # LLM (LM Studio)
    LLM_API_URL: str = os.getenv("LLM_API_URL", "http://127.0.0.1:60969/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-3-4b")

    # Файлы
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", 52428800))  # 50MB
    UPLOAD_DIR: str = _resolve_project_path(os.getenv("UPLOAD_DIR", "uploads/documents"), "uploads/documents")
    IMPORT_DIR: str = _resolve_project_path(os.getenv("IMPORT_DIR", "import_docs"), "import_docs")

    # Допустимые расширения файлов
    ALLOWED_EXTENSIONS: tuple = (".docx", ".pdf", ".dwg", ".xlsx")

    # Параметры поиска
    SEARCH_LIMIT: int = 20
    MIN_SEMANTIC_RESULTS: int = 2