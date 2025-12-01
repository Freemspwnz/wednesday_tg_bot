# CHANGELOG
## [6.0.0] 2025-11-XX — Обновлён CI, улучшена работа с GigaChat-промптами и fallback-механизм, добавлена Redis-интеграция для временного состояния и кэширования, миграция персистентных данных в PostgreSQL завершена, обновлены тесты и инфраструктура, значительно увеличено покрытие тестами, добавлены Docker volumes для файловых операций, нормализация и безопасная запись файлов промптов GigaChat

### Добавлено
- **Расширенное тестовое покрытие**:
  - `tests/test_bot/test_handlers.py` — добавлено 20+ новых тестов для команд:
    - `set_frog_used_command` — тесты успешного выполнения, неверных параметров и отсутствия аргументов
    - `unknown_command` — тест обработки неизвестных команд
    - `admin_add_chat_command` — тесты успешного добавления, отсутствия аргументов и неверного chat_id
    - `admin_remove_chat_command` — тесты успешного удаления и отсутствия аргументов
    - `list_chats_command` — тесты успешного вывода списка и пустого списка чатов
    - `stop_command` — тесты для администраторов и не-администраторов
    - `set_kandinsky_model_command` — тесты успешной установки и отсутствия аргументов
    - `set_gigachat_model_command` — тесты успешной установки, отсутствия клиента и отсутствия аргументов
    - `mod_command` — тесты успешного добавления администратора и отсутствия аргументов
    - `unmod_command` — тесты успешного удаления администратора и отсутствия аргументов
    - `list_mods_command` — тест вывода списка администраторов
    - `list_models_command` — тест вывода списка доступных моделей
  - `tests/test_bot/test_wednesday_bot.py` — добавлено 8 новых тестов:
    - `test_send_error_message` — тест отправки сообщения об ошибке
    - `test_send_user_friendly_error` — тест отправки дружелюбного сообщения об ошибке
    - `test_send_fallback_image_success` — тест успешной отправки fallback изображения
    - `test_send_fallback_image_no_image` — тест отсутствия fallback изображений
    - `test_on_my_chat_member_added` — тест обработки добавления бота в чат
    - `test_on_my_chat_member_removed` — тест обработки удаления бота из чата
    - `test_stop_bot` — тест остановки бота
    - `test_stop_bot_already_stopped` — тест повторной остановки уже остановленного бота
  - `tests/test_bot/test_support_bot.py` — добавлено 4 новых теста:
    - `test_help_command` — тест команды справки
    - `test_start_main_command_non_admin` — тест команды запуска основного бота для не-администратора
    - `test_start_main_command_admin_no_callback` — тест команды запуска без callback функции
    - `test_start_main_command_admin_with_callback` — тест команды запуска с callback функцией
    - `test_log_command_with_args` — тест команды отправки логов с аргументами
  - `tests/test_services/test_image_generator.py` — добавлено 6 новых тестов:
    - `test_get_random_caption` — тест получения случайной подписи
    - `test_get_fallback_prompt` — тест получения fallback промпта
    - `test_get_random_saved_image` — тесты получения случайного сохранённого изображения (с файлами и без)
    - `test_set_kandinsky_model_success` — тест успешной установки модели Kandinsky
    - `test_set_kandinsky_model_not_found` — тест установки несуществующей модели
    - `test_get_auth_headers` — тест получения заголовков авторизации
  - **Новые тестовые файлы для утилит**:
    - `tests/test_utils/test_admins_store.py` — 6 тестов для `AdminsStore`:
      - Добавление администратора (успешное и дубликат)
      - Удаление администратора (успешное и несуществующего)
      - Получение списка администраторов (обычный и полный с главным админом)
    - `tests/test_utils/test_dispatch_registry.py` — 4 теста для `DispatchRegistry`:
      - Проверка отсутствия записи
      - Создание и проверка записи
      - Обработка дубликатов
      - Очистка старых записей
    - `tests/test_utils/test_metrics.py` — 7 тестов для `Metrics`:
      - Инкремент успешных и неудачных генераций
      - Инкремент успешных и неудачных отправок
      - Добавление времени генерации
      - Инкремент срабатываний circuit breaker
      - Получение сводки метрик (пустая и заполненная)
    - `tests/test_utils/test_chats_store.py` — 4 теста для `ChatsStore`:
      - Добавление чата
      - Удаление чата
      - Получение списка чатов (с данными и пустой список)
- **Событийные метрики генераций и кеша в PostgreSQL**:
  - Добавлена таблица `metrics_events` (через `utils.postgres_schema.ensure_schema()` и SQL-миграции `docs/sql/003_add_metrics_events_table*.sql`) для логирования отдельных событий: ошибок, генераций, кеш-хитов/промахов, латентности и статуса.
  - Реализован helper `utils.metrics.record_metric(...)` c типизированным интерфейсом для записи событий и одновременным логированием через Loguru.
  - Добавлены агрегирующие запросы в `utils.metrics` (`get_daily_generation_stats`, `get_top_prompts`) для получения статистики по дням, средней латентности и топу промптов.
  - В `services/image_generator.ImageGenerator.generate_frog_image()` внедрена запись событий: `generation/started`, `generation/ok` с latency и `image_hash`, `cache_hit` с `status='cached'` и `latency_ms=0`, а также событий `error` при сетевых ошибках, срабатывании circuit breaker и полном провале генерации.
  - Обработчики `/frog` и `/force_send` передают `user_id` в генератор, чтобы привязывать события метрик к конкретным пользователям; при необходимости дальнейшего роста нагрузки предусмотрена возможность вынести запись событий в отдельную очередь (например, Redis Stream).
- **Тесты для `PromptStorage`** (`tests/test_services/test_prompt_generator.py`):
  - Проверка сохранения реального содержимого `"A frog"` без лишних кавычек и пробелов по краям.
  - Проверка корректной записи многострочных промптов с сохранением внутренних переводов строк и пробелов.
  - Проверка, что попытка сохранить пустой промпт приводит к `ValueError` и логируется через warning.
  - Небольшой тест, эмулирующий запись в директорию, ведущую себя как tmpfs‑volume в CI (через временную директорию pytest), для раннего отлова регрессий в файловых операциях с промптами.
- **Интеграционные тесты для команд бота**:
  - `tests/test_bot/test_handlers.py` — добавлены интеграционные тесты `test_status_command_integration_with_postgres_stores` и `test_force_send_command_integration_with_postgres_stores`, использующие реальные async‑сторы PostgreSQL для проверки работы команд `/status` и `/force_send`.
- **CI/CD с поддержкой PostgreSQL и Redis**:
  - `.github/workflows/pytest-check.yml` — добавлены сервисные контейнеры Postgres 16 и Redis 7 для запуска тестов в изолированной среде.
  - Настроены healthchecks для автоматического ожидания готовности БД перед запуском тестов.
  - Добавлена проверка готовности сервисов через Python‑скрипт перед выполнением тестов.
  - Используются безопасные тестовые учетные данные для изолированной CI‑среды.
- **Локальная тестовая инфраструктура**:
  - `docker-compose.test.yml` — отдельный docker-compose файл для тестовой среды с Postgres 16-alpine и Redis 7-alpine.
  - Контейнеры используют `tmpfs` для данных, обеспечивая быструю очистку после тестов и изоляцию от продакшн БД.
  - `Makefile` — разделены команды тестирования: `make test` (только тесты + junit.xml), `make test-cov` (тесты с покрытием + coverage.xml + junit.xml).
  - Команды тестирования автоматически запускают тестовые контейнеры, ждут их готовности, выполняют тесты и очищают контейнеры после завершения.
  - Добавлены вспомогательные команды: `make test-up` (запуск контейнеров), `make test-down` (остановка), `make test-no-containers` (запуск тестов без контейнеров для уже запущенных БД).
