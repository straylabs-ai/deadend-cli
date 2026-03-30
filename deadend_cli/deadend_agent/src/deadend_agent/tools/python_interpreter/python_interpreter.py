# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter tool for executing Python code in sandboxed environments.

This adapter keeps the original ``PythonInterpreter`` interface used by the
agent code while routing execution to the stdio worker pool implementation from
``python_sandbox_client``.
"""
from pathlib import Path
from typing import Any

from python_sandbox_client import SandboxPool

class PythonInterpreterNotFoundException(FileNotFoundError):
    """Kept for backward compatibility with existing imports."""

class PythonInterpreter:
    """Manage lifecycle of the sandboxed Python interpreter client."""
    session_id: str | None
    directory: str
    pool: SandboxPool | None = None

    def __init__(self, session_id: str | None, directory: str) -> None:
        self.session_id = session_id
        self.directory = str(Path(directory).resolve())

    async def initialize(self):
        """Start sandbox pool and bind to the configured working directory."""
        if self.pool is not None:
            return {"current_directory": self.directory}
        self.pool = SandboxPool(directory=self.directory, workers=1)
        await self.pool.__aenter__()
        return {"current_directory": self.directory}

    async def load_packages(self, packages: list[str]):
        """Request package installation inside the sandbox."""
        if self.pool is None:
            raise RuntimeError("Interpreter not initialized. Call initialize() first.")
        if not packages:
            return {"results": {}}
        return {"results": await self.pool.install_packages(packages)}


    async def run_file(self, filename: str, _session_id: str | None = None):
        """Execute a Python file within the configured working directory."""
        if self.pool is None:
            raise RuntimeError("Interpreter not initialized. Call initialize() first.")
        execution = await self.pool.run_script(filename)
        return {
            "result": execution.result,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
        }


    async def run_code(self, code: str):
        """Execute inline Python code in the sandbox (not implemented)."""
        raise NotImplementedError

    async def shutdown(self, timeout: float = 5.0):
        """Gracefully terminate worker pool."""
        del timeout  # maintained for API compatibility
        if self.pool is None:
            return
        await self.pool.aclose()
        self.pool = None
