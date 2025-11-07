# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter tool for executing Python code in sandboxed environments.

This module provides functionality to execute Python code safely within
sandboxed environments, enabling AI agents to run Python scripts and
code snippets for security research and analysis tasks.
"""
from pathlib import Path
from typing import Any

from .python_interpreter import PythonInterpreter

async def run_python_file(
    code: str,
    filename: str,
    packages: list[str],
    _directory: str | None = None,
    _session_id: str | None = None
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

    # Use cache directory as working directory if not specified
    directory = _directory if _directory is not None else str(cache_dir)

    # Generate session_id if not provided
    session_id = _session_id or f"session_{id(file_path)}"

    # Initializing the PythonInterpreter
    interpreter = PythonInterpreter(session_id=session_id, directory=directory)
    await interpreter.initialize()

    try:
        # Loading the necessary packages
        if packages:
            await interpreter.load_packages(packages)

        # Running the file (use just filename since directory is set)
        result = await interpreter.run_file(filename)

        # Returning the results
        return result

    finally:
        # Closing the process
        await interpreter.shutdown()
