# Google ADK App Factory

Python project using Google ADK to coordinate a multi-agent frontend app factory.
The workflow plans, generates, tests, and validates a frontend-only application
under a shared workspace mounted into a Docker sandbox.

## Experimental Status

This is an experimental local development project, not a production-ready
service. It is intended to explore Google ADK multi-agent orchestration,
Bedrock-backed model calls, shared workspace handoffs, and container-based
frontend validation.

Do not expose this workflow directly to untrusted users, CI runners, public web
traffic, or production credentials without additional isolation, review gates,
and security controls. Generated applications and validation reports should be
treated as machine-generated artifacts that require human review before reuse.

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

## Dev Container

The repository includes a VS Code/Cursor compatible devcontainer for a more
reproducible local environment:

```text
.devcontainer/
  Dockerfile
  devcontainer.json
```

Open the repository in a compatible editor and choose **Reopen in Container**.
The container installs Python 3.12 tooling, `uv`, Docker CLI access, and runs:

```bash
uv sync --extra dev
```

It also installs the Codex CLI for the container user and recommends the OpenAI
ChatGPT/Codex editor extension inside the devcontainer. Run `codex login` inside
the devcontainer terminal to authenticate Codex there; host Codex credentials are
not mounted by default.

The devcontainer uses the common "Docker outside of Docker" setup so the
workflow can still start the frontend sandbox with Docker Compose. This keeps
the developer environment separate from the host Python installation, but access
to the host Docker daemon is powerful and should be treated as trusted-local
development only. Do not mount cloud credentials, SSH keys, production secrets,
or other sensitive host directories into the devcontainer unless you understand
the impact.

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

## Security Considerations

This project deliberately gives agents enough access to generate, install, run,
and validate frontend code in a Docker sandbox. That makes it useful for
experimentation, but it also creates risks that should be understood before
running arbitrary requests.

- Prompt injection: user requests, generated files, reports, web content, or
  future external data sources can contain instructions that try to override the
  agent's intended behavior. Treat all content outside the developer prompts as
  untrusted data.
- Sandbox execution: AppWriter and TestWriter can request only allowlisted
  sandbox commands through `run_allowed_sandbox_command`, for example
  `npm_install`, `npm_test`, and `npm_run_build`. Commands run inside Docker,
  but the shared `workspace` volume is mounted read/write, so generated files,
  reports, and handoffs can be modified by code running in the sandbox.
- Dependency supply chain: generated frontend apps may add dependencies and run
  package manager commands. Malicious packages, postinstall scripts, or
  compromised transitive dependencies can execute inside the sandbox.
- Report trust: validation reports are artifacts in the shared workspace. For
  stronger assurance, critical build/test commands should be run by trusted
  orchestration code and reviewed separately from agent-written summaries.
- Sensitive data: `.env` is ignored by git and should never be copied into the
  workspace or Docker environment. Avoid mounting host credentials, SSH keys,
  cloud config, or the Docker socket into the sandbox.
- Cost and resource usage: model calls, package installs, and test commands can
  consume tokens, CPU, disk, and network bandwidth. Keep timeouts, iteration
  limits, token reporting, and workspace cleanup in place.
- Generated code quality: generated apps may contain ordinary web application
  issues such as unsafe HTML rendering, insecure storage assumptions, weak
  dependency choices, or accidental calls to third-party services. Review and
  scan generated code before publishing it.

Implemented hardening:

- Agent-facing free-form sandbox shell execution has been replaced with a fixed
  allowlist: `npm_install`, `npm_ci`, `npm_test`, `npm_run_build`,
  `npm_run_lint`, and `npm_run_typecheck`.

Recommended hardening before any shared or production-like use:

- Let trusted Python orchestration run build/test/install commands instead of
  relying only on agent-selected commands and agent-written reports.
- Use per-run isolated workspaces and clean them after completion.
- Mount only the minimum required directories, preferably with read-only mounts
  for inputs, plans, and previous reports.
- Run dependency and generated-code scans such as `npm audit`, secret scanning,
  linting, and Semgrep before publishing generated apps.
- Keep web search, URL fetching, and external document ingestion disabled unless
  retrieved content is clearly isolated as untrusted data.

## Current Limitations

- Token usage is recorded through an abstraction. If ADK/LiteLLM does not expose
  usage metadata on events, the report records zero tokens with a note so real
  accounting can be added later.
- The first version favors a simple Docker Compose sandbox over a heavier
  provisioning system.
- Specialist agents are expected to keep handoff JSON compact. The orchestrator
  enforces this by passing summaries between steps instead of full logs.
- The sandbox and tool permissions are designed for local experimentation. They
  are not a complete security boundary for hostile prompts, hostile packages, or
  untrusted generated code.
