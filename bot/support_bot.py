"""
Резервный (поддерживающий) бот, который включается при остановке основного.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.error import NetworkError as _TNetworkError, TimedOut as _TTimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

# Константы для магических чисел (импортируем из wednesday_bot для консистентности)
from bot.wednesday_bot import (
    CONNECT_TIMEOUT_SECONDS,
    CONNECTION_POOL_SIZE,
    POOL_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
)
from services.rate_limiter import RateLimiter
from utils.admins_store import AdminsStore
from utils.config import config
from utils.logger import get_logger, log_all_methods

# Константы для SupportBot
MAX_POLLING_ATTEMPTS = 4  # максимальное количество попыток запуска polling
LAST_POLLING_ATTEMPT_INDEX = 3  # индекс последней попытки (0-based: 3 = 4-я попытка)
MAX_LOG_DAYS_SUPPORT = 10  # максимальное количество дней для команды /log в SupportBot


@log_all_methods()
class SupportBot:
    """
    Бот-поддержка: показывает сообщение о техработах, отдает логи и умеет запускать основной бот.
    Никогда не должен работать одновременно с основным ботом.
    """

    def __init__(self, request_start_main: Callable[[dict[str, Any]], Awaitable[None]] | None = None) -> None:
        self.logger = get_logger(__name__)
        request: HTTPXRequest = HTTPXRequest(
            connection_pool_size=CONNECTION_POOL_SIZE,
            pool_timeout=POOL_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
        )
        # config.telegram_token проверяется в _validate_required_vars, поэтому не может быть None
        telegram_token: str = config.telegram_token or ""
        assert telegram_token, "TELEGRAM_BOT_TOKEN должен быть установлен"
        self.application: Application = Application.builder().token(telegram_token).request(request).build()
        self.admins: AdminsStore = AdminsStore()
        self.request_start_main: Callable[[dict[str, Any]], Awaitable[None]] | None = request_start_main
        self.is_running: bool = False
        # Данные для редактирования сообщения об остановке основного
        self.pending_shutdown_edit: dict[str, Any] | None = None
        # Данные для цепочки запуска основного: сообщение "Запускаю..."
        self.pending_startup_edit: dict[str, Any] | None = None
        # Лимитер на основе Redis для административных команд SupportBot
        # (например, /log), чтобы избежать случайного "забивания" лог‑канала.
        # В случае недоступности Redis лимитер автоматически работает в in‑memory
        # режиме и не блокирует админа.
        self.rate_limiter: RateLimiter = RateLimiter(prefix="rate:support:", window=60, limit=20)

    def setup_handlers(self) -> None:
        self.application.add_handler(CommandHandler("start", self.start_main_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("log", self.log_command))
        # Любые неизвестные команды – сообщение о техработах
        self.application.add_handler(MessageHandler(filters.COMMAND, self.maintenance_message))

    async def start(self) -> None:
        self.logger.info("Запуск бота-поддержки (SupportBot)")
        self.setup_handlers()

        # Кладем self в bot_data на всякий случай
        self.application.bot_data["support_bot"] = self
        self.application.bot_data["rate_limiter"] = self.rate_limiter

        # Этап 1: initialize с ретраями
        init_attempts = 4
        backoff = 2.0
        for attempt in range(1, init_attempts + 1):
            try:
                await self.application.initialize()
                self.logger.info("SupportBot: initialize() успешно")
                # Дополнительно «разогреем» бота, чтобы гарантированно установить контекст
                try:
                    _ = await self.application.bot.get_me()
                except Exception as warmup_err:
                    # Не фейлим старт из-за warmup; просто залогируем
                    self.logger.warning(f"SupportBot warmup get_me() не удался: {warmup_err}")
                break
            except (_TTimedOut, _TNetworkError) as e:
                self.logger.warning(
                    f"SupportBot: сеть недоступна при initialize (попытка {attempt}/{init_attempts}): {e}",
                )
                if attempt == init_attempts:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 1.5

        # Этап 2: start с ретраями (без повторного initialize)
        start_attempts = 3
        backoff = 2.0
        for attempt in range(1, start_attempts + 1):
            try:
                await self.application.start()
                self.logger.info("SupportBot: start() успешно")
                break
            except (_TTimedOut, _TNetworkError) as e:
                self.logger.warning(f"SupportBot: сеть недоступна при start (попытка {attempt}/{start_attempts}): {e}")
                if attempt == start_attempts:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 1.5
            except RuntimeError as re:
                # Обработка случая: "ExtBot is not properly initialized"
                msg = str(re)
                if "ExtBot is not properly initialized" in msg:
                    self.logger.warning("SupportBot: повторная инициализация после ошибки ExtBot not initialized")
                    try:
                        await self.application.initialize()
                        # Повторный warmup
                        try:
                            _ = await self.application.bot.get_me()
                        except Exception:
                            pass
                    except Exception as reinit_err:
                        self.logger.warning(
                            f"SupportBot: не удалось повторно инициализировать приложение: {reinit_err}",
                        )
                    # Ретраим без немедленного падения
                    if attempt == start_attempts:
                        raise
                    await asyncio.sleep(backoff)
                    backoff *= 1.5
                else:
                    raise
        # Безопасный запуск polling с ретраями на случай конфликта getUpdates
        import asyncio as _asyncio

        from telegram.error import Conflict as _TGConflict

        delay = 2.0
        for attempt in range(4):
            try:
                updater = self.application.updater
                if updater:
                    await updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
                self.logger.info("SupportBot polling запущен")
                break
            except _TGConflict as e:
                self.logger.warning(f"Conflict при запуске polling SupportBot (попытка {attempt + 1}/4): {e}")
                if attempt == LAST_POLLING_ATTEMPT_INDEX:
                    raise
                await _asyncio.sleep(delay)
                delay *= 1.5

        # Если есть сообщение о статусе остановки — редактируем его на финальное (кроме админ-чата)
        try:
            if isinstance(self.pending_shutdown_edit, dict):
                chat_id = self.pending_shutdown_edit.get("chat_id")
                message_id = self.pending_shutdown_edit.get("message_id")
                # Пропускаем редактирование, если это админ-чат
                skip_admin_edit = False
                try:
                    from utils.config import config as _cfg

                    admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                    if admin_chat_id_env:
                        try:
                            skip_admin_edit = int(str(admin_chat_id_env)) == int(str(chat_id))
                        except Exception:
                            skip_admin_edit = False
                except Exception:
                    skip_admin_edit = False

                if chat_id and message_id and not skip_admin_edit:
                    # Компактный финальный текст для не-админ чатов
                    final_text = "🛑  Wednesday Frog Bot остановлен\n✅ Резервный бот запущен"
                    try:
                        await self.application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=final_text,
                        )
                        self.logger.info("Сообщение об остановке обновлено в чате-источнике")
                    except Exception as edit_err:
                        # Игнорируем ошибку "Message is not modified" — это нормально, если текст уже установлен
                        error_str = str(edit_err).lower()
                        if "message is not modified" in error_str or "not modified" in error_str:
                            self.logger.debug("Сообщение уже имеет нужный текст, пропускаем редактирование")
                        else:
                            self.logger.warning(f"Не удалось обновить сообщение об остановке: {edit_err}")
                elif chat_id and skip_admin_edit:
                    self.logger.info("SupportBot: пропускаю редактирование статусного сообщения в админском чате")
        except Exception as e:
            self.logger.warning(f"Не удалось обновить сообщение об остановке: {e}")

        # Сообщим админам о запуске SupportBot
        try:
            admins = await AdminsStore().list_all_admins()
            for admin_id in admins:
                try:
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            "🟢 SupportBot запущен и принимает команды.\n"
                            "• /help — справка\n• /log — последний лог\n• /start — запустить основной бот"
                        ),
                    )
                except Exception:
                    pass
        except Exception:
            pass

        self.is_running = True
        try:
            while self.is_running:
                await asyncio.sleep(0.1)
        finally:
            self.logger.info("SupportBot основной цикл завершен")

    async def stop(self) -> None:
        if not self.is_running:
            return
        self.logger.info("Остановка бота-поддержки")
        self.is_running = False
        # Если был запуск основного через статусное сообщение — добавим строку про остановку Support Bot
        try:
            if isinstance(self.pending_startup_edit, dict):
                chat_id = self.pending_startup_edit.get("chat_id")
                message_id = self.pending_startup_edit.get("message_id")
                # Пропускаем для админского чата
                is_admin_chat = False
                try:
                    from utils.config import config as _cfg

                    admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                    if admin_chat_id_env and chat_id is not None:
                        try:
                            is_admin_chat = int(str(admin_chat_id_env)) == int(str(chat_id))
                        except Exception:
                            is_admin_chat = False
                except Exception:
                    is_admin_chat = False
                if chat_id and message_id and not is_admin_chat:
                    interim_text = "🚀 Запускаю основной бот...\n🛑 Support Bot остановлен"
                    try:
                        await self.application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=interim_text,
                        )
                    except Exception:
                        pass
                # Очистим ссылку, чтобы не переиспользовать
                self.pending_startup_edit = None
        except Exception:
            pass
        # Сначала останавливаем polling, чтобы освободить соединения
        try:
            if hasattr(self.application, "updater") and self.application.updater:
                await self.application.updater.stop()
        except Exception as e:
            self.logger.warning(f"Ошибка при остановке updater'а SupportBot: {e}")
        # Короткая пауза, чтобы соединения вернулись в пул
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass
        # Уведомим админов об остановке
        try:
            admins = await AdminsStore().list_all_admins()
            if admins:
                for admin_id in admins:
                    try:
                        await self.application.bot.send_message(
                            chat_id=admin_id,
                            text=(
                                "🛑 SupportBot остановлен.\n\n"
                                "Если это не плановая остановка, проверьте логи и состояние основного бота."
                            ),
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            await self.application.stop()
        except Exception as e:
            self.logger.warning(f"Ошибка при остановке приложения SupportBot: {e}")

    async def maintenance_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Ответ на любые неизвестные команды: сообщение о техработах."""
        if not update.message:
            return

        try:
            user_id = update.effective_user.id if update and update.effective_user else None
            chat_id = update.effective_chat.id if update and update.effective_chat else None
            text = update.message.text if update and update.message else None
            self.logger.info(f"/unknown for SupportBot: user_id={user_id}, chat_id={chat_id}, text={text}")
        except Exception:
            pass
        try:
            await update.message.reply_text(
                "🛠 Технические работы. Основной бот временно недоступен. \nПожалуйста, попробуйте позже.",
            )
        except Exception as e:
            self.logger.warning(f"Не удалось отправить сообщение о техработах: {e}")

    async def _is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором."""
        return await self.admins.is_admin(user_id)

    async def log_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Отправляет логи. Использование: /log [count] (1..10). Без аргумента — последний файл."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        self.logger.info(f"SupportBot /log от user_id={user_id}, chat_id={chat_id}")
        if not await self._is_admin(user_id):
            await update.message.reply_text("❌ Доступно только администратору")
            return

        try:
            logs_dir = Path("logs")
            if not logs_dir.exists():
                await update.message.reply_text("📭 Папка logs пуста или отсутствует")
                return

            # Аргумент count
            count = 1
            capped_note = None
            if context.args and len(context.args) > 0:
                raw = context.args[0]
                if not raw.isdigit():
                    await update.message.reply_text(
                        "❌ Неверный аргумент. Используйте: /log [count], где count — число 1..10",
                    )
                    return
                count = int(raw)
                if count > MAX_LOG_DAYS_SUPPORT:
                    count = MAX_LOG_DAYS_SUPPORT
                    capped_note = f"(ограничено максимумом {MAX_LOG_DAYS_SUPPORT} дней)"

            # Выбираем файлы по датам
            from datetime import datetime, timedelta

            wanted_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(count)]
            selected: list[Path] = []
            for ds in wanted_dates:
                log_path = logs_dir / f"wednesday_bot_{ds}.log"
                zip_path = logs_dir / f"wednesday_bot_{ds}.log.zip"
                if log_path.exists():
                    selected.append(log_path)
                elif zip_path.exists():
                    selected.append(zip_path)

            if not selected:
                log_files = [p for p in logs_dir.iterdir() if p.is_file()]
                selected = sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)[:1]

            if not selected:
                await update.message.reply_text("📭 Нет логов для отправки")
                return

            await update.message.reply_text(f"📦 Отправляю файл(ы) логов за {len(selected)} дн. {capped_note or ''}")
            for lf in sorted(selected, key=lambda p: p.name):
                self.logger.info(f"SupportBot отправляет лог-файл: {lf.name} ({lf.stat().st_size} bytes)")
                try:
                    with lf.open("rb") as fh:
                        await context.bot.send_document(chat_id=update.effective_chat.id, document=fh, filename=lf.name)
                    self.logger.info("SupportBot: лог отправлен успешно")
                except Exception as e:
                    self.logger.warning(f"Ошибка при отправке лога {lf}: {e}")
            await update.message.reply_text("✅ Готово")
        except Exception as e:
            self.logger.error(f"Ошибка в команде /log: {e}")
            try:
                await update.message.reply_text(f"❌ Ошибка при отправке логов: {str(e)[:200]}")
            except Exception:
                pass

    async def start_main_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда /start от админа — запускает основной бот и выключает SupportBot."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        self.logger.info(f"SupportBot /start от user_id={user_id}, chat_id={chat_id}")
        if not await self._is_admin(user_id):
            await update.message.reply_text("❌ Доступно только администратору")
            return

        # В админ-чате не отправляем изменяемое статусное сообщение
        is_admin_chat = False
        try:
            from utils.config import config as _cfg

            admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
            if admin_chat_id_env and chat_id is not None:
                try:
                    is_admin_chat = int(str(admin_chat_id_env)) == int(str(chat_id))
                except Exception:
                    is_admin_chat = False
        except Exception:
            is_admin_chat = False

        # Отправляем статусное сообщение только если это не админ-чат
        status_msg = None
        if not is_admin_chat:
            try:
                status_msg = await update.message.reply_text("🚀 Запускаю основной бот...")
                if status_msg:
                    self.logger.info(f"SupportBot /start сообщение статусное: message_id={status_msg.message_id}")
                    # Сохраним ссылку, чтобы при остановке SupportBot дополнить текст строкой о его остановке
                    try:
                        self.pending_startup_edit = {
                            "chat_id": update.effective_chat.id,
                            "message_id": status_msg.message_id,
                        }
                    except Exception:
                        self.pending_startup_edit = None
            except Exception:
                pass

        # Сигнализируем раннеру/супервизору о необходимости запуска основного бота
        if self.request_start_main is not None:
            try:
                # В админ-чате не передаём payload для последующего редактирования
                payload = {}
                if (not is_admin_chat) and (status_msg is not None):
                    payload = {"chat_id": update.effective_chat.id, "message_id": status_msg.message_id}
                await self.request_start_main(payload)
                self.logger.info("SupportBot запрос запуска основного отправлен супервизору")
                # Не редактируем статусное сообщение сразу; финальный текст поставит основной бот после запуска
            except Exception as e:
                self.logger.error(f"Ошибка при запросе запуска основного бота: {e}")
        else:
            self.logger.warning("request_start_main не задан, невозможно запустить основной бот")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда /help (только для админа): справка по резервному боту."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        self.logger.info(f"SupportBot /help от user_id={user_id}, chat_id={chat_id}")
        if not await self._is_admin(user_id):
            await update.message.reply_text("❌ Доступно только администратору")
            return
        help_text = (
            "🛠 Справка по резервному боту (SupportBot)\n\n"
            "Доступные команды:\n"
            "• /help — эта справка\n"
            "• /log [count] — отправить логи за N дней (1..10), без аргумента — последний файл (только админ)\n"
            "• /start — запустить основной бот и выключить резервный (только админ)\n\n"
            "Поведение по умолчанию: любая неизвестная команда — сообщение о техработах."
        )
        try:
            await update.message.reply_text(help_text)
        except Exception as e:
            self.logger.warning(f"Ошибка при отправке help: {e}")
