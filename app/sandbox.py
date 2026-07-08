"""Docker sandbox setup and command execution."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from app.workspace import Workspace


DOCKERFILE = """\
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git procps \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

WORKDIR /workspace/app
CMD ["bash", "-lc", "sleep infinity"]
"""

COMPOSE_FILE = """\
services:
  frontend-sandbox:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /workspace/app
    volumes:
      - ..:/workspace
    environment:
      - CI=true
    command: ["bash", "-lc", "sleep infinity"]
"""


@dataclass
class SandboxResult:
    status: str
    message: str
    details: dict[str, object]


class SandboxManager:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.compose_file = self.workspace.path("sandbox/docker-compose.yml")

    def prepare(self) -> SandboxResult:
        self.workspace.ensure_layout()
        self.workspace.write_text("sandbox/Dockerfile", DOCKERFILE)
        self.workspace.write_text("sandbox/docker-compose.yml", COMPOSE_FILE)

        summary = {
            "status": "prepared",
            "runtime": "node:22-bookworm-slim",
            "shared_volume_host": str(self.workspace.root),
            "shared_volume_container": "/workspace",
            "app_directory": "/workspace/app",
            "privileged": False,
            "tools": ["node", "npm", "corepack", "bash", "git"],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.workspace.write_json("handoffs/sandbox-summary.json", summary)
        return SandboxResult("success", "Sandbox files prepared.", summary)

    def start(self) -> SandboxResult:
        if shutil.which("docker") is None:
            result = {
                "status": "failed",
                "error": "docker executable not found",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            self.workspace.write_json("handoffs/sandbox-summary.json", result)
            return SandboxResult("failed", "Docker is not available.", result)

        command = [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "up",
            "-d",
            "--build",
        ]
        completed = subprocess.run(
            command,
            cwd=str(self.workspace.path("sandbox")),
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        status = "started" if completed.returncode == 0 else "failed"
        summary = {
            "status": status,
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
            "shared_volume_host": str(self.workspace.root),
            "shared_volume_container": "/workspace",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.workspace.write_json("handoffs/sandbox-summary.json", summary)
        if completed.returncode != 0:
            return SandboxResult("failed", "Sandbox container failed to start.", summary)
        return SandboxResult("success", "Sandbox container started.", summary)

    def run(self, command: str, cwd: str) -> SandboxResult:
        completed = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.compose_file),
                "exec",
                "-T",
                "-w",
                cwd,
                "frontend-sandbox",
                "bash",
                "-lc",
                command,
            ],
            cwd=str(self.workspace.path("sandbox")),
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        details = {
            "command": command,
            "cwd": cwd,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        status = "success" if completed.returncode == 0 else "failed"
        return SandboxResult(status, "Sandbox command completed.", details)

