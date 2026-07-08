"""Token usage reporting with a placeholder-friendly abstraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import ModelConfig
from app.workspace import Workspace


@dataclass
class TokenUsageEntry:
    agent: str
    iteration: int
    model: str
    aws_bedrock_region: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    source: str
    timestamp: str
    note: str = ""


class TokenUsageRecorder:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.entries: list[TokenUsageEntry] = []

    def record(
        self,
        agent: str,
        iteration: int,
        model_config: ModelConfig,
        prompt_tokens: int,
        completion_tokens: int,
        source: str,
        note: str = "",
    ) -> None:
        total_tokens = prompt_tokens + completion_tokens
        estimated_cost_usd = (
            prompt_tokens / 1_000_000 * model_config.input_usd_per_1m
            + completion_tokens / 1_000_000 * model_config.output_usd_per_1m
        )
        self.entries.append(
            TokenUsageEntry(
                agent=agent,
                iteration=iteration,
                model=model_config.model_id,
                aws_bedrock_region=model_config.region,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=round(estimated_cost_usd, 8),
                source=source,
                note=note,
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
        self.flush()

    def record_from_events(
        self,
        agent: str,
        iteration: int,
        model_config: ModelConfig,
        events: list[Any],
    ) -> None:
        prompt_tokens = 0
        completion_tokens = 0
        source = "placeholder"
        note = "Token usage metadata was not available on ADK events."

        for event in events:
            usage = getattr(event, "usage_metadata", None) or getattr(event, "usage", None)
            if usage is None:
                continue
            prompt = (
                getattr(usage, "prompt_token_count", None)
                or getattr(usage, "input_tokens", None)
                or getattr(usage, "prompt_tokens", None)
                or 0
            )
            completion = (
                getattr(usage, "candidates_token_count", None)
                or getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", None)
                or 0
            )
            prompt_tokens += int(prompt)
            completion_tokens += int(completion)
            source = "adk_event_usage_metadata"
            note = ""

        self.record(
            agent=agent,
            iteration=iteration,
            model_config=model_config,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            source=source,
            note=note,
        )

    def totals(self) -> dict[str, int | float]:
        return {
            "prompt_tokens": sum(entry.prompt_tokens for entry in self.entries),
            "completion_tokens": sum(entry.completion_tokens for entry in self.entries),
            "total_tokens": sum(entry.total_tokens for entry in self.entries),
            "estimated_cost_usd": round(sum(entry.estimated_cost_usd for entry in self.entries), 8),
        }

    def payload(self) -> dict[str, Any]:
        return {
            "entries": [asdict(entry) for entry in self.entries],
            "totals": self.totals(),
        }

    def flush(self) -> None:
        payload = self.payload()
        self.workspace.write_json("reports/token-usage-report.json", payload)
