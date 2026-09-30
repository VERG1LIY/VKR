"""
Репозиторий для работы с базой данных.
Реализует паттерн Repository для CRUD операций.
"""
import os
import json
import shutil
from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache

from sqlalchemy import create_engine, text, or_, and_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy import update as sql_update, delete as sql_delete

from config import Config
from database.models import Base, Document, DocumentHistory, User, VKUser


class DocumentDatabase:
    """
    Репозиторий для работы с документами.
    Предоставляет CRUD операции и методы поиска.
    """

    def __init__(self, db_url: str = None):
        """
        Инициализация подключения к базе данных.

        Args:
            db_url: URL подключения к БД. Если None, используется из Config.
        """
        self.db_url = db_url or Config.DATABASE_URL
        self._engine = None
        self._session_factory = None
        self._fallback_storage: Dict[str, Dict] = {}  # JSON fallback хранилище
        self._seen_vk_users = set()

    async def initialize(self):
        """Инициализация движка БД и создание таблиц."""
        try:
            self._engine = create_async_engine(self.db_url, echo=False)
            self._session_factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )

            # Создание таблиц
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            print(f"✅ База данных инициализирована: {self.db_url}")
        except Exception as e:
            print(f"⚠️ Ошибка инициализации БД: {e}")
            print("⚠️ Используется fallback JSON-хранилище")
            self._load_fallback()

    async def get_session(self) -> AsyncSession:
        """Получение сессии для работы с БД."""
        if self._session_factory:
            return self._session_factory()
        return None

    # ========== CRUD операции ==========

    async def search_by_criteria(self, filters: Dict[str, Any]) -> List[Document]:
        """
        Поиск документов по критериям.

        Args:
            filters: Словарь с фильтрами (doc_type, status, tech_process и т.д.)

        Returns:
            Список найденных документов.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_search(filters)

        try:
            query = select(Document)

            conditions = []
            for key, value in filters.items():
                if hasattr(Document, key) and value:
                    column = getattr(Document, key)
                    conditions.append(column == value)

            if conditions:
                query = query.where(and_(*conditions))

            query = query.order_by(Document.updated_at.desc()).limit(Config.SEARCH_LIMIT)

            result = await session.execute(query)
            documents = result.scalars().all()
            return list(documents)
        except Exception as e:
            print(f"⚠️ Ошибка поиска по критериям: {e}")
            return self._fallback_search(filters)
        finally:
            await session.close()

    async def fulltext_search(self, query_text: str) -> List[Document]:
        """
        Полнотекстовый поиск по названию, описанию и тегам.

        Args:
            query_text: Поисковый запрос.

        Returns:
            Список найденных документов.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_text_search(query_text)

        try:
            search_pattern = f"%{query_text}%"
            query = select(Document).where(
                or_(
                    Document.title.ilike(search_pattern),
                    Document.description.ilike(search_pattern),
                    Document.tags.ilike(search_pattern),
                    Document.doc_id.ilike(search_pattern),
                    Document.drawing_number.ilike(search_pattern),
                )
            ).order_by(Document.updated_at.desc()).limit(Config.SEARCH_LIMIT)

            result = await session.execute(query)
            documents = result.scalars().all()
            return list(documents)
        except Exception as e:
            print(f"⚠️ Ошибка полнотекстового поиска: {e}")
            return self._fallback_text_search(query_text)
        finally:
            await session.close()

    async def get_document_by_id(self, doc_id: str) -> Optional[Document]:
        """
        Получение документа по его ID.

        Args:
            doc_id: Уникальный ID документа (например, DOC-2024-001).

        Returns:
            Документ или None, если не найден.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_get(doc_id)

        try:
            query = select(Document).where(Document.doc_id == doc_id)
            result = await session.execute(query)
            document = result.scalar_one_or_none()
            return document
        except Exception as e:
            print(f"⚠️ Ошибка получения документа: {e}")
            return self._fallback_get(doc_id)
        finally:
            await session.close()

    async def add_document(
        self, data: Dict[str, Any], file_content: bytes = None, user: str = None
    ) -> Optional[Document]:
        """
        Добавление нового документа.

        Args:
            data: Словарь с данными документа.
            file_content: Содержимое файла (если есть).
            user: Имя пользователя, создающего документ.

        Returns:
            Созданный документ или None при ошибке.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_add(data, user)

        try:
            # Сохранение файла, если он есть
            file_path = None
            if file_content and data.get("file_name"):
                file_path = await self._save_file(file_content, data["file_name"])

            # Создание документа
            document = Document(
                doc_id=data.get("doc_id", self._generate_doc_id()),
                title=data.get("title", "Без названия"),
                doc_type=data.get("doc_type"),
                drawing_number=data.get("drawing_number"),
                version=data.get("version", "1.0"),
                tech_process=data.get("tech_process"),
                status=data.get("status", "Активен"),
                file_path=file_path,
                file_name=data.get("file_name"),
                tags=data.get("tags"),
                description=data.get("description"),
                created_by=user or data.get("created_by", "unknown"),
                metadata_json=data.get("metadata_json"),
            )

            session.add(document)
            await session.commit()
            await session.refresh(document)

            # Запись в историю
            await self._add_history(
                session, document.doc_id, "CREATE", None, document.to_dict(), user
            )

            return document
        except Exception as e:
            await session.rollback()
            print(f"⚠️ Ошибка добавления документа: {e}")
            return self._fallback_add(data, user)
        finally:
            await session.close()

    async def update_status(
        self, doc_id: str, new_status: str, user: str = None
    ) -> bool:
        """
        Обновление статуса документа.

        Args:
            doc_id: ID документа.
            new_status: Новый статус.
            user: Пользователь, изменивший статус.

        Returns:
            True при успехе, False при ошибке.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_update_status(doc_id, new_status, user)

        try:
            query = select(Document).where(Document.doc_id == doc_id)
            result = await session.execute(query)
            document = result.scalar_one_or_none()

            if not document:
                return False

            old_status = document.status
            document.status = new_status
            document.updated_at = datetime.utcnow()

            await session.commit()

            # Запись в историю
            await self._add_history(
                session, doc_id, "UPDATE_STATUS", old_status, new_status, user
            )

            return True
        except Exception as e:
            await session.rollback()
            print(f"⚠️ Ошибка обновления статуса: {e}")
            return self._fallback_update_status(doc_id, new_status, user)
        finally:
            await session.close()

    async def update_document(
        self, doc_id: str, data: Dict[str, Any], user: str = None
    ) -> bool:
        """
        Обновление метаданных документа.

        Args:
            doc_id: ID документа.
            data: Словарь с обновляемыми полями.
            user: Пользователь, изменивший документ.

        Returns:
            True при успехе, False при ошибке.
        """
        session = await self.get_session()
        if not session:
            return False

        try:
            query = select(Document).where(Document.doc_id == doc_id)
            result = await session.execute(query)
            document = result.scalar_one_or_none()

            if not document:
                return False

            old_data = document.to_dict()

            # Обновление полей
            for key, value in data.items():
                if hasattr(document, key) and value is not None:
                    setattr(document, key, value)

            document.updated_at = datetime.utcnow()
            await session.commit()

            # Запись в историю
            await self._add_history(
                session, doc_id, "UPDATE", json.dumps(old_data, ensure_ascii=False),
                json.dumps(data, ensure_ascii=False), user
            )

            return True
        except Exception as e:
            await session.rollback()
            print(f"⚠️ Ошибка обновления документа: {e}")
            return False
        finally:
            await session.close()

    async def delete_document(self, doc_id: str, user: str = None) -> bool:
        """
        Мягкое удаление документа (архивирование).

        Args:
            doc_id: ID документа.
            user: Пользователь, удаливший документ.

        Returns:
            True при успехе, False при ошибке.
        """
        return await self.update_status(doc_id, "Архивный", user)

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики по архиву документов.

        Returns:
            Словарь со статистикой.
        """
        session = await self.get_session()
        if not session:
            return self._fallback_stats()

        try:
            stats = {}

            # Общее количество
            result = await session.execute(select(Document))
            all_docs = result.scalars().all()
            stats["total"] = len(all_docs)

            # По типам
            result = await session.execute(
                select(Document.doc_type, text("COUNT(*) as cnt"))
                .group_by(Document.doc_type)
            )
            stats["by_type"] = {row[0] or "Не указан": row[1] for row in result}

            # По статусам
            result = await session.execute(
                select(Document.status, text("COUNT(*) as cnt"))
                .group_by(Document.status)
            )
            stats["by_status"] = {row[0] or "Не указан": row[1] for row in result}

            # По техпроцессам
            result = await session.execute(
                select(Document.tech_process, text("COUNT(*) as cnt"))
                .group_by(Document.tech_process)
            )
            stats["by_tech_process"] = {row[0] or "Не указан": row[1] for row in result}

            return stats
        except Exception as e:
            print(f"⚠️ Ошибка получения статистики: {e}")
            return self._fallback_stats()
        finally:
            await session.close()

    async def get_document_file(self, doc_id: str) -> Optional[bytes]:
        """
        Получение содержимого файла документа.

        Args:
            doc_id: ID документа.

        Returns:
            Содержимое файла в байтах или None.
        """
        document = await self.get_document_by_id(doc_id)
        if not document or not document.file_path:
            return None

        try:
            file_path = document.file_path
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)

            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    return f.read()
            return None
        except Exception as e:
            print(f"⚠️ Ошибка чтения файла: {e}")
            return None

    async def get_all_documents(
        self, page: int = 1, per_page: int = 10
    ) -> List[Document]:
        """
        Получение списка всех документов с пагинацией.

        Args:
            page: Номер страницы.
            per_page: Количество документов на странице.

        Returns:
            Список документов.
        """
        session = await self.get_session()
        if not session:
            return list(self._fallback_storage.values())[
                (page - 1) * per_page : page * per_page
            ]

        try:
            offset = (page - 1) * per_page
            query = (
                select(Document)
                .order_by(Document.updated_at.desc())
                .offset(offset)
                .limit(per_page)
            )
            result = await session.execute(query)
            return list(result.scalars().all())
        except Exception as e:
            print(f"⚠️ Ошибка получения списка документов: {e}")
            return []
        finally:
            await session.close()

    async def get_total_count(self) -> int:
        """Получение общего количества документов."""
        session = await self.get_session()
        if not session:
            return len(self._fallback_storage)

        try:
            result = await session.execute(select(Document))
            return len(result.scalars().all())
        except:
            return 0
        finally:
            await session.close()

    async def find_duplicate_document(
        self, file_name: str, file_hash: Optional[str] = None
    ) -> Optional[Document]:
        """Проверяет, не был ли файл уже загружен ранее."""
        session = await self.get_session()
        if not session:
            return None
        try:
            result = await session.execute(select(Document))
            documents = result.scalars().all()
            target_name = (file_name or "").lower()
            for doc in documents:
                metadata = doc.metadata_json or {}
                if file_hash and metadata.get("sha256") == file_hash:
                    return doc
                if target_name and doc.file_name and doc.file_name.lower() == target_name:
                    return doc
            return None
        except Exception as e:
            print(f"⚠️ Ошибка проверки дублей: {e}")
            return None
        finally:
            await session.close()

    async def register_vk_user(self, vk_id: int) -> bool:
        """Регистрирует пользователя VK; True означает первое обращение."""
        session = await self.get_session()
        if not session:
            if vk_id in self._seen_vk_users:
                return False
            self._seen_vk_users.add(vk_id)
            return True

        try:
            existing = await session.execute(
                select(VKUser).where(VKUser.vk_id == vk_id)
            )
            if existing.scalar_one_or_none():
                self._seen_vk_users.add(vk_id)
                return False

            session.add(VKUser(vk_id=vk_id))
            await session.commit()
            self._seen_vk_users.add(vk_id)
            return True
        except Exception as e:
            await session.rollback()
            print(f"⚠️ Ошибка регистрации пользователя VK: {e}")
            if vk_id in self._seen_vk_users:
                return False
            self._seen_vk_users.add(vk_id)
            return True
        finally:
            await session.close()

    # ========== Вспомогательные методы ==========

    async def _add_history(
        self, session: AsyncSession, doc_id: str, action: str,
        old_value: str, new_value: str, changed_by: str
    ):
        """Добавление записи в историю изменений."""
        try:
            history = DocumentHistory(
                doc_id=doc_id,
                action=action,
                old_value=str(old_value) if old_value else None,
                new_value=str(new_value) if new_value else None,
                changed_by=changed_by or "system",
            )
            session.add(history)
            await session.commit()
        except Exception as e:
            print(f"⚠️ Ошибка записи истории: {e}")

    async def _save_file(self, content: bytes, original_name: str) -> str:
        """
        Сохранение файла на диск.

        Args:
            content: Содержимое файла.
            original_name: Оригинальное имя файла.

        Returns:
            Путь к сохраненному файлу.
        """
        upload_dir = Config.UPLOAD_DIR
        os.makedirs(upload_dir, exist_ok=True)

        # Генерация уникального имени
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(original_name)
        safe_name = f"{name}_{timestamp}{ext}"
        file_path = os.path.join(upload_dir, safe_name)

        with open(file_path, "wb") as f:
            f.write(content)

        return file_path

    def _generate_doc_id(self) -> str:
        """Генерация уникального ID документа."""
        from datetime import datetime
        year = datetime.now().year
        # В реальном проекте здесь должен быть счетчик из БД
        return f"DOC-{year}-{int(datetime.now().timestamp()) % 10000:04d}"

    # ========== Fallback методы (JSON хранилище) ==========

    def _load_fallback(self):
        """Загрузка fallback хранилища из JSON файла."""
        try:
            if os.path.exists("fallback_db.json"):
                with open("fallback_db.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._fallback_storage = {d["doc_id"]: d for d in data}
        except Exception as e:
            print(f"⚠️ Ошибка загрузки fallback: {e}")

    def _save_fallback(self):
        """Сохранение fallback хранилища в JSON файл."""
        try:
            with open("fallback_db.json", "w", encoding="utf-8") as f:
                json.dump(
                    list(self._fallback_storage.values()),
                    f, ensure_ascii=False, indent=2
                )
        except Exception as e:
            print(f"⚠️ Ошибка сохранения fallback: {e}")

    def _fallback_search(self, filters: dict) -> List:
        """Fallback поиск по критериям."""
        results = list(self._fallback_storage.values())
        for key, value in filters.items():
            if value:
                results = [d for d in results if d.get(key) == value]
        return results[:Config.SEARCH_LIMIT]

    def _fallback_text_search(self, query_text: str) -> List:
        """Fallback полнотекстовый поиск."""
        query_lower = query_text.lower()
        results = []
        for doc in self._fallback_storage.values():
            if (query_lower in doc.get("title", "").lower()
                    or query_lower in doc.get("description", "").lower()
                    or query_lower in doc.get("tags", "").lower()):
                results.append(doc)
        return results[:Config.SEARCH_LIMIT]

    def _fallback_get(self, doc_id: str) -> Optional[Dict]:
        """Fallback получение документа."""
        return self._fallback_storage.get(doc_id)

    def _fallback_add(self, data: dict, user: str = None) -> Dict:
        """Fallback добавление документа."""
        doc_id = data.get("doc_id", self._generate_doc_id())
        doc = {
            "doc_id": doc_id,
            "title": data.get("title", "Без названия"),
            "doc_type": data.get("doc_type"),
            "drawing_number": data.get("drawing_number"),
            "version": data.get("version", "1.0"),
            "tech_process": data.get("tech_process"),
            "status": data.get("status", "Активен"),
            "file_path": data.get("file_path"),
            "file_name": data.get("file_name"),
            "tags": data.get("tags"),
            "description": data.get("description"),
            "created_by": user or data.get("created_by", "unknown"),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        self._fallback_storage[doc_id] = doc
        self._save_fallback()
        return doc

    def _fallback_update_status(
        self, doc_id: str, new_status: str, user: str = None
    ) -> bool:
        """Fallback обновление статуса."""
        if doc_id in self._fallback_storage:
            self._fallback_storage[doc_id]["status"] = new_status
            self._fallback_storage[doc_id]["updated_at"] = datetime.now().isoformat()
            self._save_fallback()
            return True
        return False

    def _fallback_stats(self) -> dict:
        """Fallback получение статистики."""
        docs = list(self._fallback_storage.values())
        stats = {
            "total": len(docs),
            "by_type": {},
            "by_status": {},
            "by_tech_process": {},
        }
        for doc in docs:
            t = doc.get("doc_type", "Не указан")
            stats["by_type"][t] = stats["by_type"].get(t, 0) + 1
            s = doc.get("status", "Не указан")
            stats["by_status"][s] = stats["by_status"].get(s, 0) + 1
            tp = doc.get("tech_process", "Не указан")
            stats["by_tech_process"][tp] = stats["by_tech_process"].get(tp, 0) + 1
        return stats

    async def close(self):
        """Закрытие соединения с БД."""
        if self._engine:
            await self._engine.dispose()