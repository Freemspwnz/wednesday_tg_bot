from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import Any

import pytest


@pytest.fixture
def wednesday_bot(monkeypatch: Any) -> Any:
    from bot import wednesday_bot as wb_module

    class DummyApplication:
        def __init__(self) -> None:
            self.added_handlers: list[Any] = []
            self.bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
            self.bot_data: dict[str, Any] = {}
            self.updater = SimpleNamespace(stop=AsyncMock())

        def add_handler(self, handler: Any) -> None:
            self.added_handlers.append(handler)

    def builder_factory() -> Any:
        app_instance = DummyApplication()

        class Builder:
            def __init__(self) -> None:
                self._token: Any = None
                self._request: Any = None

            def token(self, token: str) -> 'Builder':
                self._token = token
                return self

            def request(self, request: Any) -> 'Builder':
                self._request = request
                return self

            def build(self) -> DummyApplication:
                return app_instance

        return Builder()

    monkeypatch.setattr(wb_module, "Application", SimpleNamespace(builder=lambda: builder_factory()))
    monkeypatch.setattr(wb_module, "HTTPXRequest", lambda **kwargs: SimpleNamespace(**kwargs))

    class DummyImageGenerator:
        def __init__(self) -> None:
            self.saved: list[Any] = []

        async def generate_frog_image(self, metrics: Any = None) -> tuple[bytes, str]:
            return b"img", "caption"

        def save_image_locally(self, image_data: bytes, folder: str = "data/frogs", prefix: str = "wednesday") -> str:
            self.saved.append((image_data, folder, prefix))
            return "saved_path"

    class DummyScheduler:
        def __init__(self) -> None:
            self.send_times: list[str] = ["10:00"]

        def get_next_run(self) -> Any:
            return None

    class DummyUsageTracker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.total: int = 0

        def increment(self, value: int) -> None:
            self.total += value

    class DummyChatsStore:
        def __init__(self) -> None:
            self.chat_ids: list[int] = [111]

        def list_chat_ids(self) -> list[int]:
            return list(self.chat_ids)

    class DummyDispatchRegistry:
        def __init__(self) -> None:
            self.sent: set[Any] = set()

        def is_dispatched(self, date: str, slot: str, chat_id: int) -> bool:
            return (date, slot, chat_id) in self.sent

        def mark_dispatched(self, date: str, slot: str, chat_id: int) -> None:
            self.sent.add((date, slot, chat_id))

    class DummyMetrics:
        def __init__(self) -> None:
            self.success: int = 0
            self.failed: int = 0

        def increment_dispatch_success(self) -> None:
            self.success += 1

        def increment_dispatch_failed(self) -> None:
            self.failed += 1

    class DummyHandlers:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.start_command = AsyncMock()
            self.help_command = AsyncMock()
            self.frog_command = AsyncMock()
            self.status_command = AsyncMock()
            self.admin_force_send_command = AsyncMock()
            self.admin_log_command = AsyncMock()
            self.admin_add_chat_command = AsyncMock()
            self.admin_remove_chat_command = AsyncMock()
            self.stop_command = AsyncMock()
            self.list_chats_command = AsyncMock()
            self.set_kandinsky_model_command = AsyncMock()
            self.set_gigachat_model_command = AsyncMock()
            self.mod_command = AsyncMock()
            self.unmod_command = AsyncMock()
            self.list_mods_command = AsyncMock()
            self.list_models_command = AsyncMock()
            self.set_frog_limit_command = AsyncMock()
            self.set_frog_used_command = AsyncMock()
            self.unknown_command = AsyncMock()

    class DummyCommandHandler:
        def __init__(self, command: Any, callback: Any) -> None:
            self.command = command
            self.callback = callback

    class DummyMessageHandler:
        def __init__(self, command_filter: Any, callback: Any) -> None:
            self.command_filter = command_filter
            self.callback = callback

    class DummyChatMemberHandler:
        MY_CHAT_MEMBER = object()

        def __init__(self, callback: Any, member_filter: Any) -> None:
            self.callback = callback
            self.member_filter = member_filter

    monkeypatch.setattr(wb_module, "ImageGenerator", DummyImageGenerator)
    monkeypatch.setattr(wb_module, "TaskScheduler", DummyScheduler)
    monkeypatch.setattr(wb_module, "UsageTracker", DummyUsageTracker)
    monkeypatch.setattr(wb_module, "ChatsStore", DummyChatsStore)
    monkeypatch.setattr(wb_module, "DispatchRegistry", DummyDispatchRegistry)
    monkeypatch.setattr(wb_module, "Metrics", DummyMetrics)
    monkeypatch.setattr(wb_module, "CommandHandlers", DummyHandlers)
    monkeypatch.setattr(wb_module, "CommandHandler", DummyCommandHandler)
    monkeypatch.setattr(wb_module, "MessageHandler", DummyMessageHandler)
    monkeypatch.setattr(wb_module, "ChatMemberHandler", DummyChatMemberHandler)
    monkeypatch.setattr(wb_module, "filters", SimpleNamespace(COMMAND="COMMAND"))

    bot = wb_module.WednesdayBot()
    return bot


def test_wednesday_bot_initializes_components(wednesday_bot: Any) -> None:
    assert wednesday_bot.application is not None
    assert wednesday_bot.handlers is not None
    assert wednesday_bot.scheduler is not None
    assert wednesday_bot.is_running is False


def test_setup_handlers_registers_all_callbacks(wednesday_bot: Any) -> None:
    wednesday_bot.setup_handlers()
    assert len(wednesday_bot.application.added_handlers) == 20


@pytest.mark.asyncio
async def test_send_wednesday_frog_dispatches_to_targets(monkeypatch: Any, wednesday_bot: Any) -> None:
    wednesday_bot.chat_id = "222"
    wednesday_bot.chats.chat_ids = [111]
    wednesday_bot.scheduler.send_times = ["10:00"]

    async def fake_generate(metrics: Any = None) -> tuple[bytes, str]:
        return b"img", "caption"

    wednesday_bot.image_generator.generate_frog_image = AsyncMock(side_effect=fake_generate)

    await wednesday_bot.send_wednesday_frog(slot_time="10:00")

    assert wednesday_bot.application.bot.send_photo.await_count == 2
    assert wednesday_bot.usage.total == 2
    assert wednesday_bot.metrics.success == 2


@pytest.mark.asyncio
async def test_send_wednesday_frog_without_targets(monkeypatch: Any, wednesday_bot: Any) -> None:
    wednesday_bot.chat_id = None
    wednesday_bot.chats.chat_ids = []
    wednesday_bot._send_error_message = AsyncMock()

    await wednesday_bot.send_wednesday_frog(slot_time="10:00")

    wednesday_bot._send_error_message.assert_awaited_once()
    assert wednesday_bot.application.bot.send_photo.await_count == 0