- **Боевой запуск через Docker**:
  - `Makefile` — команда `make run` полностью переработана: автоматически очищает и пересобирает Docker-образ бота, поднимает боевые контейнеры Postgres и Redis, ожидает их готовности и запускает бота.
  - Команда `make build` теперь автоматически очищает старый образ перед сборкой нового.
  - Удалены неиспользуемые команды: `run-local`, `init-volumes`, `sync-volumes`.
- **Docker volumes для файловых операций**:
  - `docker-compose.yml` — добавлены именованные тома:
    - `frog_images` → примонтирован в контейнер по пути `/app/data/frogs` для хранения сгенерированных изображений жабы.
    - `logs` → примонтирован в контейнер по пути `/app/logs` для файлов логов бота.
    - `prompt_storage` → примонтирован в контейнер по пути `/app/data/prompts` для файлового хранилища промптов GigaChat.
  - Весь файловый ввод/вывод бота (изображения, логи, промпты) переведён на работу только с этими директориями внутри контейнера.
  - Добавлены рекомендации по резервному копированию томов в `README.md` и `docs/INSTALLATION.md`.
  - Таблица `prompts` используется как каноничное хранилище метаданных промптов (raw/normalized/hash), а файловый `prompt_storage` служит fallback-слоем.
- **PostgreSQL-хранилище промптов**:
  - Добавлена таблица `prompts` (через `utils/postgres_schema.ensure_schema()` и SQL-миграции `docs/sql/001_add_prompts_table*.sql`) с полями `raw_text`, `normalized_text`, `prompt_hash`, `created_at`, `ab_group` и индексом `idx_prompts_prompt_hash`.
  - Реализован репозиторий `utils/prompts_store.PromptsStore` с методами `get_or_create_prompt`, `get_prompt_by_hash`, `get_random_prompt`, нормализующий текст промпта (strip) и считающий sha256‑hash от нормализованного текста.
  - `services/image_generator.ImageGenerator._generate_prompt()` теперь регистрирует все успешные промпты (GigaChat + fallback) в таблице `prompts` и использует БД как основной источник промптов при недоступности GigaChat.
  - Добавлены тесты `tests/test_utils/test_prompts_store.py` и `tests/test_utils/test_prompts_migration_sql.py`, проверяющие корректность схемы, дедупликацию по hash и возможность применения/отката миграций.
- **PostgreSQL-хранилище изображений и content-addressable storage**:
  - Добавлена таблица `images` в `utils/postgres_schema.ensure_schema()` и SQL-миграции `docs/sql/002_add_images_table*.sql` с полями `image_hash`, `prompt_hash` (FK на `prompts.prompt_hash`), `path`, `created_at` и индексом `idx_images_prompt_hash`.
  - Реализован репозиторий `utils/images_store.ImagesStore` c content-addressable схемой: имя файла изображения вычисляется как `sha256(image_bytes).hexdigest()` и используется как ключ `image_hash`, файл хранится как `/app/data/frogs/<image_hash>.png`.
  - Добавлены тесты `tests/test_utils/test_images_store.py` и `tests/test_utils/test_images_migration_sql.py`, покрывающие базовые операции, применение/откат миграций и обработку гонок при параллельной вставке (duplicate key → reuse существующей записи).
  - Внедрён кеш изображений по `prompt_hash` в `services/image_generator.ImageGenerator.generate_frog_image()`: при повторном запросе с тем же нормализованным промптом бот сначала ищет запись в `images` и при наличии использует уже сохранённый файл (cache hit) без обращения к Kandinsky.
  - Логика генерации и сохранения изображений переписана на строгий content-addressable storage‑паттерн: сначала вычисляется `image_hash = sha256(file_bytes).hexdigest()`, затем файл атомарно сохраняется во временный путь и переносится в конечный `/app/data/frogs/<image_hash>.png` без перезаписи уже существующих файлов.
- **Workflow `docker-build.yml`, `Dockerfile`, `.dockerignore`**:
  - Автоматически создаёт Docker image на основе `Dockerfile` и пушит его в GHCR.
- **Логика ленивой загрузки `.env` в `utils/config.py`**:
  - Переменные конфигурации сначала читаются из окружения контейнера (`os.environ`).
  - При отсутствии значения для переменной один раз выполняется fallback через `python-dotenv` без жёстких путей к `.env`.
  - Добавлено логирование ошибок через стандартный `logging` для всех отсутствующих обязательных переменных.
- **Файловое хранилище промптов GigaChat в `services/prompt_generator.py`**:
  - Все успешно сгенерированные промпты GigaChat автоматически сохраняются в директорию `data/prompts/` в виде текстовых файлов.
  - Директория `data/prompts/` создаётся на лету при первом обращении, без необходимости ручной подготовки.
  - Структура хранилища (имена файлов, пометка источника) подготовлена для последующего A/B-тестирования разных вариантов промптов.
- **Файловый fallback-промпт в `services/image_generator.py`**:
  - При любой ошибке GigaChat (таймаут, недоступность API, сетевые проблемы) генератор изображений пробует выбрать случайный промпт из сохранённых файлов `data/prompts/`.
  - Если в файловом хранилище нет ни одного промпта, используется существующий статический fallback на основе `ImageConfig.FROG_PROMPTS`.
  - Добавлено подробное логирование выбора и использования fallback-промптов.
- **Единый Redis‑клиент `utils/redis_client.py`**:
  - Асинхронный клиент `redis.asyncio.Redis` с инициализацией один раз за цикл жизни приложения.
  - Функции `init_redis_pool()`, `get_redis()`, `close_redis()`, `redis_available()` для централизованного доступа.
  - Лёгкий in‑memory fallback с поддержкой TTL, используемый при недоступности Redis.
- **Сервисы Redis‑абстракций**:
  - `services/prompt_cache.py` — кэш промптов (JSON‑совместимых объектов) с TTL и автоматическим fallback.
  - `services/user_state_store.py` — хранилище временного состояния пользователей (JSON‑blob, TTL + очистка).
  - `services/rate_limiter.py` — `RateLimiter` c фиксированным окном и `CircuitBreaker` на базе атомарных операций Redis.
- **Интеграция Redis в ботов и раннер**:
  - `main.py` — при старте пробует инициализировать Redis (по `REDIS_URL` или `REDIS_HOST/PORT/DB/PASSWORD`), при ошибке продолжает работу в деградированном in‑memory режиме.
  - `bot/wednesday_bot.py` — размещает `PromptCache`, `UserStateStore` и `RateLimiter` в `bot_data` для использования обработчиками.
  - `bot/support_bot.py` — добавлен `RateLimiter` для административных команд резервного бота (fail‑open при недоступности Redis).
- **Redis‑основанный circuit breaker для Kandinsky**:
  - `services/image_generator.py` использует `CircuitBreaker` из `services/rate_limiter.py` для подсчёта неудач и окна восстановления поверх Redis.
