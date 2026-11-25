import asyncio
import logging
import os

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from config import Config
from database.repository import DocumentDatabase
from handlers.vk_callback import (
    handle_callback,
    parse_text_command,
    NavStateManager,
    parse_payload,
    build_payload,
    build_main_menu_keyboard,
    build_document_list_keyboard,
    build_document_results_keyboard,
    build_tag_keyboard,
    process_message,
    persist_pending_upload,
    handle_vk_action,
)
from services.document_service import DocumentService


def test_parse_vk_text_commands_and_arguments():
    assert parse_text_command("поиск вал приводной") == ("search", "вал приводной")
    assert parse_text_command("/status DOC-2024-0001 В работе") == (
        "status", "DOC-2024-0001 В работе"
    )
    assert parse_text_command("умный поиск вал с пазом") == (
        "smart", "вал с пазом"
    )


def test_callback_confirmation_and_secret(monkeypatch):
    async def exercise():
        monkeypatch.setattr(Config, "VK_CALLBACK_SECRET", "expected-secret")
        monkeypatch.setattr(Config, "VK_CONFIRMATION_CODE", "confirmation-code")
        app = web.Application()
        app.router.add_post("/vk/callback", handle_callback)
        async with TestClient(TestServer(app)) as client:
            denied = await client.post("/vk/callback", json={"secret": "wrong"})
            assert denied.status == 403

            confirmation = await client.post(
                "/vk/callback",
                json={"type": "confirmation", "secret": "expected-secret"},
            )
            assert confirmation.status == 200
            assert await confirmation.text() == "confirmation-code"

    asyncio.run(exercise())


def test_navigation_stack_and_payloads():
    state = NavStateManager()

    assert state.get(42) == ["main"]
    state.push(42, "search")
    state.push(42, "filters")
    assert state.get(42) == ["main", "search", "filters"]

    assert state.back(42) == "search"
    assert state.get(42) == ["main", "search"]

    state.reset(42)
    assert state.get(42) == ["main"]

    payload = build_payload("open_search")
    assert parse_payload(payload) == {"action": "open_search"}
    payload2 = build_payload("open_document", doc_id="DOC-2024-001")
    assert parse_payload(payload2) == {"action": "open_document", "doc_id": "DOC-2024-001"}


def test_process_message_handles_text_command():
    async def exercise():
        class FakeDB:
            async def register_vk_user(self, vk_id):
                return False

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append({"peer_id": peer_id, "message": message, "keyboard": keyboard})

        class FakeService:
            async def search_documents(self, query):
                return []

            async def smart_search(self, query):
                return {"all_results": [], "message": "Ничего не найдено", "llm_suggestions": []}

            async def get_document_list(self, page=1, per_page=10):
                return [], 0

            async def get_document_info(self, doc_id):
                return None

            async def get_statistics(self):
                return {"documents": 0}

            async def process_free_text(self, text):
                return "Свободный текст обработан"

        app = web.Application()
        app["db"] = FakeDB()
        app["document_service"] = FakeService()
        app["vk_client"] = FakeVKClient()
        app["menu_state"] = NavStateManager()
        app["pending_uploads"] = {}

        await process_message(app, {"text": "помощь"}, 101, 202)

        assert app["vk_client"].messages[-1]["message"].startswith("Команды для управления:")

    asyncio.run(exercise())


def test_llm_request_succeeds_after_health_check_failure():
    from services.llm_service import LLMProcessor

    async def exercise():
        app = web.Application()
        requests = []

        async def models(_request):
            return web.Response(status=503)

        async def chat_completions(request):
            requests.append(await request.json())
            return web.json_response(
                {"choices": [{"message": {"content": "Ответ от модели"}}]}
            )

        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat_completions)

        async with TestServer(app) as server:
            llm = LLMProcessor(
                api_url=f"{server.make_url('/v1/').with_scheme('http')}",
                model="test-model",
            )
            try:
                assert await llm.is_available() is False
                assert llm.enabled is True
                response = await llm._make_request(
                    [{"role": "user", "content": "test"}]
                )
                assert response == "Ответ от модели"
                assert len(requests) == 1
                assert requests[0]["model"] == "test-model"
            finally:
                await llm.close()

    asyncio.run(exercise())


