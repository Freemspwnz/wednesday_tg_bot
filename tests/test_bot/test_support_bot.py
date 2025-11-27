from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def support_bot(monkeypatch: Any) -> Any:
    from bot import support_bot as sb_module

    class DummyApplication:
        def __init__(self) -> None:
            self.added_handlers: list[Any] = []
            self.bot = SimpleNamespace(send_message=AsyncMock(), edit_message_text=AsyncMock())
            self.bot_data: dict[str, Any] = {}
            self.updater = SimpleNamespace(stop=AsyncMock(), start_polling=AsyncMock())

        def add_handler(self, handler: Any) -> None:
            self.added_handlers.append(handler)

    def builder_factory() -> Any:
        app_instance = DummyApplication()

        class Builder:
            def token(self, token: str) -> "Builder":
                self._token = token
                return self

            def request(self, request: Any) -> "Builder":
                self._request = request
                return self

            def build(self) -> DummyApplication:
                return app_instance

        return Builder()

    def app_builder() -> Any:
        return builder_factory()

    monkeypatch.setattr(sb_module, "Application", SimpleNamespace(builder=app_builder))

    def http_request(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(sb_module, "HTTPXRequest", http_request)

    class DummyAdminsStore:
        def __init__(self) -> None:
            self.admins: set[int] = {1}

        async def is_admin(self, user_id: int) -> bool:
            return user_id in self.admins

        async def list_all_admins(self) -> list[int]:
            return list(self.admins)

    class DummyCommandHandler:
        def __init__(self, command: Any, callback: Any) -> None:
            self.command = command
            self.callback = callback

    class DummyMessageHandler:
        def __init__(self, command_filter: Any, callback: Any) -> None:
            self.command_filter = command_filter
            self.callback = callback

    monkeypatch.setattr(sb_module, "AdminsStore", DummyAdminsStore)
    monkeypatch.setattr(sb_module, "CommandHandler", DummyCommandHandler)
    monkeypatch.setattr(sb_module, "MessageHandler", DummyMessageHandler)
    monkeypatch.setattr(sb_module, "filters", SimpleNamespace(COMMAND="COMMAND"))

    bot = sb_module.SupportBot()
    return bot


def _make_update(user_id: int = 1, chat_id: int = 10, text: str = "/cmd") -> Any:
    message = SimpleNamespace(
        reply_text=AsyncMock(),
        text=text,
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        message=message,
    )


def _make_context(args: Any = None) -> Any:
    return SimpleNamespace(
        args=args or [],
        bot=SimpleNamespace(send_document=AsyncMock()),
    )


def test_support_bot_setup_handlers(support_bot: Any) -> None:
    support_bot.setup_handlers()
    EXPECTED_HANDLERS_COUNT = 4
    assert len(support_bot.application.added_handlers) == EXPECTED_HANDLERS_COUNT


@pytest.mark.asyncio
async def test_maintenance_message_replies(support_bot: Any) -> None:
    update = _make_update()
    context = SimpleNamespace()

    await support_bot.maintenance_message(update, context)

    update.message.reply_text.assert_awaited_once()
    call = update.message.reply_text.await_args
    sent_text = call.kwargs.get("text", call.args[0])  # безопасное получение текста
    assert "Технические работы" in sent_text


@pytest.mark.asyncio
async def test_log_command_non_admin(support_bot: Any) -> None:
    support_bot.admins.admins = set()  # нет админов
    update = _make_update(user_id=2)
    context = _make_context()

    await support_bot.log_command(update, context)

    update.message.reply_text.assert_awaited_once()
    call = update.message.reply_text.await_args
    message = call.kwargs.get("text", call.args[0])
    assert "Доступно только администратору" in message


@pytest.mark.asyncio
async def test_log_command_no_logs_directory(monkeypatch: Any, support_bot: Any) -> None:
    update = _make_update(user_id=1)
    context = _make_context()

    class DummyPath:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def exists(self) -> bool:
            return False

    monkeypatch.setattr("bot.support_bot.Path", DummyPath)

    await support_bot.log_command(update, context)

    update.message.reply_text.assert_awaited()
    messages = []
    for call in update.message.reply_text.await_args_list:
        if call.kwargs.get("text"):
            messages.append(call.kwargs["text"])
        elif call.args:
            messages.append(call.args[0])
    assert any("папка logs пуста" in msg.lower() for msg in messages)