- **Тесты для Redis‑сервисов**:
  - `tests/test_services/test_redis_services.py` — базовые проверки `PromptCache`, `UserStateStore`, `RateLimiter` и `CircuitBreaker` на in‑memory backend.
 - **PostgreSQL‑клиент и схема БД**:
   - `utils/postgres_client.py` — асинхронный клиент PostgreSQL с одним пулом `asyncpg.Pool` на всё приложение и вспомогательными функциями `init_postgres_pool()`, `get_postgres_pool()`, `close_postgres_pool()`.
   - `utils/postgres_schema.py` — инициализация схемы БД через идемпотентную функцию `ensure_schema()`, создающую необходимые таблицы (`chats`, `admins`, `usage_stats`, `usage_settings`, `dispatch_registry`, `metrics`, `models_kandinsky`, `models_gigachat`).
 - **PostgreSQL‑репозитории вместо JSON‑файлов**:
   - `utils/chats_store.py` — `ChatsStore` переведён на хранение в таблице `chats` (список чатов рассылки).
   - `utils/admins_store.py` — `AdminsStore` использует таблицу `admins` для хранения доп. администраторов (главный по‑прежнему задаётся через `ADMIN_CHAT_ID`).
   - `utils/usage_tracker.py` — `UsageTracker` хранит помесячную статистику в `usage_stats` и настройки лимитов в `usage_settings`.
   - `utils/dispatch_registry.py` — `DispatchRegistry` отслеживает отправки по слотам в таблице `dispatch_registry` вместо `dispatch_registry.json`.
   - `utils/metrics.py` — `Metrics` агрегирует показатели в таблице `metrics` (единая строка `id=1`) вместо `metrics.json`.
   - `utils/models_store.py` — `ModelsStore` разбит на две таблицы: `models_kandinsky` и `models_gigachat` для текущих и доступных моделей.
 - **Документация и запуск**:
   - `README.md` обновлён под новую архитектуру: Postgres‑сторы вместо JSON‑файлов, единый Redis‑клиент и быстрый старт через `docker compose up`.
  - `docs/INSTALLATION.md` переработан: добавлен основной сценарий запуска через `docker-compose` (Postgres + Redis + бот), убраны упоминания JSON‑хранилищ метрик/usage, описаны варианты нативного запуска, добавлено описание Docker volumes для изображений, логов и промптов.
   - `docs/PROJECT_SUMMARY.md` обновлён: разделы по `ChatsStore`, `UsageTracker`, `DispatchRegistry`, `Metrics`, `ModelsStore` переписаны под PostgreSQL, структура `utils/` дополнена `redis_client.py`, `postgres_client.py`, `postgres_schema.py`.
 - **Async-проводка бота и тестов для работы с Postgres**:
   - `bot/wednesday_bot.py` — методы отправки жабы и обработки добавления/удаления чатов теперь используют async‑репозитории (`ChatsStore`, `DispatchRegistry`, `UsageTracker`, `Metrics`, `AdminsStore`) через `await`, без изменения внешнего API.
   - `bot/support_bot.py` — проверки прав администратора и рассылка уведомлений обрабатываются через async‑интерфейс `AdminsStore`.
   - `bot/handlers.py` — все админ‑команды и команды работы с лимитами/чатами/статусом (`/help`, `/frog`, `/status`, `/force_send`, `/add_chat`, `/remove_chat`, `/list_chats` и др.) переведены на использование async‑сторов (`AdminsStore`, `UsageTracker`, `ChatsStore`, `Metrics`) с `await`.
   - `services/image_generator.py` — обновление метрик генерации (`Metrics`) выполняется асинхронно с защитой от сбоев в слое метрик.
   - `tests/conftest.py` — добавлена сессионная async‑фикстура `_setup_test_postgres`, инициализирующая пул `asyncpg`, вызывающая `ensure_schema()` и очищающая основные таблицы перед тестами.
   - `tests/test_utils/test_usage_tracker.py`, `tests/test_utils/test_models_store.py` — переписаны как async‑тесты поверх Postgres‑репозиториев.
   - `tests/test_bot/test_wednesday_bot.py`, `tests/test_bot/test_support_bot.py` — заглушки (`Dummy*Store`, `DummyMetrics`) приведены к async‑интерфейсам, чтобы соответствовать новым async‑сторам.
 - **Расширенное тестовое покрытие**:
   - `tests/test_bot/test_handlers.py` — добавлено 20+ новых тестов для команд:
     - `set_frog_used_command` — тесты успешного выполнения, неверных параметров и отсутствия аргументов
     - `unknown_command` — тест обработки неизвестных команд
     - `admin_add_chat_command` — тесты успешного добавления, отсутствия аргументов и неверного chat_id
     - `admin_remove_chat_command` — тесты успешного удаления и отсутствия аргументов
     - `list_chats_command` — тесты успешного вывода списка и пустого списка чатов
     - `stop_command` — тесты для администраторов и не-администраторов
     - `set_kandinsky_model_command` — тесты успешной установки и отсутствия аргументов
     - `set_gigachat_model_command` — тесты успешной установки, отсутствия клиента и отсутствия аргументов
     - `mod_command` — тесты успешного добавления администратора и отсутствия аргументов
     - `unmod_command` — тесты успешного удаления администратора и отсутствия аргументов
     - `list_mods_command` — тест вывода списка администраторов
     - `list_models_command` — тест вывода списка доступных моделей
   - `tests/test_bot/test_wednesday_bot.py` — добавлено 8 новых тестов:
     - `test_send_error_message` — тест отправки сообщения об ошибке
     - `test_send_user_friendly_error` — тест отправки дружелюбного сообщения об ошибке
     - `test_send_fallback_image_success` — тест успешной отправки fallback изображения
     - `test_send_fallback_image_no_image` — тест отсутствия fallback изображений
     - `test_on_my_chat_member_added` — тест обработки добавления бота в чат
     - `test_on_my_chat_member_removed` — тест обработки удаления бота из чата
     - `test_stop_bot` — тест остановки бота
     - `test_stop_bot_already_stopped` — тест повторной остановки уже остановленного бота
   - `tests/test_bot/test_support_bot.py` — добавлено 4 новых теста:
     - `test_help_command` — тест команды справки
     - `test_start_main_command_non_admin` — тест команды запуска основного бота для не-администратора
     - `test_start_main_command_admin_no_callback` — тест команды запуска без callback функции
     - `test_start_main_command_admin_with_callback` — тест команды запуска с callback функцией
     - `test_log_command_with_args` — тест команды отправки логов с аргументами
   - `tests/test_services/test_image_generator.py` — добавлено 6 новых тестов:
     - `test_get_random_caption` — тест получения случайной подписи
     - `test_get_fallback_prompt` — тест получения fallback промпта
     - `test_get_random_saved_image` — тесты получения случайного сохранённого изображения (с файлами и без)
     - `test_set_kandinsky_model_success` — тест успешной установки модели Kandinsky
     - `test_set_kandinsky_model_not_found` — тест установки несуществующей модели
     - `test_get_auth_headers` — тест получения заголовков авторизации
   - **Новые тестовые файлы для утилит**:
     - `tests/test_utils/test_admins_store.py` — 6 тестов для `AdminsStore`:
       - Добавление администратора (успешное и дубликат)
       - Удаление администратора (успешное и несуществующего)
       - Получение списка администраторов (обычный и полный с главным админом)
     - `tests/test_utils/test_dispatch_registry.py` — 4 теста для `DispatchRegistry`:
       - Проверка отсутствия записи
       - Создание и проверка записи
       - Обработка дубликатов
       - Очистка старых записей
     - `tests/test_utils/test_metrics.py` — 7 тестов для `Metrics`:
       - Инкремент успешных и неудачных генераций
       - Инкремент успешных и неудачных отправок
       - Добавление времени генерации
       - Инкремент срабатываний circuit breaker
       - Получение сводки метрик (пустая и заполненная)
     - `tests/test_utils/test_chats_store.py` — 4 теста для `ChatsStore`:
       - Добавление чата
       - Удаление чата
       - Получение списка чатов (с данными и пустой список)

