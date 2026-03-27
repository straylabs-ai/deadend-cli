from __future__ import annotations

import os
from pathlib import Path
from pydantic_ai import RunContext

from deadend_agent.tools.avfs.avfs import avfs
from deadend_agent.tools.tool_wrappers import with_tool_events


def _session_id_from_ctx(ctx: RunContext[object]) -> str | None:
    deps = getattr(ctx, "deps", None)
    if deps is None:
        return None
    value = getattr(deps, "session_id", None)
    return str(value) if value is not None else None


@with_tool_events("avfs_mount")
async def avfs_mount(
    ctx: RunContext[object],
    workspace_root: str,
    directory: str = ".",
    workspace: str = "workspace",
) -> str:
    """Register a workspace root and initialize the virtual working directory."""
    session_id = _session_id_from_ctx(ctx)
    mounted = avfs.mount(
        workspace_root=workspace_root,
        directory=directory,
        session_id=session_id,
        workspace=workspace,
    )
    return f"AVFS workspace '{workspace}': {mounted} (cwd={avfs.current_directory(session_id=session_id, workspace=workspace)})"


@with_tool_events("avfs_umount")
async def avfs_umount(
    ctx: RunContext[object],
    workspace: str = "workspace",
) -> str:
    """Unmount AVFS for current session."""
    avfs.umount(session_id=_session_id_from_ctx(ctx), workspace=workspace)
    return f"Unmounted AVFS workspace '{workspace}'."


@with_tool_events("avfs_chdir")
async def avfs_chdir(
    ctx: RunContext[object],
    path: str,
    workspace: str = "workspace",
) -> str:
    """Change the virtual working directory inside the mounted AVFS root."""
    directory = avfs.chdir(path, session_id=_session_id_from_ctx(ctx), workspace=workspace)
    return f"Changed AVFS directory to {directory}"


@with_tool_events("avfs_list")
async def avfs_list(
    ctx: RunContext[object],
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
    max_entries: int = 200,
    workspace: str = "workspace",
) -> list[dict[str, str | int | bool]]:
    """List files and directories inside the current workspace root."""
    session_id = _session_id_from_ctx(ctx)
    target = avfs.resolve(path, session_id=session_id, workspace=workspace)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    workspace_root = avfs.current_workspace_root(session_id=session_id, workspace=workspace)
    assert workspace_root is not None

    items: list[dict[str, str | int | bool]] = []
    if max_entries <= 0:
        return items

    if recursive:
        for current_root, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
            dirnames.sort()
            filenames.sort()
            if not include_hidden:
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]

            current_root_path = Path(current_root)
            for name in dirnames + filenames:
                if not include_hidden and name.startswith("."):
                    continue
                node = current_root_path / name
                rel = node.relative_to(workspace_root).as_posix()
                items.append(
                    {
                        "path": rel,
                        "type": "directory" if node.is_dir() else "file",
                        "size_bytes": node.stat().st_size if node.is_file() else 0,
                        "is_hidden": any(part.startswith(".") for part in Path(rel).parts),
                    }
                )
                if len(items) >= max_entries:
                    return items
    else:
        for node in sorted(target.iterdir(), key=lambda entry: entry.name):
            rel = node.relative_to(workspace_root).as_posix()
            if not include_hidden and any(part.startswith(".") for part in Path(rel).parts):
                continue
            items.append(
                {
                    "path": rel,
                    "type": "directory" if node.is_dir() else "file",
                    "size_bytes": node.stat().st_size if node.is_file() else 0,
                    "is_hidden": any(part.startswith(".") for part in Path(rel).parts),
                }
            )
            if len(items) >= max_entries:
                return items
    return items
