"""
Сервис для генерации изображений жабы с помощью нейросети Kandinsky через Fusion Brain.
Обеспечивает взаимодействие с API Fusion Brain для создания изображений.
"""

import asyncio
import base64
import json
import random
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import aiohttp

if TYPE_CHECKING:
    from aiohttp import ProxyConnector
    from aiohttp.connector import BaseConnector

    from utils.metrics import Metrics
else:
    BaseConnector = Any
    ProxyConnector = Any

from PIL import Image

from services.prompt_generator import GigaChatClient, PromptStorage
from services.rate_limiter import CircuitBreaker
from utils.config import ImageConfig, config
from utils.logger import get_logger, log_all_methods
from utils.paths import FROG_IMAGES_CONTAINER_PATH, FROG_IMAGES_DIR, resolve_frog_images_dir
from utils.prompts_store import PromptsStore

# Константы для магических чисел
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 300  # 5 минут
TIMEOUT_CHECK_TOTAL_SECONDS = 15  # Короткий таймаут для проверки
TIMEOUT_CHECK_CONNECT_SECONDS = 5
TIMEOUT_CHECK_SOCK_READ_SECONDS = 10
MAX_FILES_DEFAULT = 30
HTTP_STATUS_OK = 200
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_FORBIDDEN = 403


