from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers import CommandHandlers


@pytest.mark.asyncio
async def test_start_command_replies(fake_update, fake_context, async_retry_stub):
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=lambda: None)
    async_retry_stub(handler)

    await handler.start_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()


@pytest.mark.asyncio
async def test_help_command_replies(fake_update, fake_context, async_retry_stub):
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    await handler.help_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    sent_text = call.kwargs.get("text", call.args[0])
    assert "/start" in sent_text
    assert "/help" in sent_text


@pytest.mark.asyncio
async def test_start_command_handles_retry_failure(fake_update, fake_context, monkeypatch):
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)

    async def failing_retry(func, *args, **kwargs):
        raise RuntimeError("boom")

    fake_logger = MagicMock()
    handler.logger = fake_logger
    monkeypatch.setattr(handler, "_retry_on_connect_error", failing_retry)

    # Метод не должен выбрасывать исключение наружу
    await handler.start_command(fake_update, fake_context)

    fake_logger.error.assert_called()


@pytest.mark.asyncio
async def test_help_command_admin_version(fake_update, fake_context, async_retry_stub):
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=lambda: None)
    async_retry_stub(handler)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)

    await handler.help_command(fake_update, fake_context)

    call = fake_update.message.reply_text.await_args
    sent_text = call.kwargs.get("text", call.args[0])
    assert "Админ-справка" in sent_text


@pytest.mark.asyncio
async def test_set_frog_limit_command_success(fake_update, fake_context):
    class FakeUsage:
        def __init__(self):
            self.frog_threshold = 70
            self.monthly_quota = 100
            self.total = 10

        def set_frog_threshold(self, value):
            self.frog_threshold = value
            return value

        def get_limits_info(self):
            return self.total, self.frog_threshold, self.monthly_quota

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)

    fake_context.application.bot_data["usage"] = FakeUsage()
    fake_context.args = ["80"]

    await handler.set_frog_limit_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Порог /frog установлен" in message


@pytest.mark.asyncio
async def test_set_frog_limit_command_invalid(fake_update, fake_context):
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: True)
    fake_context.args = ["-5"]

    await handler.set_frog_limit_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Неверный параметр" in message


@pytest.mark.asyncio
async def test_frog_command_success(fake_update, fake_context, async_retry_stub, monkeypatch):
    class DummyGenerator:
        def __init__(self):
            self.generate_frog_image = AsyncMock(return_value=(b"image", "caption"))
            self.save_image_locally = MagicMock(return_value="saved")
            self.get_random_saved_image = MagicMock(return_value=None)

    class DummyUsage:
        def __init__(self):
            self.count = 0
            self.monthly_quota = 100
            self.frog_threshold = 70

        def can_use_frog(self):
            return True

        def get_limits_info(self):
            return self.count, self.frog_threshold, self.monthly_quota

        def increment(self, value):
            self.count += value

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)
    async_retry_stub(handler)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: False, list_all_admins=lambda: [])

    fake_context.application.bot_data["usage"] = DummyUsage()

    await handler.frog_command(fake_update, fake_context)

    fake_update.message.reply_photo.assert_awaited_once()
    generator.save_image_locally.assert_called_once()
    assert fake_context.application.bot_data["usage"].count == 1
    fake_update.message.reply_text.return_value.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_frog_command_usage_limit(fake_update, fake_context, async_retry_stub):
    class DummyGenerator:
        def __init__(self):
            self.generate_frog_image = AsyncMock(return_value=(b"image", "caption"))
            self.save_image_locally = MagicMock(return_value="saved")
            self.get_random_saved_image = MagicMock(return_value=None)

    class LimitedUsage:
        def __init__(self):
            self.monthly_quota = 100
            self.frog_threshold = 70

        def can_use_frog(self):
            return False

        def get_limits_info(self):
            return 70, self.frog_threshold, self.monthly_quota

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)
    async_retry_stub(handler)
    handler.admins_store = SimpleNamespace(is_admin=lambda _uid: False)

    fake_context.application.bot_data["usage"] = LimitedUsage()

    await handler.frog_command(fake_update, fake_context)

    call = fake_update.message.reply_text.await_args
    message = call.kwargs.get("text", call.args[0])
    assert "Лимит ручных генераций" in message
    assert fake_update.message.reply_photo.await_count == 0