### Изменено
- **`services/prompt_generator.py` / `PromptStorage`**:
  - Добавлена нормализация промптов перед записью в файловое хранилище: удаляются ведущие и замыкающие пробелы по всему промпту, при этом внутренняя многострочная структура не изменяется.
  - Реализована фильтрация управляющих символов (кроме перевода строки), чтобы в файлы `data/prompts` не попадали невидимые управляющие коды.
  - Логика записи переписана на явное использование `open(..., encoding="utf-8")` и логируется hash содержимого и ожидаемый контейнерный путь `/app/data/prompts/<filename>`.
  - При пустом промпте после нормализации или очистки управляющих символов выбрасывается `ValueError` и пишется предупреждение в логах; вызывающий код обрабатывает ошибку как некритичную.
- **`utils/config.py`**:
  - Обязательные переменные конфигурации (`TELEGRAM_BOT_TOKEN`, `KANDINSKY_API_KEY`, `KANDINSKY_SECRET_KEY`, `CHAT_ID`, `ADMIN_CHAT_ID`) теперь полностью завязаны на переменные окружения контейнера с fallback на локальный `.env`.
  - Опциональные переменные (`GIGACHAT_AUTHORIZATION_KEY`, `SCHEDULER_SEND_TIMES`, `SCHEDULER_WEDNESDAY_DAY`, `SCHEDULER_TZ` и др.) также читаются через единый слой доступа к окружению с поддержкой fallback.
  - Сообщение об ошибке при отсутствии обязательных переменных теперь явно указывает на необходимость проверки окружения контейнера и/или локального `.env`.
  - Функция `_load_dotenv_if_needed()` обёрнута в `try-except` для graceful handling ошибок доступа к `.env` (например, `PermissionError` при отсутствии прав чтения), что позволяет тестам работать без локального `.env` файла.
- **`tests/conftest.py`**:
  - Фикстура `base_env` теперь устанавливает безопасные тестовые значения для Postgres (`test_user`/`test_password_ci_2024`) вместо реальных учетных данных.
  - Добавлены переменные окружения `SCHEDULER_SEND_TIMES`, `SCHEDULER_WEDNESDAY_DAY`, `SCHEDULER_TZ` в `base_env` для предотвращения вызовов `load_dotenv()` при инициализации `SchedulerConfig` во время коллекции тестов.
- **`.github/workflows/pytest-check.yml`**:
  - Убраны хардкод реальных паролей БД из workflow файла; используются безопасные тестовые значения (`test_user`/`test_password_ci_2024`) только для изолированной CI‑среды.
  - Добавлены переменные окружения для Postgres и Redis на уровне job'а для корректной работы тестов в CI.
- **`docker-compose.yml`**:
  - Добавлены healthchecks для Postgres и Redis для контроля готовности сервисов.
  - Сервис `bot` теперь использует только образ `wednesday-bot:local` (без секции `build`), который собирается через `make build`.
  - Добавлены `depends_on` с условиями `service_healthy` для гарантированного запуска бота только после готовности БД.
  - Сервис `bot` переопределяет `POSTGRES_HOST` и `REDIS_HOST` для работы внутри Docker-сети.
- **`Makefile`**:
  - Команда `make test` разделена на две: `make test` (без покрытия, только junit.xml) и `make test-cov` (с покрытием, coverage.xml + junit.xml).
  - Команда `make run` переработана для полного боевого запуска: сборка образа, поднятие БД, ожидание готовности сервисов, запуск бота.
  - Команда `make build` автоматически очищает старый образ перед сборкой нового.
  - Команда `make ci` обновлена: использует `make test-cov` и добавлена проверка форматирования через `make format-check`.
  - Удалены неиспользуемые команды: `run-local`, `init-volumes`, `sync-volumes`.
- **`main.py`**:
  - Удалена жёсткая проверка наличия файла `.env` и любые обращения к `Path(".env")`.
  - `_check_requirements()` больше не зависит от наличия `.env`, а опирается на валидацию и загрузку конфигурации в `utils.config`.
  - Добавлено логирование факта наличия/отсутствия ключевых переменных (`TELEGRAM_BOT_TOKEN`, `KANDINSKY_API_KEY`, `KANDINSKY_SECRET_KEY`, `CHAT_ID`, `ADMIN_CHAT_ID`) при старте бота.
  - Добавлена инициализация пула PostgreSQL (`init_postgres_pool`) и вызов `ensure_schema()` перед запуском ботов; при ошибке подключения к Postgres запуск прерывается.
 - **`services/prompt_generator.py`**:
   - Добавлен класс `PromptStorage` с ответственностью за создание директории `data/prompts/`, сохранение и выбор случайного промпта из файлов.
   - `GigaChatClient` теперь сохраняет каждый успешно сгенерированный промпт в файловое хранилище для дальнейшего анализа и reuse.
 - **`services/image_generator.py`**:
   - Логика генерации промптов через GigaChat вынесена в отдельный слой с явным файловым fallback: при сбое GigaChat используется случайный промпт из `data/prompts/`.
   - Логика построена так, чтобы в будущем было просто подменить стратегию получения промптов (разные A/B-варианты, иные источники), не трогая основной код генерации изображений.
- **`env_example.txt`**:
  - Добавлены переменные `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD` для конфигурации Redis.
- **`utils/config.py`**:
  - Добавлены свойства `redis_url`, `redis_host`, `redis_port`, `redis_db`, `redis_password` c дефолтными значениями.
  - Добавлены свойства `postgres_user`, `postgres_password`, `postgres_db`, `postgres_host`, `postgres_port` для конфигурации PostgreSQL с разумными значениями по умолчанию.
- **`services/image_generator.py`**:
  - Встроенный in‑memory circuit‑breaker заменён на Redis‑базированный `CircuitBreaker`, с сохранением минимального локального состояния для обратной совместимости логов.
  - Добавлен слой кеширования изображений по `prompt_hash` поверх таблицы `images`: при повторной генерации с тем же нормализованным промптом бот сначала ищет запись в `images` и при наличии использует уже сохранённый файл (cache hit), а не обращается к Kandinsky.
  - Логика сохранения изображений переписана на content-addressable storage: сначала вычисляется `image_hash = sha256(file_bytes).hexdigest()`, затем файл атомарно сохраняется во временный путь и переносится в конечный `/app/data/frogs/<image_hash>.png` без перезаписи уже существующих файлов.
  - Добавлено подробное логирование этапов генерации и кеширования (start gen, cache hit, save file, db insert, race condition handled, fallback на живую генерацию при потере файла на диске).
- **Тестовая инфраструктура**:
  - `tests/conftest.py` — добавлена фикстура `cleanup_tables` для автоматической очистки таблиц между тестами, обеспечивающая полную изоляцию тестов
  - Все фикстуры для `UsageTracker`, `ModelsStore`, `AdminsStore` теперь полностью асинхронные и корректно работают с PostgreSQL
  - Фикстура `_setup_test_postgres` изменена с `scope="session"` на `scope="function"` для пересоздания пула PostgreSQL в каждом тесте, что решает проблему конфликтов event loop между тестами
  - Добавлены тестовые переменные окружения PostgreSQL в `_session_env_defaults` для принудительного использования тестовых значений независимо от системных переменных
