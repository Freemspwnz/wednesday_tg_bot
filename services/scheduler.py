"""
Планировщик задач для автоматической отправки изображений жабы каждую среду.
Использует asyncio для асинхронного выполнения задач.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Callable, Awaitable, Optional

from utils.logger import get_logger
from utils.config import SchedulerConfig


class TaskScheduler:
    """
    Планировщик задач для автоматического выполнения функций по расписанию.
    
    Обеспечивает:
    - Планирование задач на определенное время
    - Выполнение задач в определенные дни недели
    - Асинхронное выполнение задач
    - Логирование выполнения задач
    """
    
    def __init__(self):
        """Инициализация планировщика задач."""
        self.logger = get_logger(__name__)
        self.running = False
        self.tasks = {}
        
        # Настройки планировщика
        self.send_times = SchedulerConfig.SEND_TIMES
        self.wednesday = SchedulerConfig.WEDNESDAY
        self.check_interval = SchedulerConfig.CHECK_INTERVAL
        self.tz = ZoneInfo(getattr(SchedulerConfig, 'TZ', 'Europe/Moscow'))
        
        self.logger.info("Планировщик задач инициализирован")
    
    def schedule_wednesday_task(self, task_func: Callable[[], Awaitable[None]]) -> None:
        """
        Планирует задачу на выполнение каждую среду в указанное время.
        
        Args:
            task_func: Асинхронная функция для выполнения
        """
        self.logger.info(f"Планирую задачу на среду в {', '.join(self.send_times)} по {self.tz.key}")
        
        # Сохраняем задачу для выполнения
        self.tasks['wednesday_frog'] = task_func
        
        self.logger.info("Задача успешно запланирована")
    
    def schedule_daily_task(self, task_func: Callable[[], Awaitable[None]], time_str: str) -> None:
        """
        Планирует задачу на выполнение каждый день в указанное время.
        
        Args:
            task_func: Асинхронная функция для выполнения
            time_str: Время выполнения в формате "HH:MM"
        """
        self.logger.info(f"Планирую ежедневную задачу в {time_str}")
        
        self.tasks['daily_task'] = {
            'func': task_func,
            'time_str': time_str,
            'last_run_date': None,
        }
        
        self.logger.info("Ежедневная задача успешно запланирована")
    
    def schedule_interval_task(self, task_func: Callable[[], Awaitable[None]], 
                             interval_minutes: int) -> None:
        """
        Планирует задачу на выполнение с заданным интервалом.
        
        Args:
            task_func: Асинхронная функция для выполнения
            interval_minutes: Интервал в минутах
        """
        self.logger.info(f"Планирую задачу с интервалом {interval_minutes} минут")
        
        self.tasks['interval_task'] = {
            'func': task_func,
            'interval_minutes': interval_minutes,
            'last_run': None,
        }
        
        self.logger.info("Задача с интервалом успешно запланирована")
    
    async def _run_async_task(self, task_func: Callable[[], Awaitable[None]]) -> None:
        """
        Обертка для выполнения асинхронных задач в планировщике.
        
        Args:
            task_func: Асинхронная функция для выполнения
        """
        try:
            self.logger.info("Выполняю запланированную задачу")
            await task_func()
            self.logger.info("Задача успешно выполнена")
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении задачи: {e}")
    
    async def start(self) -> None:
        """
        Запускает планировщик задач в асинхронном режиме.
        """
        self.logger.info("Запускаю планировщик задач")
        self.running = True
        
        while self.running:
            try:
                # Проверяем, нужно ли выполнить задачу на среду
                await self._check_wednesday_task()
                # Проверяем ежедневную задачу, если задана
                await self._check_daily_task()
                # Проверяем интервальную задачу, если задана
                await self._check_interval_task()
                
                # Ждем до следующей проверки
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                self.logger.info("Планировщик задач отменен")
                break
            except Exception as e:
                self.logger.error(f"Ошибка в планировщике: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_wednesday_task(self) -> None:
        """
        Проверяет, нужно ли выполнить задачу на среду.
        """
        now = datetime.now(self.tz)
        
        # Проверяем, что сегодня среда
        if now.weekday() == self.wednesday:
            # Проверяем, что есть запланированные времена
            if not self.send_times:
                onboarding_key = f"wednesday_executed_{now.strftime('%Y-%m-%d')}"
                if onboarding_key not in self.tasks.get('_executed', set()):
                    self.logger.warning("Не задано время отправки (SCHEDULER_SEND_TIMES пусто)")
                    if '_executed' not in self.tasks:
                        self.tasks['_executed'] = set()
                    self.tasks['_executed'].add(onboarding_key)
                return
            
            # Проверяем каждый временной слот
            executed = self.tasks.get('_executed', set())
            for time_str in self.send_times:
                key = f"wednesday_{now.strftime('%Y-%m-%d')}_{time_str}"
                
                # Пропускаем, если уже выполнено
                if key in executed:
                    continue
                
                # Проверяем, наступило ли время
                h, m = map(int, time_str.split(':'))
                target_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                
                # Выполняем, если текущее время >= целевого (с точностью до минуты)
                if now >= target_time:
                    # Выполняем задачу
                    if 'wednesday_frog' in self.tasks:
                        await self._run_async_task(self.tasks['wednesday_frog'])
                        if '_executed' not in self.tasks:
                            self.tasks['_executed'] = set()
                        self.tasks['_executed'].add(key)
                        self.logger.info(f"Задача на среду выполнена: {key}")

    async def _check_daily_task(self) -> None:
        """
        Проверяет, нужно ли выполнить ежедневную задачу.
        """
        daily = self.tasks.get('daily_task')
        if not isinstance(daily, dict):
            return
        now = datetime.now()
        last_run_date = daily.get('last_run_date')
        today_str = now.strftime('%Y-%m-%d')
        
        # Проверяем, если еще не запускалось сегодня
        if last_run_date != today_str:
            # Проверяем, наступило ли время
            h, m = map(int, daily['time_str'].split(':'))
            target_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            
            # Выполняем, если время наступило
            if now >= target_time:
                await self._run_async_task(daily['func'])
                daily['last_run_date'] = today_str
                self.logger.info(f"Ежедневная задача выполнена: {today_str}")

    async def _check_interval_task(self) -> None:
        """
        Проверяет, нужно ли выполнить интервальную задачу.
        """
        interval_meta = self.tasks.get('interval_task')
        if not isinstance(interval_meta, dict):
            return
        now = datetime.now()
        last_run = interval_meta.get('last_run')
        interval_minutes = interval_meta['interval_minutes']
        if last_run is None or (now - last_run).total_seconds() >= interval_minutes * 60:
            await self._run_async_task(interval_meta['func'])
            interval_meta['last_run'] = now
            self.logger.info("Интервальная задача выполнена")
    
    def stop(self) -> None:
        """
        Останавливает планировщик задач.
        """
        self.logger.info("Останавливаю планировщик задач")
        self.running = False
    
    def get_next_run(self) -> Optional[datetime]:
        """
        Возвращает время следующего запланированного выполнения.
        
        Returns:
            Время следующего выполнения задачи
        """
        now = datetime.now(self.tz)

        # вычислим список кандидатов времени запуска
        candidates: list[datetime] = []

        # Если сегодня среда — сначала проверяем ближайшие слоты сегодня, которые еще не прошли
        if now.weekday() == self.wednesday:
            for t in self.send_times:
                h, m = t.split(":")
                dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                if dt >= now:
                    # еще не наступившие слоты сегодня
                    candidates.append(dt)

        # Добавим слоты следующей среды
        days_ahead = (self.wednesday - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        base = (now + timedelta(days=days_ahead)).replace(second=0, microsecond=0)
        for t in self.send_times:
            h, m = t.split(":")
            candidates.append(base.replace(hour=int(h), minute=int(m)))

        return min(candidates) if candidates else None
    
    def clear_all_jobs(self) -> None:
        """
        Очищает все запланированные задачи.
        """
        self.logger.info("Очищаю все запланированные задачи")
        self.tasks.clear()
    
    def get_jobs_count(self) -> int:
        """
        Возвращает количество запланированных задач.
        
        Returns:
            Количество активных задач
        """
        return len([k for k in self.tasks.keys() if not k.startswith('_')])
