PYTHON := python3

COV_ARGS := --cov=bot --cov=services --cov=utils

IMAGE_NAME := wednesday-bot

.PHONY: lint format format-check test test-cov test-no-containers test-cleanup test-up test-down type run ci build migrate

lint:
	ruff check .

format:
	ruff check . --fix
	ruff format .

# Запуск тестовых контейнеров (Postgres + Redis)
test-up:
	@echo "Запуск тестовых контейнеров Postgres и Redis..."
	@docker-compose -f docker-compose.test.yml up -d
	@echo "Ожидание готовности сервисов (до 30 секунд)..."
	@timeout=30; \
	while [ $$timeout -gt 0 ]; do \
		postgres_health=$$(docker inspect --format='{{.State.Health.Status}}' wednesday_postgres_test 2>/dev/null || echo "starting"); \
		redis_health=$$(docker inspect --format='{{.State.Health.Status}}' wednesday_redis_test 2>/dev/null || echo "starting"); \
		if [ "$$postgres_health" = "healthy" ] && [ "$$redis_health" = "healthy" ]; then \
			echo "✓ Сервисы готовы к тестированию"; \
			break; \
		fi; \
		echo "Ожидание сервисов... (Postgres: $$postgres_health, Redis: $$redis_health)"; \
		sleep 1; \
		timeout=$$((timeout-1)); \
	done; \
	if [ $$timeout -eq 0 ]; then \
		echo "✗ Таймаут ожидания готовности сервисов"; \
		$(MAKE) test-down; \
		exit 1; \
	fi

# Остановка тестовых контейнеров
test-down:
	@echo "Остановка тестовых контейнеров..."
	@docker-compose -f docker-compose.test.yml down -v
	@echo "✓ Контейнеры остановлены"

# Очистка тестовых контейнеров (используется как fallback)
test-cleanup:
	@docker-compose -f docker-compose.test.yml down -v 2>/dev/null || true

# Запуск тестов без покрытия (только junit.xml)
test: test-cleanup
	@echo "=== Запуск тестов с тестовыми контейнерами (без покрытия) ==="
	@$(MAKE) test-up || ($(MAKE) test-cleanup && exit 1)
	@POSTGRES_USER=test_user \
	 POSTGRES_PASSWORD=test_password_ci_2024 \
	 POSTGRES_DB=wednesdaydb_test \
	 POSTGRES_HOST=localhost \
	 POSTGRES_PORT=5432 \
	 REDIS_HOST=localhost \
	 REDIS_PORT=6379 \
	 REDIS_DB=0 \
	 SCHEDULER_SEND_TIMES="09:00,12:00,18:00" \
	 SCHEDULER_WEDNESDAY_DAY="2" \
	 SCHEDULER_TZ="Europe/Moscow" \
	 pytest --junitxml=junit.xml \
		-o junit_family=legacy; \
	TEST_EXIT_CODE=$$?; \
	$(MAKE) test-down; \
	exit $$TEST_EXIT_CODE

# Запуск тестов с покрытием (coverage.xml + junit.xml)
test-cov: test-cleanup
	@echo "=== Запуск тестов с тестовыми контейнерами (с покрытием) ==="
	@$(MAKE) test-up || ($(MAKE) test-cleanup && exit 1)
	@POSTGRES_USER=test_user \
	 POSTGRES_PASSWORD=test_password_ci_2024 \
	 POSTGRES_DB=wednesdaydb_test \
	 POSTGRES_HOST=localhost \
	 POSTGRES_PORT=5432 \
	 REDIS_HOST=localhost \
	 REDIS_PORT=6379 \
	 REDIS_DB=0 \
	 SCHEDULER_SEND_TIMES="09:00,12:00,18:00" \
	 SCHEDULER_WEDNESDAY_DAY="2" \
	 SCHEDULER_TZ="Europe/Moscow" \
	pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term \
		--junitxml=junit.xml \
		-o junit_family=legacy; \
	TEST_EXIT_CODE=$$?; \
	$(MAKE) test-down; \
	exit $$TEST_EXIT_CODE

# Запуск тестов без контейнеров (предполагает, что БД уже запущены)
test-no-containers:
	@echo "=== Запуск тестов без запуска контейнеров ==="
	@pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term \
		--junitxml=junit.xml \
		-o junit_family=legacy

type:
	mypy .

# Прогон миграций/инициализации схемы БД.
# Используется локально и в CI перед запуском тестов и приложений.
migrate:
	@echo "=== Прогон миграций (инициализация схемы Postgres) ==="
	@POSTGRES_USER=$${POSTGRES_USER:-test_user} \
	 POSTGRES_PASSWORD=$${POSTGRES_PASSWORD:-test_password_ci_2024} \
	 POSTGRES_DB=$${POSTGRES_DB:-wednesdaydb_test} \
	 POSTGRES_HOST=$${POSTGRES_HOST:-localhost} \
	 POSTGRES_PORT=$${POSTGRES_PORT:-5432} \
	 python -m utils.postgres_schema

# Сборка Docker-образа бота (с очисткой старого)
build:
	@echo "Очистка старого образа $(IMAGE_NAME):local..."
	@docker rmi $(IMAGE_NAME):local 2>/dev/null || true
	@echo "Сборка нового образа $(IMAGE_NAME):local..."
	@docker build -t $(IMAGE_NAME):local .
	@echo "✓ Образ собран успешно"

# Запуск бота в Docker-контейнерах (с пересборкой образа)
run: build
	@echo "=== Запуск бота в Docker-контейнерах ==="
	@echo "Поднятие боевых контейнеров Postgres и Redis..."
	@docker-compose up -d postgres redis
	@echo "Ожидание готовности сервисов..."
	@timeout=60; \
	while [ $$timeout -gt 0 ]; do \
		postgres_health=$$(docker inspect --format='{{.State.Health.Status}}' wednesday_postgres 2>/dev/null || echo "starting"); \
		redis_health=$$(docker inspect --format='{{.State.Health.Status}}' wednesday_redis 2>/dev/null || echo "starting"); \
		if [ "$$postgres_health" = "healthy" ] && [ "$$redis_health" = "healthy" ]; then \
			echo "✓ Сервисы готовы"; \
			break; \
		fi; \
		echo "Ожидание сервисов... (Postgres: $$postgres_health, Redis: $$redis_health)"; \
		sleep 2; \
		timeout=$$((timeout-1)); \
	done; \
	if [ $$timeout -eq 0 ]; then \
		echo "✗ Таймаут ожидания готовности сервисов"; \
		exit 1; \
	fi
	@echo "Запуск бота..."
	@docker-compose up bot

# Полный CI pipeline (lint, format check, type check, tests with coverage)
ci:
	@echo "=== Запуск полного CI pipeline ==="
	@$(MAKE) lint
	@$(MAKE) type
	@$(MAKE) migrate
	@$(MAKE) test-cov
	@$(MAKE) build

# Проверка форматирования без изменений
format-check:
	@ruff format --check .