- **Покрытие тестами**:
  - Общее покрытие кода выросло с 43% до 65% (+22 процентных пункта)
  - Добавлено 50+ новых тестов для критичных компонентов бота и утилит
  - Все тесты используют реальные PostgreSQL хранилища для интеграционного тестирования
- **Тестовые заглушки**:
  - `tests/test_bot/test_wednesday_bot.py` — добавлены методы `add_chat` и `remove_chat` в `DummyChatsStore` для корректной работы тестов `on_my_chat_member`
  - Тесты для команд управления администраторами (`mod_command`, `unmod_command`, `list_mods_command`) используют реальный `AdminsStore` с перезагрузкой модуля для обхода патчей в `conftest.py`
- **Docker Compose для тестов**:
  - `docker-compose.test.yml` — удалён устаревший атрибут `version: "3.9"` (совместимо с современными версиями Docker Compose)
- **Конфигурация pytest-asyncio**:
  - `pyproject.toml` — изменён `asyncio_mode` с `"auto"` на `"strict"` для использования одного event loop для всех тестов

### Исправлено
- **`utils/config.py`**:
  - Обработка `PermissionError` и других исключений при загрузке `.env` файла: добавлен `try-except` блок в `_load_dotenv_if_needed()` для graceful fallback, позволяющий тестам работать без локального `.env` файла или при отсутствии прав доступа.
- **Типизация и стиль кода**:
  - Устранены все ошибки типизации `mypy`: добавлены `await` для всех асинхронных вызовов в `services/prompt_generator.py`, `services/image_generator.py`, `bot/handlers.py`, `bot/wednesday_bot.py`, `bot/support_bot.py`.
  - Исправлены ошибки `ruff` линтинга (`RUF029`, `F821`): добавлены недостающие `await` в тестах, перемещены определения классов внутри функций где необходимо.
  - Исправлены несовместимые типы и присвоения: корректные type hints для `gigachat_ok` и `current_gigachat` в `bot/handlers.py`, правильная обработка `Optional` типов.
- **Безопасность**:
  - Удалён хардкод реальных паролей БД из `.github/workflows/pytest-check.yml` и `tests/conftest.py`; используются безопасные тестовые значения только для изолированной CI‑среды.
- **Тесты**:
  - Исправлена проблема с `PermissionError` при запуске `pytest` из‑за попытки загрузки `.env` во время коллекции тестов: добавлены переменные планировщика в `base_env` фикстуру для предотвращения преждевременной загрузки `.env`.
- **Критические ошибки асинхронности в обработчиках команд**:
  - `bot/handlers.py` — исправлены все отсутствующие `await` для асинхронных вызовов:
    - `usage.increment(1)` → `await usage.increment(1)` (строки 659, 1247)
    - `self.admins_store.is_admin(user_id)` → `await self.admins_store.is_admin(user_id)` (строки 1081, 1640, 1697, 1773, 1828)
    - `self.admins_store.add_admin(user_id)` → `await self.admins_store.add_admin(user_id)` (строка 1666)
    - `self.admins_store.remove_admin(user_id)` → `await self.admins_store.remove_admin(user_id)` (строка 1739)
  - `bot/wednesday_bot.py` — исправлен отсутствующий `await` для `is_dispatched`:
    - `self.dispatch_registry.is_dispatched(...)` → `await self.dispatch_registry.is_dispatched(...)` (строка 292)
  - Устранены ошибки типа `TypeError: 'bool' object can't be awaited` и `RuntimeError: Task <Task pending>`
  - Устранены конфликты корутин при параллельных операциях с Postgres и Redis
- **Проблемы с event loop в тестах**:
  - `utils/postgres_client.py` — добавлена проверка и пересоздание пула PostgreSQL, если он был создан в другом event loop (решает проблему `RuntimeError: Task <Task pending> got Future attached to a different loop`)
  - `tests/conftest.py` — фикстура `_setup_test_postgres` теперь пересоздаёт пул для каждого теста, если он был создан в другом loop, обеспечивая корректную работу с `pytest-asyncio`
  - Исправлена проблема с использованием системных переменных окружения PostgreSQL вместо тестовых значений: добавлены принудительные тестовые значения в `_session_env_defaults`
- **Ошибки в тестах**:
  - Исправлены тесты `test_mod_command_success`, `test_unmod_command_success`, `test_list_mods_command_success` — теперь используют реальный `AdminsStore` с перезагрузкой модуля для корректной работы с PostgreSQL
  - Исправлен тест `test_on_my_chat_member_added` — добавлены методы `add_chat` и `remove_chat` в `DummyChatsStore`
  - Исправлен тест `test_start_main_command_admin_no_callback` — упрощена проверка результата выполнения команды
  - Исправлен тест `test_log_command_with_args` — улучшена работа с временными директориями для логов
- **Ошибки в коде**:
  - `utils/dispatch_registry.py` — исправлена обработка `slot_date` в методе `mark_dispatched`: добавлено преобразование строки в объект `date` через `date.fromisoformat()` для корректной работы с asyncpg (устранена ошибка `DataError: invalid input for query argument $2`)
  - Убран явный каст `$2::date` из SQL запроса, так как asyncpg корректно обрабатывает объекты `date` напрямую

### Поведение и заметки по миграции
- Redis используется только для временного состояния, кэшей и счётчиков: при его недоступности вся критичная бизнес‑логика продолжает работать, опираясь на in‑memory fallback.
- Лимитер `RateLimiter` сознательно настроен в режиме *fail‑open* при ошибках Redis, чтобы инфраструктурные сбои не блокировали пользователей. Для доменов с жёсткими требованиями по лимитам рекомендуется изменить политику на *fail‑closed*.
- Circuit‑breaker для Kandinsky теперь разделяет состояние между инстансами и переживает рестарты, что снижает нагрузку на внешний API при массовых ошибках.

---

## [5.1.0] 2025-11-24 — Реализована функциональность команды /force_send, добавлены pre-commit и pre-push хуки, документация перенесена в /docs

### Добавлено
- **Директория `/docs`**:
  - `PROJECT_SUMMARY.md`, `INSTALLATION.md` и `TYPING_GUIDE.md` перенесены в новую директорию для удобства. Вся документаци будет храниться здесь.
- **Pre-commit и pre-push хуки**:
  - Добавлены соответсвующие хуки для оптимизации разработки.
- **Команда /force_send** (`bot/handlers.py`):
  - Без аргумента: показывает список активных чатов с ID и инструкцию по использованию команды.
  - С аргументом `<chat_id>`: проверяет наличие чата в списке активных, генерирует и отправляет изображение жабы админу и в указанный чат. Если лимит генераций исчерпан, отправляет случайное изображение из архива (`data/frogs`).
  - С аргументом `all`: генерирует и отправляет жабу админу и во все чаты из `chats.json`. Если лимит исчерпан, отправляет случайное изображение из архива во все чаты.
  - Проверка лимита генераций через `UsageTracker.can_use_frog()`.
  - Автоматическое использование fallback-изображений при исчерпании лимита или ошибке генерации.
  - Отправка итогового отчёта о количестве успешных и неудачных отправок.
  - Логирование всех этапов выполнения команды.