def test_first_plain_message_uses_free_text_service():
    async def exercise():
        class FakeDB:
            async def register_vk_user(self, _vk_id):
                return True

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append(message)

        class FakeService:
            def __init__(self):
                self.queries = []

            async def process_free_text(self, text):
                self.queries.append(text)
                return "Ответ модели"

        service = FakeService()
        vk_client = FakeVKClient()
        app = web.Application()
        app["db"] = FakeDB()
        app["document_service"] = service
        app["vk_client"] = vk_client
        app["menu_state"] = NavStateManager()
        app["pending_uploads"] = {}

        await process_message(app, {"text": "Как найти чертеж вала?"}, 101, 202)

        assert service.queries == ["Как найти чертеж вала?"]
        assert vk_client.messages[-1] == "Ответ модели"

    asyncio.run(exercise())


def test_single_search_result_sends_document_file():
    class FakeDoc:
        def __init__(self):
            self.doc_id = "DOC-1"
            self.title = "Вал"
            self.status = "Активен"
            self.doc_type = "Чертеж"
            self.file_name = "val.pdf"
            self.file_path = "uploads/documents/val.pdf"

    class FakeVKClient:
        def __init__(self):
            self.documents = []
            self.messages = []

        async def send_document(self, peer_id, content, file_name, title):
            self.documents.append({"peer_id": peer_id, "content": content, "file_name": file_name, "title": title})

        async def send_message(self, peer_id, message, attachment=None, keyboard=None):
            self.messages.append({"peer_id": peer_id, "message": message, "keyboard": keyboard})

    class FakeService:
        def __init__(self):
            self.doc = FakeDoc()

            class FakeDB:
                async def get_document_file(self, doc_id):
                    return b"fake-pdf-content"

            self.db = FakeDB()

        async def search_documents(self, query):
            return [self.doc]

        async def process_free_text(self, query):
            return f"LLM: {query}"

        async def smart_search(self, query):
            return {"all_results": [self.doc], "message": "Найден документ", "llm_suggestions": []}

    class FakeDB:
        async def register_vk_user(self, vk_id):
            return False

    app = web.Application()
    app["document_service"] = FakeService()
    app["vk_client"] = FakeVKClient()
    app["menu_state"] = NavStateManager()
    app["db"] = FakeDB()
    app["pending_uploads"] = {}

    async def exercise():
        await process_message(app, {"text": "поиск вал"}, 1, 2)

    asyncio.run(exercise())
    assert len(app["vk_client"].documents) == 1
    assert app["vk_client"].documents[0]["file_name"] == "val.pdf"


def test_multiple_search_results_have_document_action_buttons():
    class FakeDoc:
        def __init__(self, doc_id, title):
            self.doc_id = doc_id
            self.title = title
            self.status = "Активен"
            self.doc_type = "Чертеж"

    class FakeVKClient:
        def __init__(self):
            self.messages = []

        async def send_message(self, peer_id, message, attachment=None, keyboard=None):
            self.messages.append({"message": message, "keyboard": keyboard})

    class FakeService:
        async def search_documents(self, query):
            assert query == "вал"
            return [FakeDoc("DOC-1", "Вал 1"), FakeDoc("DOC-2", "Вал 2")]

        async def process_free_text(self, query):
            return "LLM ответ"

    class FakeDB:
        async def register_vk_user(self, vk_id):
            return False

    app = web.Application()
    app["document_service"] = FakeService()
    app["vk_client"] = FakeVKClient()
    app["menu_state"] = NavStateManager()
    app["db"] = FakeDB()

    async def exercise():
        await process_message(app, {"text": "поиск вал"}, 1, 2)

    asyncio.run(exercise())
    keyboard = app["vk_client"].messages[-1]["keyboard"]
    payloads = [
        parse_payload(button["action"]["payload"])
        for row in keyboard["buttons"]
        for button in row
    ]
    assert {"action": "open_document", "doc_id": "DOC-1"} in payloads
    assert {"action": "open_document", "doc_id": "DOC-2"} in payloads


def test_vk_keyboards_stay_within_ten_row_limit():
    class FakeDoc:
        def __init__(self, index):
            self.doc_id = f"DOC-{index}"
            self.title = f"Document {index}"

    docs = [FakeDoc(index) for index in range(25)]
    keyboards = (
        build_document_list_keyboard(1, 4, docs),
        build_document_results_keyboard(docs),
        build_tag_keyboard([f"tag-{index}" for index in range(25)]),
    )

    for keyboard in keyboards:
        assert len(keyboard["buttons"]) <= 10
        assert all(len(row) <= 5 for row in keyboard["buttons"])
        assert all(
            len(button["action"]["label"]) <= 40
            for row in keyboard["buttons"]
            for button in row
        )
    assert keyboards[0]["buttons"][0][0]["action"]["label"] == "Document 0"
    assert keyboards[1]["buttons"][0][0]["action"]["label"] == "Document 0"


