"""Deterministic workflow controller around the ADK specialist agents."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents import create_appwriter_agent, create_planner_agent, create_testwriter_agent
from app.config import Settings
from app.sandbox import SandboxManager
from app.usage import TokenUsageRecorder
from app.workspace import Workspace


@dataclass
class AgentRunResult:
    final_text: str
    events: list[Any]


class AgentRunTimeoutError(TimeoutError):
    """Raised when an ADK agent call exceeds the configured wall-clock timeout."""


class AgentRunError(RuntimeError):
    """Raised when an ADK agent call fails before producing a final response."""


@dataclass
class IterationEntry:
    workflow_step_number: int
    agent_called: str
    input_summary: str
    output_summary: str
    status: str
    errors: list[str]
    next_recommended_action: str
    timestamp: str
    retry_count: int


class WorkflowReporter:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.entries: list[IterationEntry] = []

    def add(
        self,
        step: int,
        agent: str,
        input_summary: str,
        output_summary: str,
        status: str,
        errors: list[str],
        next_action: str,
        retry_count: int,
    ) -> None:
        self.entries.append(
            IterationEntry(
                workflow_step_number=step,
                agent_called=agent,
                input_summary=input_summary,
                output_summary=output_summary,
                status=status,
                errors=errors,
                next_recommended_action=next_action,
                timestamp=datetime.now(UTC).isoformat(),
                retry_count=retry_count,
            )
        )
        self.flush()

    def flush(self) -> None:
        self.workspace.write_json(
            "reports/iteration-report.json", [asdict(entry) for entry in self.entries]
        )


async def run_adk_agent(
    agent,
    prompt: str,
    app_name: str,
    timeout_seconds: int,
) -> AgentRunResult:
    session_service = InMemorySessionService()
    user_id = "local-user"
    session_id = str(uuid4())
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    events: list[Any] = []
    final_text = ""
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=message,
            ):
                events.append(event)
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = "\n".join(
                        part.text for part in event.content.parts if getattr(part, "text", None)
                    )
    except TimeoutError as exc:
        raise AgentRunTimeoutError(
            f"{agent.name} exceeded AGENT_CALL_TIMEOUT_SECONDS={timeout_seconds}"
        ) from exc
    except Exception as exc:
        raise AgentRunError(f"{agent.name} failed: {type(exc).__name__}: {exc}") from exc

    return AgentRunResult(final_text=final_text, events=events)


class FrontendFactoryWorkflow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.workspace = Workspace(settings.workspace_dir)
        self.reporter = WorkflowReporter(self.workspace)
        self.token_usage = TokenUsageRecorder(self.workspace)
        self.start_time = 0.0

    async def run(self, user_request: str) -> dict[str, Any]:
        self.settings.require_configured_models()
        self.workspace.ensure_layout()
        self.workspace.write_text("input/user-request.md", user_request)
        self.start_time = time.monotonic()
        self._write_state(
            status="running",
            current_agent=None,
            last_completed_agent=None,
            next_agent="planner_agent",
            current_iteration=0,
            appwriter_retries=0,
            testwriter_validations=0,
        )

        step = 1
        appwriter_retries = 0
        testwriter_validations = 0
        final_status = "failed"
        final_errors: list[str] = []
        repeated_error_signature = ""
        repeated_error_count = 0

        try:
            planner_ok = await self._run_planner(step)
        except (AgentRunError, AgentRunTimeoutError) as exc:
            self._write_state(
                status="timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed",
                current_agent="planner_agent",
                last_completed_agent=None,
                next_agent=None,
                current_iteration=0,
                appwriter_retries=0,
                testwriter_validations=0,
                last_error_signature=self._error_signature(exc),
            )
            return self._finalize(
                user_request=user_request,
                final_status="timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed",
                total_iterations=0,
                appwriter_retries=0,
                testwriter_validations=0,
                known_limitations=[str(exc)],
                test_results="Planner failed before tests could run.",
            )
        if not planner_ok:
            self._write_state(
                status="failed",
                current_agent="planner_agent",
                last_completed_agent=None,
                next_agent=None,
                current_iteration=0,
                appwriter_retries=0,
                testwriter_validations=0,
                last_error_signature="missing_planner_outputs",
            )
            return self._finalize(
                user_request=user_request,
                final_status="failed",
                total_iterations=0,
                appwriter_retries=0,
                testwriter_validations=0,
                known_limitations=["Planner did not produce clear acceptance criteria."],
                test_results="Planner failed before tests could run.",
            )
        step += 1

        sandbox_ok = self._prepare_sandbox(step)
        if not sandbox_ok:
            self._write_state(
                status="failed",
                current_agent="sandbox_setup_agent",
                last_completed_agent="planner_agent",
                next_agent=None,
                current_iteration=0,
                appwriter_retries=0,
                testwriter_validations=0,
                last_error_signature="sandbox_failed",
            )
            return self._finalize(
                user_request=user_request,
                final_status="failed",
                total_iterations=0,
                appwriter_retries=0,
                testwriter_validations=0,
                known_limitations=["Sandbox could not be created or started."],
                test_results="Sandbox unavailable.",
            )
        step += 1

        for iteration in range(1, self.settings.max_agent_iterations + 1):
            appwriter_retries = max(0, iteration - 1)
            try:
                await self._run_appwriter(step, iteration, appwriter_retries)
            except (AgentRunError, AgentRunTimeoutError) as exc:
                self._record_failure_token_usage(
                    "appwriter_agent", iteration, self.settings.subagent_model, exc
                )
                self.reporter.add(
                    step=step,
                    agent="appwriter_agent",
                    input_summary=f"Planner summary plus previous validation summary for iteration {iteration}.",
                    output_summary=str(exc),
                    status="timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed",
                    errors=[str(exc)],
                    next_action="stop",
                    retry_count=appwriter_retries,
                )
                final_errors.append(str(exc))
                final_status = "timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed"
                self._write_state(
                    status=final_status,
                    current_agent="appwriter_agent",
                    last_completed_agent="testwriter_agent" if testwriter_validations else "sandbox_setup_agent",
                    next_agent=None,
                    current_iteration=iteration,
                    appwriter_retries=appwriter_retries,
                    testwriter_validations=testwriter_validations,
                    last_error_signature=self._error_signature(exc),
                )
                break
            step += 1

            testwriter_validations += 1
            try:
                test_summary = await self._run_testwriter(step, iteration, appwriter_retries)
            except (AgentRunError, AgentRunTimeoutError) as exc:
                self._record_failure_token_usage(
                    "testwriter_agent", iteration, self.settings.subagent_model, exc
                )
                self.reporter.add(
                    step=step,
                    agent="testwriter_agent",
                    input_summary=f"AppWriter summary and acceptance criteria for iteration {iteration}.",
                    output_summary=str(exc),
                    status="timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed",
                    errors=[str(exc)],
                    next_action="stop",
                    retry_count=appwriter_retries,
                )
                final_errors.append(str(exc))
                final_status = "timeout" if isinstance(exc, AgentRunTimeoutError) else "agent_failed"
                self._write_state(
                    status=final_status,
                    current_agent="testwriter_agent",
                    last_completed_agent="appwriter_agent",
                    next_agent=None,
                    current_iteration=iteration,
                    appwriter_retries=appwriter_retries,
                    testwriter_validations=testwriter_validations,
                    last_error_signature=self._error_signature(exc),
                )
                break
            step += 1

            if bool(test_summary.get("accepted")):
                final_status = "accepted"
                break

            error_signature = str(test_summary.get("error_signature") or "")
            if error_signature and error_signature == repeated_error_signature:
                repeated_error_count += 1
            else:
                repeated_error_signature = error_signature
                repeated_error_count = 1

            if repeated_error_count >= 3:
                final_errors.append(
                    f"Repeated validation error without progress: {repeated_error_signature}"
                )
                final_status = "failed"
                break
        else:
            final_status = "max_iterations_reached"

        final_test_summary = self._read_handoff("testwriter-summary.json")
        test_results = str(final_test_summary.get("summary") or final_test_summary)
        known_limitations = final_errors or list(final_test_summary.get("missing_features") or [])

        return self._finalize(
            user_request=user_request,
            final_status=final_status,
            total_iterations=testwriter_validations,
            appwriter_retries=appwriter_retries,
            testwriter_validations=testwriter_validations,
            known_limitations=known_limitations,
            test_results=test_results,
        )

    async def _run_planner(self, step: int) -> bool:
        self._write_state(
            status="running",
            current_agent="planner_agent",
            last_completed_agent=None,
            next_agent="planner_agent",
            current_iteration=0,
            appwriter_retries=0,
            testwriter_validations=0,
        )
        prompt = """
