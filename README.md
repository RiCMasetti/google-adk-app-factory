# Google ADK App Factory

Python project using Google ADK to coordinate a multi-agent frontend app factory.
The workflow plans, generates, tests, and validates a frontend-only application
under a shared workspace mounted into a Docker sandbox.

## Agents

- Orchestrator: Claude Sonnet 4.6 via Amazon Bedrock. Controls workflow state,
  retry loops, stop conditions, metrics, and final report.
- Planner: Claude Haiku 4.5 via Amazon Bedrock. Writes plans and acceptance
  criteria.
- Sandbox Setup: Claude Haiku 4.5 plus deterministic Python sandbox setup.
- AppWriter: Claude Haiku 4.5. Writes the frontend app under `workspace/app`.
- TestWriter: Claude Haiku 4.5. Runs validation/build/test commands in the
  sandbox and writes reports.

Specialists communicate through artifacts in `workspace/`. The orchestrator
uses compact JSON summaries from `workspace/handoffs/` and avoids reading full
source files or logs.

## Workspace Layout

```text
workspace/
  input/user-request.md
  app/
  plans/execution-plan.md
  plans/acceptance-criteria.md
  handoffs/planner-summary.json
  handoffs/sandbox-summary.json
  handoffs/appwriter-summary.json
  handoffs/testwriter-summary.json
  reports/iteration-report.json
  reports/token-usage-report.json
  reports/final-report.md
  reports/test-report.md
  reports/build-log.txt
  reports/test-log.txt
  metrics/run-metrics.json
  metrics/workflow-state.json
  sandbox/Dockerfile
  sandbox/docker-compose.yml
```

Inside the container, the same shared directory is mounted at `/workspace`.

## Setup

1. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

2. Copy the example environment and set real Bedrock model IDs or inference
   profile IDs enabled in your AWS account:

   ```bash
   cp .env.example .env
   ```

3. Set `AWS_BEARER_TOKEN_BEDROCK` in `.env`. The value stays in the process
   environment and is passed to ADK's LiteLLM model wrapper as `api_key`; it is
   not written to reports.

4. Ensure Docker with Compose is available.

The project also installs `boto3` because LiteLLM's Bedrock provider imports
`boto3`/`botocore` while preparing Bedrock requests, including bearer-token
requests.

## Bedrock Configuration

Region is loaded in this order:

1. `BEDROCK_REGION`
2. `AWS_REGION`
3. `AWS_DEFAULT_REGION`
4. fallback `eu-central-1`

Only EU regions are accepted, for example:

- `eu-central-1`
- `eu-west-1`
- `eu-west-2`
- `eu-west-3`

The Bedrock Runtime endpoint is built as:

```text
https://bedrock-runtime.<region>.amazonaws.com
```

Model IDs are centralized in `.env` and `app/config.py`:

```bash
BEDROCK_ORCHESTRATOR_MODEL_ID=<claude-sonnet-4.6-bedrock-model-or-inference-profile-id>
BEDROCK_SUBAGENT_MODEL_ID=<claude-haiku-4.5-bedrock-model-or-inference-profile-id>
```

Bearer-token auth is loaded from:

```bash
AWS_BEARER_TOKEN_BEDROCK=<bedrock-api-key>
```

The value is required before agent execution. Both `python -m app.cli` and
`adk web .` load `.env` before creating ADK agents.

## Run

```bash
uv run python -m app.cli --request-file examples/frontend-request.md
```

Or:

```bash
make run
```

To prepare files without starting Docker, useful for configuration checks:

```bash
uv run python -m app.cli --request-file examples/frontend-request.md --no-start-sandbox
```

## Timeouts

Long-running model/tool loops are bounded by:

```bash
AGENT_CALL_TIMEOUT_SECONDS=900
BEDROCK_REQUEST_TIMEOUT_SECONDS=300
```

`AGENT_CALL_TIMEOUT_SECONDS` is the wall-clock limit for one ADK specialist
call. `BEDROCK_REQUEST_TIMEOUT_SECONDS` is passed through to LiteLLM for each
Bedrock request.

If you see `LiteLLM:ERROR ... logging_worker.py ... TimeoutError`, that is a
background callback logging timeout. It is usually secondary noise, not the
root cause of a stuck generation. You can raise:

```bash
LOGGING_WORKER_MAX_TIME_PER_COROUTINE=60
```

If Bedrock reports `prompt is too long`, the usual cause is a tool returning
too much filesystem context after dependencies/builds exist. The workspace file
listing tool intentionally omits `node_modules`, `dist`, coverage/cache
directories, and lockfiles to keep retry prompts below the context limit.

## ADK Web

The repository exposes `app/agent.py` with `root_agent` for ADK tools:

```bash
make web
```

The full bounded workflow is implemented in `app/workflow.py` and run through
`app.cli`.

## Verification

```bash
make test
make lint
```

`pytest` validates local configuration and workspace safety. End-to-end agent
quality should be evaluated with ADK evals after real Bedrock model IDs are
configured.

## Live Progress

During a run, inspect:

```bash
workspace/metrics/workflow-state.json
workspace/reports/token-usage-report.json
workspace/reports/iteration-report.json
```

`workflow-state.json` is updated before and after each major agent step. The
token report is flushed after every usage record, so partial token totals remain
available even if a later agent fails.

## Current Limitations

- Token usage is recorded through an abstraction. If ADK/LiteLLM does not expose
  usage metadata on events, the report records zero tokens with a note so real
  accounting can be added later.
- The first version favors a simple Docker Compose sandbox over a heavier
  provisioning system.
- Specialist agents are expected to keep handoff JSON compact. The orchestrator
  enforces this by passing summaries between steps instead of full logs.