def test_vk_api_error_keeps_permission_code():
    from services.vk_api import VKAPIClient, VKAPIError

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            return {
                "error": {
                    "error_code": 15,
                    "error_msg": "Access denied: no access to call this method.",
                }
            }

    class FakeSession:
        def post(self, *_args, **_kwargs):
            return FakeResponse()

    async def exercise():
        client = VKAPIClient("test-token")

        async def get_session():
            return FakeSession()

        client._get_session = get_session
        try:
            await client.call("docs.getMessagesUploadServer", peer_id=1, type="doc")
        except VKAPIError as exc:
            assert exc.error_code == 15
        else:
            raise AssertionError("Expected VKAPIError for missing Documents permission")

    asyncio.run(exercise())


def test_vk_send_document_handles_wrapped_save_responses():
    from services.vk_api import VKAPIClient

    async def exercise():
        class UploadResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            async def json(self):
                return {"file": "upload-ticket"}

        class FakeSession:
            def __init__(self):
                self.request_options = None

            def post(self, url, data, **request_options):
                assert url == "https://vk-upload.test/upload"
                self.request_options = request_options
                return UploadResponse()

        responses = [
            {"type": "doc", "doc": {"owner_id": -10, "id": 21, "access_key": "key"}},
            [{"doc": [{"owner_id": -10, "id": 22}]}],
        ]
        sent = []

        for saved_response in responses:
            client = VKAPIClient("test-token")
            session = FakeSession()
            calls = []

            async def call(method, **params):
                calls.append((method, params))
                if method == "docs.getMessagesUploadServer":
                    return {"upload_url": "https://vk-upload.test/upload"}
                return saved_response

            async def get_session():
                return session

            async def send_message(peer_id, message, attachment=None, keyboard=None):
                sent.append((peer_id, message, attachment))
                return "sent"

            client.call = call
            client._get_session = get_session
            client.send_message = send_message

            result = await client.send_document(
                42, b"document-bytes", "manual.pdf", "Manual"
            )

            assert result == "sent"
            assert calls[1] == (
                "docs.save",
                {"file": "upload-ticket", "title": "Manual"},
            )
            assert session.request_options == {}

        assert sent == [
            (42, "📎 Manual", "doc-10_21_key"),
            (42, "📎 Manual", "doc-10_22"),
        ]

    asyncio.run(exercise())


def test_document_download_explains_vk_error_15_without_assuming_scope_missing():
    from services.vk_api import VKAPIError

    async def exercise():
        class FakeService:
            async def download_document(self, _doc_id):
                return b"document", "document.pdf"

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_document(self, *_args):
                raise VKAPIError("Access denied", error_code=15)

            async def send_message(self, _peer_id, message, **_kwargs):
                self.messages.append(message)

        vk_client = FakeVKClient()
        app = web.Application()
        app["document_service"] = FakeService()
        app["vk_client"] = vk_client
        app["menu_state"] = NavStateManager()

        await handle_vk_action(
            app, 42, 42, "download_document", {"doc_id": "DOC-1"}
        )

        assert "актуальный токен нужного сообщества" in vk_client.messages[-1]
        assert "разрешение «Документы» выдано этому токену" in vk_client.messages[-1]
        assert "перезапустите бота" in vk_client.messages[-1]

    asyncio.run(exercise())


