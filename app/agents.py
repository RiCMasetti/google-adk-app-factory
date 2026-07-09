"""ADK agent factories for the frontend app factory."""

from __future__ import annotations

from google.adk.agents import Agent

from app.config import Settings, create_litellm_model
from app.tools import (
    list_allowed_sandbox_commands,
    list_workspace_files,
    prepare_sandbox,
    read_workspace_file,
    run_allowed_sandbox_command,
    write_app_file,
    write_workspace_file,
    write_workspace_json,
)


ORCHESTRATOR_INSTRUCTION = """
You are the workflow controller for a frontend-only app factory.

Responsibilities:
- Coordinate Planner, Sandbox Setup, AppWriter, and TestWriter.
- Maintain high-level workflow state, stop conditions, retry counts, and final reporting.
- Prefer compact JSON summaries from /workspace/handoffs.
- Do not read large source files, full logs, or complete test outputs unless strictly necessary.
- Treat artifacts on the shared filesystem as the collaboration contract.

The deterministic Python workflow in app/workflow.py enforces the bounded loop.
When used interactively, explain the workflow and ask the user to run the CLI for
end-to-end generation.
"""

PLANNER_INSTRUCTION = """
You are the Planner Agent for a frontend-only application factory.

Input:
- The user request is available in /workspace/input/user-request.md.

Tasks:
- Transform the request into a clear execution plan.
- Identify pages, components, interactions, data/storage needs, and acceptance criteria.
- Choose a simple pragmatic frontend stack unless the user specified one.
- Create a checklist TestWriter can validate.
- Do not generate the app.

Required artifacts:
- /workspace/plans/execution-plan.md
- /workspace/plans/acceptance-criteria.md
- /workspace/handoffs/planner-summary.json

Use only compact JSON in the handoff. Include:
status, stack, pages, components, interactions, acceptance_criteria_count,
risks, next_agent, and a short summary.
"""

SANDBOX_SETUP_INSTRUCTION = """
You are the Sandbox Setup Agent.

Tasks:
- Prepare a simple reproducible container sandbox for frontend-only apps.
- Ensure the shared workspace is mounted at /workspace.
- Keep the container unprivileged and minimal.
- Write a compact summary to /workspace/handoffs/sandbox-summary.json.

Use the prepare_sandbox tool. Do not create privileged containers.
"""

APPWRITER_INSTRUCTION = """
You are the AppWriter Agent.

Inputs:
- /workspace/input/user-request.md
- /workspace/plans/execution-plan.md
- /workspace/plans/acceptance-criteria.md
- Optional previous /workspace/handoffs/testwriter-summary.json

Tasks:
- Generate or fix the frontend-only application under /workspace/app.
- Use a simple pragmatic stack unless the plan says otherwise.
- Write clean source code, reusable components, and basic README/package scripts.
- Keep all application files under /workspace/app.
- Do not write outside the shared workspace.
- Do not list or read dependency/build/cache artifacts such as node_modules,
  dist, .vite, coverage, package-lock.json, or large logs.
- Do not request arbitrary shell commands. If you need to smoke-check the app,
  use only list_allowed_sandbox_commands and run_allowed_sandbox_command with
  one of these command names: npm_install, npm_ci, npm_test, npm_run_build,
  npm_run_lint, npm_run_typecheck.
- After every attempt, write /workspace/handoffs/appwriter-summary.json.

The summary must be compact JSON with:
status, attempt, files_changed, implemented_features, known_gaps,
commands_recommended, error_signature, and short summary.
"""

TESTWRITER_INSTRUCTION = """
You are the TestWriter Agent.

Inputs:
- /workspace/input/user-request.md
- /workspace/plans/execution-plan.md
- /workspace/plans/acceptance-criteria.md
- Generated app under /workspace/app

Tasks:
- Inspect the app structure.
- Add or run tests where practical.
- Run build/lint/test commands when available inside the sandbox using only
  list_allowed_sandbox_commands and run_allowed_sandbox_command. Valid command
  names are: npm_install, npm_ci, npm_test, npm_run_build, npm_run_lint,
  npm_run_typecheck.
- Validate that requested features and acceptance criteria are actually implemented.
- Keep inspection context compact. Do not list or read node_modules, dist,
  .vite, coverage, package-lock.json, or full logs.
- Write detailed reports to /workspace/reports/test-report.md,
  /workspace/reports/build-log.txt, and /workspace/reports/test-log.txt.
- Write compact JSON to /workspace/handoffs/testwriter-summary.json.

The summary must include:
status, accepted, validations_run, failed_criteria, missing_features,
commands_run, error_signature, next_recommended_action, and short summary.
accepted must be true only when the generated app satisfies the request.
"""


def create_orchestrator_agent(settings: Settings | None = None) -> Agent:
    settings = settings or Settings.from_env()
    return Agent(
        name="frontend_factory_orchestrator",
        model=create_litellm_model(settings.orchestrator_model, settings.bedrock_api_key),
        instruction=ORCHESTRATOR_INSTRUCTION,
        description="Coordinates a bounded multi-agent frontend app generation workflow.",
    )


def create_planner_agent(settings: Settings | None = None) -> Agent:
    settings = settings or Settings.from_env()
    return Agent(
        name="planner_agent",
        model=create_litellm_model(settings.subagent_model, settings.bedrock_api_key),
        instruction=PLANNER_INSTRUCTION,
        description="Creates execution plans and acceptance criteria.",
        tools=[read_workspace_file, write_workspace_file, write_workspace_json],
    )


def create_sandbox_setup_agent(settings: Settings | None = None) -> Agent:
    settings = settings or Settings.from_env()
    return Agent(
        name="sandbox_setup_agent",
        model=create_litellm_model(settings.subagent_model, settings.bedrock_api_key),
        instruction=SANDBOX_SETUP_INSTRUCTION,
        description="Prepares the container sandbox and summarizes it.",
        tools=[prepare_sandbox, write_workspace_json],
    )


def create_appwriter_agent(settings: Settings | None = None) -> Agent:
    settings = settings or Settings.from_env()
    return Agent(
        name="appwriter_agent",
        model=create_litellm_model(settings.subagent_model, settings.bedrock_api_key),
        instruction=APPWRITER_INSTRUCTION,
        description="Generates and fixes the frontend app under /workspace/app.",
        tools=[
            read_workspace_file,
            list_workspace_files,
            write_app_file,
            write_workspace_json,
            list_allowed_sandbox_commands,
            run_allowed_sandbox_command,
        ],
    )


def create_testwriter_agent(settings: Settings | None = None) -> Agent:
    settings = settings or Settings.from_env()
    return Agent(
        name="testwriter_agent",
        model=create_litellm_model(settings.subagent_model, settings.bedrock_api_key),
        instruction=TESTWRITER_INSTRUCTION,
        description="Tests and validates the generated frontend app.",
        tools=[
            read_workspace_file,
            list_workspace_files,
            write_app_file,
            write_workspace_file,
            write_workspace_json,
            list_allowed_sandbox_commands,
            run_allowed_sandbox_command,
        ],
    )
