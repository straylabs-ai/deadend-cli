# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter tool for executing Python code in sandboxed environments.

This module provides functionality to execute Python code safely within
sandboxed environments, enabling AI agents to run Python scripts and
code snippets for security research and analysis tasks.
"""
import json
from pathlib import Path
from typing import Any
from pydantic_ai import RunContext
from rich.pretty import pprint

from deadend_agent.utils.functions import truncate_string
from .python_interpreter import PythonInterpreter
from deadend_agent.tools.tool_wrappers import with_tool_events



@with_tool_events("read_auth_storage")
async def read_auth_storage(ctx: str) -> str:
    """Return the JSON contents of storage.json for the given session.

    If the storage file doesn't exist, returns an empty JSON object instead
    of raising an error, allowing the agent to continue without auth context.

    Args:
        ctx: Session key/identifier used to locate the storage file.

    Returns:
        str: JSON string containing stored auth data, or '{}' if no storage exists.
    """
    if not ctx:
        # Return empty object instead of raising - let agent proceed without auth
        return '{"note": "No session_id provided, no auth storage available"}'

    storage_file = (
        Path.home()
        / ".cache"
        / "deadend"
        / "memory"
        / "sessions"
        / ctx
        / "storage.json"
    )
    print(f"storage file in read_auth_storage {storage_file}")

    if not storage_file.exists():
        # Return informative empty response instead of raising error
        print(f"[INFO] storage.json not found for session {ctx}, proceeding without auth context")
        return json.dumps({
            "note": f"No auth storage found for session {ctx}",
            "cookies": [],
            "tokens": [],
            "credentials": []
        })

    try:
        data = storage_file.read_text(encoding="utf-8")
        print(f"data storage file : {data}")
        # Validate JSON before returning so callers always receive valid dumps
        json.loads(data)
        return data
    except json.JSONDecodeError as exc:
        # Return error info instead of raising - let agent handle it
        print(f"[WARNING] storage.json for {ctx} is not valid JSON: {exc}")
        return json.dumps({
            "error": f"Invalid JSON in storage.json: {str(exc)}",
            "cookies": [],
            "tokens": [],
            "credentials": []
        })

@with_tool_events("run_python_file")
async def run_python_file(
    ctx: RunContext[str],
    code: str,
    filename: str,
    packages: list[str]
) -> Any:
    """Write Python code to a file and execute it in the sandbox.

    This function combines writing Python code to a cache directory and executing
    it in a sandboxed environment. The file is written to ~/.cache/deadend/python/<filename>
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
    cache_dir = Path.home() / ".cache" / "deadend" / "python"
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / filename
    file_path.write_text(code, encoding="utf-8")
    print(code)

    # Get session_id from context deps (passed from agent), or generate one if not provided
    # ctx.deps is the session_id string passed from PythonInterpreterAgent
    session_id = ctx.deps if ctx.deps and isinstance(ctx.deps, str) else f"session_{id(file_path)}"

    # Initializing the PythonInterpreter
    # Convert cache_dir Path to string for the directory parameter
    interpreter = PythonInterpreter(session_id=session_id, directory=str(cache_dir))
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
        cache_dir = Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_id
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
