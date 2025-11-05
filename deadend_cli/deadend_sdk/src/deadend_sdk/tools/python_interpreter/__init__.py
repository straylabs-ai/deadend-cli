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

async def write_python_file(code: str, filename: str) -> Path:
    """Write Python code to the cache directory and return the file path.

    The file is written under: ~/.cache/deadend/python/<filename>

    Args:
        code: The Python source code to write.
        filename: Target filename (e.g., "script.py").

    Returns:
        Path: Path to the written file.
    """
    cache_dir = Path.home() / ".cache" / "deadend" / "python"
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_path = cache_dir / filename
    file_path.write_text(code, encoding="utf-8")
    return file_path

async def run_code(
    filename: str,
    packages: list[str],
    _directory: str = "./",
    _session_id: str | None = None
) -> Any:
    """High-level helper to execute a Python file in the sandbox.

    Args:
        filename: Relative path to the script to execute inside `directory`.
        packages: List of package specifiers to install before run.
        _directory: Host working directory to expose to the sandbox.
        _session_id: Optional session identifier to correlate runs.

    Returns:
        Any: JSON response from the sandbox with execution result.

    Raises:
        FileNotFoundError: If the specified file does not exist.
    """
    # Checking if file exists
    file_path = Path(_directory) / filename
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Generate session_id if not provided
    session_id = _session_id or f"session_{id(file_path)}"

    # Initializing the PythonInterpreter
    interpreter = PythonInterpreter(session_id=session_id, directory=_directory)
    await interpreter.initialize()

    try:
        # Loading the necessary packages
        if packages:
            await interpreter.load_packages(packages)

        # Running the file
        result = await interpreter.run_file(filename)

        # Returning the results
        return result

    finally:
        # Closing the process
        await interpreter.shutdown()