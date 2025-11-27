"""
Основной класс Wednesday Frog Bot.
Объединяет все компоненты бота и управляет его жизненным циклом.
"""

import asyncio
import os
from typing import Any

from telegram import Update
from telegram.ext import Application, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from bot.handlers import CommandHandlers
from services.image_generator import ImageGenerator
from services.prompt_cache import PromptCache
from services.rate_limiter import RateLimiter
from services.scheduler import TaskScheduler
from services.user_state_store import UserStateStore
from utils.chats_store import ChatsStore
from utils.config import config
from utils.dispatch_registry import DispatchRegistry
from utils.logger import get_logger, log_all_methods
from utils.metrics import Metrics
from utils.usage_tracker import UsageTracker

# Константы для магических чисел
CONNECTION_POOL_SIZE = 20
POOL_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 20.0
CONNECT_TIMEOUT_SECONDS = 15.0
MONTHLY_QUOTA_DEFAULT = 100
FROG_THRESHOLD_DEFAULT = 70
RETRY_AFTER_DEFAULT_SECONDS = 60  # дефолтное значение retry_after
TIMEOUT_SHORT_SECONDS = 5.0
TIMEOUT_MEDIUM_SECONDS = 30.0
TIMEOUT_BOT_INFO_SECONDS = 30.0
MAX_POLLING_ATTEMPTS = 3  # максимальное количество попыток запуска polling
LAST_POLLING_ATTEMPT_INDEX = 2  # индекс последней попытки (0-based: 2 = 3-я попытка)


