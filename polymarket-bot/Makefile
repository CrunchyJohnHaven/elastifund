.PHONY: install dev test test-cov lint migrate run-engine run-api docker-up docker-down docker-logs docker-build clean help

help:
	@echo "Polymarket Trading Bot - Available Commands"
	@echo "============================================"
	@echo "make install       - Install dependencies with Poetry"
	@echo "make dev           - Install dependencies with dev extras"
	@echo "make test          - Run the default pytest suite"
	@echo "make test-cov      - Run the pytest suite with coverage"
	@echo "make lint          - Run code linting and formatting checks"
	@echo "make migrate       - Run database migrations"
	@echo "make run-engine    - Run the trading engine locally"
	@echo "make run-api       - Run the API server locally"
	@echo "make docker-build  - Build Docker images"
	@echo "make docker-up     - Start all services with Docker Compose"
	@echo "make docker-down   - Stop all services"
	@echo "make docker-logs   - View Docker Compose logs"
	@echo "make clean         - Remove build artifacts and cache"

install:
	poetry install --no-dev

dev:
	poetry install

test:
	poetry run python -m pytest

test-cov:
	poetry run python -m pytest --cov=src --cov-report=term-missing --cov-report=html

lint:
	poetry run black --check src tests
	poetry run ruff check src tests
	poetry run mypy src

format:
	poetry run black src tests
	poetry run ruff check --fix src tests

migrate:
	poetry run alembic upgrade head

migrate-down:
	poetry run alembic downgrade -1

run-engine:
	poetry run python -m src.main

run-api:
	poetry run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-clean:
	docker-compose down -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov
	rm -rf build dist *.egg-info

.DEFAULT_GOAL := help