### Изменено
- **bot/handlers.py**: полностью переработана функция `admin_force_send_command()` с реализацией полной логики отправки изображений в чаты.

---

## [5.0.0] 2025-11-21 — Добавлен Ruff (lint, format) и улучшенный CI, масштабное улучшение логирования во всём проекте

### Добавлено
- **Централизованная система логирования** (`utils/logger.py`):
  - Декоратор `@log_execution` для автоматического логирования начала, завершения и ошибок функций/методов.
  - Декоратор `@log_all_methods()` для автоматического применения логирования ко всем методам класса.
  - Автоматическое форматирование аргументов функций в логах (исключая `self`/`cls` для читаемости).
  - Поддержка как синхронных, так и асинхронных функций/методов.
  - Автоматическое логирование ошибок с `exc_info=True` для полного стека вызовов.
- **Полное покрытие логированием всех модулей**:
  - `main.py`: логирование всех методов `BotRunner` (инициализация, запуск, остановка, обработка сигналов, очистка ресурсов).
  - `bot/handlers.py`: логирование всех команд и методов `CommandHandlers` (21 метод).
  - `bot/wednesday_bot.py`: логирование всех методов основного бота (инициализация, настройка обработчиков, отправка сообщений, запуск/остановка).
  - `bot/support_bot.py`: логирование всех методов резервного бота (инициализация, команды, запуск/остановка).
  - `services/image_generator.py`: логирование всех методов генератора изображений (генерация, проверка API, работа с моделями).
  - `services/prompt_generator.py`: логирование всех методов клиента GigaChat (получение токенов, генерация промптов, работа с моделями).
  - `services/scheduler.py`: логирование всех методов планировщика задач (планирование, проверка задач, запуск/остановка).
  - `utils/*.py`: логирование всех методов хранилищ и утилит (`ChatsStore`, `AdminsStore`, `UsageTracker`, `Metrics`, `ModelsStore`, `DispatchRegistry`).
- Добавлена полноценная интеграция Ruff.
- Включены расширенные правила (Bugbear, Comprehensions, Annotations и др.).
- Настроены форматирование, сортировка импортов и автоисправление.
- Создан Makefile с едиными командами для разработчиков.
- Добавлен новый reusable workflow GitHub Actions для линтинга.
- Интегрирован Ruff в основной CI-пайплайн.

### Изменено
- **Улучшена детализация логов**:
  - Каждая функция/метод логирует начало выполнения с параметрами.
  - Успешное завершение функций логируется с результатами (где применимо).
  - Все ошибки логируются с полным стеком вызовов через `exc_info=True`.
  - Логирование важных изменений состояния (изменение флагов, сохранение данных, отправка сообщений).
  - Логирование до и после ключевых `await` вызовов в async функциях.
- **Структура логов**:
  - Единый формат логов с указанием функции, параметров и результатов.
  - Исключение служебных параметров (`self`, `cls`) из логов для улучшения читаемости.
  - Автоматическое форматирование сложных объектов (словари, списки) в логах.

### Исправлено
- Исправлен тест `test_generate_prompt_success`: добавлен метод `_clean_prompt` в мок-класс `_DummyGigaChatClient` в `tests/conftest.py` для корректной обработки промптов в тестах.
- Исправлен тест `test_schedule_methods_register_tasks`: согласовано время выполнения задач (`12:00`) и интервал (`60` минут) между регистрацией задач и проверками в тесте.
- Исправлен тест `test_mypy_config_present`: обновлён для проверки конфигурации mypy через секцию `[tool.mypy]` в `pyproject.toml` вместо отдельного файла `mypy.ini`.
- **services/scheduler.py:188**: Исправлена передача аргумента `slot_time` в функцию `send_wednesday_frog` — изменено с keyword argument на positional argument для соответствия сигнатуре функции.
- **tests/test_services/test_prompt_generator.py**: Исправлены ошибки присвоения методов и использования `assert_called_once`:
  - Заменено прямое присвоение `client.session.post = MagicMock(...)` на использование `monkeypatch.setattr()` для корректной типизации.
  - Исправлено использование `assert_called_once()` на объекте типа `Callable` — теперь используется mock-объект напрямую.
  - Обновлены тесты `test_get_access_token_success`, `test_get_access_token_bad_status`, `test_get_access_token_timeout`, `test_generate_prompt_success`.
- **bot/handlers.py:753**: Добавлена проверка на `None` для `status_message` перед вызовом метода `delete()` для предотвращения ошибки `Item "None" of "Message | None" has no attribute "delete"`.
- **bot/wednesday_bot.py:359, 396, 397**: Исправлены несовместимые типы аргументов и присвоений:
  - Исправлено определение `error_details` на строке 351 — убрана запятая в конце, чтобы переменная имела тип `str` вместо `tuple[str]`.
  - Исправлен вызов `_send_admin_error()` — теперь передаётся строка вместо tuple.
  - Исправлен вызов `logger.error()` — теперь передаётся строка вместо tuple.
- **main.py:119**: Исправлен тип аргумента `request_start_main` для `SupportBot`:
  - Функция `request_start_main` теперь объявлена как `async def` для соответствия ожидаемому типу `Callable[[dict[str, Any]], Awaitable[None]]`.

---

## [4.0.0] 2025-11-15

### Добавлено
- Полная типизация проекта с использованием mypy и PEP 484/604:
  - Добавлены аннотации типов во всех модулях: `bot/wednesday_bot.py`, `bot/support_bot.py`, `bot/handlers.py`, `services/image_generator.py`, `services/prompt_generator.py`, `services/scheduler.py`, `utils/*.py`, `main.py`.
  - Создан `mypy.ini` с строгими правилами проверки типов (`disallow_untyped_defs`, `disallow_incomplete_defs`).
  - Добавлены диагностические тесты `tests/test_typing.py` для проверки корректности типизации в CI.
  - Использование современных типов: `Optional`, `Union`, `Callable`, `List`, `Dict`, `Tuple`, `Set`, `Literal`, `Protocol`, `Final`.
  - Типизация Telegram-бота: корректные типы для `Update`, `ContextTypes`, `Message`, `Chat`, `User`.
  - Безопасная работа с Optional: добавлены проверки на `None` для `update.message`, `update.effective_user`, `update.effective_chat` во всех обработчиках.
  - Типизация асинхронных операций: корректные типы для `async def` функций и `Callable[[], Awaitable[None]]`.
  - Типизация хранилищ данных: корректные типы для JSON-хранилищ (`Dict[str, Any]`, `TypedDict` где применимо).
  - Типизация HTTP-клиентов: `aiohttp.ProxyConnector`, `aiohttp.ClientSession` с правильными типами.
  - Вспомогательный метод `ImageGenerator._get_auth_headers()` для безопасного получения заголовков авторизации с проверкой ключей.
- Автоматическая отправка результатов тестов в Codecov при push и PR.
- Каркас автоматических тестов:
  - Структура `tests/` с юнит-тестами для `utils.config`, `services.prompt_generator`, `services.image_generator` и Telegram-обработчиков.
  - `pytest.ini` с настройками запуска и добавлением корня проекта в `PYTHONPATH`.
  - GitHub Actions workflow `.github/workflows/ci.yml` для прогонов тестов и проверки типов при `push`/`pull request`.
- Фикстуры `pytest`:
  - Сессионная фикстура для подстановки обязательных переменных окружения, позволяющая запускать тесты без `.env`.
  - In-memory замены `ModelsStore` и `AdminsStore`, заглушка `GigaChatClient`, моки Telegram-контекста.
