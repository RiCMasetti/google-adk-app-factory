from __future__ import annotations

from app.config import ModelConfig
from app.usage import TokenUsageRecorder
from app.workspace import Workspace


def test_token_usage_flushes_after_record(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()
    recorder = TokenUsageRecorder(workspace)
    model = ModelConfig(
        role="subagent",
        model_id="model-id",
        region="eu-central-1",
        endpoint="https://bedrock-runtime.eu-central-1.amazonaws.com",
        input_usd_per_1m=1.0,
        output_usd_per_1m=2.0,
    )

    recorder.record(
        agent="planner_agent",
        iteration=1,
        model_config=model,
        prompt_tokens=100,
        completion_tokens=50,
        source="test",
    )

    report = workspace.read_json("reports/token-usage-report.json")
    assert report["totals"]["prompt_tokens"] == 100
    assert report["totals"]["completion_tokens"] == 50
    assert report["totals"]["total_tokens"] == 150
    assert report["totals"]["estimated_cost_usd"] == 0.0002
