from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers import CommandHandlers


@pytest.mark.asyncio
async def test_start_command_replies(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=lambda: None)
    async_retry_stub(handler)

    await handler.start_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()


@pytest.mark.asyncio
async def test_help_command_replies(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    await handler.help_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    sent_text = call.kwargs.get("text", call.args[0])
    assert "/start" in sent_text
    assert "/help" in sent_text


@pytest.mark.asyncio
async def test_start_command_handles_retry_failure(fake_update: Any, fake_context: Any, monkeypatch: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)

    def failing_retry(func: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    fake_logger = MagicMock()
    handler.logger = fake_logger
    monkeypatch.setattr(handler, "_retry_on_connect_error", failing_retry)

    # Метод не должен выбрасывать исключение наружу
    await handler.start_command(fake_update, fake_context)

    fake_logger.error.assert_called()


@pytest.mark.asyncio
async def test_help_command_admin_version(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=lambda: None)
    async_retry_stub(handler)
    # Используем Union для совместимости с тестовым SimpleNamespace
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)  # type: ignore[assignment]

    await handler.help_command(fake_update, fake_context)

    call = fake_update.message.reply_text.await_args
    sent_text = call.kwargs.get("text", call.args[0])
    assert "Админ-справка" in sent_text


@pytest.mark.asyncio
async def test_set_frog_limit_command_success(fake_update: Any, fake_context: Any) -> None:
    class FakeUsage:
        def __init__(self) -> None:
            self.frog_threshold: int = 70
            self.monthly_quota: int = 100
            self.total: int = 10

        def set_frog_threshold(self, value: int) -> int:
            self.frog_threshold = value
            return value

        def get_limits_info(self) -> tuple[int, int, int]:
            return self.total, self.frog_threshold, self.monthly_quota

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)  # type: ignore[assignment]

    fake_context.application.bot_data["usage"] = FakeUsage()
    fake_context.args = ["80"]

    await handler.set_frog_limit_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Порог /frog установлен" in message


@pytest.mark.asyncio
async def test_set_frog_limit_command_invalid(fake_update: Any, fake_context: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)  # type: ignore[assignment]
    fake_context.args = ["-5"]

    await handler.set_frog_limit_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Неверный параметр" in message


@pytest.mark.asyncio
async def test_frog_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    monkeypatch: Any,
) -> None:
    class DummyGenerator:
        def __init__(self) -> None:
            self.generate_frog_image = AsyncMock(return_value=(b"image", "caption"))
            self.save_image_locally = MagicMock(return_value="saved")
            self.get_random_saved_image = MagicMock(return_value=None)

    class DummyUsage:
        def __init__(self) -> None:
            self.count: int = 0
            self.monthly_quota: int = 100
            self.frog_threshold: int = 70

        def can_use_frog(self) -> bool:
            return True

        def get_limits_info(self) -> tuple[int, int, int]:
            return self.count, self.frog_threshold, self.monthly_quota

        def increment(self, value: int) -> None:
            self.count += value

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)  # type: ignore[arg-type]
    async_retry_stub(handler)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: False, list_all_admins=lambda: [])  # type: ignore[assignment]

    fake_context.application.bot_data["usage"] = DummyUsage()

    await handler.frog_command(fake_update, fake_context)

    fake_update.message.reply_photo.assert_awaited_once()
    generator.save_image_locally.assert_called_once()
    assert fake_context.application.bot_data["usage"].count == 1
    fake_update.message.reply_text.return_value.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_frog_command_usage_limit(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    class DummyGenerator:
        def __init__(self) -> None:
            self.generate_frog_image = AsyncMock(return_value=(b"image", "caption"))
            self.save_image_locally = MagicMock(return_value="saved")
            self.get_random_saved_image = MagicMock(return_value=None)

    class LimitedUsage:
        def __init__(self) -> None:
            self.monthly_quota: int = 100
            self.frog_threshold: int = 70

        def can_use_frog(self) -> bool:
            return False

        def get_limits_info(self) -> tuple[int, int, int]:
            return 70, self.frog_threshold, self.monthly_quota

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)  # type: ignore[arg-type]
    async_retry_stub(handler)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: False)  # type: ignore[assignment]

    fake_context.application.bot_data["usage"] = LimitedUsage()

    await handler.frog_command(fake_update, fake_context)

    call = fake_update.message.reply_text.await_args
    message = call.kwargs.get("text", call.args[0])
    assert "Лимит ручных генераций" in message
    assert fake_update.message.reply_photo.await_count == 0
