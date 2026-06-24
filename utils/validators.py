"""
Валидация данных для системы документооборота.
"""
import os
from typing import Tuple, Optional


class Validators:
    """Набор статических методов для валидации данных."""

    @staticmethod
    def validate_doc_id(doc_id: str) -> Tuple[bool, str]:
        """
        Валидация ID документа.

        Формат: DOC-YYYY-NNNN (например, DOC-2024-0001)

        Args:
            doc_id: ID документа.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        if not doc_id:
            return False, "ID документа не может быть пустым."

        if len(doc_id) > 50:
            return False, "ID документа слишком длинный (макс. 50 символов)."

        import re
        if not re.match(r'^DOC-\d{4}-\d{4}$', doc_id):
            return False, (
                "Неверный формат ID. Используйте: DOC-YYYY-NNNN "
                "(например, DOC-2024-0001)"
            )

        return True, ""

    @staticmethod
    def validate_title(title: str) -> Tuple[bool, str]:
        """
        Валидация названия документа.

        Args:
            title: Название документа.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        if not title or not title.strip():
            return False, "Название документа не может быть пустым."

        if len(title.strip()) < 3:
            return False, "Название слишком короткое (минимум 3 символа)."

        if len(title) > 255:
            return False, "Название слишком длинное (макс. 255 символов)."

        return True, ""

    @staticmethod
    def validate_doc_type(doc_type: str) -> Tuple[bool, str]:
        """
        Валидация типа документа.

        Args:
            doc_type: Тип документа.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        valid_types = [
            "Чертеж", "Техпроцесс", "Спецификация",
            "Инструкция", "Схема", "Расчет"
        ]

        if doc_type and doc_type not in valid_types:
            return False, (
                f"Недопустимый тип документа. "
                f"Допустимые: {', '.join(valid_types)}"
            )

        return True, ""

    @staticmethod
    def validate_status(status: str) -> Tuple[bool, str]:
        """
        Валидация статуса документа.

        Args:
            status: Статус документа.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        valid_statuses = ["Активен", "Архивный", "В работе", "Отменен"]

        if status and status not in valid_statuses:
            return False, (
                f"Недопустимый статус. "
                f"Допустимые: {', '.join(valid_statuses)}"
            )

        return True, ""

    @staticmethod
    def validate_tech_process(tech_process: str) -> Tuple[bool, str]:
        """
        Валидация техпроцесса.

        Args:
            tech_process: Название техпроцесса.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        valid_processes = [
            "Токарная", "Фрезерная", "Сверлильная", "Шлифовальная",
            "Сварочная", "Сборочная", "Термическая", "Гальваническая"
        ]

        if tech_process and tech_process not in valid_processes:
            return False, (
                f"Недопустимый техпроцесс. "
                f"Допустимые: {', '.join(valid_processes)}"
            )

        return True, ""

    @staticmethod
    def validate_file(filename: str, file_size: int) -> Tuple[bool, str]:
        """
        Валидация файла документа.

        Args:
            filename: Имя файла.
            file_size: Размер файла в байтах.

        Returns:
            Кортеж (валиден, сообщение об ошибке).
        """
        from config import Config

        # Проверка расширения
        _, ext = os.path.splitext(filename.lower())
        if ext not in Config.ALLOWED_EXTENSIONS:
            return False, (
                f"Недопустимый тип файла. "
                f"Разрешены: {', '.join(Config.ALLOWED_EXTENSIONS)}"
            )

        # Проверка размера
        max_size = Config.MAX_FILE_SIZE
        if file_size > max_size:
            size_mb = max_size / (1024 * 1024)
            return False, (
                f"Файл слишком большой. "
                f"Максимальный размер: {size_mb:.0f} МБ"
            )

        return True, ""

    @staticmethod
    def validate_page_number(page: int) -> int:
        """
        Валидация номера страницы.

        Args:
            page: Номер страницы.

        Returns:
            Корректный номер страницы (минимум 1).
        """
        return max(1, page)

    @staticmethod
    def sanitize_string(text: str) -> str:
        """
        Очистка строки от нежелательных символов.

        Args:
            text: Исходная строка.

        Returns:
            Очищенная строка.
        """
        if not text:
            return ""

        # Удаление управляющих символов
        cleaned = "".join(c for c in text if c.isprintable() or c in "\n\r\t")
        return cleaned.strip()