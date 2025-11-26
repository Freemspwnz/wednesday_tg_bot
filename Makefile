PYTHON := python3

COV_ARGS := --cov=bot --cov=services --cov=utils

IMAGE_NAME := wednesday-bot
VOLUME_DATA := wednesday_data
VOLUME_LOGS := wednesday_logs

.PHONY: lint format test type run ci build run-local

lint:
	ruff check .

format:
	ruff check . --fix
	ruff format .

test:
	pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term \
		--junitxml=junit.xml \
		-o junit_family=legacy

type:
	mypy .

run:
	$(PYTHON) main.py

ci:
	ruff check .
	ruff format --check .
	mypy .
	pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term \
		--junitxml=junit.xml \
		-o junit_family=legacy

# Локальная сборка Docker-образа
build:
	docker build -t $(IMAGE_NAME):local .

# Создание volumes, если их нет
init-volumes:
	@if [ -z "$$(docker volume ls -q -f name=$(VOLUME_DATA))" ]; then \
		echo "Creating volume $(VOLUME_DATA)"; \
		docker volume create $(VOLUME_DATA); \
	fi
	@if [ -z "$$(docker volume ls -q -f name=$(VOLUME_LOGS))" ]; then \
		echo "Creating volume $(VOLUME_LOGS)"; \
		docker volume create $(VOLUME_LOGS); \
	fi

# Наполнение volumes начальными данными
# Наполнение volumes начальными данными и выставление прав
sync-volumes: init-volumes
	@echo "Syncing data/ → $(VOLUME_DATA)"
	@docker run --rm -v $(VOLUME_DATA):/v -v $(PWD)/data:/src alpine sh -c "cp -r /src/* /v || true && chown -R 1000:1000 /v"

	@echo "Syncing logs/ → $(VOLUME_LOGS)"
	@docker run --rm -v $(VOLUME_LOGS):/v -v $(PWD)/logs:/src alpine sh -c "cp -r /src/* /v || true && chown -R 1000:1000 /v"

# Локальный запуск
run-local: sync-volumes
	docker run --rm \
		--env-file .env \
		-v $(VOLUME_DATA):/app/data \
		-v $(VOLUME_LOGS):/app/logs \
		-it $(IMAGE_NAME):local