Create the execution plan and acceptance criteria for this frontend app request.
Read /workspace/input/user-request.md through tools. Write all required Planner
artifacts exactly where specified. Keep the handoff JSON compact.
"""
        result = await run_adk_agent(
            create_planner_agent(self.settings),
            prompt,
            app_name="frontend_app_factory",
            timeout_seconds=self.settings.agent_call_timeout_seconds,
        )
        self.token_usage.record_from_events(
            "planner_agent", 0, self.settings.subagent_model, result.events
        )
        summary = self._read_handoff("planner-summary.json")
        has_criteria = self.workspace.exists("plans/acceptance-criteria.md") and bool(summary)
        self.reporter.add(
            step=step,
            agent="planner_agent",
            input_summary="User request path: input/user-request.md",
            output_summary=str(summary.get("summary") or result.final_text[:500]),
            status="success" if has_criteria else "failed",
            errors=[] if has_criteria else ["Missing planner summary or acceptance criteria."],
            next_action="prepare_sandbox" if has_criteria else "stop",
            retry_count=0,
        )
        if has_criteria:
            self._write_state(
                status="running",
                current_agent=None,
                last_completed_agent="planner_agent",
                next_agent="sandbox_setup_agent",
                current_iteration=0,
                appwriter_retries=0,
                testwriter_validations=0,
            )
        return has_criteria

    def _prepare_sandbox(self, step: int) -> bool:
        self._write_state(
            status="running",
            current_agent="sandbox_setup_agent",
            last_completed_agent="planner_agent",
            next_agent="sandbox_setup_agent",
            current_iteration=0,
            appwriter_retries=0,
            testwriter_validations=0,
        )
        manager = SandboxManager(self.workspace)
        prepared = manager.prepare()
        errors: list[str] = []
        status = "success" if prepared.status == "success" else "failed"

        if status == "success" and self.settings.sandbox_auto_start:
            started = manager.start()
            status = "success" if started.status == "success" else "failed"
            if started.status != "success":
                errors.append(started.message)

        summary = self._read_handoff("sandbox-summary.json")
        self.token_usage.record(
            agent="sandbox_setup_agent",
            iteration=0,
            model_config=self.settings.subagent_model,
            prompt_tokens=0,
            completion_tokens=0,
            source="deterministic_python_sandbox_manager",
            note="Sandbox files and container lifecycle are handled deterministically.",
        )
        self.reporter.add(
            step=step,
            agent="sandbox_setup_agent",
            input_summary="Prepare Docker sandbox and shared workspace volume.",
            output_summary=str(summary.get("status") or prepared.message),
            status=status,
            errors=errors,
            next_action="appwriter" if status == "success" else "stop",
            retry_count=0,
        )
        if status == "success":
            self._write_state(
                status="running",
                current_agent=None,
                last_completed_agent="sandbox_setup_agent",
                next_agent="appwriter_agent",
                current_iteration=1,
                appwriter_retries=0,
                testwriter_validations=0,
            )
        return status == "success"

    async def _run_appwriter(self, step: int, iteration: int, retry_count: int) -> None:
        self._write_state(
            status="running",
            current_agent="appwriter_agent",
            last_completed_agent="testwriter_agent" if retry_count else "sandbox_setup_agent",
            next_agent="appwriter_agent",
            current_iteration=iteration,
            appwriter_retries=retry_count,
            testwriter_validations=max(0, iteration - 1),
        )
        planner_summary = self._read_handoff("planner-summary.json")
        test_summary = self._read_handoff("testwriter-summary.json")
        compact_test_summary = self._compact_testwriter_summary(test_summary)
        prompt = f"""
