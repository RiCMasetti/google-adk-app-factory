#!/usr/bin/env bash
set -euo pipefail

uv run python -m app.cli --request-file "${1:-examples/frontend-request.md}"

