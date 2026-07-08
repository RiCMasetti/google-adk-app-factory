"""Filesystem helpers for the shared workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKSPACE_DIRS = (
    "input",
    "app",
    "plans",
    "handoffs",
    "reports",
    "metrics",
    "sandbox",
)

CONTEXT_HEAVY_DIRS = frozenset(
    {
        ".git",
        ".cache",
        ".next",
        ".nuxt",
        ".parcel-cache",
        ".pytest_cache",
        ".ruff_cache",
        ".turbo",
        ".vite",
        "coverage",
        "dist",
        "node_modules",
    }
)
CONTEXT_HEAVY_FILES = frozenset(
    {
        ".package-lock.json",
        "bun.lockb",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
DEFAULT_LIST_FILES_LIMIT = 500


class WorkspaceError(ValueError):
    """Raised when a workspace path is invalid."""


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    def ensure_layout(self) -> None:
        for directory in WORKSPACE_DIRS:
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise WorkspaceError(f"Workspace paths must be relative: {relative}")

        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspaceError(f"Path escapes workspace: {relative}")
        return candidate

    def write_text(self, relative_path: str | Path, content: str) -> Path:
        target = self.path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read_text(self, relative_path: str | Path, max_chars: int) -> str:
        target = self.path(relative_path)
        data = target.read_text(encoding="utf-8")
        if len(data) > max_chars:
            return data[:max_chars] + "\n...[truncated]"
        return data

    def write_json(self, relative_path: str | Path, payload: dict[str, Any] | list[Any]) -> Path:
        return self.write_text(relative_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def read_json(self, relative_path: str | Path) -> Any:
        return json.loads(self.path(relative_path).read_text(encoding="utf-8"))

    def exists(self, relative_path: str | Path) -> bool:
        return self.path(relative_path).exists()

    def list_files(
        self,
        relative_path: str | Path,
        max_files: int = DEFAULT_LIST_FILES_LIMIT,
    ) -> list[str]:
        base = self.path(relative_path)
        if not base.exists():
            return []
        if base.is_file():
            return [str(base.relative_to(self.root))]

        files: list[str] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.root).parts
            if any(part in CONTEXT_HEAVY_DIRS for part in relative_parts):
                continue
            if path.name in CONTEXT_HEAVY_FILES:
                continue
            files.append(str(path.relative_to(self.root)))
            if len(files) >= max_files:
                files.append(f"...[truncated after {max_files} files]")
                break
        return files

    def app_path(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise WorkspaceError(f"App paths must be relative: {relative}")
        return self.path(Path("app") / relative)

    def write_app_file(self, relative_path: str | Path, content: str) -> Path:
        target = self.app_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target