Generate or fix the frontend app for iteration {iteration}.

Use these compact summaries only:
Planner summary:
{json.dumps(planner_summary, indent=2)}

Previous TestWriter summary, if any:
{json.dumps(compact_test_summary, indent=2)}

Read detailed plan and acceptance criteria through tools only when needed.
Do not list or read dependency, build, cache, coverage, or lockfile artifacts
such as node_modules, dist, .vite, coverage, or package-lock.json.
Write all app files under /workspace/app and update appwriter-summary.json.
"""
        result = await run_adk_agent(
            create_appwriter_agent(self.settings),
            prompt,
            app_name="frontend_app_factory",
            timeout_seconds=self.settings.agent_call_timeout_seconds,
        )
        self.token_usage.record_from_events(
            "appwriter_agent", iteration, self.settings.subagent_model, result.events
        )
        summary = self._read_handoff("appwriter-summary.json")
        self.reporter.add(
            step=step,
            agent="appwriter_agent",
            input_summary=f"Planner summary plus previous validation summary for iteration {iteration}.",
            output_summary=str(summary.get("summary") or result.final_text[:500]),
            status=str(summary.get("status") or "completed"),
            errors=list(summary.get("errors") or []),
            next_action="testwriter",
            retry_count=retry_count,
        )
        self._write_state(
            status="running",
            current_agent=None,
            last_completed_agent="appwriter_agent",
            next_agent="testwriter_agent",
            current_iteration=iteration,
            appwriter_retries=retry_count,
            testwriter_validations=max(0, iteration - 1),
        )

    async def _run_testwriter(
        self, step: int, iteration: int, retry_count: int
    ) -> dict[str, Any]:
        self._write_state(
            status="running",
            current_agent="testwriter_agent",
            last_completed_agent="appwriter_agent",
            next_agent="testwriter_agent",
            current_iteration=iteration,
            appwriter_retries=retry_count,
            testwriter_validations=iteration,
        )
        appwriter_summary = self._read_handoff("appwriter-summary.json")
        prompt = f"""