- Документация тестов `tests/README.md` с инструкциями по локальному запуску.
- Дополнительные модульные тесты: покрытие ключевых обработчиков (`CommandHandlers`, `WednesdayBot`, `SupportBot`), а также утилит `models_store.py`, `usage_tracker.py` и планировщика задач.

### Изменено
- Типы возвращаемых значений в `utils/config.py`: свойства `telegram_token`, `kandinsky_api_key`, `kandinsky_secret_key`, `chat_id` теперь возвращают `Optional[str]` вместо `str` для корректной типизации.
- Добавлены проверки и assert для обязательных конфигурационных значений при инициализации ботов.
- Улучшена типизация контекста: `on_my_chat_member` теперь использует `ContextTypes.DEFAULT_TYPE` вместо `Any`.
- Все обработчики команд проверяют наличие `update.message` и `update.effective_user` перед использованием.
- `tests/conftest.py` расширен дополнительными фикстурами для валидной инициализации сервисов и очистки окружения между тестами.
- Тесты `test_config_missing_required_env`, `test_prompt_generator`, `test_image_generator` скорректированы для корректной обработки ошибок и моков.
- Workflow CI/CD переработан:
  - Основной workflow `ci.yml` разделён на отдельные job'ы: `type-check` (проверка типов через mypy) и `test` (запуск pytest с покрытием).
  - Добавлена отправка результатов тестов (junit.xml) в Codecov через `codecov/test-results-action@v1`.
  - Настроен полный отчёт о покрытии кода (XML и терминальный формат) с интеграцией в Codecov.

### Исправлено
- Исправлены ошибки типизации: все функции имеют явные аннотации return type и argument type.
- Исправлены несовместимые типы: `str | None` вместо `str` где применимо, удалены возвраты `Any` где возможно.
- Исправлены union-attr ошибки: добавлены проверки на `None` для Optional атрибутов (`update.message`, `status_message`, `next_run`, `self.bot`, и т.д.).
- Исправлены ошибки override сигнатур: все переопределения методов соответствуют сигнатурам родительских классов.
- Исправлены неправильные типы переменных: добавлены явные аннотации для `connector`, `candidates`, `models_list`, `api_models`, `targets`, `chat_id_val`, `pipeline_id`, `uuid_value` и других переменных.
- Исправлены проблемы в `image_generator`:
  - Корректная типизация для `aiohttp.ProxyConnector.from_url()` с использованием `type: ignore[attr-defined]` для совместимости с mypy.
  - Создан метод `_get_auth_headers()` для безопасного получения заголовков авторизации с проверкой ключей API.
  - Добавлено явное приведение к `str` для значений, полученных из API ответов (pipeline_id, uuid) для устранения возврата `Any`.
- Исправлены ошибки `no-redef`: переименованы локальные переменные (`chat_id_val` → `chat_id_error_val`, `model_name` → `matched_model_name`/`selected_model_name`, `pipeline_id` → `selected_pipeline_id`) для избежания конфликтов имён в одной области видимости.
- Исправлены ошибки `method-assign` в тестах: использование `monkeypatch.setattr()` вместо прямого присваивания методов для корректной типизации моков (`test_prompt_generator`, `test_image_generator`).
- Исправлены проблемы с `Generator` фикстурами: добавлены явные типы возврата `Generator[None, None, None]` для всех фикстур в `tests/conftest.py`.
- Исправлена сигнатура `ModelsStore.set_kandinsky_available_models`: теперь поддерживает `List[Dict[str, Any]] | List[str]` для совместимости с тестами.
- Исправлена обработка `last_error` в `CommandHandlers._retry_on_connect_error`: добавлена проверка на `None` перед `raise` для корректной типизации.
- Исправлена типизация `chats_info` в `CommandHandlers.status_command`: изменён тип на `str | int` для поддержки как строковых, так и числовых значений.
- Исправлены проблемы с проверкой `models_data` в `GigaChatClient.get_available_models`: добавлена проверка на `None` перед итерацией.
- Устранены потенциальные ошибки при работе с Optional значениями: добавлены проверки перед вызовом методов (например, `status_message.delete()`, `next_run.weekday()`, `updater.start_polling()`).
- Исключены `ModuleNotFoundError` при запуске `pytest` за счёт добавления `pythonpath = .`.
- Исправлены `AttributeError` в тестах, связанных с моками `ModelsStore`, `GigaChatClient`, `Path.write_bytes`.
- Устранён `ValueError` при повторной инициализации `Config` в teardown благодаря восстановлению переменных окружения в тестах.
- Исправлен `SyntaxWarning` в `tests/conftest.py`: убран `return None` из `finally` блока в фикстуре `reload_config`.

---

## [3.0.0] - 2025-11-11

### Добавлено
- Дополнительная стабилизация сети:
  - Принудительное `http_version: "1.1"` для `HTTPXRequest` у обоих ботов.
  - Warmup `get_me()` и повторная инициализация при `ExtBot is not properly initialized` у `SupportBot`.
- Админ-команды:
  - `/set_frog_limit <threshold>` — установить порог ручных генераций `/frog` (макс. 100, не выше квоты).
  - `/set_frog_used <count>` — установить текущее значение выработки `/frog` за месяц (0..квота).
- Персистентность лимитов в `usage_stats.json`:
  - Теперь файл хранит секцию `settings` с `monthly_quota` и `frog_threshold`.
  - Базовые значения записываются при первом запуске; изменения через команды сохраняются.
- Цепочка переключения SupportBot → основной:
  - SupportBot отправляет “🚀 Запускаю основной бот...”.
  - При своём выключении добавляет строку “🛑 Support Bot остановлен”.
  - После фактического запуска основной редактирует сообщение на “🛑 Support Bot остановлен\n✅ Wednesday Frog Bot запущен”.
- Команда `/stop` (только для админа): полностью останавливает бота с корректным завершением планировщика и polling.
- Резервный бот (поддержка): автоматически запускается при остановке основного бота (по ошибке, сигналу или команде `/stop`).
  - Отвечает на любые неизвестные команды сообщением о техработах.
  - Команда `/log` (только админ): отправляет последний файл логов (и у основного, и у резервного бота).
  - Поддерживает параметр `count`: `/log [count]` — отправляет логи за N дней (1..10). Если аргумент не число — сообщает об ошибке; если больше 10 — ограничивает до 10 и сообщает об ограничении.
  - Команда `/start` (только админ): запускает основной бот и останавливает резервный.
  - При `/stop` финальное сообщение об остановке отправляется также в чат-источник команды.
  - Команда `/help` (только админ): справка по командам резервного бота.
  - При запуске основного через `/start` в резервном боте: отправляется статусное сообщение "🚀 Запускаю...", затем основной бот редактирует его на "✅ Основной бот запущен".
  - При остановке основного через `/stop`: основной бот отправляет "🛑 Останавливаю...", после переключения резервный бот редактирует это сообщение на финальное "🛑 Wednesday Frog Bot остановлен! ...".

### Изменено
- Инфраструктура запуска переработана для взаимного переключения между основным и резервным ботами, исключая одновременную работу на одном токене.
 - По умолчанию при запуске приложения стартует SupportBot; основной включается по команде `/start` от админа.
