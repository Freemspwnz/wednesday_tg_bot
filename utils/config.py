"""
Модуль конфигурации приложения.
Содержит настройки для работы с переменными окружения и константы.
"""

import os
from typing import ClassVar

from dotenv import load_dotenv

_DOTENV_STATE = {"loaded": False}


def _load_dotenv_if_needed() -> None:
    """
    Ленивый fallback: при первом обращении к отсутствующей переменной
    пробуем загрузить их из локального `.env` без жестко заданного пути.
    """
    if _DOTENV_STATE["loaded"]:
        return
    # Порядок загрузки:
    # 1) Сначала читаем переменные из окружения контейнера (os.environ)
    # 2) Если какой-то переменной не хватает — однократно пробуем загрузить `.env`
    #    через python-dotenv (если файл существует в текущем каталоге).
    load_dotenv()
    _DOTENV_STATE["loaded"] = True


class Config:  # noqa: PLR0904
    """
    Класс для управления конфигурацией приложения.
    Содержит все необходимые настройки и токены.
    """

    def __init__(self) -> None:
        """Инициализация конфигурации с проверкой обязательных переменных."""
        Config._validate_required_vars()

    @staticmethod
    def _validate_required_vars() -> None:
        """
        Проверяет наличие всех обязательных переменных окружения.
        Вызывает исключение, если какая-то переменная отсутствует.
        """
        required_vars = [
            "TELEGRAM_BOT_TOKEN",
            "KANDINSKY_API_KEY",
            "KANDINSKY_SECRET_KEY",
            "CHAT_ID",
            "ADMIN_CHAT_ID",
        ]

        missing_vars = []
        for var in required_vars:
            if not Config._get_env_var(var):
                missing_vars.append(var)

        if missing_vars:
            # Используем стандартный logging, чтобы избежать циклических импортов с utils.logger
            import logging

            logger = logging.getLogger(__name__)
            for var in missing_vars:
                logger.error(f"Отсутствует обязательная переменная окружения: {var}")

            raise ValueError(
                "Отсутствуют обязательные переменные окружения: "
                f"{', '.join(missing_vars)}. Проверьте переменные окружения контейнера "
                "и/или локальный файл .env",
            )

    @staticmethod
    def _get_env_var(name: str) -> str | None:
        """
        Получает значение переменной окружения.

        Args:
            name: Имя переменной окружения

        Returns:
            Значение переменной или None, если переменная не найдена
        """
        # Сначала читаем значение только из переменных окружения контейнера
        value = os.getenv(name)
        if value is not None:
            return value

        # Если переменная не найдена, один раз пробуем подгрузить .env через python-dotenv
        _load_dotenv_if_needed()
        return os.getenv(name)

    @property
    def telegram_token(self) -> str | None:
        """
        Токен Telegram бота.

        Returns:
            Токен бота из переменной TELEGRAM_BOT_TOKEN
        """
        return Config._get_env_var("TELEGRAM_BOT_TOKEN")

    @property
    def kandinsky_api_key(self) -> str | None:
        """
        API ключ для сервиса Kandinsky (Fusion Brain).

        Returns:
            API ключ из переменной KANDINSKY_API_KEY
        """
        return Config._get_env_var("KANDINSKY_API_KEY")

    @property
    def kandinsky_secret_key(self) -> str | None:
        """
        Secret ключ для сервиса Kandinsky (Fusion Brain).

        Returns:
            Secret ключ из переменной KANDINSKY_SECRET_KEY
        """
        return Config._get_env_var("KANDINSKY_SECRET_KEY")

    @property
    def chat_id(self) -> str | None:
        """
        ID чата или канала для отправки сообщений.

        Returns:
            ID чата из переменной CHAT_ID
        """
        return Config._get_env_var("CHAT_ID")

    @property
    def telegram_proxy_url(self) -> str | None:
        """
        URL прокси для Telegram (HTTP/SOCKS), например:
        http://user:pass@host:port или socks5://user:pass@host:port
        """
        return Config._get_env_var("TELEGRAM_PROXY_URL")

    @property
    def telegram_vless_url(self) -> str | None:
        """
        VLESS URL (не используется напрямую HTTP-клиентом; нужен локальный клиент Xray/V2Ray).
        Пример: vless://<uuid>@host:port?encryption=none&security=reality#name
        """
        return Config._get_env_var("TELEGRAM_VLESS_URL")

    @property
    def telegram_vless_proxy(self) -> str | None:
        """
        Локальный прокси (HTTP/SOCKS), за которым работает VLESS-клиент.
        Пример: http://127.0.0.1:8080 или socks5://127.0.0.1:1080
        Если задан, будет использован как proxy_url для Telegram-запросов.
        """
        return Config._get_env_var("TELEGRAM_VLESS_PROXY")

    @property
    def log_level(self) -> str:
        """
        Уровень логирования.

        Returns:
            Уровень логирования из переменной LOG_LEVEL или "INFO" по умолчанию
        """
        return Config._get_env_var("LOG_LEVEL") or "INFO"

    @property
    def generation_timeout(self) -> int:
        """
        Таймаут для генерации изображения в секундах.

        Returns:
            Таймаут из переменной GENERATION_TIMEOUT или 60 секунд по умолчанию
        """
        return int(Config._get_env_var("GENERATION_TIMEOUT") or "60")

    @property
    def max_retries(self) -> int:
        """
        Максимальное количество попыток генерации изображения.

        Returns:
            Количество попыток из переменной MAX_RETRIES или 3 по умолчанию
        """
        return int(Config._get_env_var("MAX_RETRIES") or "3")

    # --- Redis / кэш / состояние ---

    @property
    def redis_url(self) -> str | None:
        """
        Полный URL для подключения к Redis.

        Пример:
            redis://localhost:6379/0
            rediss://user:pass@host:6380/1
        """
        return Config._get_env_var("REDIS_URL")

    @property
    def redis_host(self) -> str:
        """
        Хост Redis при отсутствии REDIS_URL.
        """
        return Config._get_env_var("REDIS_HOST") or "localhost"

    @property
    def redis_port(self) -> int:
        """
        Порт Redis при отсутствии REDIS_URL.
        """
        return int(Config._get_env_var("REDIS_PORT") or "6379")

    @property
    def redis_db(self) -> int:
        """
        Номер базы Redis при отсутствии REDIS_URL.
        """
        return int(Config._get_env_var("REDIS_DB") or "0")

    @property
    def redis_password(self) -> str | None:
        """
        Пароль для Redis (если требуется).
        """
        return Config._get_env_var("REDIS_PASSWORD")

    @property
    def gigachat_auth_url(self) -> str:
        """
        URL для аутентификации в GigaChat API.

        Returns:
            URL из переменной GIGACHAT_AUTH_URL или значение по умолчанию
        """
        return Config._get_env_var("GIGACHAT_AUTH_URL") or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    @property
    def gigachat_api_url(self) -> str:
        """
        URL для запросов к GigaChat API.

        Returns:
            URL из переменной GIGACHAT_API_URL или значение по умолчанию
        """
        return Config._get_env_var("GIGACHAT_API_URL") or "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    @property
    def gigachat_authorization_key(self) -> str:
        """
        Authorization key для GigaChat API (Base64 encoded).

        Returns:
            Authorization key из переменной GIGACHAT_AUTHORIZATION_KEY
        """
        key = Config._get_env_var("GIGACHAT_AUTHORIZATION_KEY")
        if not key:
            # Ленивый импорт чтобы избежать циклической зависимости
            try:
                from utils.logger import get_logger

                logger = get_logger(__name__)
                logger.warning(
                    "GIGACHAT_AUTHORIZATION_KEY не установлен. Генерация промптов через GigaChat будет недоступна.",
                )
            except ImportError:
                # Если logger еще не инициализирован, просто пропускаем предупреждение
                pass
        return key or ""

    @property
    def gigachat_scope(self) -> str:
        """
        Scope для аутентификации GigaChat.

        Returns:
            Scope из переменной GIGACHAT_SCOPE или значение по умолчанию
        """
        return Config._get_env_var("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS"

    @property
    def gigachat_model(self) -> str:
        """
        Модель GigaChat для использования.

        Returns:
            Название модели из переменной GIGACHAT_MODEL или значение по умолчанию
        """
        return Config._get_env_var("GIGACHAT_MODEL") or "GigaChat"

    @property
    def gigachat_cert_path(self) -> str | None:
        """
        Путь к файлу сертификата для GigaChat API.

        Returns:
            Путь к файлу сертификата или None если не указан
        """
        cert_path = Config._get_env_var("GIGACHAT_CERT_PATH")
        if cert_path:
            from pathlib import Path

            cert_file = Path(cert_path)
            if cert_file.exists():
                return str(cert_file.absolute())
            else:
                # Ленивый импорт logger
                try:
                    from utils.logger import get_logger

                    logger = get_logger(__name__)
                    logger.warning(f"Файл сертификата не найден: {cert_path}")
                except ImportError:
                    pass
        return None

    @property
    def gigachat_verify_ssl(self) -> str | bool:
        """
        Настройка проверки SSL сертификатов для GigaChat API.

        Returns:
            Путь к файлу сертификата, True для стандартной проверки, или False для отключения
            Приоритет: GIGACHAT_CERT_PATH > GIGACHAT_VERIFY_SSL
        """
        # Сначала проверяем путь к сертификату
        cert_path = self.gigachat_cert_path
        if cert_path:
            return cert_path

        # Если сертификат не указан, проверяем флаг verify_ssl
        verify_ssl_str = Config._get_env_var("GIGACHAT_VERIFY_SSL")
        if verify_ssl_str is None:
            return True  # По умолчанию проверяем
        return verify_ssl_str.lower() in {"true", "1", "yes", "on"}

    @property
    def admin_chat_id(self) -> str | None:
        """
        ID администратора для доступа к админ-командам.

        Returns:
            ID администратора из переменной ADMIN_CHAT_ID или None если не указан
        """
        return Config._get_env_var("ADMIN_CHAT_ID")


# Создаем глобальный экземпляр конфигурации
config = Config()


# Константы для работы с изображениями
class ImageConfig:
    """Константы для настройки генерации изображений."""

    # Разнообразные промпты для жабы
    FROG_PROMPTS: ClassVar[list[str]] = [
        "cute cartoon frog, green, sitting on a mushroom",
        "funny cartoon frog, green, jumping with excitement",
        "cool cartoon frog, green, wearing sunglasses",
        "sleepy cartoon frog, green, yawning in bed",
        "dancing cartoon frog, green, moving to music",
        "superhero cartoon frog, green, with cape flying",
        "chef cartoon frog, green, cooking in kitchen",
        "scientist cartoon frog, green, with test tubes",
        "artist cartoon frog, green, painting pictures",
        "musician cartoon frog, green, playing guitar",
        "astronaut cartoon frog, green, in space suit",
        "detective cartoon frog, green, with magnifying glass",
        "pirate cartoon frog, green, with eye patch and hat",
        "knight cartoon frog, green, with sword and shield",
        "wizard cartoon frog, green, with magic wand",
    ]

    # Разнообразные стили
    STYLES: ClassVar[list[str]] = [
        "cartoon, cute, friendly, bright colors",
        "cartoon, funny, expressive, vibrant",
        "cartoon, cool, stylish, modern",
        "cartoon, adorable, charming, detailed",
        "cartoon, energetic, dynamic, colorful",
        "cartoon, heroic, powerful, dramatic",
        "cartoon, creative, artistic, imaginative",
    ]

    # Размер изображения (ширина x высота)
    WIDTH = 1024
    HEIGHT = 1024

    # Подписи для изображений
    CAPTIONS: ClassVar[list[str]] = [
        "It's Wednesday, my dudes!",
        "Среда, мои чуваки!",
    ]


# Константы для планировщика
TIME_FORMAT_LENGTH = 5  # Длина строки времени в формате HH:MM
HOURS_IN_DAY = 24
MINUTES_IN_HOUR = 60
DAYS_IN_WEEK = 7
WEDNESDAY_DEFAULT = 2  # default (среда)


class SchedulerConfig:
    """Константы для настройки планировщика задач."""

    @staticmethod
    def _parse_send_times() -> list[str]:
        """Парсит времена отправки из ENV с валидацией."""
        # Берем значение из окружения контейнера, при необходимости с fallback в .env
        env_times = Config._get_env_var("SCHEDULER_SEND_TIMES")
        if env_times:
            times = [t.strip() for t in env_times.split(",")]
            validated = []
            for t in times:
                if len(t) == TIME_FORMAT_LENGTH and t[2] == ":" and t[:2].isdigit() and t[3:].isdigit():
                    h, m = int(t[:2]), int(t[3:])
                    if 0 <= h < HOURS_IN_DAY and 0 <= m < MINUTES_IN_HOUR:
                        validated.append(t)
                    else:
                        print(f"⚠️  Неверное время в SCHEDULER_SEND_TIMES: {t} (должно быть HH:MM)")
                else:
                    print(f"⚠️  Неверный формат времени: {t} (ожидается HH:MM)")
            if validated:
                return validated
        return ["09:00", "12:00", "18:00"]  # default

    # Время(ена) отправки сообщения (список строк HH:MM по МСК)
    SEND_TIMES = _parse_send_times()

    @staticmethod
    def _parse_wednesday_day() -> int:
        """Парсит день недели с валидацией."""
        env_day = Config._get_env_var("SCHEDULER_WEDNESDAY_DAY")
        if env_day:
            try:
                day = int(env_day)
                if 0 <= day < DAYS_IN_WEEK:
                    return day
                else:
                    print(f"⚠️  SCHEDULER_WEDNESDAY_DAY должен быть 0-{DAYS_IN_WEEK - 1}, получен {day}")
            except ValueError:
                print("⚠️  SCHEDULER_WEDNESDAY_DAY должен быть числом")
        return WEDNESDAY_DEFAULT

    # День недели для отправки (среда = 2, где понедельник = 0)
    WEDNESDAY = _parse_wednesday_day()

    # Интервал проверки планировщика в секундах
    CHECK_INTERVAL = 30

    # Часовой пояс для расписания
    TZ = Config._get_env_var("SCHEDULER_TZ") or "Europe/Moscow"