def test_document_card_and_back_return_to_current_list_page(tmp_path):
    async def exercise():
        file_path = tmp_path / "existing.pdf"
        file_path.write_bytes(b"pdf")

        class FakeDoc:
            def __init__(self, index):
                self.doc_id = f"DOC-{index}"
                self.title = f"Document {index}"
                self.status = "Активен"
                self.file_path = str(file_path)

        class FakeService:
            def __init__(self):
                self.docs = [FakeDoc(index) for index in range(20)]
                self.list_calls = []
                self.download_calls = 0

            async def get_document_list(self, page=1, per_page=10):
                self.list_calls.append((page, per_page))
                start = (page - 1) * per_page
                return self.docs[start : start + per_page], len(self.docs)

            async def get_document_info(self, doc_id):
                doc = next(doc for doc in self.docs if doc.doc_id == doc_id)
                return {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "status": doc.status,
                    "file_path": doc.file_path,
                }

            async def download_document(self, _doc_id):
                self.download_calls += 1
                return b"pdf", "existing.pdf"

        class FakeVKClient:
            def __init__(self):
                self.messages = []
                self.documents = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append({"message": message, "keyboard": keyboard})

            async def send_document(self, *args):
                self.documents.append(args)

        service = FakeService()
        vk_client = FakeVKClient()
        state = NavStateManager()
        app = web.Application()
        app["document_service"] = service
        app["vk_client"] = vk_client
        app["menu_state"] = state

        await handle_vk_action(app, 42, 42, "open_document_list")
        await handle_vk_action(app, 42, 42, "list_page", {"page": 2})
        list_keyboard = vk_client.messages[-1]["keyboard"]
        open_payload = parse_payload(
            list_keyboard["buttons"][0][0]["action"]["payload"]
        )
        assert open_payload["page"] == 2

        await handle_vk_action(app, 42, 42, "open_document", open_payload)
        assert state.current(42) == "document_card"
        assert service.download_calls == 0
        assert not vk_client.documents
        assert "Файл доступен" in vk_client.messages[-1]["message"]

        await handle_vk_action(app, 42, 42, "back")
        assert state.current(42) == "document_list"
        assert service.list_calls[-1] == (2, 8)
        assert "Документы 2/3" in vk_client.messages[-1]["message"]

    asyncio.run(exercise())


def test_document_without_file_still_opens_card_without_download_button():
    async def exercise():
        class FakeService:
            async def get_document_info(self, doc_id):
                return {
                    "doc_id": doc_id,
                    "title": "Metadata only",
                    "file_path": None,
                }

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append({"message": message, "keyboard": keyboard})

        state = NavStateManager()
        vk_client = FakeVKClient()
        app = web.Application()
        app["document_service"] = FakeService()
        app["vk_client"] = vk_client
        app["menu_state"] = state

        await handle_vk_action(app, 42, 42, "open_document", {"doc_id": "DOC-1"})

        assert "Файл отсутствует" in vk_client.messages[-1]["message"]
        payloads = [
            parse_payload(button["action"]["payload"])
            for row in vk_client.messages[-1]["keyboard"]["buttons"]
            for button in row
        ]
        assert not any(item.get("action") == "download_document" for item in payloads)

    asyncio.run(exercise())


def test_vk_user_is_greeted_only_once(tmp_path):
    async def exercise():
        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'vk-users.db'}")
        await db.initialize()
        assert await db.register_vk_user(987654321) is True
        assert await db.register_vk_user(987654321) is False
        await db.close()

        fallback_db = DocumentDatabase()
        assert await fallback_db.register_vk_user(123456789) is True
        assert await fallback_db.register_vk_user(123456789) is False

    asyncio.run(exercise())


