.PHONY: install lint format typecheck test up down

install:
	uv sync --dev

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app

test:
	uv run pytest

up:
	docker compose up --build

down:
	docker compose down
