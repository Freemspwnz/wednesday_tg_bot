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
        self.shutdown_event = asyncio.Event()
        self.should_stop = False
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
            
            # Создаем экземпляр бота
            self.bot = WednesdayBot()
            
            # Получаем информацию о боте (не блокируем запуск при ошибке)
            try:
                bot_info = await self.bot.get_bot_info()
                if "error" in bot_info:
                    self.logger.warning(f"Не удалось получить информацию о боте: {bot_info.get('error_message', bot_info.get('error', 'Unknown error'))}")
                    self.logger.info("Продолжаю запуск бота...")
                else:
                    self.logger.info(f"Информация о боте: {bot_info}")
            except Exception as e:
                self.logger.warning(f"Критическая ошибка при получении информации о боте: {e}. Продолжаю запуск...")
            
            # Настраиваем обработчики сигналов ПОСЛЕ создания асинхронного контекста
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._signal_handler)
                except (ValueError, RuntimeError, AttributeError) as e:
                    self.logger.warning(f"Не удалось установить обработчик сигнала {sig}: {e}")
            
            # Запускаем бота в отдельной задаче
            bot_task = asyncio.create_task(self.bot.start())
            
            # Запускаем задачу отслеживания сигнала остановки
            shutdown_task = asyncio.create_task(self._wait_for_shutdown())
            
            # Ждем либо завершения бота, либо получения сигнала остановки
            done, pending = await asyncio.wait(
                [bot_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Если получен сигнал остановки, останавливаем бота
            if not bot_task.done() and (self.should_stop or self.shutdown_event.is_set()):
                self.logger.info("Получен сигнал остановки, останавливаю бота...")
                await self._stop_bot()
                # Отменяем задачу бота
                if not bot_task.done():
                    bot_task.cancel()
            
            # Отменяем задачу shutdown_task, если она еще выполняется
            if not shutdown_task.done():
                shutdown_task.cancel()
                try:
                    await shutdown_task
                except asyncio.CancelledError:
                    pass
            
            # Ждем завершения bot_task
            if not bot_task.done():
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
                except Exception as bot_error:
                    self.logger.warning(f"Ошибка в задаче бота: {bot_error}")
            
            self.logger.info("Wednesday Frog Bot завершил работу")
            
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
        
        if self.bot:
            try:
                await self.bot.stop()
            except Exception as e:
                self.logger.error(f"Ошибка при остановке бота: {e}")
                
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