def test_relative_database_path_is_resolved_to_project_root(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///documents.db")
    import importlib
    import config

    importlib.reload(config)
    db_url = config.Config.DATABASE_URL
    assert db_url.startswith("sqlite+aiosqlite:///")
    db_path = db_url.split("sqlite+aiosqlite:///", 1)[1]
    assert os.path.isabs(db_path)


def test_pending_upload_is_saved_to_database(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setattr(Config, "UPLOAD_DIR", str(tmp_path / "uploads"))
        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'uploads.db'}")
        await db.initialize()
        service = DocumentService(db=db)
        app = web.Application()
        app["document_service"] = service
        app["pending_uploads"] = {
            123: {
                "file_name": "specification.pdf",
                "file_bytes": b"pdf-bytes",
                "file_hash": "abc123",
            }
        }
        result = await persist_pending_upload(app, 123, 456)
        assert "сохранён" in result.lower()
        assert await db.get_total_count() == 1
        await db.close()

    asyncio.run(exercise())


def test_upload_button_flow_stores_retrievable_document_file(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setattr(Config, "UPLOAD_DIR", str(tmp_path / "documents"))
        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'button-upload.db'}")
        await db.initialize()
        service = DocumentService(db=db)

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append({"message": message, "keyboard": keyboard})

            async def download_attachment(self, attachment):
                return b"uploaded-pdf-bytes"

        vk_client = FakeVKClient()
        app = web.Application()
        app["document_service"] = service
        app["vk_client"] = vk_client
        app["menu_state"] = NavStateManager()
        app["pending_uploads"] = {}

        await handle_vk_action(app, 123, 123, "open_upload")
        assert app["menu_state"].current(123) == "upload_waiting"

        await process_message(
            app,
            {"text": "", "attachments": [{"type": "doc", "doc": {"title": "spec.pdf"}}]},
            123,
            123,
        )
        assert app["menu_state"].current(123) == "upload_confirm"

        await handle_vk_action(app, 123, 123, "confirm_upload")
        docs = await db.get_all_documents(1, 10)
        assert len(docs) == 1
        assert docs[0].file_path
        assert os.path.isfile(docs[0].file_path)
        assert await service.download_document(docs[0].doc_id) == (
            b"uploaded-pdf-bytes",
            "spec.pdf",
        )
        await db.close()

    asyncio.run(exercise())


def test_filter_tag_button_applies_database_filter():
    async def exercise():
        class FakeDoc:
            doc_id = "DOC-TAG"
            title = "Проверочный документ"
            status = "Активен"
            doc_type = "Чертеж"

        class FakeService:
            def __init__(self):
                self.filtered_tag = None

            async def get_available_tags(self):
                return ["насос", "вал"]

            async def filter_documents(self, tags=None):
                self.filtered_tag = tags
                return [FakeDoc()]

        class FakeVKClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, peer_id, message, attachment=None, keyboard=None):
                self.messages.append({"message": message, "keyboard": keyboard})

        service = FakeService()
        vk_client = FakeVKClient()
        app = web.Application()
        app["document_service"] = service
        app["vk_client"] = vk_client
        app["menu_state"] = NavStateManager()

        await handle_vk_action(app, 123, 123, "filter_mode", {"filter_name": "tags"})
        keyboard = vk_client.messages[-1]["keyboard"]
        tag_buttons = [button for row in keyboard["buttons"] for button in row]
        tag_payloads = [parse_payload(button["action"]["payload"]) for button in tag_buttons]
        assert any(item == {"action": "filter_tag", "tag": "насос"} for item in tag_payloads)

        await handle_vk_action(app, 123, 123, "filter_tag", {"tag": "насос"})
        assert service.filtered_tag == "насос"
        assert "Проверочный документ" in vk_client.messages[-1]["message"]

    asyncio.run(exercise())


def test_folder_import_repairs_legacy_file_and_is_idempotent(tmp_path):
    async def exercise():
        source = tmp_path / "source"
        source.mkdir()
        source_file = source / "part.pdf"
        source_file.write_bytes(b"existing-pdf")

        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'folder-import.db'}")
        await db.initialize()
        await db.add_document(
            {
                "doc_id": "DOC-FS-OLD",
                "title": "part",
                "file_name": "part.pdf",
                "file_path": str(source / "old-location" / "part.pdf"),
                "tags": "imported",
            }
        )
        service = DocumentService(db=db)

        assert await service.import_documents_from_folder(str(source)) == 0
        assert await db.get_total_count() == 1
        document = await db.get_document_by_id("DOC-FS-OLD")
        assert document.file_path == str(source_file)
        assert await service.download_document("DOC-FS-OLD") == (
            b"existing-pdf",
            "part.pdf",
        )
        assert await service.import_documents_from_folder(str(source)) == 0
        assert await db.get_total_count() == 1
        docs, total = await service.get_document_list(page=1, per_page=10)
        assert len(docs) == total == 1
        await db.close()

    asyncio.run(exercise())


def test_startup_repair_links_only_existing_database_records(tmp_path):
    async def exercise():
        upload_dir = tmp_path / "documents"
        upload_dir.mkdir()
        indexed_file = upload_dir / "indexed.pdf"
        indexed_file.write_bytes(b"indexed-content")
        (upload_dir / "unindexed.pdf").write_bytes(b"unindexed-content")

        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'repair.db'}")
        await db.initialize()
        await db.add_document(
            {
                "doc_id": "DOC-FS-LEGACY",
                "title": "indexed",
                "file_name": "indexed.pdf",
                "file_path": None,
            }
        )
        service = DocumentService(db=db)

        assert await service.repair_missing_file_paths(str(upload_dir)) == 1
        assert await db.get_total_count() == 1
        assert await service.download_document("DOC-FS-LEGACY") == (
            b"indexed-content",
            "indexed.pdf",
        )
        await db.close()

    asyncio.run(exercise())


