"""Command-line entrypoint for the frontend app factory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.config import ConfigurationError, Settings, load_env_file
from app.workflow import run_workflow_sync


def _read_request(args: argparse.Namespace) -> str:
    if args.request:
        return args.request
    if args.request_file:
        return Path(args.request_file).read_text(encoding="utf-8")
    raise SystemExit("Provide --request or --request-file.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ADK frontend app factory.")
    parser.add_argument("--request", help="Frontend app request text.")
    parser.add_argument("--request-file", help="Path to a markdown/text request file.")
    parser.add_argument("--workspace", help="Override WORKSPACE_DIR.")
    parser.add_argument("--max-iterations", type=int, help="Override MAX_AGENT_ITERATIONS.")
    parser.add_argument(
        "--no-start-sandbox",
        action="store_true",
        help="Prepare sandbox files but do not start Docker Compose.",
    )
    return parser


def main() -> None:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args()

    if args.workspace:
        os.environ["WORKSPACE_DIR"] = args.workspace
    if args.max_iterations is not None:
        os.environ["MAX_AGENT_ITERATIONS"] = str(args.max_iterations)
    if args.no_start_sandbox:
        os.environ["SANDBOX_AUTO_START"] = "false"

    try:
        settings = Settings.from_env()
        result = run_workflow_sync(settings, _read_request(args))
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except KeyboardInterrupt:
        raise SystemExit(
            "Interrupted by user. Partial artifacts and reports, if any, remain under WORKSPACE_DIR."
        ) from None

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
