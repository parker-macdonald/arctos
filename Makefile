.PHONY: test unit integration format

test:
	uv run pytest tests/

unit:
	uv run pytest tests/ -m unit

integration:
	uv run pytest tests/ -m integration

format:
	uv run black .