@log_all_methods()
class ImageGenerator:
    """
    Класс для генерации изображений жабы с помощью Kandinsky API.

    Обеспечивает:
    - Асинхронную генерацию изображений
    - Обработку ошибок и повторные попытки
    - Сохранение изображений в память
    - Случайный выбор подписей
    """

    def __init__(self) -> None:
        """Инициализация генератора изображений."""
        import os

        self.logger = get_logger(__name__)
        self.api_key: str | None = config.kandinsky_api_key
        self.secret_key: str | None = config.kandinsky_secret_key
        self.base_url: str = "https://api-key.fusionbrain.ai"
        self.timeout: int = config.generation_timeout
        self.max_retries: int = config.max_retries

        # Circuit breaker для API.
        # Исторически счётчики хранились в памяти, что сбрасывало состояние при рестарте.
        # Теперь используем Redis‑базированный CircuitBreaker, чтобы:
        # - разделять счётчики между воркерами/процессами;
        # - сохранять окно ошибок даже при перезапуске приложения.
        #
        # Локальные поля оставлены только для обратной совместимости логов
        # и могут быть удалены в будущих версиях.
        self.circuit_breaker_failures: int = 0
        self.circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD
        self.circuit_breaker_cooldown: int = CIRCUIT_BREAKER_COOLDOWN_SECONDS
        self.circuit_breaker_open_until: float | None = None
        self._circuit_breaker = CircuitBreaker(
            key="cb:kandinsky_api",
            threshold=CIRCUIT_BREAKER_THRESHOLD,
            window=CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        )

        # Промпт для генерации жабы (fallback)
        self.frog_prompt: list[str] = ImageConfig.FROG_PROMPTS
        self.style: list[str] = ImageConfig.STYLES

        # Размеры изображения
        self.width: int = ImageConfig.WIDTH
        self.height: int = ImageConfig.HEIGHT

        # Подписи для изображений
        self.captions: list[str] = ImageConfig.CAPTIONS

        # Поддержка прокси
        self.proxy_url: str | None = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

        # Инициализация GigaChat клиента для генерации промптов
        self.gigachat_enabled: bool = False
        self.gigachat_client: GigaChatClient | None = None
        # Файловое хранилище промптов:
        # - исторический fallback, использовался до появления Postgres‑хранилища;
        # - сейчас основной источник истины для промптов — таблица `prompts`,
        #   а файлы используются только как дополнительный backup.
        self.prompt_storage: PromptStorage = PromptStorage()
        if config.gigachat_authorization_key:
            try:
                self.gigachat_client = GigaChatClient()
                # Проверяем подключение
                if self.gigachat_client.test_connection():
                    self.gigachat_enabled = True
                    self.logger.info(
                        "GigaChat клиент успешно инициализирован. Промпты будут генерироваться через GigaChat.",
                    )
                else:
                    self.logger.warning(
                        "Не удалось подключиться к GigaChat. Будет использоваться fallback на статические промпты.",
                    )
            except Exception as e:
                self.logger.warning(
                    f"Ошибка инициализации GigaChat клиента: {e}. "
                    "Будет использоваться fallback на статические промпты.",
                )
        else:
            self.logger.info(
                "GIGACHAT_AUTHORIZATION_KEY не установлен. Будет использоваться fallback на статические промпты.",
            )

        self.logger.info("Генератор изображений инициализирован")

    def _get_auth_headers(self) -> dict[str, str]:
        """
        Получает заголовки авторизации с проверкой ключей.

        Returns:
            Словарь с заголовками авторизации

        Raises:
            ValueError: Если ключи не установлены
        """
        api_key: str = self.api_key or ""
        secret_key: str = self.secret_key or ""
        if not api_key or not secret_key:
            raise ValueError("API ключи Kandinsky не установлены")
        return {
            "X-Key": f"Key {api_key}",
            "X-Secret": f"Secret {secret_key}",
        }

    async def generate_frog_image(self, metrics: Optional["Metrics"] = None) -> tuple[bytes, str] | None:
        """
        Генерирует изображение жабы с помощью Kandinsky API.

        Returns:
            Кортеж (изображение в байтах, случайная подпись) или None при ошибке
        """
        import time

        start_time = time.time()

        # Проверяем circuit breaker (Redis‑базированный).
        try:
            if await self._circuit_breaker.is_open():
                remaining = self.circuit_breaker_cooldown
                self.logger.warning(
                    "Circuit breaker для Kandinsky уже открыт (Redis). "
                    f"Запрос к API пропущен до окончания окна cooldown ({remaining} c)",
                )
                if metrics:
                    try:
                        await metrics.increment_circuit_breaker_trip()
                    except Exception as exc:
                        self.logger.warning(f"Не удалось обновить метрики circuit breaker: {exc}")
                return None
        except Exception as cb_err:
            # В случае проблем с Redis не блокируем генерацию — работаем как раньше.
            self.logger.warning(
                f"Не удалось проверить состояние circuit breaker в Redis, продолжаем генерацию: {cb_err!s}",
            )

        self.logger.info("Начинаю генерацию изображения жабы")

        # Выбираем случайную подпись
        caption = random.choice(self.captions)
        self.logger.info(f"Выбрана подпись: {caption}")

        # Генерируем промпт через GigaChat или используем fallback
        full_prompt = await self._generate_prompt()
        if not full_prompt:
            self.logger.warning("Не удалось сгенерировать промпт, используем fallback")
            full_prompt = ImageGenerator._get_fallback_prompt()

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
                        try:
                            await metrics.increment_generation_success()
                            await metrics.add_generation_time(elapsed)
                            if attempt > 0:
                                await metrics.increment_generation_retry()
                        except Exception as exc:
                            self.logger.warning(f"Не удалось обновить метрики успешной генерации: {exc}")
                    return image_data, caption
                else:
                    self.logger.warning(f"Попытка {attempt + 1} не удалась")
                    if metrics and attempt == 0:
                        try:
                            await metrics.increment_generation_retry()
                        except Exception as exc:
                            self.logger.warning(f"Не удалось обновить метрики retry генерации: {exc}")

            except Exception as e:
                self.logger.error(f"Ошибка при генерации (попытка {attempt + 1}): {e}")
                self.circuit_breaker_failures += 1
                try:
                    await self._circuit_breaker.record_failure()
                except Exception as cb_rec_err:
                    self.logger.warning(
                        f"Не удалось записать ошибку в Redis‑based circuit breaker: {cb_rec_err!s}",
                    )

                # Если это не последняя попытка, ждем перед следующей
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2**attempt)  # Экспоненциальная задержка

        elapsed = time.time() - start_time

        # Если не удалось сгенерировать
        if metrics:
            try:
                await metrics.increment_generation_failed()
                await metrics.add_generation_time(elapsed)
            except Exception as exc:
                self.logger.warning(f"Не удалось обновить метрики неуспешной генерации: {exc}")

        self.logger.error("Все попытки генерации изображения исчерпаны")
        return None

    async def _generate_image(self, prompt: str) -> bytes | None:
        """
        Выполняет запрос к API Fusion Brain для генерации изображения.

        Args:
            prompt: Текстовый промпт для генерации

        Returns:
            Изображение в байтах или None при ошибке
        """
        try:
            headers = self._get_auth_headers()
            # Granular таймауты
            timeout = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=10,
                sock_read=30,
            )

            # Настройка connector с прокси если указан
            connector: BaseConnector | None = None
            if self.proxy_url:
                # aiohttp.ProxyConnector.from_url возвращает ProxyConnector, который является подтипом BaseConnector
                connector = aiohttp.ProxyConnector.from_url(self.proxy_url)  # type: ignore[attr-defined]
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

        except TimeoutError:
            self.logger.error("Таймаут при генерации изображения")
            return None
        except aiohttp.ClientConnectorError as e:
            self.logger.error(
                f"Ошибка подключения к Kandinsky API: {e}. "
                "Возможные причины: проблемы с сетью, недоступность сервера, "
                "проблемы с прокси.",
            )
            return None
        except aiohttp.ClientError as e:
            self.logger.error(f"Ошибка клиента при запросе к Kandinsky API: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при запросе к Kandinsky API: {e}", exc_info=True)
            return None

    async def check_api_status(
        self,
        save_models: bool = True,
    ) -> tuple[bool, str, list[str], tuple[str | None, str | None]]:
        """
        Проверяет статус API и валидность ключа без генерации изображения (dry-run).

        Returns:
            Кортеж (успех_проверки, сообщение_о_статусе, список_моделей, (текущий_pipeline_id, текущее_имя))
        """
        self.logger.debug(f"Начало проверки статуса Kandinsky (save_models={save_models})")
        try:
            headers = self._get_auth_headers()
            timeout = aiohttp.ClientTimeout(
                total=TIMEOUT_CHECK_TOTAL_SECONDS,
                connect=TIMEOUT_CHECK_CONNECT_SECONDS,
                sock_read=TIMEOUT_CHECK_SOCK_READ_SECONDS,
            )

            connector: BaseConnector | None = None
            if self.proxy_url:
                connector = aiohttp.ProxyConnector.from_url(self.proxy_url)  # type: ignore[attr-defined]

            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                # Проверка статуса ключа через эндпоинт pipelines (более надежный способ)
                status_ok = False
                status_message = "❌ Ошибка проверки"

                # Получаем список моделей (pipelines) и одновременно проверяем доступность API
                models_list: list[str] = []
                current_pipeline_id: str | None = None
                current_pipeline_name: str | None = None
                try:
                    from utils.models_store import ModelsStore

                    models_store = ModelsStore()
                    current_pipeline_id, current_pipeline_name = await models_store.get_kandinsky_model()
                    self.logger.debug("Выполняю запрос списка pipelines для dry-run статуса")
                    async with session.get(f"{self.base_url}/key/api/v1/pipelines", headers=headers) as response:
                        if response.status == HTTP_STATUS_OK:
                            status_ok = True
                            status_message = "✅ API доступен, ключ валиден"
                            pipelines_data = await response.json()
                            if isinstance(pipelines_data, list) and len(pipelines_data) > 0:
                                # Сохраняем список моделей в хранилище
                                if save_models:
                                    await models_store.set_kandinsky_available_models(pipelines_data)
                                    self.logger.debug(
                                        f"Сохранен список из {len(pipelines_data)} моделей Kandinsky",
                                    )

                                for pipeline in pipelines_data:
                                    model_name: str = str(pipeline.get("name", "Unknown"))
                                    model_id: str = str(pipeline.get("id", "N/A"))
                                    is_current = (
                                        " ⭐" if (current_pipeline_id and model_id == current_pipeline_id) else ""
                                    )
                                    models_list.append(f"{model_name} (ID: {model_id}){is_current}")
                            else:
                                models_list = ["Модели не найдены"]
                        elif response.status == HTTP_STATUS_UNAUTHORIZED:
                            status_message = "❌ Неверный API ключ или секретный ключ"
                            status_ok = False
                            models_list = ["Требуется проверка авторизации"]
                        elif response.status == HTTP_STATUS_FORBIDDEN:
                            status_message = "❌ Доступ запрещен (проверьте права ключа)"
                            status_ok = False
                            models_list = ["Нет доступа к моделям"]
                        else:
                            status_message = f"⚠️  Ошибка API: {response.status}"
                            status_ok = False
                            models_list = [f"Ошибка получения моделей: {response.status}"]
                except TimeoutError:
                    status_message = "❌ Таймаут при проверке API"
                    status_ok = False
                    models_list = ["Таймаут при запросе"]
                except Exception as e:
                    status_message = f"❌ Ошибка проверки: {str(e)[:50]}"
                    status_ok = False
                    models_list = [f"Ошибка: {str(e)[:50]}"]

                self.logger.debug(
                    f"Завершена проверка статуса Kandinsky: "
                    f"ok={status_ok}, models={len(models_list)}, "
                    f"current=({current_pipeline_id}, {current_pipeline_name})",
                )
                return status_ok, status_message, models_list, (current_pipeline_id, current_pipeline_name)

        except TimeoutError:
            return False, "❌ Таймаут при подключении к API", [], (None, None)
        except Exception as e:
            return False, f"❌ Ошибка подключения: {str(e)[:50]}", [], (None, None)

    async def _get_pipeline_id(self, session: aiohttp.ClientSession, headers: dict[str, str]) -> str | None:
        """
        Получает ID pipeline для генерации изображений.
        Использует сохраненную модель, если она есть, иначе выбирает первую доступную.

        Args:
            session: Сессия aiohttp
            headers: Заголовки с ключами авторизации

        Returns:
            ID pipeline или None при ошибке
        """
        from utils.models_store import ModelsStore

        models_store = ModelsStore()
        saved_pipeline_id: str | None
        saved_pipeline_name: str | None
        saved_pipeline_id, saved_pipeline_name = await models_store.get_kandinsky_model()

        try:
            async with session.get(f"{self.base_url}/key/api/v1/pipelines", headers=headers) as response:
                if response.status == HTTP_STATUS_OK:
                    data = await response.json()
                    if data and len(data) > 0:
                        # Если есть сохраненная модель, ищем её в списке
                        if saved_pipeline_id:
                            for pipeline in data:
                                if pipeline.get("id") == saved_pipeline_id:
                                    self.logger.info(
                                        f"Используется сохраненная модель: {saved_pipeline_name or saved_pipeline_id}",
                                    )
                                    return saved_pipeline_id
                            # Если сохраненная модель не найдена, используем первую доступную
                            self.logger.warning(
                                f"Сохраненная модель {saved_pipeline_id} не найдена. Используется первая доступная.",
                            )

                        # Используем первую доступную модель
                        pipeline_id_raw: str | None = data[0].get("id")
                        pipeline_name_raw: str | None = data[0].get("name", "Unknown")
                        pipeline_id: str = str(pipeline_id_raw) if pipeline_id_raw is not None else ""
                        pipeline_name: str = str(pipeline_name_raw)
                        # Сохраняем выбранную модель
                        await models_store.set_kandinsky_model(pipeline_id, pipeline_name)
                        self.logger.info(f"Получен pipeline ID: {pipeline_id} ({pipeline_name})")
                        return pipeline_id
                    else:
                        self.logger.error("Пустой ответ при получении pipeline")
                        return None
                else:
                    self.logger.error(f"Ошибка при получении pipeline: {response.status}")
                    return None
        except aiohttp.ClientConnectorError as e:
            self.logger.error(
                f"Ошибка подключения к Kandinsky API при получении pipeline ID: {e}. "
                "Возможные причины: проблемы с сетью, недоступность сервера, "
                "проблемы с прокси.",
            )
            return None
        except aiohttp.ClientError as e:
            self.logger.error(f"Ошибка клиента при получении pipeline ID: {e}")
            return None
        except TimeoutError:
            self.logger.error("Таймаут при получении pipeline ID")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении pipeline ID: {e}", exc_info=True)
            return None

    async def set_kandinsky_model(self, model_identifier: str) -> tuple[bool, str]:
        """
        Устанавливает модель Kandinsky по ID или названию.

        Args:
            model_identifier: ID pipeline или название модели (или часть названия)

        Returns:
            Кортеж (успех, сообщение)
        """
        try:
            headers = self._get_auth_headers()
            timeout = aiohttp.ClientTimeout(
                total=TIMEOUT_CHECK_TOTAL_SECONDS,
                connect=TIMEOUT_CHECK_CONNECT_SECONDS,
                sock_read=TIMEOUT_CHECK_SOCK_READ_SECONDS,
            )

            connector: BaseConnector | None = None
            if self.proxy_url:
                connector = aiohttp.ProxyConnector.from_url(self.proxy_url)  # type: ignore[attr-defined]

            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(f"{self.base_url}/key/api/v1/pipelines", headers=headers) as response:
                    if response.status == HTTP_STATUS_OK:
                        pipelines_data = await response.json()
                        if isinstance(pipelines_data, list):
                            # Сначала пытаемся найти по точному совпадению ID
                            for pipeline_item in pipelines_data:
                                if pipeline_item.get("id") == model_identifier:
                                    matched_model_name: str = str(pipeline_item.get("name", "Unknown"))
                                    matched_pipeline_id: str = str(pipeline_item.get("id", ""))
                                    from utils.models_store import ModelsStore

                                    models_store = ModelsStore()
                                    await models_store.set_kandinsky_model(
                                        matched_pipeline_id,
                                        matched_model_name,
                                    )
                                    self.logger.info(
                                        f"Модель Kandinsky установлена: {matched_model_name} "
                                        f"(ID: {matched_pipeline_id})",
                                    )
                                    return True, f"Модель установлена: {matched_model_name} (ID: {matched_pipeline_id})"

                            # Если не найдено по ID, ищем по названию (регистронезависимо, частичное совпадение)
                            model_identifier_lower = model_identifier.lower()
                            matches = []
                            for pipeline_item in pipelines_data:
                                pipeline_name = pipeline_item.get("name", "")
                                if model_identifier_lower in pipeline_name.lower():
                                    matches.append(pipeline_item)

                            if len(matches) == 1:
                                # Одно совпадение - используем его
                                matched_pipeline = matches[0]
                                selected_model_name: str = str(matched_pipeline.get("name", "Unknown"))
                                selected_pipeline_id: str = str(matched_pipeline.get("id", ""))
                                from utils.models_store import ModelsStore

                                models_store = ModelsStore()
                                await models_store.set_kandinsky_model(
                                    selected_pipeline_id,
                                    selected_model_name,
                                )
                                self.logger.info(
                                    f"Модель Kandinsky установлена: {selected_model_name} (ID: {selected_pipeline_id})",
                                )
                                return True, (f"Модель установлена: {selected_model_name} (ID: {selected_pipeline_id})")
                            elif len(matches) > 1:
                                # Несколько совпадений - показываем список
                                models_list: list[str] = [
                                    f"{p.get('name', 'Unknown')!s} (ID: {p.get('id', 'N/A')!s})" for p in matches
                                ]
                                return False, (
                                    "Найдено несколько моделей:\n"
                                    + "\n".join(models_list)
                                    + "\n\nУточните название или используйте ID"
                                )
                            else:
                                return False, (
                                    f"Модель '{model_identifier}' не найдена. "
                                    "Используйте /status для просмотра доступных моделей."
                                )
                        else:
                            return False, "Не удалось получить список моделей"
                    else:
                        return False, f"Ошибка API: {response.status}"
        except Exception as e:
            self.logger.error(f"Ошибка при установке модели Kandinsky: {e}")
            return False, f"Ошибка: {str(e)[:50]}"

    async def _start_generation(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        pipeline_id: str,
        prompt: str,
    ) -> str | None:
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
                "query": prompt,
            },
        }

        # Формируем multipart/form-data запрос
        form_data = aiohttp.FormData()
        form_data.add_field("pipeline_id", pipeline_id)
        form_data.add_field("params", json.dumps(params), content_type="application/json")

        try:
            async with session.post(
                f"{self.base_url}/key/api/v1/pipeline/run",
                headers=headers,
                data=form_data,
            ) as response:
                # API возвращает 201 (Created) при успешном создании задачи
                if response.status in {200, 201}:
                    result = await response.json()
                    uuid_value = result.get("uuid")
                    if uuid_value:
                        uuid_str: str = str(uuid_value)
                        self.logger.info(f"Запущена генерация с UUID: {uuid_str}")
                        return uuid_str
                    else:
                        self.logger.error("UUID не найден в ответе")
                        return None
                else:
                    self.logger.error(f"Ошибка при запуске генерации: {response.status}")
                    # Добавим больше информации об ошибке
                    error_text = await response.text()
                    self.logger.error(f"Текст ошибки: {error_text}")
                    return None
        except aiohttp.ClientConnectorError as e:
            self.logger.error(
                f"Ошибка подключения к Kandinsky API при запуске генерации: {e}. "
                "Возможные причины: проблемы с сетью, недоступность сервера, "
                "проблемы с прокси.",
            )
            return None
        except aiohttp.ClientError as e:
            self.logger.error(f"Ошибка клиента при запуске генерации: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при запуске генерации: {e}", exc_info=True)
            return None

    async def _wait_for_generation(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        uuid: str,
    ) -> bytes | None:
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
                async with session.get(
                    f"{self.base_url}/key/api/v1/pipeline/status/{uuid}",
                    headers=headers,
                ) as response:
                    if response.status == HTTP_STATUS_OK:
                        data = await response.json()
                        status = data.get("status")

                        if status == "DONE":
                            # Получаем изображение из результата
                            result = data.get("result", {})
                            files = result.get("files", [])

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

                        elif status == "FAIL":
                            error_desc = data.get("errorDescription", "Неизвестная ошибка")
                            self.logger.error(f"Генерация завершилась с ошибкой: {error_desc}")
                            return None

                        elif status in {"INITIAL", "PROCESSING"}:
                            self.logger.info(f"Генерация в процессе (попытка {attempt + 1}/{max_attempts})")
                            await asyncio.sleep(delay)
                            continue

                        else:
                            self.logger.error(f"Неизвестный статус: {status}")
                            return None
                    else:
                        self.logger.error(f"Ошибка при проверке статуса: {response.status}")
                        return None

            except aiohttp.ClientConnectorError as e:
                self.logger.error(
                    f"Ошибка подключения к Kandinsky API при проверке статуса (попытка {attempt + 1}): {e}",
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None
            except aiohttp.ClientError as e:
                self.logger.error(f"Ошибка клиента при проверке статуса (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None
            except TimeoutError:
                self.logger.warning(f"Таймаут при проверке статуса (попытка {attempt + 1})")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None
            except Exception as e:
                self.logger.error(f"Неожиданная ошибка при проверке статуса (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None

        self.logger.error(f"Превышено максимальное количество попыток проверки статуса генерации ({max_attempts})")
        return None

    async def _generate_prompt(self) -> str | None:
        """
        Генерирует промпт для Kandinsky через GigaChat или использует fallback.

        Порядок:
        1. Попытка получить промпт из GigaChat.
        2. При любой ошибке GigaChat — берём случайный промпт из таблицы `prompts`.
        3. Если в БД нет данных — используем файловый fallback из `data/prompts/`.
        4. Если и файлов нет — вызывающий код использует статический fallback.

        При любом успешно выбранном промпте он регистрируется в таблице `prompts`
        (raw + normalized + hash), чтобы БД оставалась каноническим источником метаданных.
        """
        prompts_store = PromptsStore()
        prompt: str | None = None

        # 1. Пытаемся сгенерировать промпт через GigaChat.
        if self.gigachat_enabled and self.gigachat_client:
            try:
                candidate = self.gigachat_client.generate_prompt_for_kandinsky()
                if candidate:
                    prompt = candidate
                else:
                    self.logger.warning(
                        "GigaChat вернул пустой промпт, пробуем использовать сохранённые промпты из БД",
                    )
            except Exception as e:
                # Любая ошибка GigaChat переводит нас на fallback.
                self.logger.error(
                    f"Ошибка при генерации промпта через GigaChat, используем fallback: {e}",
                    exc_info=True,
                )

        # 2. Fallback на сохранённые в БД промпты.
        if prompt is None:
            try:
                random_record = await prompts_store.get_random_prompt()
            except Exception as e:
                self.logger.error(
                    f"Ошибка при получении fallback-промпта из БД: {e}",
                    exc_info=True,
                )
                random_record = None

            if random_record is not None:
                self.logger.info(
                    "Используем fallback-промпт из таблицы prompts "
                    f"(id={random_record.id}, hash={random_record.prompt_hash})",
                )
                prompt = random_record.raw_text

        # 3. Файловый fallback: историческое хранилище `data/prompts/`.
        if prompt is None:
            try:
                file_prompt = self.prompt_storage.get_random_prompt()
            except Exception as e:  # на всякий случай не ломаем основную логику
                self.logger.error(
                    f"Ошибка при получении fallback-промпта из файлового хранилища: {e}",
                    exc_info=True,
                )
                file_prompt = None

            if file_prompt:
                self.logger.info("Используем fallback-промпт из сохранённых файлов data/prompts")
                prompt = file_prompt

        # 4. Если даже файлового fallback-а нет — вызывающий код перейдёт к статическому промпту.
        if prompt is None:
            self.logger.warning(
                "Fallback-промпт недоступен (ни БД, ни файлы). Будет использован статический fallback-промпт.",
            )
            return None

        # Регистрируем выбранный промпт в таблице `prompts`
        # (алгоритм нормализации и hash реализован в репозитории).
        try:
            record = await prompts_store.get_or_create_prompt(prompt)
            self.logger.info(
                f"Prompt registered in DB for generation: id={record.id}, hash={record.prompt_hash}",
            )
        except Exception as e:  # pragma: no cover - защитный фоллбек
            self.logger.error(f"Не удалось сохранить промпт в таблице prompts: {e}", exc_info=True)

        return prompt

    @staticmethod
    def _get_fallback_prompt() -> str:
        """
        Возвращает промпт из статического списка (fallback).

        Returns:
            Промпт для генерации изображения
        """
        # Выбираем случайный промпт и стиль для разнообразия
        frog_prompt = random.choice(ImageConfig.FROG_PROMPTS)
        style = random.choice(ImageConfig.STYLES)

        # Формируем полный промпт
        return f"{frog_prompt}, {style}, high quality, detailed, Wednesday frog meme"

    def get_random_caption(self) -> str:
        """
        Возвращает случайную подпись для изображения.

        Returns:
            Случайная подпись из списка доступных
        """
        return random.choice(self.captions)

    def save_image_locally(
        self,
        image_data: bytes,
        folder: str = FROG_IMAGES_DIR,
        prefix: str = "frog",
        max_files: int = MAX_FILES_DEFAULT,
    ) -> str:
        """
        # ВАЖНО: по умолчанию используем относительный путь `data/frogs`.
        # Внутри Docker-контейнера при WORKDIR=/app это соответствует
        # абсолютному пути /app/data/frogs, который примонтирован как volume.
        Сохраняет байты изображения на диск.
        При достижении лимита max_files удаляет самые старые файлы.

        Args:
            image_data: Содержимое изображения в байтах
            folder: Папка для сохранения
            prefix: Префикс имени файла
            max_files: Максимальное количество файлов в папке (по умолчанию 30)
        Returns:
            Путь к сохраненному файлу или пустая строка при ошибке
        """
        try:
            # Разрешаем путь через единый helper, чтобы обеспечить единообразное
            # поведение в контейнере и при локальном запуске.
            path = resolve_frog_images_dir() if folder == FROG_IMAGES_DIR else Path(folder)
            path.mkdir(parents=True, exist_ok=True)

            # Сохраняем новый файл
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = path / f"{prefix}_{ts}.png"
            file_path.write_bytes(image_data)
            # Логируем как реальный путь на файловой системе, так и ожидаемый
            # путь внутри контейнера (/app/data/frogs/...), чтобы было понятно,
            # что файл попадает в Docker volume.
            self.logger.info(
                f"Изображение сохранено: {file_path} "
                f"(контейнерный путь: {FROG_IMAGES_CONTAINER_PATH}/{file_path.name})",
            )

            # Ограничим количество файлов в папке
            # Получаем все PNG файлы и сортируем по времени модификации (новейшие первые)
            try:
                all_files = list(path.glob("*.png"))

                if len(all_files) > max_files:
                    # Сортируем по времени модификации: новейшие файлы первыми
                    files_sorted = sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True)

                    # Удаляем самые старые файлы (начиная с индекса max_files)
                    files_to_delete = files_sorted[max_files:]
                    deleted_count = 0

                    for old_file in files_to_delete:
                        try:
                            # Не удаляем только что сохраненный файл (на всякий случай)
                            if old_file != file_path:
                                old_file.unlink(missing_ok=True)
                                deleted_count += 1
                                self.logger.debug(f"Удален старый файл: {old_file.name}")
                        except Exception as e:
                            self.logger.warning(f"Не удалось удалить файл {old_file.name}: {e}")

                    if deleted_count > 0:
                        self.logger.info(
                            f"Удалено {deleted_count} старых файлов. "
                            f"Всего файлов: {len(all_files) - deleted_count} (лимит: {max_files})",
                        )
                    else:
                        self.logger.warning(f"Достигнут лимит файлов ({max_files}), но не удалось удалить старые")
                else:
                    self.logger.debug(f"Всего файлов в папке: {len(all_files)} (лимит: {max_files})")

            except Exception as e:
                self.logger.error(f"Ошибка при ограничении количества файлов в {path}: {e}")
                # Продолжаем работу, даже если не удалось очистить старые файлы

            return str(file_path)
        except Exception as e:
            self.logger.error(
                (
                    f"Ошибка при сохранении изображения в директорию {folder} "
                    f"(контейнерный путь: {FROG_IMAGES_CONTAINER_PATH}): {e}"
                ),
            )
            return ""

    def get_random_saved_image(self, folder: str = FROG_IMAGES_DIR) -> tuple[bytes, str] | None:
        """
        Получает случайное изображение из сохраненных файлов.

        Args:
            folder: Папка с сохраненными изображениями

        Returns:
            Кортеж (изображение в байтах, случайная подпись) или None если нет сохраненных изображений
        """
        try:
            path = resolve_frog_images_dir() if folder == FROG_IMAGES_DIR else Path(folder)
            if not path.exists():
                self.logger.warning(
                    f"Папка с сохранёнными изображениями не существует: {path} "
                    f"(контейнерный путь: {FROG_IMAGES_CONTAINER_PATH})",
                )
                return None

            # Получаем все PNG файлы
            image_files = list(path.glob("*.png"))
            if not image_files:
                self.logger.warning(
                    f"Нет сохраненных изображений в папке {path} (контейнерный путь: {FROG_IMAGES_CONTAINER_PATH})",
                )
                return None

            # Выбираем случайный файл
            random_file = random.choice(image_files)

            # Читаем файл
            image_data = random_file.read_bytes()

            # Выбираем случайную подпись
            caption = self.get_random_caption()

            self.logger.info(
                f"Загружено случайное изображение: {random_file} "
                f"(контейнерный путь: {FROG_IMAGES_CONTAINER_PATH}/{random_file.name})",
            )
            return image_data, caption

        except Exception as e:
            self.logger.error(
                (
                    f"Ошибка при получении случайного изображения из {folder} "
                    f"(контейнерный путь: {FROG_IMAGES_CONTAINER_PATH}): {e}"
                ),
            )
            return None
