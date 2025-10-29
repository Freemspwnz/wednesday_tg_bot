"""
Сервис для генерации изображений жабы с помощью нейросети Kandinsky через Fusion Brain.
Обеспечивает взаимодействие с API Fusion Brain для создания изображений.
"""

import asyncio
import aiohttp
import random
import json
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image

from utils.logger import get_logger
from utils.config import config, ImageConfig

class ImageGenerator:
    """
    Класс для генерации изображений жабы с помощью Kandinsky API.
    
    Обеспечивает:
    - Асинхронную генерацию изображений
    - Обработку ошибок и повторные попытки
    - Сохранение изображений в память
    - Случайный выбор подписей
    """
    
    def __init__(self):
        """Инициализация генератора изображений."""
        import os
        self.logger = get_logger(__name__)
        self.api_key = config.kandinsky_api_key
        self.secret_key = config.kandinsky_secret_key
        self.base_url = "https://api-key.fusionbrain.ai"
        self.timeout = config.generation_timeout
        self.max_retries = config.max_retries
        
        # Circuit breaker для API
        self.circuit_breaker_failures = 0
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_cooldown = 300  # 5 минут
        self.circuit_breaker_open_until = None
        
        # Промпт для генерации жабы
        self.frog_prompt = ImageConfig.FROG_PROMPTS
        self.style = ImageConfig.STYLES
        
        # Размеры изображения
        self.width = ImageConfig.WIDTH
        self.height = ImageConfig.HEIGHT
        
        # Подписи для изображений
        self.captions = ImageConfig.CAPTIONS
        
        # Поддержка прокси
        self.proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        
        self.logger.info("Генератор изображений инициализирован")
    
    async def generate_frog_image(self, metrics=None) -> Optional[Tuple[bytes, str]]:
        """
        Генерирует изображение жабы с помощью Kandinsky API.
        
        Returns:
            Кортеж (изображение в байтах, случайная подпись) или None при ошибке
        """
        import time
        start_time = time.time()
        
        # Проверяем circuit breaker
        if self.circuit_breaker_open_until is not None:
            if time.time() < self.circuit_breaker_open_until:
                remaining = int(self.circuit_breaker_open_until - time.time())
                self.logger.warning(f"Circuit breaker открыт, API временно недоступен. Повтор через {remaining}с")
                if metrics:
                    metrics.increment_circuit_breaker_trip()
                return None
            else:
                self.logger.info("Circuit breaker восстановлен, пробуем снова")
                self.circuit_breaker_open_until = None
                self.circuit_breaker_failures = 0
        
        self.logger.info("Начинаю генерацию изображения жабы")
        
        # Выбираем случайную подпись
        caption = random.choice(self.captions)
        self.logger.info(f"Выбрана подпись: {caption}")
        
        # Выбираем случайный промпт и стиль для разнообразия
        frog_prompt = random.choice(ImageConfig.FROG_PROMPTS)
        style = random.choice(ImageConfig.STYLES)
        
        # Формируем полный промпт
        full_prompt = f"{frog_prompt}, {style}, high quality, detailed, Wednesday frog meme"
        self.logger.info(f"Промпт для генерации: {full_prompt}")
        
        # Пытаемся сгенерировать изображение с повторными попытками
        for attempt in range(self.max_retries):
            try:
                self.logger.info(f"Попытка генерации {attempt + 1}/{self.max_retries}")
                
                # Генерируем изображение
                image_data = await self._generate_image(full_prompt)
                
                if image_data:
                    self.logger.info("Изображение успешно сгенерировано")
                    elapsed = time.time() - start_time
                    if metrics:
                        metrics.increment_generation_success()
                        metrics.add_generation_time(elapsed)
                        if attempt > 0:
                            metrics.increment_generation_retry()
                    return image_data, caption
                else:
                    self.logger.warning(f"Попытка {attempt + 1} не удалась")
                    if metrics and attempt == 0:
                        metrics.increment_generation_retry()
                    
            except Exception as e:
                self.logger.error(f"Ошибка при генерации (попытка {attempt + 1}): {e}")
                self.circuit_breaker_failures += 1
                
                # Активируем circuit breaker при превышении порога
                if self.circuit_breaker_failures >= self.circuit_breaker_threshold:
                    import time
                    self.circuit_breaker_open_until = time.time() + self.circuit_breaker_cooldown
                    self.logger.error(f"Circuit breaker активирован на {self.circuit_breaker_cooldown}с из-за {self.circuit_breaker_failures} ошибок")
                    break
                
                # Если это не последняя попытка, ждем перед следующей
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
        
        elapsed = time.time() - start_time
        
        # Если не удалось сгенерировать
        if metrics:
            metrics.increment_generation_failed()
            metrics.add_generation_time(elapsed)
        
        self.logger.error("Все попытки генерации изображения исчерпаны")
        return None
    
    async def _generate_image(self, prompt: str) -> Optional[bytes]:
        """
        Выполняет запрос к API Fusion Brain для генерации изображения.
        
        Args:
            prompt: Текстовый промпт для генерации
            
        Returns:
            Изображение в байтах или None при ошибке
        """
        headers = {
            "X-Key": f"Key {self.api_key}",
            "X-Secret": f"Secret {self.secret_key}",
        }
        
        try:
            # Granular таймауты
            timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=10,
                sock_read=30
            )
            
            # Настройка connector с прокси если указан
            connector = None
            if self.proxy_url:
                connector = aiohttp.ProxyConnector.from_url(self.proxy_url)
                self.logger.info(f"Используется прокси: {self.proxy_url}")
            
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                # Получаем pipeline ID
                pipeline_id = await self._get_pipeline_id(session, headers)
                if not pipeline_id:
                    self.logger.error("Не удалось получить pipeline ID")
                    return None
                
                # Генерируем изображение
                uuid = await self._start_generation(session, headers, pipeline_id, prompt)
                if not uuid:
                    self.logger.error("Не удалось запустить генерацию")
                    return None
                
                # Ждем завершения генерации
                image_data = await self._wait_for_generation(session, headers, uuid)
                if image_data:
                    return image_data
                else:
                    self.logger.error("Не удалось получить результат генерации")
                    return None
                        
        except asyncio.TimeoutError:
            self.logger.error("Таймаут при генерации изображения")
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при запросе к API: {e}")
            return None
    
    async def _get_pipeline_id(self, session: aiohttp.ClientSession, headers: dict) -> Optional[str]:
        """
        Получает ID pipeline для генерации изображений.
        
        Args:
            session: Сессия aiohttp
            headers: Заголовки с ключами авторизации
            
        Returns:
            ID pipeline или None при ошибке
        """
        try:
            async with session.get(f"{self.base_url}/key/api/v1/pipelines", headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pipeline_id = data[0]['id']
                        self.logger.info(f"Получен pipeline ID: {pipeline_id}")
                        return pipeline_id
                    else:
                        self.logger.error("Пустой ответ при получении pipeline")
                        return None
                else:
                    self.logger.error(f"Ошибка при получении pipeline: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Ошибка при получении pipeline ID: {e}")
            return None
    
    async def _start_generation(self, session: aiohttp.ClientSession, headers: dict, 
                              pipeline_id: str, prompt: str) -> Optional[str]:
        """
        Запускает генерацию изображения.
        
        Args:
            session: Сессия aiohttp
            headers: Заголовки с ключами авторизации
            pipeline_id: ID pipeline
            prompt: Текстовый промпт
            
        Returns:
            UUID задачи генерации или None при ошибке
        """
        params = {
            "type": "GENERATE",
            "numImages": 1,
            "width": self.width,
            "height": self.height,
            "generateParams": {
                "query": prompt
            }
        }
        
        # Формируем multipart/form-data запрос
        form_data = aiohttp.FormData()
        form_data.add_field('pipeline_id', pipeline_id)
        form_data.add_field('params', json.dumps(params), content_type='application/json')
        
        try:
            async with session.post(f"{self.base_url}/key/api/v1/pipeline/run", 
                                  headers=headers, 
                                  data=form_data) as response:
                # API возвращает 201 (Created) при успешном создании задачи
                if response.status in (200, 201):
                    result = await response.json()
                    uuid = result.get('uuid')
                    if uuid:
                        self.logger.info(f"Запущена генерация с UUID: {uuid}")
                        return uuid
                    else:
                        self.logger.error("UUID не найден в ответе")
                        return None
                else:
                    self.logger.error(f"Ошибка при запуске генерации: {response.status}")
                    # Добавим больше информации об ошибке
                    error_text = await response.text()
                    self.logger.error(f"Текст ошибки: {error_text}")
                    return None
        except Exception as e:
            self.logger.error(f"Ошибка при запуске генерации: {e}")
            return None
    
    async def _wait_for_generation(self, session: aiohttp.ClientSession, headers: dict, 
                                  uuid: str) -> Optional[bytes]:
        """
        Ожидает завершения генерации и получает результат.
        
        Args:
            session: Сессия aiohttp
            headers: Заголовки с ключами авторизации
            uuid: UUID задачи генерации
            
        Returns:
            Изображение в байтах или None при ошибке
        """
        max_attempts = 10
        delay = 10
        
        for attempt in range(max_attempts):
            try:
                async with session.get(f"{self.base_url}/key/api/v1/pipeline/status/{uuid}", 
                                     headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        status = data.get('status')
                        
                        if status == 'DONE':
                            # Получаем изображение из результата
                            result = data.get('result', {})
                            files = result.get('files', [])
                            
                            if files and len(files) > 0:
                                # Декодируем Base64 изображение
                                image_base64 = files[0]
                                image_data = base64.b64decode(image_base64)
                                
                                # Проверяем, что это действительно изображение
                                try:
                                    Image.open(BytesIO(image_data))
                                    self.logger.info("Изображение успешно получено")
                                    return image_data
                                except Exception as e:
                                    self.logger.error(f"Ошибка при проверке изображения: {e}")
                                    return None
                            else:
                                self.logger.error("Файлы не найдены в результате")
                                return None
                                
                        elif status == 'FAIL':
                            error_desc = data.get('errorDescription', 'Неизвестная ошибка')
                            self.logger.error(f"Генерация завершилась с ошибкой: {error_desc}")
                            return None
                            
                        elif status in ['INITIAL', 'PROCESSING']:
                            self.logger.info(f"Генерация в процессе (попытка {attempt + 1}/{max_attempts})")
                            await asyncio.sleep(delay)
                            continue
                            
                        else:
                            self.logger.error(f"Неизвестный статус: {status}")
                            return None
                    else:
                        self.logger.error(f"Ошибка при проверке статуса: {response.status}")
                        return None
                        
            except Exception as e:
                self.logger.error(f"Ошибка при проверке статуса (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
        
        self.logger.error("Превышено максимальное количество попыток ожидания")
        return None
    
    def get_random_caption(self) -> str:
        """
        Возвращает случайную подпись для изображения.
        
        Returns:
            Случайная подпись из списка доступных
        """
        return random.choice(self.captions)

    def save_image_locally(self, image_data: bytes, folder: str = "data/frogs", prefix: str = "frog", max_files: int = 30) -> str:
        """
        Сохраняет байты изображения на диск.
        
        Args:
            image_data: Содержимое изображения в байтах
            folder: Папка для сохранения
            prefix: Префикс имени файла
        Returns:
            Путь к сохраненному файлу
        """
        try:
            path = Path(folder)
            path.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = path / f"{prefix}_{ts}.png"
            file_path.write_bytes(image_data)
            # Ограничим количество файлов в папке
            try:
                files = sorted([p for p in path.glob("*.png")], key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[max_files:]:
                    try:
                        old.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                pass
            return str(file_path)
        except Exception:
            return ""
