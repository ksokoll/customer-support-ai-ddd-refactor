.PHONY: format lint test test-unit test-integration docker-build run build-store

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

lint:
	ruff check src/ tests/
	mypy src/

test:
	pytest --cov=src --cov-report=term-missing

test-unit:
	pytest -m unit

test-integration:
	pytest -m integration

docker-build:
	docker build -t customer-support-ai:latest .

run:
	uvicorn customer_support.main:app --reload

build-store:
	python -m customer_support.retrieval.store_builder
