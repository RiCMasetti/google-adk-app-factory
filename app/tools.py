"""ADK tools exposed to specialist agents."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.sandbox import SandboxManager
from app.workspace import Workspace, WorkspaceError

MAX_TOOL_READ_CHARS = 20_000
MAX_TOOL_LIST_FILES = 500


def _workspace() -> Workspace:
    root = Path(os.getenv("WORKSPACE_DIR", "./workspace"))
    workspace = Workspace(root)
    workspace.ensure_layout()
    return workspace


def write_workspace_file(relative_path: str, content: str) -> dict:
    """Write a UTF-8 text file under the shared workspace."""

    try:
        target = _workspace().write_text(relative_path, content)
        return {"status": "success", "path": str(target)}
    except WorkspaceError as exc:
        return {"status": "error", "error": str(exc)}


def write_workspace_json(relative_path: str, json_payload: str) -> dict:
    """Write a JSON file under the shared workspace from a JSON string."""

    try:
        payload = json.loads(json_payload)
        target = _workspace().write_json(relative_path, payload)
        return {"status": "success", "path": str(target)}
    except (json.JSONDecodeError, WorkspaceError) as exc:
        return {"status": "error", "error": str(exc)}


def write_app_file(relative_path: str, content: str) -> dict:
    """Write a UTF-8 source file under /workspace/app only."""

    try:
        target = _workspace().write_app_file(relative_path, content)
        return {"status": "success", "path": str(target)}
    except WorkspaceError as exc:
        return {"status": "error", "error": str(exc)}


def read_workspace_file(relative_path: str, max_chars: int) -> dict:
    """Read a UTF-8 workspace file with a bounded character limit."""

    try:
        effective_max_chars = min(max_chars, MAX_TOOL_READ_CHARS)
        content = _workspace().read_text(relative_path, max_chars=effective_max_chars)
        return {
            "status": "success",
            "path": relative_path,
            "max_chars": effective_max_chars,
            "content": content,
        }
    except (FileNotFoundError, WorkspaceError) as exc:
        return {"status": "error", "error": str(exc)}


def list_workspace_files(relative_path: str) -> dict:
    """List context-safe files below a relative workspace path.

    Dependency, build, coverage, and cache directories are omitted.
    """

    try:
        files = _workspace().list_files(relative_path, max_files=MAX_TOOL_LIST_FILES)
        return {
            "status": "success",
            "files": files,
            "file_count": len(files),
            "max_files": MAX_TOOL_LIST_FILES,
            "ignored_directories": [
                "node_modules",
                "dist",
                "coverage",
                ".git",
                ".cache",
                ".vite",
            ],
        }
    except WorkspaceError as exc:
        return {"status": "error", "error": str(exc)}


def prepare_sandbox() -> dict:
    """Create Dockerfile and docker-compose.yml for the frontend sandbox."""

    result = SandboxManager(_workspace()).prepare()
    return {"status": result.status, "message": result.message, "details": result.details}


def run_sandbox_command(command: str, cwd: str) -> dict:
    """Run a shell command inside the frontend sandbox container."""

    result = SandboxManager(_workspace()).run(command=command, cwd=cwd)
    return {"status": result.status, "message": result.message, "details": result.details}