Validate the generated frontend app for iteration {iteration}.

Use this compact AppWriter summary:
{json.dumps(appwriter_summary, indent=2)}

Read the acceptance criteria and inspect the app through tools. Run build, lint,
and tests inside the sandbox only through list_allowed_sandbox_commands and
run_allowed_sandbox_command. Write detailed reports and testwriter-summary.json.
"""
        result = await run_adk_agent(
            create_testwriter_agent(self.settings),
            prompt,
            app_name="frontend_app_factory",
            timeout_seconds=self.settings.agent_call_timeout_seconds,
        )
        self.token_usage.record_from_events(
            "testwriter_agent", iteration, self.settings.subagent_model, result.events
        )
        summary = self._read_handoff("testwriter-summary.json")
        accepted = bool(summary.get("accepted"))
        self.reporter.add(
            step=step,
            agent="testwriter_agent",
            input_summary=f"AppWriter summary and acceptance criteria for iteration {iteration}.",
            output_summary=str(summary.get("summary") or result.final_text[:500]),
            status="accepted" if accepted else "requires_iteration",
            errors=list(summary.get("failed_criteria") or summary.get("missing_features") or []),
            next_action="final_report" if accepted else "appwriter_retry",
            retry_count=retry_count,
        )
        self._write_state(
            status="running",
            current_agent=None,
            last_completed_agent="testwriter_agent",
            next_agent="final_report" if accepted else "appwriter_agent",
            current_iteration=iteration,
            appwriter_retries=retry_count,
            testwriter_validations=iteration,
            last_error_signature=str(summary.get("error_signature") or ""),
        )
        return summary

    def _read_handoff(self, filename: str) -> dict[str, Any]:
        path = f"handoffs/{filename}"
        if not self.workspace.exists(path):
            return {}
        try:
            payload = self.workspace.read_json(path)
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _compact_testwriter_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        if not summary:
            return {}

        failed_criteria = summary.get("failed_criteria")
        if isinstance(failed_criteria, list):
            failed_criteria = failed_criteria[:10]

        return {
            "accepted": summary.get("accepted"),
            "status": summary.get("status"),
            "summary": summary.get("summary"),
            "error_signature": summary.get("error_signature"),
            "next_recommended_action": summary.get("next_recommended_action"),
            "failed_criteria": failed_criteria,
            "missing_features": summary.get("missing_features"),
            "commands_run": summary.get("commands_run"),
        }

    def _write_state(
        self,
        status: str,
        current_agent: str | None,
        last_completed_agent: str | None,
        next_agent: str | None,
        current_iteration: int,
        appwriter_retries: int,
        testwriter_validations: int,
        last_error_signature: str = "",
    ) -> None:
        runtime_seconds = round(time.monotonic() - self.start_time, 3) if self.start_time else 0
        self.workspace.write_json(
            "metrics/workflow-state.json",
            {
                "status": status,
                "current_agent": current_agent,
                "last_completed_agent": last_completed_agent,
                "next_agent": next_agent,
                "current_iteration": current_iteration,
                "appwriter_retries": appwriter_retries,
                "testwriter_validations": testwriter_validations,
                "last_error_signature": last_error_signature,
                "runtime_seconds": runtime_seconds,
                "token_totals": self.token_usage.totals(),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def _error_signature(self, exc: BaseException) -> str:
        message = str(exc)
        if "prompt is too long" in message:
            return "context_window_exceeded"
        return type(exc).__name__

    def _record_failure_token_usage(
        self,
        agent: str,
        iteration: int,
        model_config,
        exc: BaseException,
    ) -> None:
        message = str(exc)
        match = re.search(r"prompt is too long:\s*(\d+)\s*tokens", message)
        if not match:
            return
        self.token_usage.record(
            agent=agent,
            iteration=iteration,
            model_config=model_config,
            prompt_tokens=int(match.group(1)),
            completion_tokens=0,
            source="bedrock_error_message",
            note="Prompt token count parsed from Bedrock context-window error.",
        )

    def _finalize(
        self,
        user_request: str,
        final_status: str,
        total_iterations: int,
        appwriter_retries: int,
        testwriter_validations: int,
        known_limitations: list[str],
        test_results: str,
    ) -> dict[str, Any]:
        self.token_usage.flush()
        runtime_seconds = round(time.monotonic() - self.start_time, 3) if self.start_time else 0
        token_report = self.workspace.read_json("reports/token-usage-report.json")
        final_payload = {
            "user_request": user_request,
            "final_status": final_status,
            "total_iterations": total_iterations,
            "total_runtime_seconds": runtime_seconds,
            "total_token_usage": token_report.get("totals", {}),
            "appwriter_retries": appwriter_retries,
            "testwriter_validations": testwriter_validations,
            "generated_application_path": str(self.workspace.path("app")),
            "test_results": test_results,
            "known_limitations": known_limitations,
            "suggested_next_improvements": [
                "Add ADK evalsets for representative frontend generation requests.",
                "Wire provider-specific token usage metadata when available.",
                "Add artifact cleanup and per-run workspace isolation if running concurrently.",
            ],
            "aws_bedrock_region_used": self.settings.bedrock_region,
            "bedrock_endpoint": self.settings.bedrock_endpoint,
            "bedrock_auth": "AWS_BEARER_TOKEN_BEDROCK configured",
            "models": {
                "orchestrator": self.settings.orchestrator_model.model_id,
                "subagents": self.settings.subagent_model.model_id,
            },
        }
        self.workspace.write_json("metrics/run-metrics.json", final_payload)
        self.workspace.write_text("reports/final-report.md", self._render_final_report(final_payload))
        self._write_state(
            status=final_status,
            current_agent=None,
            last_completed_agent="final_report",
            next_agent=None,
            current_iteration=total_iterations,
            appwriter_retries=appwriter_retries,
            testwriter_validations=testwriter_validations,
            last_error_signature="; ".join(known_limitations[:3]),
        )
        return final_payload

    def _render_final_report(self, payload: dict[str, Any]) -> str:
        limitations = payload["known_limitations"] or ["None recorded."]
        improvements = payload["suggested_next_improvements"]
        token_usage = payload["total_token_usage"]
        return f"""# Final Execution Report