- Поведение сообщений в админ-чате: только полные сообщения о старте/остановке ботов; редактируемые статусные сообщения не используются.
- Сообщение о старте основного теперь отправляется также в админ-чат (если отличается от `CHAT_ID`) без дублей.
- `/help` основного бота дополнено новыми командами управления лимитами (`/set_frog_limit`, `/set_frog_used`).

### Исправлено
- Улучшена устойчивость к сетевым ошибкам при старте и polling в условиях нестабильного соединения/блокировок.
- Ctrl+C при активном основном боте: супервизор возвращается к SupportBot (флаги остановки сбрасываются), а не завершает приложение.
- /stop в не-админ чатах: после переключения на SupportBot финальное статусное сообщение дополнено строкой о запуске резервного бота.
- Pool timeout при остановке SupportBot: остановка polling выполняется перед отправкой уведомлений админам, добавлена короткая пауза.
- Очистка `pending_*` состояний и флага `_stop_message_sent` предотвращает повторные сообщения об остановке при последовательных /stop и сигналах.
- Финальное сообщение об остановке основного отправляется после остановки polling, чтобы не занимать connection pool.
- Конфликт при остановке `/stop`: добавлена задержка перед запуском резервного бота, чтобы дать PTB завершить финальный `getUpdates` cleanup и избежать `Conflict: terminated by other getUpdates request`.
- Повторная генерация при рестарте в тот же день: привязка слота отправки к ближайшему запланированному времени (а не к текущей минуте), что предотвращает дубликаты после перезапуска благодаря `dispatch_registry`.
- Планировщик больше не выполняет слоты «задним числом» после рестарта: выполнение слота только в окне `[0, CHECK_INTERVAL)` сек после целевого времени. В `send_wednesday_frog` перед генерацией выполняется проверка, что в слоте есть хотя бы один чат без отправки; иначе генерация пропускается.
- Стабилизация переключения на резервного бота: увеличена пауза до 5с перед его запуском и добавлен ретрай `start_polling` при `Conflict`, чтобы гарантировать отсутствие параллельных `getUpdates`.
 - Graceful shutdown: при сигнале во время работы основного — останавливается только основной и автоматически запускается резервный; при сигнале во время работы резервного — завершается приложение полностью.
 - Двойное срабатывание на один Ctrl+C: перед запуском резервного бота сбрасываются флаги остановки (создаётся новый `shutdown_event`, `should_stop=False`), чтобы SupportBot не ловил тот же сигнал.
 - Дублирование финального сообщения при `/stop`: основной бот больше не отправляет своё финальное сообщение, если его уже обязан завершить SupportBot (редактирование статусного сообщения).
 - /help основного бота дополнен описанием команды `/log`.
 - /help резервного бота обновлён с описанием параметра `count` для `/log`.
 - Убрано сообщение "✅ Основной бот запущен" при запуске из SupportBot.
 - Видимость логов SupportBot в терминале: добавлены дополнительные консольные сообщения при старте/остановке.
 - Подробное логирование SupportBot: логируются вызовы команд (/help, /log, /start, unknown), выбранный файл логов и успешная отправка.
 - Финальные сообщения и уведомления:
   - При остановке основного добавлена информация о запуске SupportBot.
   - SupportBot уведомляет админов о своём запуске и остановке.
   - Цепочка сообщений при `/start`: одно сообщение обновляется по шагам.
   - Цепочка сообщений при `/stop`: сначала статус меняется на "Основной бот остановлен", затем добавляется строка о запуске SupportBot.
 - Снижение ошибок cleanup `getUpdates`: уменьшены таймауты connect/read (5с/10с) в обоих ботах, чтобы быстрее завершать очистку при сетевых проблемах.
 - Ошибка `Pool timeout` (HTTPX): увеличен пул соединений до 20 и уменьшён pool timeout до 5с через `HTTPXRequest` в обоих ботах.
 - Исправлена ошибка конфигурации PTB: при использовании `HTTPXRequest` убраны builder-параметры `get_updates_*_timeout` (иначе RuntimeError: "The parameter `connect_timeout` may only be set, if no request instance was set."). Таймауты задаются в `HTTPXRequest`.
 - Надёжный старт при сетевых сбоях: добавлены ретраи запуска (initialize/start) SupportBot с экспоненциальной задержкой; увеличены таймауты HTTPX (connect=15с, read=20с).

### Удалено
- Команда `/set_frog_rate` — признана избыточной.
- Команда `/set_usage_total` — заменена на `/set_frog_used` (корректировка текущей выработки).
- Улучшена устойчивость к сетевым ошибкам при старте и polling в условиях нестабильного соединения/блокировок.
- Ctrl+C при активном основном боте: супервизор возвращается к SupportBot (флаги остановки сбрасываются), а не завершает приложение.
- /stop в не-админ чатах: после переключения на SupportBot финальное статусное сообщение дополнено строкой о запуске резервного бота.
- Pool timeout при остановке SupportBot: остановка polling выполняется перед отправкой уведомлений админам, добавлена короткая пауза.

---

## [2.0.0] - 2025-11-03

### Добавлено
- Генерация промптов через GigaChat с fallback на статические при ошибках.
- Dry-run проверки API:
  - Kandinsky: запрос `/key/api/v1/pipelines` без траты генераций; сохранение списка моделей.
  - GigaChat: получение токена без расхода токенов модели; запрос доступных моделей `GET /api/v1/models`.
- Хранилище моделей `utils/models_store.py` и `data/models.json`:
  - Текущая и доступные модели для Kandinsky и GigaChat.
- Хранилище админов `utils/admins_store.py` и `data/admins.json`.
- Команда `/list_models` (админ): выводит доступные модели обеих систем, отмечает текущие.
- Новые админ-команды: `/force_send`, `/add_chat`, `/remove_chat`, `/list_chats`, `/set_kandinsky_model`, `/set_gigachat_model`, `/mod`, `/unmod`, `/list_mods`.
- Расширенное логирование: подробные debug-логи в dry-run и при сохранении списков моделей.
- Повторные попытки (до 3) при `httpx.ConnectError` для всех команд (отправка сообщений/медиа).

### Изменено
- `/status` доступна только админам и объединяет функциональность старых `/admin_status` и `/health`.
- `/help`: у пользователей убрана информация о логах; показана дата ближайшей авто-отправки. У админов — расширенная справка по новым командам.
- Админ-команды без префикса `admin_` для удобства.
- Метрики: отображаются успешные, всего и процент успеха.
- Убрано ограничение per-user для `/frog` у администраторов.
- Улучшен graceful shutdown: гарантированная отправка финального сообщения перед остановкой компонентов.

### Исправлено
- SSL для GigaChat: поддержка пользовательского сертификата (`GIGACHAT_CERT_PATH`), параметр `GIGACHAT_VERIFY_SSL`.
- Таймауты и обработка сетевых ошибок при запросах к GigaChat (токен/промпт/модели).
- Циклический импорт `utils.config` ↔ `utils.logger` (lazy import).
- Сообщения админам при длинных трассировках: обрезка и отправка короткой версии, защита от `Message is too long`.
- Команда `/status` больше не тратит генерации.

### Удалено
- Команды: `/admin_status`, `/admin_help`, `/health`.

### Технические улучшения
- Логика кэширования и использования сохранённых списков моделей при недоступности API.
- Сохранение не более 30 изображений в `data/frogs` с удалением самых старых.
- Централизованное хранилище конфигураций моделей.

---

## [1.0.0] - 2025-09-01
- Первый релиз бота с генерацией через Kandinsky, планировщиком и базовыми командами `/start`, `/help`, `/frog`.
