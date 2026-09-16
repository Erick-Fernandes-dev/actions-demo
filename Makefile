.PHONY: install lint test run docker-build docker-run

install:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check app/

test:
	pytest --cov=app --cov-report=term-missing

run:
	uvicorn app.main:app --reload

docker-build:
	docker build --build-arg APP_VERSION=local -t actions-demo:local .

docker-run:
	docker run --rm -p 8000:8000 actions-demo:local
