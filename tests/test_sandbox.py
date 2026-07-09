from __future__ import annotations

from types import SimpleNamespace

from app.sandbox import SANDBOX_APP_DIR, SandboxManager
from app.workspace import Workspace


def test_run_allowed_rejects_unknown_command_without_docker(
    tmp_path, monkeypatch
) -> None:
    workspace = Workspace(tmp_path / "workspace")
    manager = SandboxManager(workspace)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr("app.sandbox.subprocess.run", fail_if_called)

    result = manager.run_allowed("rm_rf")

    assert result.status == "failed"
    assert "npm_run_build" in result.details["allowed_commands"]


def test_run_allowed_uses_fixed_command_and_cwd(tmp_path, monkeypatch) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()
    manager = SandboxManager(workspace)
    captured: dict[str, object] = {}

    def fake_run(command, cwd, text, capture_output, timeout, check):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["text"] = text
        captured["capture_output"] = capture_output
        captured["timeout"] = timeout
        captured["check"] = check
        return SimpleNamespace(returncode=0, stdout="built\n", stderr="")

    monkeypatch.setattr("app.sandbox.subprocess.run", fake_run)

    result = manager.run_allowed("npm_run_build")

    command = captured["command"]
    assert result.status == "success"
    assert command[-4:] == ["frontend-sandbox", "npm", "run", "build"]
    assert "bash" not in command
    assert "-lc" not in command
    assert command[command.index("-w") + 1] == SANDBOX_APP_DIR
    assert captured["cwd"] == str(workspace.path("sandbox"))
