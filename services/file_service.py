"""
Сервис для работы с файлами документов.
Обеспечивает сохранение, загрузку и валидацию файлов.
"""
import os
from datetime import datetime
from typing import Optional

from config import Config


class FileService:
    """Сервис для работы с файлами технической документации."""

    @staticmethod
    def validate_file_size(file_size: int) -> bool:
        """
        Проверка размера файла.

        Args:
            file_size: Размер файла в байтах.

        Returns:
            True если размер допустим, False если превышен.
        """
        max_size = Config.MAX_FILE_SIZE
        if file_size > max_size:
            return False
        return True

    @staticmethod
    def validate_file_extension(filename: str) -> bool:
        """
        Проверка расширения файла.

        Args:
            filename: Имя файла.

        Returns:
            True если расширение допустимо, False если нет.
        """
        _, ext = os.path.splitext(filename.lower())
        return ext in Config.ALLOWED_EXTENSIONS

    @staticmethod
    def save_file(file_content: bytes, original_name: str) -> Optional[str]:
        """
        Сохранение файла на диск.

        Args:
            file_content: Содержимое файла в байтах.
            original_name: Оригинальное имя файла.

        Returns:
            Путь к сохраненному файлу или None при ошибке.
        """
        try:
            upload_dir = Config.UPLOAD_DIR
            os.makedirs(upload_dir, exist_ok=True)

            # Генерация уникального имени
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name, ext = os.path.splitext(original_name)
            # Очистка имени от недопустимых символов
            safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
            safe_name = f"{safe_name}_{timestamp}{ext}"
            file_path = os.path.join(upload_dir, safe_name)

            with open(file_path, "wb") as f:
                f.write(file_content)

            print(f"✅ Файл сохранён: {file_path}")
            return file_path
        except Exception as e:
            print(f"⚠️ Ошибка сохранения файла: {e}")
            return None

    @staticmethod
    def read_file(file_path: str) -> Optional[bytes]:
        """
        Чтение файла с диска.

        Args:
            file_path: Путь к файлу.

        Returns:
            Содержимое файла в байтах или None при ошибке.
        """
        try:
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)

            if not os.path.exists(file_path):
                print(f"⚠️ Файл не найден: {file_path}")
                return None

            with open(file_path, "rb") as f:
                return f.read()
        except Exception as e:
            print(f"⚠️ Ошибка чтения файла: {e}")
            return None

    @staticmethod
    def delete_file(file_path: str) -> bool:
        """
        Удаление файла с диска.

        Args:
            file_path: Путь к файлу.

        Returns:
            True при успешном удалении, False при ошибке.
        """
        try:
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)

            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Файл удалён: {file_path}")
                return True
            return False
        except Exception as e:
            print(f"⚠️ Ошибка удаления файла: {e}")
            return False

    @staticmethod
    def get_file_size_str(file_size: int) -> str:
        """
        Форматирование размера файла для вывода пользователю.

        Args:
            file_size: Размер в байтах.

        Returns:
            Строка с размером (КБ, МБ).
        """
        if file_size < 1024:
            return f"{file_size} Б"
        elif file_size < 1024 * 1024:
            return f"{file_size / 1024:.1f} КБ"
        else:
            return f"{file_size / (1024 * 1024):.1f} МБ"