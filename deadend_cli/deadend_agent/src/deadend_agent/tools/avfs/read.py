from __future__ import annotations

from pathlib import Path
from typing import Any
from pydantic_ai import RunContext

from deadend_agent.tools.avfs.avfs import avfs
from deadend_agent.tools.tool_wrappers import with_tool_events


def _session_id_from_ctx(ctx: RunContext[object]) -> str | None:
    deps = getattr(ctx, "deps", None)
    if deps is None:
        return None
    value = getattr(deps, "session_id", None)
    return str(value) if value is not None else None


def _read(
    ctx: RunContext[object],
    path: str,
    start_line: int,
    end_line: int | None,
    max_chars: int,
    workspace: str,
) -> str:
    start_line = int(start_line)
    if end_line is not None:
        end_line = int(end_line)
    max_chars = int(max_chars)

    session_id = _session_id_from_ctx(ctx)
    target = avfs.resolve(path, session_id=session_id, workspace=workspace)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must be >= start_line")
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    chunks: list[str] = []
    total_chars = 0
    truncated = False
    try:
        with open(target, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number < start_line:
                    continue
                if end_line is not None and line_number > end_line:
                    break

                remaining = max_chars - total_chars
                if remaining <= 0:
                    truncated = True
                    break

                if len(line) <= remaining:
                    chunks.append(line)
                    total_chars += len(line)
                    continue

                chunks.append(line[:remaining])
                total_chars += remaining
                truncated = True
                break
    except UnicodeDecodeError as exc:
        raise ValueError(f"File is not valid UTF-8 text: {path}") from exc

    result = "".join(chunks)
    if truncated:
        suffix = "\n...[truncated]"
        if len(result) + len(suffix) <= max_chars:
            result = f"{result}{suffix}"
    return result


def _grep(
    ctx: RunContext[object],
    pattern: str,
    path: str,
    max_results: int,
    case_sensitive: bool,
    include_hidden: bool,
    workspace: str,
) -> list[dict[str, str | int]]:
    session_id = _session_id_from_ctx(ctx)
    target = avfs.resolve(path, session_id=session_id, workspace=workspace)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    if max_results <= 0:
        return []

    Ripgrepy = _load_ripgrepy()
    search = Ripgrepy(pattern, str(target)).json().no_config().no_messages().no_ignore().m(max_results)
    if not case_sensitive:
        search = search.ignore_case()
    if include_hidden:
        search = search.hidden()

    raw_matches = search.run().as_dict
    matches: list[dict[str, str | int]] = []
    for raw_match in raw_matches:
        if raw_match.get("type") != "match":
            continue
        data = raw_match.get("data", {})
        host_path = _extract_text_field(data.get("path", {}))
        if not host_path:
            continue
        line_text = _extract_text_field(data.get("lines", {})).rstrip("\n")
        line_number = int(data.get("line_number", 0))
        submatches = data.get("submatches", [])

        if not submatches:
            matches.append(
                {
                    "path": avfs.to_virtual_path(host_path, session_id=session_id, workspace=workspace).as_posix(),
                    "line_number": line_number,
                    "match": "",
                    "context": line_text[:240],
                }
            )
        else:
            for submatch in submatches:
                matched_text = _extract_text_field(submatch.get("match", {}))
                matches.append(
                    {
                        "path": avfs.to_virtual_path(host_path, session_id=session_id, workspace=workspace).as_posix(),
                        "line_number": line_number,
                        "match": matched_text,
                        "context": line_text[:240],
                    }
                )
                if len(matches) >= max_results:
                    return matches
        if len(matches) >= max_results:
            return matches
    return matches


@with_tool_events("avfs_read")
async def avfs_read(
    ctx: RunContext[object],
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_chars: int = 100_000,
    workspace: str = "workspace",
) -> str:
    """Read a text file inside the current workspace root with optional 1-based line slicing."""
    return _read(ctx, path, start_line, end_line, max_chars, workspace)


@with_tool_events("avfs_grep")
async def avfs_grep(
    ctx: RunContext[object],
    pattern: str,
    path: str = ".",
    max_results: int = 50,
    case_sensitive: bool = False,
    include_hidden: bool = False,
    workspace: str = "workspace",
) -> list[dict[str, str | int]]:
    """Search files in the current workspace root using a regex pattern."""
    return _grep(ctx, pattern, path, max_results, case_sensitive, include_hidden, workspace)


@with_tool_events("read_workspace_file")
async def read_workspace_file(
    ctx: RunContext[object],
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_chars: int = 100_000,
) -> str:
    """Read a text file from the fixed project workspace namespace."""
    return _read(ctx, path, start_line, end_line, max_chars, "workspace")


@with_tool_events("grep_workspace_files")
async def grep_workspace_files(
    ctx: RunContext[object],
    pattern: str,
    path: str = ".",
    max_results: int = 50,
    case_sensitive: bool = False,
    include_hidden: bool = False,
) -> list[dict[str, str | int]]:
    """Search files in the fixed project workspace namespace."""
    return _grep(ctx, pattern, path, max_results, case_sensitive, include_hidden, "workspace")


@with_tool_events("read_memory_file")
async def read_memory_file(
    ctx: RunContext[object],
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_chars: int = 100_000,
) -> str:
    """Read a text file from the fixed memory workspace namespace."""
    return _read(ctx, path, start_line, end_line, max_chars, "memory")


@with_tool_events("grep_memory_files")
async def grep_memory_files(
    ctx: RunContext[object],
    pattern: str,
    path: str = ".",
    max_results: int = 50,
    case_sensitive: bool = False,
    include_hidden: bool = False,
) -> list[dict[str, str | int]]:
    """Search files in the fixed memory workspace namespace."""
    return _grep(ctx, pattern, path, max_results, case_sensitive, include_hidden, "memory")


def _load_ripgrepy() -> Any:
    try:
        from ripgrepy import Ripgrepy
    except ModuleNotFoundError as exc:
        raise RuntimeError("ripgrepy is required for avfs_grep but is not installed.") from exc
    return Ripgrepy


def _extract_text_field(value: Any) -> str:
    if isinstance(value, dict):
        if "text" in value and value["text"] is not None:
            return str(value["text"])
        if "bytes" in value and value["bytes"] is not None:
            return str(value["bytes"])
    if value is None:
        return ""
    return str(value)
