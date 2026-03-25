.PHONY: help install install-backend install-frontend up down logs test test-integration

help:
	@echo "Usage:"
	@echo "  make install              Install backend + frontend dependencies"
	@echo "  make install-backend      Install backend dependencies only"
	@echo "  make install-frontend     Install frontend dependencies only"
	@echo "  make up                   Build and start all services (docker compose)"
	@echo "  make down                 Stop all services"
	@echo "  make logs                 Follow docker compose logs"
	@echo "  make test                 Run unit tests (no external dependencies required)"
	@echo "  make test-integration     Run integration tests (requires network + API keys)"

install: install-backend install-frontend

install-backend:
	cd backend && poetry install --no-root

install-frontend:
	cd frontend && poetry install --no-root

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && poetry run pytest tests/unit -v

test-integration:
	cd backend && poetry run pytest tests/integration -v -m integration