def test_folder_import_indexes_and_downloads_xlsx(tmp_path):
    async def exercise():
        source = tmp_path / "source"
        source.mkdir()
        source_file = source / "materials.xlsx"
        source_file.write_bytes(b"spreadsheet")

        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'xlsx-import.db'}")
        await db.initialize()
        service = DocumentService(db=db)

        assert await service.import_documents_from_folder(str(source)) == 1
        docs, total = await service.get_document_list(page=1, per_page=10)
        assert total == len(docs) == 1
        assert docs[0].file_name == "materials.xlsx"
        assert await service.download_document(docs[0].doc_id) == (
            b"spreadsheet",
            "materials.xlsx",
        )
        await db.close()

    asyncio.run(exercise())


def test_service_initialization_imports_configured_folder(tmp_path, monkeypatch):
    from main import init_services

    import main
    from database.repository import DocumentDatabase

    class FakeLLM:
        enabled = True

        async def is_available(self):
            return False

    async def exercise():
        import_dir = tmp_path / "import_docs"
        import_dir.mkdir()
        (import_dir / "startup.pdf").write_bytes(b"startup-pdf")

        db = DocumentDatabase(f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}")
        monkeypatch.setattr(main, "DocumentDatabase", lambda: db)
        monkeypatch.setattr(main.Config, "IMPORT_DIR", str(import_dir))
        monkeypatch.setattr(main.Config, "UPLOAD_DIR", str(tmp_path / "uploads"))
        monkeypatch.setattr(main, "LLMProcessor", lambda **_kwargs: FakeLLM())

        db, service = await init_services()
        try:
            docs, total = await service.get_document_list(page=1, per_page=10)
            assert total == len(docs) == 1
            assert docs[0].file_name == "startup.pdf"
        finally:
            await db.close()

    asyncio.run(exercise())


def test_text_keyboard_payload_dispatches_button_action_and_logs(caplog):
    class FakeDB:
        async def register_vk_user(self, vk_id):
            return False

    class FakeVKClient:
        def __init__(self):
            self.messages = []

        async def send_message(self, peer_id, message, attachment=None, keyboard=None):
            self.messages.append({"message": message, "keyboard": keyboard})

    class FakeService:
        pass

    app = web.Application()
    app["db"] = FakeDB()
    app["document_service"] = FakeService()
    app["vk_client"] = FakeVKClient()
    app["menu_state"] = NavStateManager()
    app["pending_uploads"] = {}

    async def exercise():
        await process_message(
            app,
            {"text": "🔎 Поиск", "payload": build_payload("open_search")},
            101,
            202,
        )

    caplog.set_level(logging.INFO, logger="docbot")
    asyncio.run(exercise())

    assert app["menu_state"].current(101) == "search"
    assert "Введите название документа" in app["vk_client"].messages[-1]["message"]
    assert "🔎 Поиск" in caplog.text


def test_main_menu_payload_buttons_dispatch_to_their_own_handlers():
    class FakeDB:
        async def register_vk_user(self, vk_id):
            return False

    class FakeVKClient:
        def __init__(self):
            self.messages = []

        async def send_message(self, peer_id, message, attachment=None, keyboard=None):
            self.messages.append({"message": message, "keyboard": keyboard})

    class FakeService:
        async def get_available_tags(self):
            return ["насос"]

        async def get_document_list(self, page=1, per_page=10):
            return [], 0

    app = web.Application()
    app["db"] = FakeDB()
    app["document_service"] = FakeService()
    app["vk_client"] = FakeVKClient()
    app["menu_state"] = NavStateManager()
    app["pending_uploads"] = {}

    expected_responses = {
        "open_search": "Введите название документа",
        "open_smart_search": "умного поиска",
        "open_filters": "Выберите тег",
        "open_document_list": "В архиве пока нет документов",
        "open_upload": "Отправьте один файл документа",
        "main_menu": "Главное меню",
    }

    async def exercise():
        buttons = build_main_menu_keyboard()["buttons"]
        payload_actions = {
            parse_payload(button["action"]["payload"])["action"]
            for row in buttons for button in row
        }
        assert payload_actions == set(expected_responses)

        for action, expected_text in expected_responses.items():
            await process_message(
                app,
                {"text": f"button label {action}", "payload": build_payload(action)},
                101,
                202,
            )
            assert expected_text in app["vk_client"].messages[-1]["message"]

    asyncio.run(exercise())