## Status

- Final status: {payload["final_status"]}
- Total iterations: {payload["total_iterations"]}
- Runtime seconds: {payload["total_runtime_seconds"]}
- AppWriter retries: {payload["appwriter_retries"]}
- TestWriter validations: {payload["testwriter_validations"]}

## Generated App

- Path: {payload["generated_application_path"]}

## AWS Bedrock

- Region: {payload["aws_bedrock_region_used"]}
- Endpoint: {payload["bedrock_endpoint"]}
- Auth: {payload["bedrock_auth"]}
- Orchestrator model: {payload["models"]["orchestrator"]}
- Subagent model: {payload["models"]["subagents"]}

## Token Usage

- Prompt tokens: {token_usage.get("prompt_tokens", 0)}
- Completion tokens: {token_usage.get("completion_tokens", 0)}
- Total tokens: {token_usage.get("total_tokens", 0)}
- Estimated cost USD: {token_usage.get("estimated_cost_usd", 0)}

## Test Results

{payload["test_results"]}

## Known Limitations

{chr(10).join(f"- {item}" for item in limitations)}

## Suggested Next Improvements

{chr(10).join(f"- {item}" for item in improvements)}
"""


def run_workflow_sync(settings: Settings, user_request: str) -> dict[str, Any]:
    return asyncio.run(FrontendFactoryWorkflow(settings).run(user_request))
