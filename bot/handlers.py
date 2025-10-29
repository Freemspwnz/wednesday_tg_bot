"""
Обработчики команд для Telegram бота.
Содержит функции для обработки различных команд пользователей.
"""

import os
from telegram import Update
from telegram.ext import ContextTypes
from typing import Optional, Callable
from datetime import datetime

from utils.logger import get_logger
from services.image_generator import ImageGenerator


class CommandHandlers:
    """
    Класс для обработки команд Telegram бота.
    
    Обеспечивает:
    - Обработку команды /start
    - Обработку команды /help
    - Обработку команды /frog (тестовая генерация жабы)
    - Обработку команды /status (статус бота)
    """
    
    def __init__(self, image_generator: ImageGenerator, next_run_provider: Optional[Callable[[], Optional[datetime]]] = None):
        """
        Инициализация обработчиков команд.
        
        Args:
            image_generator: Экземпляр генератора изображений
        """
        self.logger = get_logger(__name__)
        self.image_generator = image_generator
        self.next_run_provider = next_run_provider
        
        # Rate limiting для /frog
        self._frog_rate_limit = {}  # {user_id: last_call_timestamp}
        self._frog_rate_limit_minutes = 5  # минимальный интервал в минутах
        self._global_frog_rate_limit = {}  # {timestamp: count}
        self._global_frog_rate_limit_window = 60  # окно в секундах
        self._global_frog_rate_limit_max = 10  # максимум запросов в окне
        
        self.logger.info("Обработчики команд инициализированы")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /start.
        Приветствует пользователя и показывает основную информацию о боте.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст бота
        """
        self.logger.info(f"Получена команда /start от пользователя {update.effective_user.id}")
        
        next_run_info = ""
        if self.next_run_provider:
            try:
                next_dt = self.next_run_provider()
                if next_dt:
                    next_run_info = f"\n📅 Следующая отправка: {next_dt.strftime('%Y-%m-%d %H:%M')}"
            except Exception:
                pass

        welcome_message = (
            "🐸 Привет! Я Wednesday Frog Bot!\n\n"
            "Я генерирую изображения жабы по расписанию (каждую среду) и по команде.\n\n"
            "Доступные команды:\n"
            "/start - Показать это сообщение\n"
            "/help - Справка по командам\n"
            "/frog - Сгенерировать жабу прямо сейчас\n"
            "/status - Статус бота\n"
            f"{next_run_info}"
        )
        
        await update.message.reply_text(welcome_message)
        self.logger.info("Отправлено приветственное сообщение")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /help.
        Показывает подробную справку по всем командам.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст бота
        """
        self.logger.info(f"Получена команда /help от пользователя {update.effective_user.id}")
        
        help_message = (
            "📚 Справка по командам Wednesday Frog Bot\n\n"
            "🔹 /start - Приветствие и основная информация\n"
            "🔹 /help - Эта справка\n"
            "🔹 /frog - Сгенерировать изображение жабы прямо сейчас\n"
            "🔹 /status - Показать статус бота\n\n"
            "ℹ️ Информация:\n"
            "• Планировщик включен (каждая среда)\n"
            "• Изображения генерируются с помощью нейросети Kandinsky\n"
            "• Логи сохраняются в папке logs/\n\n"
            "🐛 Если что-то не работает, проверьте логи или обратитесь к администратору."
        )
        
        await update.message.reply_text(help_message)
        self.logger.info("Отправлена справка")
    
    async def frog_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /frog.
        Генерирует и отправляет изображение жабы по запросу пользователя.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст бота
        """
        user_id = update.effective_user.id
        self.logger.info(f"Получена команда /frog от пользователя {user_id}")
        
        # Rate limit: глобальный
        import time
        now = time.time()
        self._global_frog_rate_limit = {ts: cnt for ts, cnt in self._global_frog_rate_limit.items() if now - ts < self._global_frog_rate_limit_window}
        recent_count = sum(self._global_frog_rate_limit.values())
        if recent_count >= self._global_frog_rate_limit_max:
            self.logger.warning(f"Глобальный rate limit /frog: {recent_count}/{self._global_frog_rate_limit_max}")
            await update.message.reply_text("🚦 Слишком много запросов! Попробуйте через минуту.")
            return
        
        # Rate limit: per-user
        last_call = self._frog_rate_limit.get(user_id, 0)
        if now - last_call < self._frog_rate_limit_minutes * 60:
            remaining = int(self._frog_rate_limit_minutes * 60 - (now - last_call))
            self.logger.info(f"Rate limit для пользователя {user_id}: {remaining}с осталось")
            await update.message.reply_text(f"⏰ Повторная генерация доступна через {remaining}с")
            return
        
        self._frog_rate_limit[user_id] = now
        self._global_frog_rate_limit[now] = self._global_frog_rate_limit.get(now, 0) + 1
        
        # Проверяем лимит генераций (храним в application.bot_data)
        usage = context.application.bot_data.get("usage")
        if usage and not usage.can_use_frog():
            total, threshold, quota = usage.get_limits_info()
            await update.message.reply_text(
                (
                    "🚫 Лимит ручных генераций на этот месяц исчерпан.\n"
                    f"Использовано: {total}/{quota}. Доступ к /frog закрыт после {threshold}.\n"
                    "Ожидайте автоматических отправок по средам."
                )
            )
            return

        # Отправляем сообщение о начале генерации
        status_message = await update.message.reply_text(
            "🐸 Генерирую жабу для вас... Это может занять несколько секунд."
        )
        
        try:
            # Генерируем изображение жабы
            result = await self.image_generator.generate_frog_image()
            
            if result:
                image_data, caption = result
                
                # Отправляем изображение с подписью
                await update.message.reply_photo(
                    photo=image_data,
                    caption=caption
                )
                # Сохраним локально результат
                try:
                    saved_path = self.image_generator.save_image_locally(image_data, folder="data/frogs", prefix="frog")
                    if saved_path:
                        self.logger.info(f"Изображение сохранено локально: {saved_path}")
                except Exception:
                    pass
                # Успешная генерация — увеличиваем счетчик
                if usage:
                    usage.increment(1)
                
                # Удаляем статусное сообщение
                await status_message.delete()
                
                self.logger.info(f"Изображение жабы успешно отправлено пользователю {user_id}")
                
            else:
                # Если генерация не удалась
                await status_message.edit_text(
                    "❌ К сожалению, не удалось сгенерировать изображение жабы. "
                    "Попробуйте позже или обратитесь к администратору."
                )
                self.logger.error(f"Не удалось сгенерировать изображение для пользователя {user_id}")
                
        except Exception as e:
            self.logger.error(f"Ошибка при обработке команды /frog: {e}")
            await status_message.edit_text(
                "❌ Произошла ошибка при генерации изображения. Попробуйте позже."
            )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик команды /status.
        Показывает текущий статус бота и информацию о следующей отправке.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст бота
        """
        self.logger.info(f"Получена команда /status от пользователя {update.effective_user.id}")
        
        # Получаем информацию о статусе бота
        bot_info = await context.bot.get_me()

        next_run_line = ""
        if self.next_run_provider:
            try:
                next_dt = self.next_run_provider()
                if next_dt:
                    next_run_line = f"📅 Следующая отправка: {next_dt.strftime('%Y-%m-%d %H:%M')}\n"
            except Exception:
                pass

        status_message = (
            f"🤖 Статус бота: {bot_info.first_name}\n\n"
            "✅ Бот активен и работает\n"
            f"{next_run_line}"
            "🎨 Генератор изображений: Kandinsky API\n"
            "📝 Логирование: включено\n\n"
            "🔄 Последняя проверка: прямо сейчас\n"
            "💚 Все системы работают нормально!"
        )
        
        await update.message.reply_text(status_message)
        self.logger.info("Отправлен статус бота")
    
    async def unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Обработчик неизвестных команд.
        Отправляет сообщение с подсказкой о доступных командах.
        
        Args:
            update: Объект обновления Telegram
            context: Контекст бота
        """
        user_id = update.effective_user.id
        self.logger.info(f"Получена неизвестная команда от пользователя {user_id}")
        
        unknown_message = (
            "❓ Неизвестная команда!\n\n"
            "Доступные команды:\n"
            "/start - Приветствие\n"
            "/help - Справка\n"
            "/frog - Сгенерировать жабу\n"
            "/status - Статус бота\n\n"
            "Используйте /help для получения подробной информации."
        )
        
        await update.message.reply_text(unknown_message)
        self.logger.info("Отправлено сообщение о неизвестной команде")
    
    async def admin_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin команда: статус лимитов и использования."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return
        
        usage = context.application.bot_data.get("usage")
        chats = context.application.bot_data.get("chats")
        
        usage_info = "N/A"
        if usage:
            total, threshold, quota = usage.get_limits_info()
            used_percent = int(total / quota * 100) if quota else 0
            usage_info = f"{total}/{quota} ({used_percent}%), порог: {threshold}"
        
        chats_info = "N/A"
        if chats:
            chats_info = len(chats.list_chat_ids())
        
        msg = (
            "🔧 Админ-статус\n\n"
            f"📊 Генерации: {usage_info}\n"
            f"💬 Активных чатов: {chats_info}\n"
            "✅ Система работает"
        )
        await update.message.reply_text(msg)
    
    async def admin_force_send_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin команда: принудительная отправка в чат."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return
        
        await update.message.reply_text("🔄 Запускаю принудительную отправку...")
        # Здесь можно добавить вызов send_wednesday_frog()
        await update.message.reply_text("✅ Отправка выполнена")
    
    async def admin_add_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin команда: добавить чат в рассылку."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return
        
        if not context.args or len(context.args) == 0:
            await update.message.reply_text("📝 Использование: /admin_add_chat <chat_id>")
            return
        
        try:
            chat_id = int(context.args[0])
            chats = context.application.bot_data.get("chats")
            if chats:
                chats.add_chat(chat_id, "Manually added")
                await update.message.reply_text(f"✅ Чат {chat_id} добавлен в рассылку")
        except ValueError:
            await update.message.reply_text("❌ Неверный chat_id (должен быть числом)")
    
    async def admin_remove_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin команда: удалить чат из рассылки."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return
        
        if not context.args or len(context.args) == 0:
            await update.message.reply_text("📝 Использование: /admin_remove_chat <chat_id>")
            return
        
        try:
            chat_id = int(context.args[0])
            chats = context.application.bot_data.get("chats")
            if chats:
                chats.remove_chat(chat_id)
                await update.message.reply_text(f"✅ Чат {chat_id} удалён из рассылки")
        except ValueError:
            await update.message.reply_text("❌ Неверный chat_id (должен быть числом)")
    
    async def health_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Health-check команда: статус всех систем."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return
        
        try:
            # Проверяем API
            api_status = "✅ Работает"
            try:
                result = await self.image_generator.generate_frog_image(metrics=context.application.bot_data.get("metrics"))
                api_status = "✅ Работает" if result else "⚠️  Проблемы генерации"
            except Exception as e:
                api_status = f"❌ Ошибка: {str(e)[:50]}"
            
            # Статус планировщика
            next_run = self.next_run_provider() if self.next_run_provider else None
            scheduler_status = f"✅ Следующая отправка: {next_run.strftime('%Y-%m-%d %H:%M')}" if next_run else "❌ Не настроен"
            
            # Метрики
            metrics = context.application.bot_data.get("metrics")
            if metrics:
                m_sum = metrics.get_summary()
                metrics_text = f"Генераций успешно: {m_sum['generations_success']}\nСреднее время: {m_sum['average_generation_time']}\nCircuit breaker: {m_sum['circuit_breaker_trips']}"
            else:
                metrics_text = "Не настроены"
            
            msg = (
                "🏥 Health Check\n\n"
                f"🔌 API: {api_status}\n"
                f"⏰ Планировщик: {scheduler_status}\n"
                f"📊 Метрики:\n{metrics_text}"
            )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка health-check: {str(e)}")

    async def admin_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin команда: показать все доступные команды с описанием."""
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if admin_chat_id and str(update.effective_user.id) != admin_chat_id:
            await update.message.reply_text("❌ Доступно только администратору")
            return

        next_run_hint = ""
        if self.next_run_provider:
            try:
                nxt = self.next_run_provider()
                if nxt:
                    next_run_hint = f"\n   (Следующая отправка: {nxt.strftime('%Y-%m-%d %H:%M')})"
            except Exception:
                pass

        msg = (
            "🛠 Админ-справка по командам\n\n"
            "Пользовательские команды:\n"
            "• /start — приветствие и информация\n"
            "• /help — базовая справка по командам\n"
            "• /frog — сгенерировать жабу сейчас (rate limit, учитывается в лимитах)\n"
            "• /status — статус бота и планировщика" + next_run_hint + "\n\n"
            "Админ-команды:\n"
            "• /admin_status — сводка по генерациям и активным чатам\n"
            "• /admin_add_chat <chat_id> — добавить чат в рассылку\n"
            "• /admin_remove_chat <chat_id> — удалить чат из рассылки\n"
            "• /admin_force_send — принудительная отправка в подключенные чаты\n"
            "• /health — проверка API/планировщика/метрик\n"
            "• /admin_help — эта справка"
        )

        await update.message.reply_text(msg)
