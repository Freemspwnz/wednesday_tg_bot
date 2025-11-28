"""
Клиент и инфраструктура для работы с GigaChat-промптами.

Модуль отвечает за:
- вызовы GigaChat API;
- генерацию промптов для Kandinsky;
- сохранение всех удачно сгенерированных промптов в `data/prompts/`;
- подготовку структуры для будущих A/B-тестов разных вариантов промптов.
"""

import random
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from utils.config import config
from utils.logger import get_logger, log_all_methods

# Константы для магических чисел
TIMEOUT_TOKEN_SECONDS = 60  # Увеличен с 30 до 60 секунд
TOKEN_EXPIRY_BUFFER_SECONDS = 300  # Запас времени (5 минут)
DEFAULT_EXPIRES_IN_SECONDS = 1800
TIMEOUT_PROMPT_SECONDS = 60
TIMEOUT_PROMPT_LONG_SECONDS = 120
MAX_TOKENS_DEFAULT = 300
HTTP_STATUS_OK = 200
MAX_ERROR_TEXT_LENGTH = 100

# Директория, где храним все сгенерированные промпты GigaChat.
# Выделена в константу, чтобы при A/B-тестах было проще управлять источниками/вариантами промптов.
PROMPTS_DIR = Path("data") / "prompts"


class PromptStorage:
    """
    Простое файловое хранилище промптов.

    Вынесено в отдельный класс, чтобы:
    - централизовать работу с `data/prompts/`;
    - упростить повторное использование (генератор изображений, доп. сервисы);
    - подготовить почву для A/B-тестов (разные источники/варианты промптов по полю `source`).
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self.base_dir: Path = PROMPTS_DIR
        # Создаём директорию один раз при инициализации, чтобы не требовать ручного создания.
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_prompt(self, prompt: str, source: str = "gigachat") -> str | None:
        """
        Сохраняет промпт в файл в папке `data/prompts/`.

        Args:
            prompt: текст промпта
            source: логическое имя источника/варианта (для A/B-тестов)

        Returns:
            Путь к сохранённому файлу или None при ошибке.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{source}_prompt_{ts}.txt"
        file_path = self.base_dir / filename

        try:
            file_path.write_text(prompt, encoding="utf-8")
            self.logger.info(f"Промпт сохранён в файл: {file_path}")
            return str(file_path)
        except Exception as e:
            # Ошибка сохранения не должна ломать генерацию промпта — только логируем.
            self.logger.error(f"Ошибка при сохранении промпта в файл {file_path}: {e}", exc_info=True)
            return None

    def get_random_prompt(self) -> str | None:
        """
        Возвращает случайный промпт из сохранённых файлов.

        Используется другими сервисами как файловый fallback при сбоях GigaChat.
        """
        try:
            # Повторно гарантируем наличие папки на случай, если её удалили между запусками.
            self.base_dir.mkdir(parents=True, exist_ok=True)
            prompt_files = list(self.base_dir.glob("*.txt"))
            if not prompt_files:
                self.logger.debug(f"В папке {self.base_dir} нет сохранённых промптов для fallback")
                return None

            random_file = random.choice(prompt_files)
            content = random_file.read_text(encoding="utf-8").strip()
            if not content:
                self.logger.warning(f"Файл промпта {random_file} пуст, пропускаем")
                return None

            self.logger.info(f"Выбран fallback-промпт из файла: {random_file}")
            return content
        except Exception as e:
            self.logger.error(f"Ошибка при чтении fallback-промпта из файлов: {e}", exc_info=True)
            return None


