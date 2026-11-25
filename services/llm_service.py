"""
Сервис для работы с локальной LLM через LM Studio API.
Обеспечивает RAG (Retrieval-Augmented Generation) подстановку контекста.
"""
import json
from typing import List, Optional, Dict, Any
import aiohttp
import asyncio

from config import Config
from database.models import Document
from utils.logger import logger


class LLMProcessor:
    """
    Класс для взаимодействия с локальной LLM через LM Studio.
    Совместим с OpenAI API форматом.
    """

    def __init__(self, api_url: str = None, model: str = None):
        """
        Инициализация LLM процессора.

        Args:
            api_url: URL LM Studio API (например, http://localhost:1234/v1)
            model: Название модели (например, qwen-3-4b)
        """
        self.api_url = (api_url or Config.LLM_API_URL).rstrip("/")
        self.model = model or Config.LLM_MODEL
        self.enabled = bool(self.api_url)
        self._last_connection_error: Optional[str] = None
        self._warned_about_unavailability = False
        self._session: Optional[aiohttp.ClientSession] = None

    async def is_available(self) -> bool:
        """Проверяет доступность локального LM Studio."""
        if not self.api_url:
            self.enabled = False
            return False
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.api_url.rstrip('/')}/models",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as response:
                if response.status == 200:
                    self.enabled = True
                    self._last_connection_error = None
                    return True
                self._last_connection_error = f"HTTP {response.status}"
        except Exception as exc:
            self._last_connection_error = str(exc)
        return False

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение HTTP сессии (создание при первом вызове)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _make_request(
        self, messages: List[Dict[str, str]], 
        max_tokens: int = 512,
        temperature: float = 0.3
    ) -> Optional[str]:
        """
        Отправка запроса к LM Studio API.

        Args:
            messages: Список сообщений для чата.
            max_tokens: Максимальное количество токенов в ответе.
            temperature: Температура генерации (0.0 - 1.0).

        Returns:
            Текст ответа или None при ошибке.
        """
        if not self.enabled:
            return None

        try:
            session = await self._get_session()

            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }

            async with session.post(
                f"{self.api_url}/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    if not self._warned_about_unavailability:
                        logger.warning("LLM API вернул HTTP %s", response.status)
                        self._warned_about_unavailability = True
                    return None

        except asyncio.TimeoutError:
            if not self._warned_about_unavailability:
                logger.warning("LLM API: превышено время ожидания ответа (120 сек)")
                self._warned_about_unavailability = True
            return None
        except Exception as e:
            if not self._warned_about_unavailability:
                logger.warning("LLM API недоступен: %s", e)
                self._warned_about_unavailability = True
            return None

    async def process_query(
        self, user_query: str, context_docs: List[Document]
    ) -> str:
        """
        Обработка запроса пользователя с RAG контекстом.

        Формирует промпт с найденными документами и отправляет в LLM.

        Args:
            user_query: Запрос пользователя.
            context_docs: Список релевантных документов.

        Returns:
            Ответ LLM.
        """
        # Формирование контекста из документов
        context_parts = []
        for i, doc in enumerate(context_docs[:5], 1):  # максимум 5 документов
            doc_info = (
                f"{i}. Документ: {doc.doc_id}\n"
                f"   Название: {doc.title}\n"
                f"   Тип: {doc.doc_type}\n"
                f"   Статус: {doc.status}\n"
                f"   Описание: {doc.description or 'Нет описания'}\n"
                f"   Теги: {doc.tags or 'Нет тегов'}"
            )
            context_parts.append(doc_info)

        context = "\n\n".join(context_parts) if context_parts else "Документы не найдены."

        system_prompt = (
            "Ты — ассистент системы документооборота машиностроительного предприятия. "
            "Отвечай на русском языке. Используй информацию из предоставленных документов. "
            "Если информации недостаточно, предложи варианты поиска. "
            "Будь краток и точен."
        )

        user_prompt = (
            f"Контекст (найденные документы):\n{context}\n\n"
            f"Вопрос пользователя: {user_query}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self._make_request(messages)
        if response:
            return response
        else:
            # Fallback: базовый ответ без LLM
            return self._fallback_response(user_query, context_docs)

    async def suggest_synonyms(self, query: str) -> List[str]:
        """
        Генерация синонимов для улучшения поиска.

        Args:
            query: Поисковый запрос.

        Returns:
            Список синонимов.
        """
        system_prompt = (
            "Ты — помощник инженера. Напиши список из 3-5 синонимов или "
            "родственных терминов для заданного технического термина. "
            "Формат ответа: каждый синоним на новой строке, без нумерации."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Найди синонимы для: {query}"},
        ]

        response = await self._make_request(messages, max_tokens=200)
        if response:
            synonyms = [s.strip() for s in response.split("\n") if s.strip()]
            return synonyms[:5]
        return [query]

    async def classify_intent(self, query: str) -> Dict[str, Any]:
        """
        Классификация намерения пользователя.

        Args:
            query: Текст запроса.

        Returns:
            Словарь с типом намерения и параметрами.
        """
        system_prompt = (
            "Определи намерение пользователя по запросу. "
            "Варианты: search (поиск), filter (фильтрация), "
            "add (добавление), help (помощь), unknown (неизвестно). "
            "Ответь JSON: {\"intent\": \"...\", \"params\": {...}}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        response = await self._make_request(messages, max_tokens=150)
        if response:
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                pass

        return {"intent": "unknown", "params": {}}

    async def generate_document_summary(self, doc: Document) -> str:
        """
        Генерация краткого описания документа.

        Args:
            doc: Документ.

        Returns:
            Краткое описание.
        """
        system_prompt = (
            "Сформируй краткое (2-3 предложения) описание технического документа "
            "для инженера. Укажи основные характеристики."
        )

        doc_info = (
            f"Название: {doc.title}\n"
            f"Тип: {doc.doc_type}\n"
            f"Номер чертежа: {doc.drawing_number}\n"
            f"Техпроцесс: {doc.tech_process}\n"
            f"Описание: {doc.description}\n"
            f"Теги: {doc.tags}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": doc_info},
        ]

        response = await self._make_request(messages, max_tokens=200)
        return response or (doc.description or "Описание отсутствует")

    def _fallback_response(self, query: str, docs: List[Document]) -> str:
        """
        Формирование ответа без LLM (если API недоступен).

        Args:
            query: Запрос пользователя.
            docs: Найденные документы.

        Returns:
            Текстовый ответ.
        """
        if not docs:
            return (
                f"🔍 По запросу \"{query}\" документов не найдено.\n"
                "Попробуйте изменить запрос или используйте /filter для фильтрации."
            )

        parts = [f"🔍 Результаты поиска по запросу \"{query}\":"]
        for i, doc in enumerate(docs[:5], 1):
            parts.append(
                f"{i}. {doc.doc_id} — {doc.title} ({doc.status})\n"
                f"   Тип: {doc.doc_type or 'Не указан'} | "
                f"Техпроцесс: {doc.tech_process or 'Не указан'}"
            )

        if len(docs) > 5:
            parts.append(f"\n... и ещё {len(docs) - 5} документов.")

        return "\n".join(parts)

    async def close(self):
        """Закрытие HTTP сессии."""
        if self._session and not self._session.closed:
            await self._session.close()