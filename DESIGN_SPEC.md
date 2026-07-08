# DESIGN_SPEC.md

## Overview

This project implements a Google ADK based multi-agent workflow that generates,
tests, and validates a frontend-only application in a shared workspace mounted
into a container sandbox.

The workflow uses one orchestrator agent and four specialist subagents:
Planner, Sandbox Setup, AppWriter, and TestWriter. The orchestrator controls
state, retry loops, stop conditions, metrics, and final reporting. It does not
consume large source files or full logs. Specialists communicate through
filesystem artifacts and compact JSON handoff summaries.

Amazon Bedrock is the model provider through ADK's LiteLLM integration. The
orchestrator uses Claude Sonnet 4.6 and subagents use Claude Haiku 4.5. Bedrock
region, bearer-token auth, and model IDs are configured centrally and must use
EU Bedrock runtime endpoints.

## Example Use Cases

1. User requests a portfolio SPA with sections, navigation, and responsive UI.
   The system plans pages/components, generates a Vite app, runs tests/builds,
   and returns a final report.
2. User requests a frontend dashboard with filters and charts. Planner records
   expected interactions and TestWriter validates that controls exist.
3. User requests a small game or calculator. AppWriter generates the app under
   `workspace/app`, and TestWriter validates behavior with tests where possible.
4. A generated app fails validation. The orchestrator sends only the compact
   TestWriter summary back to AppWriter for a bounded correction loop.

## Tools Required

- Google ADK Python SDK for agent definitions and execution.
- LiteLLM for Amazon Bedrock model access.
- Docker with Compose for the frontend sandbox.
- Node.js tooling inside the sandbox image.
- Shared filesystem rooted at `WORKSPACE_DIR`, mounted in the container as
  `/workspace`.

## Constraints & Safety Rules

- Do not hardcode AWS credentials.
- Bedrock calls must use `AWS_BEARER_TOKEN_BEDROCK` as the bearer API key shared
  with ADK/LiteLLM.
- Do not hardcode AWS regions. Region is loaded from `BEDROCK_REGION`,
  `AWS_REGION`, or `AWS_DEFAULT_REGION`.
- Only EU Bedrock regions are accepted by configuration validation.
- Do not scatter model IDs. Keep them in `.env` and `app/config.py`.
- AppWriter writes generated app artifacts only under `/workspace/app`.
- Orchestrator reads compact JSON summaries and state files, not full app
  source trees or full logs unless a failure makes it strictly necessary.
- Stop after `MAX_AGENT_ITERATIONS`, default 5.
- Stop immediately when sandbox preparation/start fails.
- Stop when Planner cannot produce acceptance criteria.
- Stop when the same validation error repeats without progress.

## Success Criteria

- The project can be installed with `uv sync --extra dev`.
- The workflow can be started with `python -m app.cli --request-file ...`.
- Workspace artifacts are written to the requested layout.
- Sandbox files are reproducible and mount the shared workspace.
- Reports include iterations, token usage placeholders, final status, model IDs,
  region, retries, validations, and generated app path.
- Configuration rejects non-EU Bedrock regions.

## Edge Cases to Handle

- Missing or placeholder Bedrock model IDs or API key.
- Missing Docker or failed sandbox startup.
- Planner creates no acceptance criteria.
- TestWriter reports repeated equivalent failures.
- Token usage is unavailable from the model response.
- Generated app lacks package scripts for build/test/lint.