@log_all_methods()
class WednesdayBot:
    """
    Основной класс Telegram бота для отправки изображений жабы каждую среду.

    Обеспечивает:
    - Инициализацию всех компонентов бота
    - Регистрацию обработчиков команд
    - Запуск и остановку бота
    - Планирование автоматических задач
    - Обработку ошибок и логирование
    """

    def __init__(self) -> None:
        """Инициализация основного класса бота."""
        self.logger = get_logger(__name__)
        self.logger.info("Начало инициализации WednesdayBot")

        # Инициализируем компоненты
        self.logger.info("Создание HTTPXRequest с настройками подключения")
        request: HTTPXRequest = HTTPXRequest(
            connection_pool_size=CONNECTION_POOL_SIZE,
            pool_timeout=POOL_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
        )
        # config.telegram_token проверяется в _validate_required_vars, поэтому не может быть None
        telegram_token: str = config.telegram_token or ""
        assert telegram_token, "TELEGRAM_BOT_TOKEN должен быть установлен"
        self.logger.info("Создание Application с токеном")
        self.application: Application = Application.builder().token(telegram_token).request(request).build()

        # Создаем сервисы
        self.logger.info(
            "Инициализация сервисов: ImageGenerator, TaskScheduler, "
            "UsageTracker, ChatsStore, DispatchRegistry, Metrics",
        )
        self.image_generator: ImageGenerator = ImageGenerator()
        self.scheduler: TaskScheduler = TaskScheduler()
        self.usage: UsageTracker = UsageTracker(
            storage_path=os.getenv("USAGE_STORAGE", "usage_stats.json"),
            monthly_quota=MONTHLY_QUOTA_DEFAULT,
            frog_threshold=FROG_THRESHOLD_DEFAULT,
        )
        self.chats: ChatsStore = ChatsStore()
        self.dispatch_registry: DispatchRegistry = DispatchRegistry()
        self.metrics: Metrics = Metrics()
        # Redis‑сервисы (поднимаются один раз и переиспользуются через bot_data):
        # - PromptCache: быстрый кэш промптов/параметров генерации;
        # - UserStateStore: временное состояние пользователей (диалоги, флаги и т.п.);
        # - RateLimiter: базовый лимитер для административных/ручных операций.
        # Эти сервисы построены поверх Redis, но автоматически деградируют в in‑memory режим,
        # если Redis недоступен, поэтому их безопасно инициализировать без жёсткой зависимости.
        self.prompt_cache: PromptCache = PromptCache()
        self.user_state_store: UserStateStore = UserStateStore()
        self.rate_limiter: RateLimiter = RateLimiter(prefix="rate:wednesday:", window=60, limit=100)
        # Данные для пост-старта (например, редактирование сообщения из SupportBot)
        self.pending_startup_edit: dict[str, Any] | None = None
        # Данные для пост-остановки (например, редактирование сообщения об остановке)
        self.pending_shutdown_edit: dict[str, Any] | None = None
        # Флаг, чтобы избежать дублирующих сообщений об остановке
        self._stop_message_sent: bool = False

        # Создаем обработчики команд
        self.logger.info("Создание CommandHandlers")
        self.handlers: CommandHandlers = CommandHandlers(self.image_generator, self.scheduler.get_next_run)

        # ID чата для отправки сообщений
        self.chat_id: str | None = config.chat_id
        self.logger.info(f"Chat ID установлен: {self.chat_id}")

        # Флаг состояния бота
        self.is_running: bool = False

        # Задача планировщика (инициализируется при старте)
        self.scheduler_task: asyncio.Task[None] | None = None

        self.logger.info("WednesdayBot успешно инициализирован")

    def setup_handlers(self) -> None:
        """
        Настраивает обработчики команд для бота.
        Регистрирует все доступные команды и обработчики сообщений.
        """
        self.logger.info("Начало настройки обработчиков команд")

        # Регистрируем обработчики команд
        self.application.add_handler(
            CommandHandler("start", self.handlers.start_command),
        )
        self.application.add_handler(
            CommandHandler("help", self.handlers.help_command),
        )
        self.application.add_handler(
            CommandHandler("frog", self.handlers.frog_command),
        )
        self.application.add_handler(
            CommandHandler("status", self.handlers.status_command),
        )

        # Admin команды (регистрируем перед unknown_command!)
        self.application.add_handler(
            CommandHandler("force_send", self.handlers.admin_force_send_command),
        )
        self.application.add_handler(
            CommandHandler("log", self.handlers.admin_log_command),
        )
        self.application.add_handler(
            CommandHandler("add_chat", self.handlers.admin_add_chat_command),
        )
        self.application.add_handler(
            CommandHandler("remove_chat", self.handlers.admin_remove_chat_command),
        )
        self.application.add_handler(
            CommandHandler("stop", self.handlers.stop_command),
        )

        self.application.add_handler(
            CommandHandler("list_chats", self.handlers.list_chats_command),
        )

        self.application.add_handler(
            CommandHandler("set_kandinsky_model", self.handlers.set_kandinsky_model_command),
        )

        self.application.add_handler(
            CommandHandler("set_gigachat_model", self.handlers.set_gigachat_model_command),
        )

        self.application.add_handler(
            CommandHandler("mod", self.handlers.mod_command),
        )

        self.application.add_handler(
            CommandHandler("unmod", self.handlers.unmod_command),
        )

        self.application.add_handler(
            CommandHandler("list_mods", self.handlers.list_mods_command),
        )

        self.application.add_handler(
            CommandHandler("list_models", self.handlers.list_models_command),
        )

        # Админ: управление лимитами
        self.application.add_handler(
            CommandHandler("set_frog_limit", self.handlers.set_frog_limit_command),
        )
        self.application.add_handler(
            CommandHandler("set_frog_used", self.handlers.set_frog_used_command),
        )

        # Обработчик для неизвестных команд
        self.application.add_handler(
            MessageHandler(filters.COMMAND, self.handlers.unknown_command),
        )

        # Обработчик событий изменения статуса бота в чатах
        self.application.add_handler(
            ChatMemberHandler(self.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER),
        )

        self.logger.info("Обработчики команд успешно настроены и зарегистрированы")

    async def send_wednesday_frog(self, slot_time: str | None = None) -> None:
        """
        Основная функция для отправки изображения жабы каждую среду.
        Генерирует изображение и отправляет его в указанный чат.
        """
        from datetime import datetime

        now = datetime.now()
        slot_date = now.strftime("%Y-%m-%d")
        # Если слот не передан планировщиком — сопоставим ближайший (<= now)
        if slot_time is None:
            try:
                configured_times: list[str] = list(self.scheduler.send_times or [])
            except Exception:
                configured_times = []
            resolved_slot: str | None = None
            if configured_times:
                try:
                    candidates: list[tuple[datetime, str]] = []
                    for t in configured_times:
                        from utils.config import TIME_FORMAT_LENGTH

                        if len(t) == TIME_FORMAT_LENGTH and t[2] == ":" and t[:2].isdigit() and t[3:].isdigit():
                            h, m = int(t[:2]), int(t[3:])
                            candidate_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                            if candidate_dt <= now:
                                candidates.append((candidate_dt, t))
                    if candidates:
                        candidates.sort(key=lambda x: x[0])
                        resolved_slot = candidates[-1][1]
                except Exception:
                    resolved_slot = None
            slot_time = resolved_slot or now.strftime("%H:%M")

        self.logger.info("Выполняю запланированную отправку жабы")

        try:
            # Сначала соберём список целевых чатов
            targets: set[int] = set(self.chats.list_chat_ids() or [])
            if self.chat_id:
                try:
                    chat_id_int: int = int(str(self.chat_id))
                    targets.add(chat_id_int)
                except (ValueError, TypeError):
                    pass

            # Если нет ни одного чата — просто выходим
            if not targets:
                self.logger.warning("Нет целевых чатов для отправки сообщения")
                await self._send_error_message("Нет настроенных чатов для отправки")
                return

            # Проверяем, отправляли ли уже в этот слот во ВСЕ целевые чаты
            already_dispatched_for_all = True
            for target_chat in targets:
                if not self.dispatch_registry.is_dispatched(slot_date, slot_time, target_chat):
                    already_dispatched_for_all = False
                    break

            if already_dispatched_for_all:
                self.logger.info(
                    f"Уже отправлено ранее для всех чатов в слот {slot_date}_{slot_time}. Пропускаю генерацию.",
                )
                return

            # Генерируем изображение жабы только если есть хотя бы один чат без отправки
            result = await self.image_generator.generate_frog_image(metrics=self.metrics)

            if result:
                image_data, caption = result

                # Сохраняем изображение локально заранее (на случай сбоев сети)
                try:
                    saved_path = self.image_generator.save_image_locally(
                        image_data,
                        folder="data/frogs",
                        prefix="wednesday",
                    )
                    if saved_path:
                        self.logger.info(f"Изображение сохранено локально: {saved_path}")
                except Exception as e:
                    self.logger.warning(f"Не удалось сохранить изображение локально: {e}")

                for target_chat in targets:
                    # Проверяем, не было ли уже отправлено в этот чат в этот тайм-слот
                    if self.dispatch_registry.is_dispatched(slot_date, slot_time, target_chat):
                        self.logger.info(
                            f"Пропускаем отправку в {target_chat} - уже отправлено в слот {slot_date}_{slot_time}",
                        )
                        continue

                    send_attempts = 3
                    initial_backoff = 2
                    for attempt in range(1, send_attempts + 1):
                        try:
                            await self.application.bot.send_photo(
                                chat_id=target_chat,
                                photo=image_data,
                                caption=caption,
                            )
                            # Отмечаем в реестре успешную отправку
                            self.dispatch_registry.mark_dispatched(slot_date, slot_time, target_chat)
                            # инкрементируем счетчик после успешной отправки
                            self.usage.increment(1)
                            try:
                                self.metrics.increment_dispatch_success()
                            except Exception:
                                pass
                            self.logger.info(f"Жаба отправлена в чат {target_chat}")
                            break
                        except Exception as send_error:
                            error_str = str(send_error).lower()
                            is_429 = "429" in error_str or "rate limit" in error_str or "too many requests" in error_str

                            if is_429 and attempt < send_attempts:
                                # Обработка 429: читаем Retry-After из заголовков если доступно
                                retry_after = RETRY_AFTER_DEFAULT_SECONDS
                                if hasattr(send_error, "retry_after") and send_error.retry_after:
                                    retry_after = int(send_error.retry_after)
                                elif hasattr(send_error, "response") and send_error.response:
                                    retry_after_header = send_error.response.headers.get("retry-after")
                                    if retry_after_header:
                                        retry_after = int(retry_after_header)

                                self.logger.warning(
                                    f"429 Rate Limit в {target_chat} "
                                    f"(попытка {attempt}/{send_attempts}), ждём {retry_after}с",
                                )
                                await asyncio.sleep(retry_after)
                                continue

                            self.logger.warning(
                                f"Сбой отправки в {target_chat} (попытка {attempt}/{send_attempts}): {send_error}",
                            )
                            if attempt == send_attempts:
                                self.logger.error(
                                    f"Не удалось отправить изображение в чат {target_chat} после всех попыток",
                                )
                                try:
                                    await self._send_error_message(
                                        f"Не удалось отправить изображение в чат {target_chat}",
                                    )
                                except Exception:
                                    pass
                                try:
                                    self.metrics.increment_dispatch_failed()
                                except Exception:
                                    pass
                            else:
                                # Экспоненциальный backoff с джиттером
                                import random

                                backoff = initial_backoff * (2 ** (attempt - 1))
                                jitter = random.uniform(0, backoff * 0.3)
                                wait_time = backoff + jitter
                                self.logger.info(f"Ждём {wait_time:.1f}с перед повторной попыткой")
                                await asyncio.sleep(wait_time)

            else:
                # Если генерация не удалась, отправляем сообщения об ошибке и случайное изображение
                error_details = (
                    "Не удалось сгенерировать изображение жабы для среды. "
                    "API вернул None (возможные причины: лимит API, circuit breaker, "
                    "ошибка генерации)"
                )
                self.logger.error(error_details)

                # Отправляем детальное сообщение администратору
                await self._send_admin_error(error_details)

                # Отправляем дружелюбные сообщения и случайные изображения во все целевые чаты
                targets = set(self.chats.list_chat_ids() or [])
                if self.chat_id:
                    try:
                        chat_id_val: int = int(str(self.chat_id))
                        targets.add(chat_id_val)
                    except (ValueError, TypeError):
                        pass

                for target_chat in targets:
                    try:
                        # Проверяем, не было ли уже отправлено в этот чат в этот тайм-слот
                        if self.dispatch_registry.is_dispatched(slot_date, slot_time, target_chat):
                            self.logger.info(
                                f"Пропускаем fallback отправку в {target_chat} - "
                                f"уже отправлено в слот {slot_date}_{slot_time}",
                            )
                            continue

                        # Отправляем дружелюбное сообщение
                        await self._send_user_friendly_error(target_chat)

                        # Отправляем случайное изображение
                        if await self._send_fallback_image(target_chat):
                            # Отмечаем в реестре успешную отправку
                            self.dispatch_registry.mark_dispatched(slot_date, slot_time, target_chat)
                            try:
                                self.metrics.increment_dispatch_success()
                            except Exception:
                                pass

                    except Exception as send_error:
                        self.logger.error(f"Ошибка при отправке fallback в чат {target_chat}: {send_error}")

        except Exception as e:
            error_details = f"Произошла ошибка при отправке жабы: {e!s}"
            self.logger.error(error_details, exc_info=True)

            # Отправляем детальное сообщение администратору
            import traceback

            full_error = traceback.format_exc()
            # Обрезаем трейс до последних 2000 символов (важная информация обычно в конце)
            max_trace_length = 2000
            if len(full_error) > max_trace_length:
                full_error = "..." + full_error[-max_trace_length:]
            await self._send_admin_error(
                f"{error_details}\n\nТрейс (последние {max_trace_length} символов):\n{full_error}",
            )

            # Отправляем дружелюбные сообщения и случайные изображения во все целевые чаты
            targets = set(self.chats.list_chat_ids() or [])
            if self.chat_id:
                try:
                    chat_id_error_val: int = int(str(self.chat_id))
                    targets.add(chat_id_error_val)
                except (ValueError, TypeError):
                    pass

            for target_chat in targets:
                try:
                    # Проверяем, не было ли уже отправлено в этот чат в этот тайм-слот
                    if self.dispatch_registry.is_dispatched(slot_date, slot_time, target_chat):
                        self.logger.info(
                            f"Пропускаем fallback отправку в {target_chat} - "
                            f"уже отправлено в слот {slot_date}_{slot_time}",
                        )
                        continue

                    # Отправляем дружелюбное сообщение
                    await self._send_user_friendly_error(target_chat)

                    # Отправляем случайное изображение
                    if await self._send_fallback_image(target_chat):
                        try:
                            self.metrics.increment_dispatch_success()
                        except Exception:
                            pass

                except Exception as send_error:
                    self.logger.error(f"Ошибка при отправке fallback в чат {target_chat}: {send_error}")

    async def _send_error_message(self, error_text: str) -> None:
        """
        Отправляет сообщение об ошибке в чат.

        Args:
            error_text: Текст сообщения об ошибке
        """
        try:
            error_message = f"⚠️ {error_text}\nПопробуем в следующий раз! 🐸"
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=error_message,
            )
        except Exception as send_error:
            self.logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")

    async def _send_user_friendly_error(self, chat_id: int, error_context: str = "генерации изображения") -> None:
        """
        Отправляет дружелюбное сообщение об ошибке пользователю.

        Args:
            chat_id: ID чата для отправки
            error_context: Контекст ошибки (для пользовательского сообщения)
        """
        try:
            friendly_message = (
                "🐸 К сожалению, не удалось сгенерировать новую картинку.\n"
                "Но не расстраивайтесь! Вот случайная картинка из архива! 🎲"
            )
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=friendly_message,
            )
        except Exception as send_error:
            self.logger.error(f"Не удалось отправить дружелюбное сообщение об ошибке: {send_error}")

    async def _send_admin_error(self, error_details: str) -> None:
        """
        Отправляет детальное сообщение об ошибке всем администраторам.

        Args:
            error_details: Детальная информация об ошибке
        """
        from utils.admins_store import AdminsStore

        admins_store = AdminsStore()
        all_admins = admins_store.list_all_admins()

        if not all_admins:
            self.logger.warning("Нет администраторов для отправки ошибки")
            return

        admin_message = f"⚠️ Ошибка генерации изображения:\n\n{error_details}"

        # Разбиваем длинные сообщения на части (лимит Telegram: 4096 символов)
        max_message_length = 4000  # Оставляем запас

        for admin_id in all_admins:
            try:
                if len(admin_message) > max_message_length:
                    # Отправляем короткую версию
                    short_message = error_details[:3000] + "\n\n⚠️ Сообщение обрезано, полный текст в логах."
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=short_message,
                    )
                else:
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                    )
                self.logger.info(f"Отправлено сообщение об ошибке админу {admin_id}")
            except Exception as send_error:
                error_str = str(send_error)
                # Если ошибка "Message is too long", отправляем сокращенную версию
                if "too long" in error_str.lower():
                    try:
                        short_message = error_details[:2000] + "\n\n⚠️ Полное сообщение слишком длинное, смотрите логи."
                        await self.application.bot.send_message(
                            chat_id=admin_id,
                            text=short_message,
                        )
                        self.logger.info(f"Отправлено сокращенное сообщение об ошибке админу {admin_id}")
                    except Exception as retry_error:
                        self.logger.error(
                            f"Не удалось отправить даже сокращенное сообщение админу {admin_id}: {retry_error}",
                        )
                else:
                    self.logger.error(f"Не удалось отправить сообщение об ошибке админу {admin_id}: {send_error}")

    async def _send_fallback_image(self, chat_id: int) -> bool:
        """
        Отправляет случайное изображение из сохраненных в случае ошибки генерации.

        Args:
            chat_id: ID чата для отправки

        Returns:
            True если изображение успешно отправлено, False в противном случае
        """
        try:
            fallback_image = self.image_generator.get_random_saved_image()
            if fallback_image:
                image_data, caption = fallback_image
                await self.application.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_data,
                    caption=caption,
                )
                self.logger.info(f"Случайное изображение отправлено в чат {chat_id} как fallback")
                return True
            else:
                self.logger.warning("Нет сохраненных изображений для отправки как fallback")
                return False
        except Exception as e:
            self.logger.error(f"Ошибка при отправке fallback изображения: {e}")
            return False

    def setup_scheduler(self) -> None:
        """
        Настраивает планировщик задач для автоматической отправки жабы.
        """
        self.logger.info("Настраиваю планировщик задач")

        # Планируем отправку жабы каждую среду
        self.scheduler.schedule_wednesday_task(self.send_wednesday_frog)

        # Необязательный тестовый интервал для проверки планировщика
        test_minutes = os.getenv("SCHEDULER_TEST_MINUTES")
        if test_minutes:
            try:
                minutes = int(test_minutes)
                if minutes > 0:
                    self.logger.info(f"Включен тестовый интервал планировщика: каждые {minutes} минут")
                    self.scheduler.schedule_interval_task(self.send_wednesday_frog, minutes)
            except ValueError:
                self.logger.warning("Переменная SCHEDULER_TEST_MINUTES должна быть целым числом")

        self.logger.info("Планировщик задач настроен")

    async def start(self) -> None:
        """
        Запускает бота и планировщик.
        """
        self.logger.info("Запускаю Wednesday Bot (боевой режим с планировщиком)")

        # Валидация конфигурации слотов
        self.logger.info(
            f"Валидация планировщика: день недели={self.scheduler.wednesday}, "
            f"времена={self.scheduler.send_times}, TZ={self.scheduler.tz.key}",
        )
        if len(self.scheduler.send_times) == 0:
            self.logger.error("⚠️  Не заданы времена отправки! Используются значения по умолчанию.")

        try:
            # Настраиваем обработчики
            self.setup_handlers()

            # Настраиваем и запускаем планировщик
            self.setup_scheduler()

            # Проверяем доступность чата перед отправкой сообщения
            await self._check_chat_access()

            # Инициализируем приложение асинхронно
            await self.application.initialize()

            # Положим трекеры в bot_data, чтобы команды им пользовались
            self.application.bot_data["usage"] = self.usage
            self.application.bot_data["chats"] = self.chats
            self.application.bot_data["metrics"] = self.metrics
            # Redis‑обёртки тоже доступны обработчикам через bot_data:
            self.application.bot_data["prompt_cache"] = self.prompt_cache
            self.application.bot_data["user_state_store"] = self.user_state_store
            self.application.bot_data["rate_limiter"] = self.rate_limiter
            # Сохраняем ссылку на экземпляр бота для управленческих команд (/stop)
            self.application.bot_data["bot"] = self

            # Ретраи запуска сети (start + polling)
            delay = 3
            for attempt in range(3):
                try:
                    await self.application.start()
                    updater = self.application.updater
                    if updater:
                        await updater.start_polling(
                            allowed_updates=Update.ALL_TYPES,
                            drop_pending_updates=True,
                        )
                    break
                except Exception as e:
                    self.logger.warning(
                        f"Не удалось запустить polling (попытка {attempt + 1}/{MAX_POLLING_ATTEMPTS}): {e}",
                    )
                    if attempt == LAST_POLLING_ATTEMPT_INDEX:
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2

            # Отправляем сообщение о запуске после старта
            try:
                startup_message = (
                    "🚀 Wednesday Frog Bot запущен!\n\n"
                    "✅ Бот активен и готов к работе\n"
                    "📅 Планировщик: включен (среда в указанное время)\n"
                    "🎨 Генератор изображений: Kandinsky API\n"
                    "📝 Логирование: включено\n\n"
                    "🐸 Используйте команду /frog для генерации жабы!"
                )
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=startup_message,
                )
                # Дублируем в админ-чат, если задан, избегая повтора, если CHAT_ID совпадает
                try:
                    from utils.admins_store import AdminsStore as _AdminsStore
                    from utils.config import config as _cfg

                    admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                    if admin_chat_id_env:
                        try:
                            admin_chat_id_val = int(str(admin_chat_id_env))
                            chat_id_val = int(str(self.chat_id)) if self.chat_id is not None else None
                            if chat_id_val != admin_chat_id_val:
                                await self.application.bot.send_message(
                                    chat_id=admin_chat_id_val,
                                    text=startup_message,
                                )
                        except Exception:
                            pass
                    else:
                        # Если ADMIN_CHAT_ID не задан, разошлем всем админам из хранилища (без дубля с CHAT_ID)
                        try:
                            admins = _AdminsStore().list_all_admins()
                            for admin_id in admins:
                                try:
                                    chat_id_val = int(str(self.chat_id)) if self.chat_id is not None else None
                                    if chat_id_val is not None and admin_id == chat_id_val:
                                        continue
                                    await self.application.bot.send_message(
                                        chat_id=admin_id,
                                        text=startup_message,
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass
                self.logger.info("Сообщение о запуске отправлено")
            except Exception as send_error:
                self.logger.warning(f"Не удалось отправить сообщение о запуске: {send_error}")
                self.logger.info("Бот запущен, но не удалось отправить уведомление в чат")

            # Если был передан статус от SupportBot — дополняем его финальным состоянием основного
            try:
                if isinstance(self.pending_startup_edit, dict):
                    chat_id = self.pending_startup_edit.get("chat_id")
                    message_id = self.pending_startup_edit.get("message_id")
                    # Не редактируем сообщение в админском чате — оно предназначено для других чатов
                    skip_admin_edit = False
                    try:
                        from utils.config import config as _cfg

                        admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                        if admin_chat_id_env:
                            try:
                                admin_chat_str: str = str(admin_chat_id_env)
                                chat_id_str: str = str(chat_id) if chat_id is not None else ""
                                if admin_chat_str and chat_id_str:
                                    skip_admin_edit = int(admin_chat_str) == int(chat_id_str)
                                else:
                                    skip_admin_edit = False
                            except Exception:
                                skip_admin_edit = False
                    except Exception:
                        skip_admin_edit = False

                    if chat_id and message_id and not skip_admin_edit:
                        # Финальный текст после фактической остановки Support Bot и запуска основного
                        final_text = "🛑 Support Bot остановлен\n✅ Wednesday Frog Bot запущен"
                        await self.application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=final_text,
                        )
                        self.logger.info("Основной бот подтвердил запуск в сообщение SupportBot")
                    elif chat_id and skip_admin_edit:
                        self.logger.info("Пропускаю редактирование статусного сообщения в админском чате")
            except Exception as e:
                self.logger.warning(f"Не удалось обновить статусное сообщение SupportBot: {e}")

            # Запускаем планировщик в фоновой задаче
            self.scheduler_task = asyncio.create_task(self.scheduler.start())

            # Устанавливаем флаг запуска
            self.is_running = True

            # Бесконечный цикл для поддержания работы бота
            # Он будет работать до получения сигнала остановки
            while self.is_running:
                try:
                    # Используем await asyncio.sleep вместо обычного sleep
                    # Это позволяет корректно обрабатывать прерывания
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    self.logger.info("Получен сигнал отмены для основного цикла бота")
                    self.is_running = False
                    break

        except Exception as e:
            self.logger.error(f"Ошибка при запуске бота: {e}")
            raise

    async def on_my_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            my_cm = update.my_chat_member
            if not my_cm:
                return
            old = getattr(my_cm.old_chat_member, "status", None)
            new = getattr(my_cm.new_chat_member, "status", None)
            chat = my_cm.chat
            chat_id = chat.id
            title = getattr(chat, "title", None) or getattr(chat, "username", "") or ""

            # Бот добавлен/активирован в чате
            if new in {"member", "administrator"} and old in {"left", "kicked", "restricted", None}:
                self.chats.add_chat(chat_id, title)
                welcome = (
                    "🐸 Привет! Я Wednesday Frog Bot.\n\n"
                    "Я присылаю картинки с жабой по средам (09:00, 12:00, 18:00 по Мск), "
                    "а также по команде /frog (если не превышен лимит ручных генераций).\n\n"
                    "Доступные команды:\n"
                    "• /start — информация\n"
                    "• /help — справка\n"
                    "• /frog — сгенерировать жабу сейчас\n"
                )
                try:
                    await self.application.bot.send_message(chat_id=chat_id, text=welcome)
                except Exception as e:
                    self.logger.warning(f"Не удалось отправить приветствие в чат {chat_id}: {e}")

            # Бот удалён из чата
            if new in {"left", "kicked"} and old in {"member", "administrator", "restricted"}:
                self.chats.remove_chat(chat_id)

        except Exception as e:
            self.logger.error(f"Ошибка в on_my_chat_member: {e}")

    async def _check_chat_access(self) -> None:
        """
        Проверяет доступность чата для отправки сообщений.
        """
        try:
            # Пытаемся получить информацию о чате с увеличенным таймаутом
            chat_info = await asyncio.wait_for(
                self.application.bot.get_chat(self.chat_id),
                timeout=TIMEOUT_MEDIUM_SECONDS,
            )
            self.logger.info(f"Чат доступен: {chat_info.title or chat_info.first_name}")
        except TimeoutError:
            self.logger.warning(f"Таймаут при проверке доступа к чату {self.chat_id}")
            self.logger.warning("Возможно, проблемы с сетью или Telegram API")
            self.logger.warning("Бот будет работать, но проверка доступа к чату не выполнена")
        except Exception as e:
            self.logger.warning(f"Не удалось получить доступ к чату {self.chat_id}: {e}")
            self.logger.warning("Бот будет работать, но не сможет отправлять сообщения в указанный чат")
            self.logger.warning("Убедитесь, что:")
            self.logger.warning("1. CHAT_ID указан правильно")
            self.logger.warning("2. Бот добавлен в чат/канал")
            self.logger.warning("3. У бота есть права на отправку сообщений")

    async def stop(self) -> None:
        """
        Останавливает бота и планировщик.
        """
        # Защита от повторных вызовов
        if not self.is_running:
            self.logger.info("Бот уже остановлен или остановка уже начата")
            return

        self.logger.info("Останавливаю Wednesday Bot")

        try:
            # Устанавливаем флаг остановки
            self.is_running = False

            # Останавливаем планировщик
            try:
                if hasattr(self, "scheduler_task") and self.scheduler_task:
                    self.scheduler.stop()
                    self.scheduler_task.cancel()
                    try:
                        await self.scheduler_task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке планировщика: {e}")

            # Безопасная остановка updater'а
            try:
                if hasattr(self.application, "updater") and self.application.updater:
                    await self.application.updater.stop()
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке updater'а: {e}")
            # Небольшая пауза, чтобы освободить соединения пула перед отправкой финальных сообщений
            try:
                await asyncio.sleep(0.2)
            except Exception:
                pass

            # Отправляем сообщение об остановке в CHAT_ID после остановки polling (во избежание Pool timeout)
            try:
                if self.application and self.application.bot and hasattr(self.application.bot, "send_message"):
                    has_pending_edit = hasattr(self, "pending_shutdown_edit") and isinstance(
                        self.pending_shutdown_edit,
                        dict,
                    )
                    if (not has_pending_edit) and (not self._stop_message_sent):
                        shutdown_message = (
                            "🛑 Wednesday Frog Bot остановлен!\n\n📝 Логи сохранены в папке logs/\n👋 До свидания!"
                        )
                        await asyncio.wait_for(
                            self.application.bot.send_message(
                                chat_id=self.chat_id,
                                text=shutdown_message,
                            ),
                            timeout=TIMEOUT_SHORT_SECONDS,
                        )
                        self.logger.info("Сообщение об остановке отправлено")
                        self._stop_message_sent = True
            except TimeoutError:
                self.logger.warning("Таймаут при отправке сообщения об остановке")
            except Exception as send_error:
                self.logger.debug(
                    f"Не удалось отправить сообщение об остановке (возможно, соединение уже закрыто): {send_error}",
                )

            # Обновляем статусное сообщение в чате-источнике: основной бот остановлен (кроме админ-чата)
            try:
                if hasattr(self, "pending_shutdown_edit") and isinstance(self.pending_shutdown_edit, dict):
                    chat_id = self.pending_shutdown_edit.get("chat_id")
                    message_id = self.pending_shutdown_edit.get("message_id")
                    # Не редактируем в админском чате
                    skip_admin_edit = False
                    try:
                        from utils.config import config as _cfg

                        admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                        if admin_chat_id_env:
                            try:
                                admin_chat_str: str = str(admin_chat_id_env)
                                chat_id_str: str = str(chat_id) if chat_id is not None else ""
                                if admin_chat_str and chat_id_str:
                                    skip_admin_edit = int(admin_chat_str) == int(chat_id_str)
                                else:
                                    skip_admin_edit = False
                            except Exception:
                                skip_admin_edit = False
                    except Exception:
                        skip_admin_edit = False

                    if chat_id and message_id and not skip_admin_edit:
                        await self.application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=("🛑 Wednesday Frog Bot остановлен!"),
                        )
                        self.logger.info("Статусное сообщение обновлено: основной бот остановлен")
                    elif chat_id and skip_admin_edit:
                        self.logger.info(
                            "Пропускаю редактирование статусного сообщения в админском чате (остановка основного)",
                        )
            except Exception as e:
                self.logger.warning(f"Не удалось обновить статусное сообщение об остановке: {e}")
            finally:
                # Очистим данные, чтобы не переиспользовать их при последующих переключениях
                self.pending_shutdown_edit = None
                self.pending_startup_edit = None

            # Безопасная остановка приложения
            try:
                await self.application.stop()
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке приложения: {e}")

            self.logger.info("Бот успешно остановлен")

        except Exception as e:
            self.logger.error(f"Ошибка при остановке бота: {e}")
        finally:
            # Рассылка длинного сообщения об остановке также в админ-чат(ы), избегая дубля с CHAT_ID
            try:
                shutdown_message = (
                    "🛑 Wednesday Frog Bot остановлен!\n\n📝 Логи сохранены в папке logs/\n👋 До свидания!"
                )
                from utils.admins_store import AdminsStore
                from utils.config import config as _cfg

                admin_chat_id_env = getattr(_cfg, "admin_chat_id", None)
                has_pending_edit = hasattr(self, "pending_shutdown_edit") and isinstance(
                    self.pending_shutdown_edit,
                    dict,
                )
                if admin_chat_id_env and (not self._stop_message_sent):
                    try:
                        admin_chat_id_val = int(str(admin_chat_id_env))
                        chat_id_val = int(str(self.chat_id)) if self.chat_id is not None else None
                        # Если админ-чат совпадает с CHAT_ID и сообщение уже отправлено в try — пропускаем
                        if chat_id_val == admin_chat_id_val and self._stop_message_sent:
                            # Сообщение уже отправлено в CHAT_ID, пропускаем дубль
                            pass
                        elif has_pending_edit or (chat_id_val != admin_chat_id_val):
                            await self.application.bot.send_message(
                                chat_id=admin_chat_id_val,
                                text=shutdown_message,
                            )
                            self._stop_message_sent = True
                    except Exception:
                        pass
                else:
                    admins = AdminsStore().list_all_admins()
                    for admin_id in admins:
                        try:
                            chat_id_val = int(str(self.chat_id)) if self.chat_id is not None else None
                            # Если был pending edit — не пропускаем даже если это тот же чат;
                            # иначе избегаем дубля с CHAT_ID
                            if not has_pending_edit:
                                if chat_id_val is not None and admin_id == chat_id_val:
                                    continue
                            await self.application.bot.send_message(
                                chat_id=admin_id,
                                text=shutdown_message,
                            )
                            self._stop_message_sent = True
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                # Дополнительно защитимся от повторных отправок в жизненном цикле объекта
                self._stop_message_sent = True

    async def get_bot_info(self) -> dict[str, Any]:
        """
        Получает информацию о боте.

        Returns:
            Словарь с информацией о боте
        """
        try:
            bot_info = await asyncio.wait_for(
                self.application.bot.get_me(),
                timeout=TIMEOUT_MEDIUM_SECONDS,
            )
            return {
                "name": bot_info.first_name,
                "username": bot_info.username,
                "id": bot_info.id,
                "is_running": self.is_running,
            }
        except TimeoutError:
            error_msg = (
                f"Таймаут при получении информации о боте ({TIMEOUT_BOT_INFO_SECONDS} секунд). "
                "Возможные причины: проблемы с интернет-соединением, недоступность Telegram API."
            )
            self.logger.error(error_msg)
            return {"error": "Timeout", "error_message": error_msg, "is_running": self.is_running}
        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)

            # Определяем тип ошибки для более информативного сообщения
            if "ConnectError" in error_type or "ConnectionError" in error_type or "Connection" in error_str:
                error_msg = (
                    f"Ошибка подключения к Telegram API при получении информации о боте.\n"
                    f"Тип: {error_type}\n"
                    f"Детали: {error_str[:200]}\n\n"
                    "Возможные причины:\n"
                    "- Проблемы с интернет-соединением\n"
                    "- Telegram API временно недоступен\n"
                    "- Проблемы с прокси (если используется)\n"
                    "- Блокировка доступа на стороне провайдера\n\n"
                    "Бот будет запущен, но некоторые функции могут быть недоступны."
                )
            else:
                error_msg = f"Ошибка при получении информации о боте: {error_type} - {error_str[:200]}"

            self.logger.error(f"Ошибка при получении информации о боте: {error_type} - {error_str}")
            return {"error": error_type, "error_message": error_msg, "is_running": self.is_running}
