import asyncio

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
)


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