@log_all_methods()
class GigaChatClient:
    """
    Клиент для взаимодействия с GigaChat API.
    Обеспечивает получение токенов и генерацию промптов.
    """

    def __init__(self) -> None:
        """Инициализация клиента GigaChat."""
        self.logger = get_logger(__name__)
        self.session: requests.Session = requests.Session()
        # Отдельное хранилище промптов, чтобы сохранять все успешные ответы GigaChat.
        self._prompt_storage = PromptStorage()

        # Настройка проверки SSL сертификата
        # Приоритет: путь к сертификату > флаг verify_ssl
        verify_ssl: bool | str = config.gigachat_verify_ssl
        # requests.Session.verify может быть bool или str (путь к сертификату)
        self.session.verify = verify_ssl
        self.session.trust_env = False

        if verify_ssl is False:
            # Отключена проверка SSL
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.logger.warning("⚠️ Проверка SSL сертификатов для GigaChat отключена! Это снижает безопасность.")
        elif isinstance(verify_ssl, str):
            # Указан путь к сертификату
            cert_path = Path(verify_ssl)
            if cert_path.exists():
                self.logger.info(f"✅ Используется сертификат для GigaChat: {verify_ssl}")
            else:
                self.logger.warning(f"⚠️ Файл сертификата не найден: {verify_ssl}. Проверка SSL может не работать.")

        self.access_token: str | None = None
        self.token_expiry_time: float | None = None

        # Получаем конфигурацию из config
        self.auth_url: str = config.gigachat_auth_url
        self.api_url: str = config.gigachat_api_url
        self.authorization_key: str = config.gigachat_authorization_key
        self.scope: str = config.gigachat_scope
        # Загружаем текущую модель из хранилища или используем из конфига
        from utils.models_store import ModelsStore

        # В синхронном конструкторе не обращаемся к async-хранилищу моделей,
        # используем модель по умолчанию из конфигурации.
        _ = ModelsStore  # заглушка для сохранения зависимости и логики импорта
        self.model = config.gigachat_model

        self.logger.info("GigaChat клиент инициализирован")

    def get_access_token(self) -> str | None:
        """
        Получает access token для работы с API.
        Кэширует токен до истечения срока действия.

        Returns:
            Access token или None при ошибке
        """
        # Проверяем кэш токена
        if self.access_token and self.token_expiry_time and time.time() < self.token_expiry_time:
            return self.access_token

        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self.authorization_key}",
            }

            payload = {"scope": self.scope}

            self.logger.debug("Запрос нового токена доступа GigaChat")
            # Увеличиваем таймаут для запроса токена (может быть медленное соединение)
            response = self.session.post(
                self.auth_url,
                headers=headers,
                data=payload,
                timeout=TIMEOUT_TOKEN_SECONDS,
            )

            if response.status_code == HTTP_STATUS_OK:
                token_data = response.json()
                self.access_token = token_data["access_token"]
                # Сохраняем время истечения с запасом (минус TOKEN_EXPIRY_BUFFER_SECONDS)
                expires_in = token_data.get("expires_in", DEFAULT_EXPIRES_IN_SECONDS)
                self.token_expiry_time = time.time() + expires_in - TOKEN_EXPIRY_BUFFER_SECONDS
                self.logger.info("Успешно получен access token для GigaChat")
                return self.access_token
            else:
                self.logger.error(f"Ошибка аутентификации GigaChat: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.Timeout as e:
            self.logger.error(
                f"Таймаут при получении токена GigaChat ({TIMEOUT_TOKEN_SECONDS} секунд): {e}. "
                "Возможные причины: медленное соединение, проблемы с сетью, перегрузка сервера GigaChat.",
            )
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(
                f"Ошибка подключения к GigaChat API при получении токена: {e}. "
                "Возможные причины: проблемы с сетью, недоступность сервера, "
                "проблемы с прокси.",
            )
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка запроса к GigaChat API при получении токена: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении токена GigaChat: {e}", exc_info=True)
            return None

    def test_connection(self) -> bool:
        """
        Проверяет подключение к API.

        Returns:
            True если подключение успешно, False в противном случае
        """
        return self.get_access_token() is not None

    def check_api_status(self) -> tuple[bool, str]:
        """
        Проверяет статус GigaChat API без траты токенов (dry-run).
        Проверяет только получение токена доступа.

        Returns:
            Кортеж (успех_проверки, сообщение_о_статусе)
        """
        try:
            token = self.get_access_token()
            if token:
                return True, "✅ API доступен, ключ валиден"
            else:
                return False, "❌ Не удалось получить токен доступа"
        except Exception as e:
            return False, f"❌ Ошибка проверки: {str(e)[:50]}"

    def get_available_models(self, save_models: bool = True) -> list[str]:
        """
        Возвращает список доступных моделей GigaChat через API.

        Args:
            save_models: Сохранять ли полученный список в хранилище (по умолчанию True)

        Returns:
            Список доступных моделей. В случае ошибки возвращает список из хранилища или стандартный список.
        """
        self.logger.debug(f"Запрос списка моделей GigaChat (save_models={save_models})")
        access_token = self.get_access_token()
        if not access_token:
            self.logger.warning("Не удалось получить токен для запроса списка моделей, используем сохраненный список")
            return self._get_fallback_models()

        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }

            models_url = "https://gigachat.devices.sberbank.ru/api/v1/models"

            self.logger.debug("Запрос списка моделей GigaChat через API")
            # Увеличенный таймаут для запроса списка моделей
            response = self.session.get(
                models_url,
                headers=headers,
                timeout=TIMEOUT_PROMPT_SECONDS,
            )

            if response.status_code == HTTP_STATUS_OK:
                data = response.json()
                # API может вернуть данные в разных форматах, обрабатываем оба случая
                if isinstance(data, dict):
                    # Если это объект с полем data или models
                    models_data = data.get("data", data.get("models", []))
                elif isinstance(data, list):
                    models_data = data
                else:
                    self.logger.warning(f"Неожиданный формат ответа от API моделей: {type(data)}")
                    return self._get_fallback_models()

                # Извлекаем названия моделей
                models_list: list[str] = []
                if models_data is None:
                    return self._get_fallback_models()
                for model in models_data:
                    if isinstance(model, dict):
                        # Если модель - это объект, берем поле id или name
                        model_name = model.get("id") or model.get("name") or model.get("model")
                    elif isinstance(model, str):
                        # Если модель - это просто строка
                        model_name = model
                    else:
                        continue

                    if model_name:
                        models_list.append(model_name)

                if models_list:
                    self.logger.info(f"Получен список из {len(models_list)} моделей GigaChat через API")
                    # Ранее здесь список моделей сохранялся в async‑хранилище ModelsStore.
                    # Так как клиент GigaChat синхронный, чтобы не мешать event loop,
                    # сохраняем список только в памяти и не трогаем async‑репозиторий.
                    return models_list
                else:
                    self.logger.warning("API вернул пустой список моделей, используем сохраненный список")
                    return self._get_fallback_models()
            else:
                error_text = response.text[:MAX_ERROR_TEXT_LENGTH]
                self.logger.warning(
                    f"Ошибка при запросе списка моделей: {response.status_code} - {error_text}, "
                    "используем сохраненный список",
                )
                return self._get_fallback_models()
        except requests.exceptions.Timeout as e:
            self.logger.warning(
                f"Таймаут при запросе списка моделей GigaChat ({TIMEOUT_PROMPT_SECONDS} секунд): {e}, "
                "используем сохраненный список",
            )
            return self._get_fallback_models()
        except requests.exceptions.ConnectionError as e:
            self.logger.warning(
                f"Ошибка подключения при запросе списка моделей GigaChat: {e}, используем сохраненный список",
            )
            return self._get_fallback_models()
        except requests.exceptions.RequestException as e:
            self.logger.warning(
                f"Ошибка запроса при получении списка моделей GigaChat: {e}, используем сохраненный список",
            )
            return self._get_fallback_models()
        except Exception as e:
            self.logger.warning(
                f"Неожиданная ошибка при получении списка моделей через API: {e}, используем сохраненный список",
            )
            return self._get_fallback_models()

    def _get_fallback_models(self) -> list[str]:
        """
        Возвращает стандартный список моделей GigaChat (fallback).

        Async‑хранилище моделей используется только в асинхронных слоях бота.
        Синхронный HTTP‑клиент GigaChat не обращается к Postgres‑репозиторию
        напрямую, чтобы не блокировать event loop.
        """
        standard_models = [
            "GigaChat",
            "GigaChat-2",
            "GigaChat-2-Max",
            "GigaChat-2-Pro",
            "GigaChat-Max",
            "GigaChat-Max-preview",
            "GigaChat-Plus",
            "GigaChat-Pro",
            "GigaChat-Pro-preview",
            "Embeddings",
            "Embeddings-2",
            "EmbeddingsGigaR",
        ]
        self.logger.debug("Используется стандартный список моделей GigaChat")
        return standard_models

    def set_model(self, model_name: str) -> bool:
        """
        Устанавливает текущую модель GigaChat только в памяти клиента.

        Persist‑хранилище моделей для GigaChat используется в async‑слоях бота,
        чтобы не смешивать sync/async‑код внутри HTTP‑клиента.
        """
        available_models = self.get_available_models()
        if model_name in available_models:
            self.model = model_name
            self.logger.info(f"Модель GigaChat изменена на: {model_name}")
            return True

        self.logger.warning(f"Попытка установить несуществующую модель: {model_name}")
        return False

    def generate_prompt_for_kandinsky(self) -> str | None:
        """
        Генерирует креативный промпт для генерации Wednesday Frog изображения через Kandinsky.

        Returns:
            Сгенерированный промпт или None при ошибке
        """
        access_token = self.get_access_token()
        if not access_token:
            self.logger.error("Не удалось получить access token для генерации промпта")
            return None

        try:
            # Системное сообщение для получения качественных промптов
            system_message = """Ты эксперт по созданию промптов для генерации изображений.
Создавай креативные, детальные и разнообразные промпты для генерации мемов Wednesday Frog (жаба по средам).
Каждый промпт должен быть уникальным, содержать детальное описание внешности жабы, позы, стиля и атмосферы.
Используй разнообразие в стилях: мультяшный, реалистичный, пиксель-арт, минимализм и т.д.
Промпт должен быть на английском языке, готовым для Kandinsky API.
Формат: детальное описание жабы, её действия/позы, стиль, атмосфера.
Примеры хороших промптов:
- "a cheerful cartoon green frog wearing a tiny blue hat, sitting on a mushroom, \
Wednesday meme style, vibrant colors, cute and friendly, digital art"
- "a cool green frog with sunglasses jumping in excitement, Wednesday my dudes meme, \
cartoon style, bright background, dynamic pose"
"""

            # Пользовательский промпт с инструкцией
            user_message = (
                "Создай креативный и уникальный промпт для генерации изображения "
                "Wednesday Frog (жабы по средам) в стиле мема.\n"
                "Промпт должен быть:\n"
                "1. Детальным и конкретным\n"
                "2. Описывать внешность жабы (цвет, размер, особенности)\n"
                "3. Описывать действие или позу (сидит, прыгает, танцует и т.д.)\n"
                "4. Указывать стиль изображения (cartoon, realistic, pixel art, minimalistic, watercolor и т.д.)\n"
                "5. Описывать атмосферу и окружение\n"
                "6. Быть готовым для Kandinsky API (на английском языке)\n\n"
                "Важно: каждый промпт должен быть уникальным и разнообразным! Прояви креативность!\n"
                "Промпт должен быть одним предложением, готовым к использованию в Kandinsky API."
            )

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # Используем текущее значение self.model (без обращения к async‑хранилищу)
            current_model = self.model

            payload = {
                "model": current_model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_message,
                    },
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
                "max_tokens": MAX_TOKENS_DEFAULT,
                "temperature": 0.9,  # Высокая температура для разнообразия
                "top_p": 0.95,
                "n": 1,
            }

            self.logger.info("Генерация промпта через GigaChat...")
            response = self.session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=TIMEOUT_PROMPT_SECONDS,
            )

            if response.status_code == HTTP_STATUS_OK:
                result = response.json()
                generated_prompt = result["choices"][0]["message"]["content"].strip()

                # Очищаем промпт от лишних символов и форматирования
                generated_prompt = GigaChatClient._clean_prompt(generated_prompt)

                self.logger.info(f"Промпт успешно сгенерирован: {generated_prompt[:100]}...")

                # Сохраняем успешный промпт в файловое хранилище.
                # Это нужно для:
                # - последующего fallback-а на уже существующие промпты при сбоях GigaChat;
                # - удобного анализа и A/B-тестов разных вариантов промптов.
                self._save_prompt_to_storage(generated_prompt)

                return generated_prompt
            else:
                self.logger.error(
                    f"Ошибка GigaChat API при генерации промпта: {response.status_code} - {response.text}",
                )
                return None
        except requests.exceptions.Timeout as e:
            self.logger.error(
                f"Таймаут при генерации промпта через GigaChat ({TIMEOUT_PROMPT_LONG_SECONDS} секунд): {e}. "
                "Возможные причины: медленное соединение, перегрузка сервера.",
            )
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(
                f"Ошибка подключения к GigaChat API при генерации промпта: {e}. "
                "Возможные причины: проблемы с сетью, недоступность сервера.",
            )
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка запроса к GigaChat API при генерации промпта: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при генерации промпта через GigaChat: {e}", exc_info=True)
            return None

    def _save_prompt_to_storage(self, prompt: str) -> None:
        """
        Сохраняет сгенерированный промпт в `data/prompts/`.

        Вынесено в отдельный метод, чтобы централизовать обработку ошибок
        и упростить возможное переиспользование при добавлении новых типов промптов.
        """
        try:
            self._prompt_storage.save_prompt(prompt, source="gigachat")
        except Exception as e:
            # Ошибка записи промпта не критична для работы бота, поэтому только логируем.
            self.logger.error(f"Ошибка при сохранении промпта в PromptStorage: {e}", exc_info=True)

    @staticmethod
    def _clean_prompt(prompt: str) -> str:
        """
        Очищает промпт от лишних символов, форматирования и маркеров.

        Args:
            prompt: Исходный промпт

        Returns:
            Очищенный промпт
        """
        # Удаляем маркеры типа "```" если есть
        prompt = prompt.replace("```", "")

        # Удаляем префиксы типа "Промпт:" если есть
        prompt = prompt.replace("Prompt:", "").replace("prompt:", "").replace("Промпт:", "")

        # Удаляем кавычки в начале и конце если есть
        prompt = prompt.strip("\"'")

        # Удаляем лишние пробелы
        prompt = " ".join(prompt.split())

        return prompt.strip()
