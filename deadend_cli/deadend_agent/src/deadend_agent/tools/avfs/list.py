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


def _mount(
    ctx: RunContext[object],
    workspace_root: str,
    directory: str,
    workspace: str,
) -> str:
    session_id = _session_id_from_ctx(ctx)
    mounted = avfs.mount(
        workspace_root=workspace_root,
        directory=directory,
        session_id=session_id,
        workspace=workspace,
    )
    return f"AVFS workspace '{workspace}': {mounted} (cwd={avfs.current_directory(session_id=session_id, workspace=workspace)})"


def _umount(
    ctx: RunContext[object],
    workspace: str,
) -> str:
    avfs.umount(session_id=_session_id_from_ctx(ctx), workspace=workspace)
    return f"Unmounted AVFS workspace '{workspace}'."


def _chdir(
    ctx: RunContext[object],
    path: str,
    workspace: str,
) -> str:
    directory = avfs.chdir(path, session_id=_session_id_from_ctx(ctx), workspace=workspace)
    return f"Changed AVFS directory to {directory}"


def _list(
    ctx: RunContext[object],
    path: str,
    recursive: bool,
    include_hidden: bool,
    max_entries: int,
    workspace: str,
) -> list[dict[str, str | int | bool]]:
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


@with_tool_events("avfs_mount")
async def avfs_mount(
    ctx: RunContext[object],
    workspace_root: str,
    directory: str = ".",
    workspace: str = "workspace",
) -> str:
    """Register a workspace root and initialize the virtual working directory."""
    return _mount(ctx, workspace_root, directory, workspace)


@with_tool_events("avfs_umount")
async def avfs_umount(
    ctx: RunContext[object],
    workspace: str = "workspace",
) -> str:
    """Unmount AVFS for current session."""
    return _umount(ctx, workspace)


@with_tool_events("avfs_chdir")
async def avfs_chdir(
    ctx: RunContext[object],
    path: str,
    workspace: str = "workspace",
) -> str:
    """Change the virtual working directory inside the mounted AVFS root."""
    return _chdir(ctx, path, workspace)


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
    return _list(ctx, path, recursive, include_hidden, max_entries, workspace)


@with_tool_events("mount_workspace")
async def mount_workspace(
    ctx: RunContext[object],
    workspace_root: str,
    directory: str = ".",
) -> str:
    """Mount the current project workspace under the fixed 'workspace' namespace."""
    return _mount(ctx, workspace_root, directory, "workspace")


@with_tool_events("umount_workspace")
async def umount_workspace(
    ctx: RunContext[object],
) -> str:
    """Unmount the fixed project workspace namespace."""
    return _umount(ctx, "workspace")


@with_tool_events("chdir_workspace")
async def chdir_workspace(
    ctx: RunContext[object],
    path: str,
) -> str:
    """Change directory inside the fixed project workspace namespace."""
    return _chdir(ctx, path, "workspace")


@with_tool_events("list_workspace_files")
async def list_workspace_files(
    ctx: RunContext[object],
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
    max_entries: int = 200,
) -> list[dict[str, str | int | bool]]:
    """List files inside the fixed project workspace namespace."""
    return _list(ctx, path, recursive, include_hidden, max_entries, "workspace")


@with_tool_events("mount_memory_workspace")
async def mount_memory_workspace(
    ctx: RunContext[object],
    workspace_root: str,
    directory: str = ".",
) -> str:
    """Mount the persistent memory workspace under the fixed 'memory' namespace."""
    return _mount(ctx, workspace_root, directory, "memory")


@with_tool_events("umount_memory_workspace")
async def umount_memory_workspace(
    ctx: RunContext[object],
) -> str:
    """Unmount the fixed memory workspace namespace."""
    return _umount(ctx, "memory")


@with_tool_events("chdir_memory_directory")
async def chdir_memory_directory(
    ctx: RunContext[object],
    path: str,
) -> str:
    """Change directory inside the fixed memory workspace namespace."""
    return _chdir(ctx, path, "memory")


@with_tool_events("list_memory_files")
async def list_memory_files(
    ctx: RunContext[object],
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
    max_entries: int = 200,
) -> list[dict[str, str | int | bool]]:
    """List files inside the fixed memory workspace namespace."""
    return _list(ctx, path, recursive, include_hidden, max_entries, "memory")
