"""
Основной класс Wednesday Frog Bot.
Объединяет все компоненты бота и управляет его жизненным циклом.
"""

import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ChatMemberHandler
from typing import Optional

from utils.logger import get_logger
from utils.config import config
from services.image_generator import ImageGenerator
from services.scheduler import TaskScheduler
from bot.handlers import CommandHandlers
import os
from utils.usage_tracker import UsageTracker
from utils.chats_store import ChatsStore
from utils.dispatch_registry import DispatchRegistry
from utils.metrics import Metrics


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
    
    def __init__(self):
        """Инициализация основного класса бота."""
        self.logger = get_logger(__name__)
        
        # Инициализируем компоненты
        self.application = (
            Application.builder()
            .token(config.telegram_token)
            .get_updates_connect_timeout(10.0)
            .get_updates_read_timeout(20.0)
            .build()
        )
        
        # Создаем сервисы
        self.image_generator = ImageGenerator()
        self.scheduler = TaskScheduler()
        self.usage = UsageTracker(storage_path=os.getenv("USAGE_STORAGE", "usage_stats.json"), monthly_quota=100, frog_threshold=70)
        self.chats = ChatsStore()
        self.dispatch_registry = DispatchRegistry()
        self.metrics = Metrics()
        
        # Создаем обработчики команд
        self.handlers = CommandHandlers(self.image_generator, self.scheduler.get_next_run)
        
        # ID чата для отправки сообщений
        self.chat_id = config.chat_id
        
        # Флаг состояния бота
        self.is_running = False
        
        self.logger.info("Wednesday Bot инициализирован")
    
    def setup_handlers(self) -> None:
        """
        Настраивает обработчики команд для бота.
        Регистрирует все доступные команды и обработчики сообщений.
        """
        self.logger.info("Настраиваю обработчики команд")
        
        # Регистрируем обработчики команд
        self.application.add_handler(
            CommandHandler("start", self.handlers.start_command)
        )
        self.application.add_handler(
            CommandHandler("help", self.handlers.help_command)
        )
        self.application.add_handler(
            CommandHandler("frog", self.handlers.frog_command)
        )
        self.application.add_handler(
            CommandHandler("status", self.handlers.status_command)
        )
        
        # Admin команды (регистрируем перед unknown_command!)
        self.application.add_handler(
            CommandHandler("admin_status", self.handlers.admin_status_command)
        )
        self.application.add_handler(
            CommandHandler("admin_help", self.handlers.admin_help_command)
        )
        self.application.add_handler(
            CommandHandler("admin_force_send", self.handlers.admin_force_send_command)
        )
        self.application.add_handler(
            CommandHandler("admin_add_chat", self.handlers.admin_add_chat_command)
        )
        self.application.add_handler(
            CommandHandler("admin_remove_chat", self.handlers.admin_remove_chat_command)
        )
        self.application.add_handler(
            CommandHandler("health", self.handlers.health_check_command)
        )
        
        # Обработчик для неизвестных команд
        self.application.add_handler(
            MessageHandler(filters.COMMAND, self.handlers.unknown_command)
        )

        # Обработчик событий изменения статуса бота в чатах
        self.application.add_handler(
            ChatMemberHandler(self.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
        )
        
        self.logger.info("Обработчики команд успешно настроены")
    
    async def send_wednesday_frog(self) -> None:
        """
        Основная функция для отправки изображения жабы каждую среду.
        Генерирует изображение и отправляет его в указанный чат.
        """
        from datetime import datetime
        now = datetime.now()
        slot_date = now.strftime("%Y-%m-%d")
        slot_time = now.strftime("%H:%M")
        
        self.logger.info("Выполняю запланированную отправку жабы")
        
        try:
            # Учет генерации для планировщика не ограничиваем порогом 70,
            # но считаем общее потребление
            # Генерируем изображение жабы
            result = await self.image_generator.generate_frog_image(metrics=self.metrics)
            
            if result:
                image_data, caption = result
                
                # Сохраняем изображение локально заранее (на случай сбоев сети)
                try:
                    saved_path = self.image_generator.save_image_locally(image_data, folder="data/frogs", prefix="wednesday")
                    if saved_path:
                        self.logger.info(f"Изображение сохранено локально: {saved_path}")
                except Exception as e:
                    self.logger.warning(f"Не удалось сохранить изображение локально: {e}")

                # Целевые чаты: сохранённые чаты + резервный конфиг чат
                targets = set(self.chats.list_chat_ids() or [])
                # Добавляем резервный чат из конфигурации
                try:
                    targets.add(int(self.chat_id))
                except Exception:
                    pass
                
                # Если нет ни одного чата, пропускаем отправку
                if not targets:
                    self.logger.warning("Нет целевых чатов для отправки сообщения")
                    await self._send_error_message("Нет настроенных чатов для отправки")
                    return

                for target_chat in targets:
                    # Проверяем, не было ли уже отправлено в этот чат в этот тайм-слот
                    if self.dispatch_registry.is_dispatched(slot_date, slot_time, target_chat):
                        self.logger.info(f"Пропускаем отправку в {target_chat} - уже отправлено в слот {slot_date}_{slot_time}")
                        continue
                    
                    send_attempts = 3
                    initial_backoff = 2
                    for attempt in range(1, send_attempts + 1):
                        try:
                            await self.application.bot.send_photo(
                                chat_id=target_chat,
                                photo=image_data,
                                caption=caption
                            )
                            # Отмечаем в реестре успешную отправку
                            self.dispatch_registry.mark_dispatched(slot_date, slot_time, target_chat)
                            # инкрементируем счетчик после успешной отправки
                            self.usage.increment(1)
                            self.logger.info(f"Жаба отправлена в чат {target_chat}")
                            break
                        except Exception as send_error:
                            error_str = str(send_error).lower()
                            is_429 = "429" in error_str or "rate limit" in error_str or "too many requests" in error_str
                            
                            if is_429 and attempt < send_attempts:
                                # Обработка 429: читаем Retry-After из заголовков если доступно
                                retry_after = 60  # дефолтное значение
                                if hasattr(send_error, 'retry_after') and send_error.retry_after:
                                    retry_after = int(send_error.retry_after)
                                elif hasattr(send_error, 'response') and send_error.response:
                                    retry_after_header = send_error.response.headers.get('retry-after')
                                    if retry_after_header:
                                        retry_after = int(retry_after_header)
                                
                                self.logger.warning(f"429 Rate Limit в {target_chat} (попытка {attempt}/{send_attempts}), ждём {retry_after}с")
                                await asyncio.sleep(retry_after)
                                continue
                            
                            self.logger.warning(f"Сбой отправки в {target_chat} (попытка {attempt}/{send_attempts}): {send_error}")
                            if attempt == send_attempts:
                                self.logger.error(f"Не удалось отправить изображение в чат {target_chat} после всех попыток")
                                try:
                                    await self._send_error_message(f"Не удалось отправить изображение в чат {target_chat}")
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
                # Если генерация не удалась, отправляем сообщение об ошибке
                await self._send_error_message("Не удалось сгенерировать изображение жабы для среды")
                self.logger.error("Не удалось сгенерировать изображение для среды")
                
        except Exception as e:
            self.logger.error(f"Ошибка при отправке жабы: {e}")
            await self._send_error_message("Произошла ошибка при отправке жабы")
    
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
                text=error_message
            )
        except Exception as send_error:
            self.logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")
    
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
        self.logger.info(f"Валидация планировщика: день недели={self.scheduler.wednesday}, времена={self.scheduler.send_times}, TZ={self.scheduler.tz.key}")
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

            # Ретраи запуска сети (start + polling)
            delay = 3
            for attempt in range(3):
                try:
                    await self.application.start()
                    await self.application.updater.start_polling(
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True
                    )
                    break
                except Exception as e:
                    self.logger.warning(f"Не удалось запустить polling (попытка {attempt+1}/3): {e}")
                    if attempt == 2:
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
                    "🐸 Используйте команду /frog для тестирования!\n"
                    "ℹ️ Команда /status покажет время следующей отправки"
                )
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=startup_message
                )
                self.logger.info("Сообщение о запуске отправлено")
            except Exception as send_error:
                self.logger.warning(f"Не удалось отправить сообщение о запуске: {send_error}")
                self.logger.info("Бот запущен, но не удалось отправить уведомление в чат")
            
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

    async def on_my_chat_member(self, update, context):
        try:
            my_cm = update.my_chat_member
            if not my_cm:
                return
            old = getattr(my_cm.old_chat_member, 'status', None)
            new = getattr(my_cm.new_chat_member, 'status', None)
            chat = my_cm.chat
            chat_id = chat.id
            title = getattr(chat, 'title', None) or getattr(chat, 'username', '') or ''

            # Бот добавлен/активирован в чате
            if new in ("member", "administrator") and old in ("left", "kicked", "restricted", None):
                self.chats.add_chat(chat_id, title)
                welcome = (
                    "🐸 Привет! Я Wednesday Frog Bot.\n\n"
                    "Я присылаю картинки с жабой по средам (09:00, 12:00, 18:00 по Мск), "
                    "а также по команде /frog (если не превышен лимит ручных генераций).\n\n"
                    "Доступные команды:\n"
                    "• /start — информация\n"
                    "• /help — справка\n"
                    "• /frog — сгенерировать жабу сейчас\n"
                    "• /status — статус и ближайшая отправка\n"
                )
                try:
                    await self.application.bot.send_message(chat_id=chat_id, text=welcome)
                except Exception as e:
                    self.logger.warning(f"Не удалось отправить приветствие в чат {chat_id}: {e}")

            # Бот удалён из чата
            if new in ("left", "kicked") and old in ("member", "administrator", "restricted"):
                self.chats.remove_chat(chat_id)

        except Exception as e:
            self.logger.error(f"Ошибка в on_my_chat_member: {e}")
    
    async def _check_chat_access(self) -> None:
        """
        Проверяет доступность чата для отправки сообщений.
        """
        try:
            # Пытаемся получить информацию о чате
            chat_info = await self.application.bot.get_chat(self.chat_id)
            self.logger.info(f"Чат доступен: {chat_info.title or chat_info.first_name}")
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
        
        # Сразу устанавливаем флаг, чтобы предотвратить повторные вызовы
        self.is_running = False
        
        try:
            # Останавливаем планировщик
            try:
                if hasattr(self, 'scheduler_task') and self.scheduler_task:
                    self.scheduler.stop()
                    self.scheduler_task.cancel()
                    try:
                        await self.scheduler_task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке планировщика: {e}")

            # Отправляем сообщение об остановке (с более коротким таймаутом)
            try:
                shutdown_message = (
                    "🛑 Wednesday Frog Bot остановлен!\n\n"
                    "📝 Логи сохранены в папке logs/\n"
                    "👋 До свидания!"
                )
                
                # Используем более короткий таймаут для отправки
                await asyncio.wait_for(
                    self.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=shutdown_message
                    ),
                    timeout=5.0
                )
                self.logger.info("Сообщение об остановке отправлено")
            except asyncio.TimeoutError:
                self.logger.warning("Таймаут при отправке сообщения об остановке")
            except Exception as send_error:
                self.logger.warning(f"Не удалось отправить сообщение об остановке: {send_error}")
            
            # Безопасная остановка updater'а
            try:
                if hasattr(self.application, 'updater') and self.application.updater:
                    await self.application.updater.stop()
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке updater'а: {e}")
            
            # Безопасная остановка приложения
            try:
                await self.application.stop()
            except Exception as e:
                self.logger.warning(f"Ошибка при остановке приложения: {e}")
            
            self.logger.info("Бот успешно остановлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка при остановке бота: {e}")
    
    async def get_bot_info(self) -> dict:
        """
        Получает информацию о боте.
        
        Returns:
            Словарь с информацией о боте
        """
        try:
            bot_info = await self.application.bot.get_me()
            return {
                "name": bot_info.first_name,
                "username": bot_info.username,
                "id": bot_info.id,
                "is_running": self.is_running
            }
        except Exception as e:
            self.logger.error(f"Ошибка при получении информации о боте: {e}")
            return {"error": str(e)}
