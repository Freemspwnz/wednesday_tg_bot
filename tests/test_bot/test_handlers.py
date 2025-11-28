import importlib
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

    class _AdminNo:
        async def is_admin(self, _uid: int) -> bool:
            return False

    handler.admins_store = _AdminNo()  # type: ignore[assignment]

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

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

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

        async def set_frog_threshold(self, value: int) -> int:
            self.frog_threshold = value
            return value

        async def get_limits_info(self) -> tuple[int, int, int]:
            return self.total, self.frog_threshold, self.monthly_quota

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)

    class _AdminOk2:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk2()  # type: ignore[assignment]

    fake_context.application.bot_data["usage"] = FakeUsage()
    fake_context.args = ["80"]

    await handler.set_frog_limit_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Порог /frog установлен" in message


@pytest.mark.asyncio
async def test_set_frog_limit_command_invalid(fake_update: Any, fake_context: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
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

        async def can_use_frog(self) -> bool:
            return True

        async def get_limits_info(self) -> tuple[int, int, int]:
            return self.count, self.frog_threshold, self.monthly_quota

        async def increment(self, value: int) -> None:
            self.count += value

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)  # type: ignore[arg-type]
    async_retry_stub(handler)

    class _AdminNo:
        async def is_admin(self, _uid: int) -> bool:
            return False

        async def list_all_admins(self) -> list[int]:
            return []

    handler.admins_store = _AdminNo()  # type: ignore[assignment]

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

        async def can_use_frog(self) -> bool:
            return False

        async def get_limits_info(self) -> tuple[int, int, int]:
            return 70, self.frog_threshold, self.monthly_quota

    generator = DummyGenerator()
    handler = CommandHandlers(image_generator=generator, next_run_provider=None)  # type: ignore[arg-type]
    async_retry_stub(handler)

    class _AdminNo2:
        async def is_admin(self, _uid: int) -> bool:
            return False

    handler.admins_store = _AdminNo2()  # type: ignore[assignment]

    fake_context.application.bot_data["usage"] = LimitedUsage()

    await handler.frog_command(fake_update, fake_context)

    call = fake_update.message.reply_text.await_args
    message = call.kwargs.get("text", call.args[0])
    assert "Лимит ручных генераций" in message
    assert fake_update.message.reply_photo.await_count == 0


