"""
Главный файл запуска Wednesday Frog Bot.
Точка входа в приложение с обработкой ошибок и graceful shutdown.
"""

import asyncio
import signal
import sys
from pathlib import Path

from utils.logger import get_logger
from utils.config import config
from bot.wednesday_bot import WednesdayBot
from bot.support_bot import SupportBot


class BotRunner:
    """
    Класс для управления запуском и остановкой бота.
    
    Обеспечивает:
    - Graceful shutdown при получении сигналов
    - Обработку ошибок запуска
    - Логирование состояния приложения
    """
    
    def __init__(self):
        """Инициализация runner'а бота."""
        self.logger = get_logger(__name__)
        self.bot = None
        self.support_bot = None
        self.shutdown_event = asyncio.Event()
        self.should_stop = False
        self.request_start_main_event = asyncio.Event()
        self.pending_startup_edit = None
        self.pending_shutdown_edit = None
        self.logger.info("Bot Runner инициализирован")

    def setup_signal_handlers(self) -> None:
        """
        Настраивает обработчики сигналов для graceful shutdown.
        """
        self.logger.info("Настраиваю обработчики сигналов")
        
        # Обработчики для SIGINT (Ctrl+C) и SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)
        
        self.logger.info("Обработчики сигналов настроены")

    def _signal_handler(self, signum=None, frame=None) -> None:
        """
        Обработчик сигналов для graceful shutdown.
        
        Args:
            signum: Номер сигнала
            frame: Текущий стекадрес
        """
        try:
            print("\n🛑 Получен сигнал остановки, начинаю graceful shutdown...")
            
            # Устанавливаем флаг остановки
            self.should_stop = True
            
            # Устанавливаем событие для остановки
            if hasattr(self, 'shutdown_event') and self.shutdown_event is not None:
                self.shutdown_event.set()
                
            # Попытка логирования (безопасно)
            if hasattr(self, 'logger') and self.logger is not None:
                try:
                    self.logger.info("Получен сигнал остановки, начинаю graceful shutdown")
                except:
                    pass  # Игнорируем ошибки логирования
                    
        except Exception as e:
            # В случае любой ошибки в обработчике сигналов, просто выводим в консоль
            print(f"Ошибка в обработчике сигналов: {e}")

    async def run(self) -> None:
        """
        Основной метод запуска бота.
        """
        self.logger.info("Запускаю Wednesday Frog Bot")
        
        try:
            # Проверяем наличие необходимых файлов
            self._check_requirements()
            
            # Общий цикл: сначала пробуем запускать основной бот; при остановке — включаем SupportBot
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._signal_handler)
                except (ValueError, RuntimeError, AttributeError) as e:
                    self.logger.warning(f"Не удалось установить обработчик сигнала {sig}: {e}")

            while not self.should_stop and not self.shutdown_event.is_set():
                # Этап 1: всегда запускаем SupportBot первым
                self.logger.info("[Supervisor] Старт SupportBot (режим по умолчанию)")
                self.request_start_main_event.clear()

                async def request_start_main(payload: dict):
                    self.logger.info("[Supervisor] Получен запрос запуска основного бота из SupportBot")
                    self.pending_startup_edit = payload or None
                    self.request_start_main_event.set()

                self.support_bot = SupportBot(request_start_main=request_start_main)
                # Если есть отложенное редактирование для статуса остановки основного — передадим SupportBot
                try:
                    if isinstance(self.pending_shutdown_edit, dict):
                        self.support_bot.pending_shutdown_edit = self.pending_shutdown_edit
                        self.pending_shutdown_edit = None
                except Exception:
                    self.pending_shutdown_edit = None
                support_task = asyncio.create_task(self.support_bot.start())

                # Ждём либо сигнал завершения процесса, либо запрос запуска основного
                while True:
                    if self.should_stop or self.shutdown_event.is_set():
                        self.logger.info("[Supervisor] Сигнал завершения в режиме SupportBot — завершаем работу")
                        await self._stop_support_bot()
                        if not support_task.done():
                            support_task.cancel()
                        return
                    if self.request_start_main_event.is_set():
                        break
                    await asyncio.sleep(0.1)

                # Переключение: останавливаем SupportBot, запускаем основной бот
                self.logger.info("[Supervisor] Переключение: SupportBot -> основной бот")
                await self._stop_support_bot()
                if not support_task.done():
                    support_task.cancel()
                # Дадим немного времени освободить getUpdates
                await asyncio.sleep(5.0)

                # Этап 2: запускаем основной бот
                self.bot = WednesdayBot()
                try:
                    self.bot.pending_startup_edit = self.pending_startup_edit
                except Exception:
                    pass
                try:
                    _ = await self.bot.get_bot_info()
                except Exception:
                    pass
                bot_task = asyncio.create_task(self.bot.start())
                shutdown_task = asyncio.create_task(self._wait_for_shutdown())

                done, pending = await asyncio.wait([bot_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED)

                # Если пришёл сигнал — останавливаем основной и снова уходим в SupportBot
                if self.should_stop or self.shutdown_event.is_set():
                    self.logger.info("[Supervisor] Сигнал завершения при активном основном — останавливаю основной и возвращаюсь к SupportBot")
                    # Сохраним отложенное редактирование статуса остановки
                    try:
                        if hasattr(self.bot, 'pending_shutdown_edit') and isinstance(self.bot.pending_shutdown_edit, dict):
                            self.pending_shutdown_edit = self.bot.pending_shutdown_edit
                    except Exception:
                        pass
                    await self._stop_bot()
                    self.bot = None
                    if not bot_task.done():
                        bot_task.cancel()
                    # Сбрасываем флаги остановки, чтобы НЕ завершать приложение и вернуться к SupportBot
                    self.should_stop = False
                    self.shutdown_event = asyncio.Event()
                    # Небольшая пауза, чтобы освободить getUpdates/соединения
                    await asyncio.sleep(5.0)
                    # Переходим к началу while, где снова запустится SupportBot
                    continue
                else:
                    # Основной завершился сам (ошибка или /stop) — возвращаемся к SupportBot
                    self.logger.warning("[Supervisor] Основной бот остановлен. Запуск SupportBot")
                    # Сохраним отложенное редактирование статуса остановки
                    try:
                        if hasattr(self.bot, 'pending_shutdown_edit') and isinstance(self.bot.pending_shutdown_edit, dict):
                            self.pending_shutdown_edit = self.bot.pending_shutdown_edit
                    except Exception:
                        pass
                    await self._stop_bot()
                    self.bot = None
                    try:
                        if not bot_task.done():
                            bot_task.cancel()
                            await bot_task
                    except Exception:
                        pass
                    await asyncio.sleep(5.0)
                    # Сбросим сигналы перед повторным запуском SupportBot
                    self.should_stop = False
                    self.shutdown_event = asyncio.Event()
            
            self.logger.info("Wednesday Frog Bot (supervisor) завершил работу")
            
        except Exception as e:
            # Более подробное логирование ошибки
            import traceback
            error_details = traceback.format_exc()
            self.logger.error(f"Критическая ошибка при запуске бота: {e}")
            self.logger.error(f"Подробности ошибки:\n{error_details}")
            await self._cleanup()
            raise

    def _check_requirements(self) -> None:
        """
        Проверяет наличие необходимых файлов и настроек.
        """
        self.logger.info("Проверяю требования для запуска")
        
        # Проверяем наличие файла .env
        env_file = Path(".env")
        if not env_file.exists():
            self.logger.error("Файл .env не найден!")
            self.logger.error("Создайте файл .env со следующими переменными:")
            self.logger.error("TELEGRAM_BOT_TOKEN=your_bot_token_here")
            self.logger.error("KANDINSKY_API_KEY=your_kandinsky_api_key_here")
            self.logger.error("KANDINSKY_SECRET_KEY=your_kandinsky_secret_key_here")
            self.logger.error("CHAT_ID=your_chat_or_channel_id_here")
            sys.exit(1)
        
        # Проверяем конфигурацию
        try:
            # Проверяем, что все обязательные переменные загружены
            _ = config.telegram_token
            _ = config.kandinsky_api_key
            _ = config.kandinsky_secret_key
            _ = config.chat_id
            self.logger.info("Конфигурация проверена успешно")
        except Exception as e:
            self.logger.error(f"Ошибка в конфигурации: {e}")
            sys.exit(1)

    async def _cleanup(self) -> None:
        """
        Выполняет очистку ресурсов при завершении работы.
        """
        self.logger.info("Выполняю очистку ресурсов")
        
        if self.bot and getattr(self.bot, "is_running", False):
            try:
                await self.bot.stop()
            except Exception as e:
                self.logger.error(f"Ошибка при остановке бота: {e}")
        self.bot = None
        if self.support_bot and getattr(self.support_bot, "is_running", False):
            try:
                await self.support_bot.stop()
            except Exception as e:
                self.logger.error(f"Ошибка при остановке SupportBot: {e}")
        self.support_bot = None
                
    async def _wait_for_shutdown(self) -> None:
        """
        Ожидает сигнал остановки.
        """
        while not self.should_stop and not self.shutdown_event.is_set():
            await asyncio.sleep(0.1)
    
    async def _stop_bot(self) -> None:
        """
        Асинхронно останавливает бота.
        """
        try:
            await self.bot.stop()
        except Exception as e:
            self.logger.error(f"Ошибка при остановке бота: {e}")

    async def _stop_support_bot(self) -> None:
        try:
            if self.support_bot:
                await self.support_bot.stop()
        except Exception as e:
            self.logger.error(f"Ошибка при остановке SupportBot: {e}")


async def main() -> None:
    """
    Главная функция приложения.
    """
    runner = BotRunner()
    await runner.run()


if __name__ == "__main__":
    """
    Точка входа в приложение.
    """
    try:
        # Запускаем главную функцию
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Получен сигнал прерывания. Завершение работы...")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
