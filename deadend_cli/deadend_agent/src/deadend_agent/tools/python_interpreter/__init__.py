# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter tool for executing Python code in sandboxed environments.

This module provides functionality to execute Python code safely within
sandboxed environments, enabling AI agents to run Python scripts and
code snippets for security research and analysis tasks.
"""
from deadend_agent.constants import CACHE_DEADEND_LOGS, DEADEND_AGENTS_PATH
import json
from pathlib import Path
from typing import Any
from pydantic_ai import RunContext

from deadend_agent.logging import logger
from deadend_agent.utils.functions import truncate_string
from .python_interpreter import PythonInterpreter
from deadend_agent.tools.tool_wrappers import with_tool_events
from deadend_agent.auth_resolver import AuthContextHandler, safe_auth_summary



@with_tool_events("read_auth_storage")
async def read_auth_storage(
    ctx: Any,
    profile: str = "default",
    include_secrets: bool = False,
) -> str:
    """Return JSON metadata about a saved authentication context.

    By default this returns a *safe* summary (cookie names, storage keys,
    header names, final URL). Real cookie/token values are only returned when
    ``include_secrets=True`` and should be reserved for sandboxed code paths
    that strictly need the raw material.

    The function accepts either a ``RunContext`` (with ``deps.target``,
    ``deps.agent_id``, ``deps.session_id``) or a plain string treated as
    ``session_id`` for backward compatibility.
    """
    target: str | None = None
    agent_id: Any = None
    session_id: Any = None

    deps = getattr(ctx, "deps", None) if ctx is not None else None
    if deps is not None:
        target = getattr(deps, "target", None)
        agent_id = getattr(deps, "agent_id", None)
        session_id = getattr(deps, "session_id", None)
    elif isinstance(ctx, str):
        session_id = ctx
    elif ctx is None:
        return json.dumps({"available": False, "note": "No context provided"})

    if not target or agent_id is None or session_id is None:
        # Backward-compatible fallback: walk the legacy session-only directory
        # and report what we find without secrets.
        if isinstance(ctx, str):
            legacy_dir = DEADEND_AGENTS_PATH / ctx / "auth_context"
            index_file = legacy_dir / "index.json"
            if index_file.exists():
                try:
                    return json.dumps({
                        "available": True,
                        "legacy": True,
                        "index": json.loads(index_file.read_text(encoding="utf-8")),
                    })
                except json.JSONDecodeError:
                    pass
        return json.dumps({
            "available": False,
            "note": "target, agent_id and session_id are required to resolve auth context",
        })

    try:
        handler = AuthContextHandler(target=target, agent_id=agent_id, session_id=session_id)
        context = handler.load_context(profile)
        if context is None:
            return json.dumps({
                "available": False,
                "profile": profile,
                "target": target,
                "agent_id": str(agent_id),
                "session_id": str(session_id),
            })
        if include_secrets:
            return context.model_dump_json()
        return json.dumps(safe_auth_summary(context))
    except Exception as exc:
        logger.warning("read_auth_storage failed: %s", exc)
        return json.dumps({"available": False, "error": str(exc)})

@with_tool_events("run_python_file")
async def run_python_file(
    ctx: RunContext[Any],
    code: str,
    filename: str,
    packages: list[str]
) -> Any:
    """Write Python code to a file and execute it in the sandbox.

    This function combines writing Python code to a cache directory and executing
    it in a sandboxed environment. The file is written to ./<filename> in the current working directory
    and then executed in an isolated WebAssembly-based Python interpreter.

    Args:
        code: The Python source code to write and execute.
        filename: Target filename (e.g., "script.py").
        packages: List of package specifiers to install before execution.
        _directory: Optional host working directory to expose to the sandbox.
                    If not provided, uses the cache directory where the file is written.
        _session_id: Optional session identifier to correlate runs.

    Returns:
        Any: JSON response from the sandbox with execution result.

    Raises:
        FileNotFoundError: If execution fails due to file not found (should not occur
                          as the file is created by this function).
    """
    # Write Python code to cache directory
    # TODO: needs to be reviewed and changed here, we might want to save it more 
    # in the same place as the agents root or make it more easier 
    python_output_dir = Path.cwd() / "python_scripts"
    python_output_dir.mkdir(parents=True, exist_ok=True)
    file_path = python_output_dir / filename
    file_path.write_text(code, encoding="utf-8")
    print(code)

    deps = getattr(ctx, "deps", None)
    if isinstance(deps, str):
        session_id = deps
    else:
        session_id = getattr(deps, "session_id", None) if deps is not None else None
    session_id = session_id or f"session_{id(file_path)}"

    # Initializing the PythonInterpreter
    # Convert cache_dir Path to string for the directory parameter
    interpreter = PythonInterpreter(session_id=session_id, directory=str(python_output_dir))
    await interpreter.initialize()

    try:
        # Loading the necessary packages
        if packages:
            await interpreter.load_packages(packages)

        # Running the file (use just filename since directory is set)
        result = await interpreter.run_file(filename)
        # Save result to python_interpreter.jsonl file
        await _save_result_to_file(session_id, result)

        # Convert result to string if needed before truncation
        if isinstance(result, bytes):
            try:
                result_str = result.decode('utf-8', errors='replace')
            except Exception:
                result_str = str(result)
        elif not isinstance(result, str):
            result_str = str(result)
        else:
            result_str = result

        # Pretty print result using rich
        # pprint(result)
        truncated_result = truncate_string(result_str)
        # Returning the results
        return truncated_result

    finally:
        # Closing the process
        await interpreter.shutdown()


async def _save_result_to_file(session_id: str, result: Any):
    """
    Save Python interpreter result to python_interpreter.jsonl file in the session directory.

    Args:
        session_id (str): Session identifier
        result (Any): Result object to save
    """
    try:
        # Create the directory path
        cache_dir = CACHE_DEADEND_LOGS / session_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create the file path
        file_path = cache_dir / "python_interpreter.jsonl"

        # Convert result to JSON-serializable format
        if isinstance(result, (dict, list, str, int, float, bool, type(None))):
            # Already JSON-serializable
            result_data = result
        else:
            # Convert to string if not directly serializable
            result_data = str(result)

        # Create JSON object for this result
        result_entry = {
            "result": result_data
        }

        # Append to file with pretty-printed JSON (indented for readability)
        with open(file_path, "a", encoding="utf-8") as f:
            json_line = json.dumps(result_entry, ensure_ascii=False, indent=2)
            f.write(json_line + "\n")

    except Exception as e:
        print(f"Warning: Could not save Python interpreter result to file: {e}")
