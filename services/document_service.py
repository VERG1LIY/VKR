"""
Сервисный слой для бизнес-логики работы с документами.
Реализует паттерн Service Layer.
"""
import os
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from database.repository import DocumentDatabase
from database.models import Document
from services.file_service import FileService
from services.llm_service import LLMProcessor
from config import Config


class DocumentService:
    """
    Сервис для работы с документами.
    Содержит бизнес-логику и координирует работу репозитория и других сервисов.
    """

    def __init__(self, db: DocumentDatabase, llm: LLMProcessor = None):
        """
        Инициализация сервиса.

        Args:
            db: Репозиторий базы данных.
            llm: LLM процессор (опционально).
        """
        self.db = db
        self.llm = llm or LLMProcessor()

    async def search_documents(self, query: str) -> List[Document]:
        """
        Простой поиск документов по текстовому запросу.

        Args:
            query: Поисковый запрос.

        Returns:
            Список найденных документов.
        """
        return await self.db.fulltext_search(query)

    async def smart_search(self, query: str) -> Dict[str, Any]:
        """
        Умный поиск с использованием LLM.

        Сначала выполняет SQL поиск, если результатов мало -
        использует LLM для генерации синонимов и расширенного поиска.

        Args:
            query: Поисковый запрос.

        Returns:
            Словарь с результатами поиска и пояснением.
        """
        # Шаг 1: SQL поиск
        sql_results = await self.db.fulltext_search(query)

        result = {
            "query": query,
            "sql_results": sql_results,
            "llm_suggestions": [],
            "expanded_results": [],
            "best_match": None,
            "message": "",
        }

        # Шаг 2: Если результатов мало и LLM доступен, используем его для расширения
        if len(sql_results) < Config.MIN_SEMANTIC_RESULTS and self.llm.enabled:
            synonyms = await self.llm.suggest_synonyms(query)
            result["llm_suggestions"] = synonyms

            # Поиск по синонимам
            expanded_ids = set()
            for synonym in synonyms:
                if synonym.lower() != query.lower():
                    docs = await self.db.fulltext_search(synonym)
                    for doc in docs:
                        if doc.doc_id not in expanded_ids:
                            expanded_ids.add(doc.doc_id)
                            result["expanded_results"].append(doc)

            # Объединение результатов
            all_results = list(sql_results)
            seen_ids = {doc.doc_id for doc in all_results}
            for doc in result["expanded_results"]:
                if doc.doc_id not in seen_ids:
                    all_results.append(doc)
                    seen_ids.add(doc.doc_id)

            result["all_results"] = all_results

            if all_results:
                result["best_match"] = all_results[0]
                result["message"] = (
                    f"✅ Найдено {len(all_results)} документов "
                    f"(включая {len(result['expanded_results'])} по синонимам)"
                )
            else:
                result["message"] = "❌ Документов не найдено. Попробуйте изменить запрос."
        else:
            result["all_results"] = sql_results
            result["best_match"] = sql_results[0] if sql_results else None
            result["message"] = (
                f"✅ Найдено {len(sql_results)} документов."
                if sql_results else "❌ Документов не найдено. Попробуйте изменить запрос."
            )

        return result

    async def filter_documents(
        self, doc_type: str = None, status: str = None,
        tech_process: str = None, tags: str = None
    ) -> List[Document]:
        """
        Фильтрация документов по критериям.

        Args:
            doc_type: Тип документа.
            status: Статус документа.
            tech_process: Техпроцесс.
            tags: Тег документа.

        Returns:
            Список отфильтрованных документов.
        """
        if tags:
            docs = await self.db.fulltext_search(tags)
            return [doc for doc in docs if doc.tags and any(tag.strip().lower() == tags.strip().lower() for tag in doc.tags.split(","))]

        filters = {}
        if doc_type:
            filters["doc_type"] = doc_type
        if status:
            filters["status"] = status
        if tech_process:
            filters["tech_process"] = tech_process

        return await self.db.search_by_criteria(filters)

    async def get_available_tags(self) -> List[str]:
        """Возвращает список всех тегов, связанных с документами."""
        return await self.db.get_all_tags()

    async def get_document_info(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение полной информации о документе.

        Args:
            doc_id: ID документа.

        Returns:
            Словарь с информацией о документе или None.
        """
        doc = await self.db.get_document_by_id(doc_id)
        if not doc:
            return None

        info = doc.to_dict()

        # Добавление размера файла, если есть
        if doc.file_path:
            file_size = FileService.get_file_size_str(
                os.path.getsize(doc.file_path) if os.path.exists(doc.file_path) else 0
            )
            info["file_size"] = file_size

        return info

    async def download_document(self, doc_id: str) -> Optional[Tuple[bytes, str]]:
        """
        Подготовка документа для скачивания.

        Args:
            doc_id: ID документа.

        Returns:
            Кортеж (содержимое файла, имя файла) или None.
        """
        doc = await self.db.get_document_by_id(doc_id)
        if not doc or not doc.file_path:
            return None

        content = await self.db.get_document_file(doc_id)
        if not content:
            return None

        file_name = doc.file_name or f"{doc.doc_id}.pdf"
        return (content, file_name)

    async def add_new_document(
        self, data: Dict[str, Any], file_content: bytes = None,
        user: str = None
    ) -> Optional[Document]:
        """
        Добавление нового документа с валидацией.

        Args:
            data: Данные документа.
            file_content: Содержимое файла (опционально).
            user: Пользователь.

        Returns:
            Созданный документ или None при ошибке.
        """
        # Валидация обязательных полей
        if not data.get("title"):
            return None

        # Валидация файла, если он есть
        if file_content and data.get("file_name"):
            if not FileService.validate_file_extension(data["file_name"]):
                return None

        return await self.db.add_document(data, file_content, user)

    async def change_status(
        self, doc_id: str, new_status: str, user: str = None
    ) -> Tuple[bool, str]:
        """
        Изменение статуса документа с проверкой.

        Args:
            doc_id: ID документа.
            new_status: Новый статус.
            user: Пользователь.

        Returns:
            Кортеж (успех, сообщение).
        """
        valid_statuses = ["Активен", "Архивный", "В работе", "Отменен"]

        if new_status not in valid_statuses:
            return False, (
                f"❌ Недопустимый статус. Допустимые: "
                f"{', '.join(valid_statuses)}"
            )

        doc = await self.db.get_document_by_id(doc_id)
        if not doc:
            return False, f"❌ Документ {doc_id} не найден."

        if doc.status == new_status:
            return False, f"❌ Документ уже имеет статус '{new_status}'."

        success = await self.db.update_status(doc_id, new_status, user)
        if success:
            return True, f"✅ Статус документа {doc_id} изменён на '{new_status}'."
        return False, "❌ Ошибка при изменении статуса."

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики по архиву.

        Returns:
            Словарь со статистикой.
        """
        return await self.db.get_statistics()

    async def get_document_list(
        self, page: int = 1, per_page: int = 10
    ) -> Tuple[List[Document], int]:
        """
        Получение списка документов с пагинацией.

        Args:
            page: Номер страницы.
            per_page: Количество на странице.

        Returns:
            Кортеж (список документов, общее количество).
        """
        docs = await self.db.get_all_documents(page, per_page)
        total = await self.db.get_total_count()
        return docs, total

    async def process_free_text(self, text: str) -> str:
        """
        Обработка произвольного текстового сообщения через LLM с RAG.

        Args:
            text: Текст сообщения.

        Returns:
            Ответ пользователю.
        """
        # Поиск релевантных документов
        docs = await self.db.fulltext_search(text)

        # Если документов нет и LLM доступен, пробуем найти синонимы
        if not docs and self.llm.enabled:
            synonyms = await self.llm.suggest_synonyms(text)
            for synonym in synonyms:
                if synonym.lower() != text.lower():
                    docs = await self.db.fulltext_search(synonym)
                    if docs:
                        break

        # Формирование ответа через LLM, если он доступен
        if self.llm.enabled:
            response = await self.llm.process_query(text, docs)
            return response
        return self.llm._fallback_response(text, docs)

    async def import_documents_from_folder(self, folder: str) -> int:
        """Импортирует файлы из папки в индекс документов без использования бота."""
        if not folder:
            return 0

        root = folder if os.path.isabs(folder) else os.path.join(os.getcwd(), folder)
        if not os.path.isdir(root):
            return 0

        imported = 0
        for file_name in sorted(os.listdir(root)):
            path = os.path.join(root, file_name)
            if not os.path.isfile(path):
                continue
            if not FileService.validate_file_extension(file_name):
                continue

            doc_id = f"DOC-FS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{imported + 1:03d}"
            data = {
                "doc_id": doc_id,
                "title": os.path.splitext(file_name)[0],
                "doc_type": None,
                "drawing_number": None,
                "version": "1.0",
                "tech_process": None,
                "status": "Активен",
                "file_path": path,
                "file_name": file_name,
                "tags": "imported",
                "description": "Импортировано из папки хранения",
            }
            await self.db.add_document(data, file_content=None, user="system")
            imported += 1

        return imported

    async def find_duplicate_document(
        self, file_name: str, file_hash: Optional[str] = None
    ) -> Optional[Document]:
        """Проверяет похожий документ по имени или хэшу."""
        return await self.db.find_duplicate_document(file_name=file_name, file_hash=file_hash)

    async def get_available_types(self) -> List[str]:
        """Получение списка доступных типов документов."""
        return ["Чертеж", "Техпроцесс", "Спецификация", "Инструкция", "Схема", "Расчет"]

    async def get_available_statuses(self) -> List[str]:
        """Получение списка доступных статусов."""
        return ["Активен", "Архивный", "В работе", "Отменен"]

    async def get_available_tech_processes(self) -> List[str]:
        """Получение списка доступных техпроцессов."""
        return [
            "Токарная", "Фрезерная", "Сверлильная", "Шлифовальная",
            "Сварочная", "Сборочная", "Термическая", "Гальваническая"
        ]


import os