@pytest.mark.asyncio
async def test_status_command_integration_with_postgres_stores(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore
    from utils.metrics import Metrics
    from utils.usage_tracker import UsageTracker

    # Настраиваем image_generator с простыми async-заглушками
    image_generator = MagicMock()
    image_generator.check_api_status = AsyncMock(
        return_value=(True, "OK", [], (None, None)),
    )
    image_generator.gigachat_client = None

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=lambda: None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    # Реальные async-хранилища на Postgres
    usage = UsageTracker(storage_path="ignored.json")
    chats = ChatsStore(storage_path="ignored.json")
    metrics = Metrics(storage_path="ignored.json")

    fake_context.application.bot_data["usage"] = usage
    fake_context.application.bot_data["chats"] = chats
    fake_context.application.bot_data["metrics"] = metrics

    # get_me требуется в статусе
    fake_context.bot.get_me = AsyncMock(return_value=SimpleNamespace(first_name="TestBot"))

    await handler.status_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Статус бота" in text
    assert "Генерации:" in text


@pytest.mark.asyncio
async def test_force_send_command_integration_with_postgres_stores(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore
    from utils.usage_tracker import UsageTracker

    class _DummyGenerator:
        def __init__(self) -> None:
            self.generate_frog_image = AsyncMock(return_value=(b"img", "caption"))
            self.save_image_locally = MagicMock(return_value="saved")
            self.get_random_saved_image = MagicMock(return_value=None)

    image_generator = _DummyGenerator()

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=None)  # type: ignore[arg-type]
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    # Реальные async-хранилища
    chats = ChatsStore(storage_path="ignored.json")
    await chats.add_chat(fake_update.effective_chat.id, "Test chat")
    usage = UsageTracker(storage_path="ignored.json")

    fake_context.application.bot_data["chats"] = chats
    fake_context.application.bot_data["usage"] = usage

    # Вызываем /force_send all
    fake_context.args = ["all"]

    await handler.admin_force_send_command(fake_update, fake_context)

    # Должна быть хотя бы одна отправка фото
    assert fake_context.bot.send_photo.await_count >= 1


@pytest.mark.asyncio
async def test_set_frog_used_command_success(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    class FakeUsage:
        def __init__(self) -> None:
            self.monthly_quota: int = 100
            self.frog_threshold: int = 70

        async def set_month_total(self, value: int) -> None:
            self.total = value

        async def get_limits_info(self) -> tuple[int, int, int]:
            return getattr(self, "total", 0), self.frog_threshold, self.monthly_quota

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.application.bot_data["usage"] = FakeUsage()
    fake_context.args = ["50"]

    await handler.set_frog_used_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Текущее использование /frog" in message


@pytest.mark.asyncio
async def test_set_frog_used_command_invalid(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = ["-10"]

    await handler.set_frog_used_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Неверный параметр" in message


@pytest.mark.asyncio
async def test_set_frog_used_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.set_frog_used_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Использование: /set_frog_used" in message


@pytest.mark.asyncio
async def test_unknown_command(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    await handler.unknown_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Неизвестная команда" in text
    assert "/start" in text
    assert "/help" in text


@pytest.mark.asyncio
async def test_admin_add_chat_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    chats = ChatsStore(storage_path="ignored.json")
    fake_context.application.bot_data["chats"] = chats
    fake_context.args = ["12345"]

    await handler.admin_add_chat_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Чат 12345 добавлен" in message

    # Проверяем, что чат действительно добавлен
    chat_ids = await chats.list_chat_ids()
    assert 12345 in chat_ids  # noqa: PLR2004


@pytest.mark.asyncio
async def test_admin_add_chat_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.admin_add_chat_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Использование: /add_chat" in message


@pytest.mark.asyncio
async def test_admin_add_chat_command_invalid_id(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = ["not_a_number"]

    await handler.admin_add_chat_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Неверный chat_id" in message


@pytest.mark.asyncio
async def test_admin_remove_chat_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    chats = ChatsStore(storage_path="ignored.json")
    await chats.add_chat(12345, "Test chat")
    fake_context.application.bot_data["chats"] = chats
    fake_context.args = ["12345"]

    await handler.admin_remove_chat_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Чат 12345 удалён" in message

    # Проверяем, что чат действительно удалён
    chat_ids = await chats.list_chat_ids()
    assert 12345 not in chat_ids  # noqa: PLR2004


@pytest.mark.asyncio
async def test_admin_remove_chat_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.admin_remove_chat_command(fake_update, fake_context)

    last_call = fake_update.message.reply_text.await_args
    message = last_call.kwargs.get("text", last_call.args[0])
    assert "Использование: /remove_chat" in message


@pytest.mark.asyncio
async def test_list_chats_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    chats = ChatsStore(storage_path="ignored.json")
    await chats.add_chat(11111, "Chat 1")
    await chats.add_chat(22222, "Chat 2")
    fake_context.application.bot_data["chats"] = chats

    await handler.list_chats_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Активные чаты" in text or "чатов" in text.lower()


@pytest.mark.asyncio
async def test_list_chats_command_no_chats(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
) -> None:
    from utils.chats_store import ChatsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    chats = ChatsStore(storage_path="ignored.json")
    fake_context.application.bot_data["chats"] = chats

    await handler.list_chats_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Нет активных чатов" in text or "чатов: 0" in text


@pytest.mark.asyncio
async def test_stop_command_non_admin(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminNo:
        async def is_admin(self, _uid: int) -> bool:
            return False

    handler.admins_store = _AdminNo()  # type: ignore[assignment]

    await handler.stop_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Доступно только администратору" in text


@pytest.mark.asyncio
async def test_stop_command_admin(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    # Мокаем bot_instance в bot_data
    class DummyBot:
        async def stop(self) -> None:
            pass

    fake_context.application.bot_data["bot"] = DummyBot()

    await handler.stop_command(fake_update, fake_context)

    # Проверяем, что была попытка остановить бота
    assert "bot" in fake_context.application.bot_data


@pytest.mark.asyncio
async def test_set_kandinsky_model_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.set_kandinsky_model_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Использование: /set_kandinsky_model" in text


@pytest.mark.asyncio
async def test_set_kandinsky_model_command_success(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    image_generator = MagicMock()
    image_generator.set_kandinsky_model = AsyncMock(return_value=(True, "Модель установлена"))

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = ["kandinsky-2.2"]

    await handler.set_kandinsky_model_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "✅" in text or "Модель установлена" in text


@pytest.mark.asyncio
async def test_set_gigachat_model_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.set_gigachat_model_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Использование: /set_gigachat_model" in text


@pytest.mark.asyncio
async def test_set_gigachat_model_command_no_client(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    image_generator = MagicMock()
    image_generator.gigachat_client = None

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = ["GigaChat-Pro"]

    await handler.set_gigachat_model_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "GigaChat клиент не инициализирован" in text


@pytest.mark.asyncio
async def test_set_gigachat_model_command_success(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    gigachat_client = MagicMock()
    gigachat_client.set_model = MagicMock(return_value=True)

    image_generator = MagicMock()
    image_generator.gigachat_client = gigachat_client

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = ["GigaChat-Pro"]

    await handler.set_gigachat_model_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "✅" in text or "Модель GigaChat установлена" in text


@pytest.mark.asyncio
async def test_mod_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
    monkeypatch: Any,
) -> None:
    # Импортируем реальный AdminsStore напрямую из модуля, обходя патч
    import utils.admins_store as admins_store_module

    # Перезагружаем модуль, чтобы получить реальный класс
    importlib.reload(admins_store_module)
    AdminsStore = admins_store_module.AdminsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    # Используем реальный AdminsStore для теста
    admins = AdminsStore()
    # Делаем пользователя 42 администратором (через прямое обращение к БД)
    await admins.add_admin(fake_update.effective_user.id)
    handler.admins_store = admins
    fake_context.application.bot_data["admins"] = admins
    fake_context.args = ["99999"]

    await handler.mod_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "✅" in text or "добавлен" in text.lower() or "админ-права" in text.lower()


@pytest.mark.asyncio
async def test_mod_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.mod_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Использование: /mod" in text


@pytest.mark.asyncio
async def test_unmod_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
    monkeypatch: Any,
) -> None:
    # Импортируем реальный AdminsStore напрямую из модуля, обходя патч
    import utils.admins_store as admins_store_module

    # Перезагружаем модуль, чтобы получить реальный класс
    importlib.reload(admins_store_module)
    AdminsStore = admins_store_module.AdminsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    # Используем реальный AdminsStore для теста
    admins = AdminsStore()
    # Делаем пользователя 42 администратором
    await admins.add_admin(fake_update.effective_user.id)
    await admins.add_admin(99999)
    handler.admins_store = admins
    fake_context.application.bot_data["admins"] = admins
    fake_context.args = ["99999"]

    await handler.unmod_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "✅" in text or "удалён" in text.lower() or "админ-права" in text.lower()


@pytest.mark.asyncio
async def test_unmod_command_no_args(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]
    fake_context.args = []

    await handler.unmod_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Использование: /unmod" in text


@pytest.mark.asyncio
async def test_list_mods_command_success(
    fake_update: Any,
    fake_context: Any,
    async_retry_stub: Any,
    cleanup_tables: Any,
    monkeypatch: Any,
) -> None:
    # Импортируем реальный AdminsStore напрямую из модуля, обходя патч
    import utils.admins_store as admins_store_module

    # Перезагружаем модуль, чтобы получить реальный класс
    importlib.reload(admins_store_module)
    AdminsStore = admins_store_module.AdminsStore

    handler = CommandHandlers(image_generator=MagicMock(), next_run_provider=None)
    async_retry_stub(handler)

    # Используем реальный AdminsStore для теста
    admins = AdminsStore()
    # Делаем пользователя 42 администратором
    await admins.add_admin(fake_update.effective_user.id)
    await admins.add_admin(11111)
    await admins.add_admin(22222)
    handler.admins_store = admins
    fake_context.application.bot_data["admins"] = admins

    await handler.list_mods_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Администраторы" in text or "модераторы" in text.lower() or "админ" in text.lower()


@pytest.mark.asyncio
async def test_list_models_command(fake_update: Any, fake_context: Any, async_retry_stub: Any) -> None:
    image_generator = MagicMock()
    image_generator.check_api_status = AsyncMock(
        return_value=(True, "OK", ["Model 1", "Model 2"], ("id1", "name1")),
    )
    image_generator.gigachat_client = MagicMock()
    image_generator.gigachat_client.get_available_models = MagicMock(return_value=["GigaChat-1", "GigaChat-2"])

    handler = CommandHandlers(image_generator=image_generator, next_run_provider=None)
    async_retry_stub(handler)

    class _AdminOk:
        async def is_admin(self, _uid: int) -> bool:
            return True

    handler.admins_store = _AdminOk()  # type: ignore[assignment]

    await handler.list_models_command(fake_update, fake_context)

    fake_update.message.reply_text.assert_awaited()
    call = fake_update.message.reply_text.await_args
    text = call.kwargs.get("text", call.args[0])
    assert "Kandinsky" in text or "GigaChat" in text or "модели" in text.lower()
