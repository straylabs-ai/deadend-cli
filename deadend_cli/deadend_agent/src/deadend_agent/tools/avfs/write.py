from __future__ import annotations

from pydantic_ai import RunContext

from deadend_agent.tools.avfs.avfs import avfs
from deadend_agent.tools.tool_wrappers import with_tool_events


def _session_id_from_ctx(ctx: RunContext[object]) -> str | None:
    deps = getattr(ctx, "deps", None)
    if deps is None:
        return None
    value = getattr(deps, "session_id", None)
    return str(value) if value is not None else None


def write_text(
    path: str,
    content: str,
    *,
    session_id: str | None,
    workspace: str = "workspace",
    append: bool = False,
) -> str:
    """Write content to a virtual path without requiring a RunContext."""
    target = avfs.resolve(path, session_id=session_id, workspace=workspace)
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"Cannot write to directory: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(target, mode, encoding="utf-8") as handle:
        handle.write(content)
    virtual_path = avfs.resolve_virtual_path(path, session_id=session_id, workspace=workspace)
    return f"Wrote {len(content.encode('utf-8'))} bytes to {avfs.format_virtual_path(virtual_path)}"


@with_tool_events("avfs_write")
async def avfs_write(
    ctx: RunContext[object],
    path: str,
    content: str,
    append: bool = False,
    workspace: str = "workspace",
) -> str:
    """Write content to a file under the current workspace root."""
    session_id = _session_id_from_ctx(ctx)
    return write_text(
        path,
        content,
        session_id=session_id,
        workspace=workspace,
        append=append,
    )
