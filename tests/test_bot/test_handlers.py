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
    sent_text = fake_update.message.reply_text.await_args[0][0]
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

