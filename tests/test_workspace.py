from __future__ import annotations

import pytest

from app.workspace import Workspace, WorkspaceError


def test_workspace_writes_and_reads_json(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()

    workspace.write_json("handoffs/example.json", {"status": "ok"})

    assert workspace.read_json("handoffs/example.json") == {"status": "ok"}


def test_workspace_rejects_absolute_paths(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")

    with pytest.raises(WorkspaceError):
        workspace.path("/tmp/outside")


def test_app_file_is_forced_under_app_directory(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()

    target = workspace.write_app_file("src/main.js", "console.log('ok')\n")

    assert target.relative_to(workspace.root).as_posix() == "app/src/main.js"


def test_list_files_skips_context_heavy_directories(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()
    workspace.write_app_file("src/main.js", "console.log('ok')\n")
    workspace.write_app_file("node_modules/pkg/index.js", "module.exports = {}\n")
    workspace.write_app_file("dist/assets/index.js", "console.log('built')\n")
    workspace.write_app_file("package-lock.json", "{}\n")

    assert workspace.list_files("app") == ["app/src/main.js"]


def test_list_files_caps_large_results(tmp_path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    workspace.ensure_layout()
    for index in range(3):
        workspace.write_app_file(f"src/file-{index}.js", "\n")

    files = workspace.list_files("app", max_files=2)

    assert files == [
        "app/src/file-0.js",
        "app/src/file-1.js",
        "...[truncated after 2 files]",
    ]
