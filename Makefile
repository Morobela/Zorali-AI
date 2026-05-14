.PHONY: up down logs pull-model test validate zip

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

pull-model:
	docker compose exec ollama ollama pull llama3.1

test:
	pytest tests/backend

validate:
	python -m compileall backend/app tests/backend

zip:
	cd .. && zip -r zorali-ai.zip zorali-ai
