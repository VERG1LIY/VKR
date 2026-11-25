"""Минимальный асинхронный клиент VK API для Callback-бота."""
import json
from io import BytesIO
import secrets
from typing import Any, Dict, Optional

import aiohttp


class VKAPIError(RuntimeError):
    """Ошибка вызова VK API."""

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code


class VKAPIClient:
    def __init__(self, access_token: str, api_version: str = "5.199"):
        self.access_token = access_token
        self.api_version = api_version
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )
        return self._session

    async def call(self, method: str, **params: Any) -> Any:
        session = await self._get_session()
        payload = {
            **params,
            "access_token": self.access_token,
            "v": self.api_version,
        }

        async with session.post(
            f"https://api.vk.com/method/{method}", data=payload
        ) as response:
            response.raise_for_status()
            body = await response.json()

        if "error" in body:
            error = body["error"]
            raise VKAPIError(
                f"VK API {method}: {error.get('error_code')} "
                f"{error.get('error_msg', 'unknown error')}",
                error_code=error.get("error_code"),
            )
        return body.get("response")

    async def send_message(
        self, peer_id: int, message: str, attachment: Optional[str] = None,
        keyboard: Optional[Dict[str, Any]] = None
    ) -> Any:
        params: Dict[str, Any] = {
            "peer_id": peer_id,
            "random_id": secrets.randbelow(2**31 - 1) + 1,
            "message": message,
        }
        if attachment:
            params["attachment"] = attachment
        if keyboard is not None:
            params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
        return await self.call("messages.send", **params)

    async def download_file(self, url: str) -> bytes:
        session = await self._get_session()
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()

    async def download_attachment(self, attachment: Dict[str, Any]) -> bytes:
        doc = attachment.get("doc") if isinstance(attachment, dict) else None
        if doc is None and isinstance(attachment, dict):
            doc = attachment
        if doc is None:
            raise VKAPIError("Пустое вложение VK")

        file_url = doc.get("url")
        if not file_url:
            raise VKAPIError("VK не вернул URL файла для вложения")
        return await self.download_file(file_url)

    async def send_document(
        self, peer_id: int, content: bytes, file_name: str, title: str
    ) -> Any:
        upload_info = await self.call(
            "docs.getMessagesUploadServer", peer_id=peer_id, type="doc"
        )
        if not isinstance(upload_info, dict):
            raise VKAPIError("VK вернул некорректный ответ для сервера загрузки документов")
        upload_url = upload_info.get("upload_url")
        if not isinstance(upload_url, str) or not upload_url:
            raise VKAPIError("VK не вернул адрес сервера загрузки документов")

        session = await self._get_session()
        form = aiohttp.FormData()
        form.add_field(
            "file", BytesIO(content), filename=file_name,
            content_type="application/octet-stream"
        )

        async with session.post(upload_url, data=form) as response:
            response.raise_for_status()
            upload_result = await response.json()

        if not isinstance(upload_result, dict):
            raise VKAPIError("Сервер загрузки VK вернул некорректный ответ")
        upload_file = upload_result.get("file")
        if not isinstance(upload_file, str) or not upload_file:
            raise VKAPIError("Сервер загрузки VK не вернул идентификатор файла")

        saved = await self.call(
            "docs.save", file=upload_file, title=title
        )

        document = saved
        if isinstance(document, list):
            if not document:
                raise VKAPIError("VK вернул пустой список документов")
            document = document[0]
        if isinstance(document, dict) and "doc" in document:
            document = document["doc"]
            if isinstance(document, list):
                if not document:
                    raise VKAPIError("VK вернул пустой список документов")
                document = document[0]
        if not isinstance(document, dict):
            raise VKAPIError("VK вернул некорректную структуру ответа docs.save")

        owner_id = document.get("owner_id")
        document_id = document.get("id")
        if owner_id is None or document_id is None:
            raise VKAPIError("В ответе docs.save отсутствуют owner_id или id")

        access_key = document.get("access_key")
        attachment = f"doc{owner_id}_{document_id}"
        if access_key:
            attachment += f"_{access_key}"
        return await self.send_message(
            peer_id, f"📎 {title}", attachment=attachment
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()