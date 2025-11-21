PYTHON := python3
COV_ARGS := --cov=bot --cov=services --cov=utils

.PHONY: lint format test type run ci build

lint:
	ruff check .

format:
	ruff check . --fix
	ruff format .

test:
	pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term

type:
	mypy .

run:
	$(PYTHON) main.py

ci:
	ruff check .
	ruff format --check .
	mypy .
	pytest $(COV_ARGS) --cov-report=xml:coverage.xml --cov-report=term

build:
	@echo "TODO: docker build"

