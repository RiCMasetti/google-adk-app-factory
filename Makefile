.PHONY: install run test lint web clean-workspace

install:
	uv sync --extra dev

run:
	uv run python -m app.cli --request-file examples/frontend-request.md

test:
	uv run --extra dev pytest

lint:
	uv run --extra dev ruff check .

web:
	uv run adk web .

clean-workspace:
	find workspace/app workspace/plans workspace/handoffs workspace/reports workspace/metrics -type f ! -name .gitkeep -delete
