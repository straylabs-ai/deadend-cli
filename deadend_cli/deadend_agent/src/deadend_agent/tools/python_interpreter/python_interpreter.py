# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter tool for executing Python code in sandboxed environments.

This module provides functionality to execute Python code safely within
sandboxed environments, enabling AI agents to run Python scripts and
code snippets for security research and analysis tasks.

The python sandbox is a WebAssembly server that is ran from a binary : `python-sandbox-tool`
This binary is compiled from : https://github.com/xoxruns/simple-python-interpreter-sandbox
and will be intergrated to the whole project in the future.
"""
import asyncio
from enum import StrEnum, unique
from asyncio.subprocess import PIPE, Process
from pathlib import Path
from typing import Any
import aiohttp

ENDPOINT_PYTHON_SANDBOX="http://127.0.0.1:45555"
PYTHON_SANDBOX_NAME="python-sandbox-tool-linux"

class PythonInterpreterNotFoundException(FileNotFoundError):
    """Raised when the sandbox binary cannot be found locally."""

@unique
class CommandsInterpreter(StrEnum):
    """HTTP endpoints exposed by the sandboxed Python interpreter service."""
    INSTALL_PACKAGES = f"{ENDPOINT_PYTHON_SANDBOX}/installpackages"
    RUN_SCRIPT = f"{ENDPOINT_PYTHON_SANDBOX}/runscript"
    CHECK_PACKAGES = f"{ENDPOINT_PYTHON_SANDBOX}/checkpackages"
    SET_DIRECTORY = f"{ENDPOINT_PYTHON_SANDBOX}/setdirectory"

class PythonInterpreter:
    """Manage lifecycle of the sandboxed Python interpreter and issue HTTP commands.

    Responsibilities:
    - Ensure the sandbox binary exists locally (download on first use).
    - Start and stop the sandbox process.
    - Send JSON requests (set directory, install packages, run scripts).
    """
    session_id: str | None
    directory: str
    pid: Process | None = None

    def __init__(self, session_id: str | None, directory: str) -> None:
        self.session_id = session_id
        self.directory = directory
        self.cache_python_dir = Path.home() / ".cache" / "deadend" / "python"
        self.cache_python_dir.mkdir(parents=True, exist_ok=True)
        self.cache_python_sandbox = self.cache_python_dir / PYTHON_SANDBOX_NAME

    async def initialize(self):
        """Ensure the sandbox binary exists, start the process, set working directory.

        Downloads the binary if missing, spawns the process if not already running,
        then calls the sandbox to set the working directory.

        Returns:
            Any: JSON response from the sandbox for the set-directory request.
        """

        # Downloads the python-sandbox-tool binary to cache if it doesn't exist
        # This is a lot of context managers for a simple download.
        # We need to add a checksum verification here
        if not self.cache_python_sandbox.exists():
            raise PythonInterpreterNotFoundException(
                f"Python sandbox not found at {self.cache_python_sandbox}. "
                "Download it first via deadend_agent.core.download_python_sandbox()."
            )

        # and starts the process
        if self.pid and self.pid.returncode is None:
            return

        self.pid = await asyncio.create_subprocess_exec(
            program=str(self.cache_python_sandbox),
            stdout=PIPE, stderr=PIPE,
            cwd=self.directory
        )

        # Setting the directory
        resp = await self._send_instruction_post(
            command=CommandsInterpreter.SET_DIRECTORY,
            key="directory",
            data=self.directory,
        )

        return resp

    async def load_packages(self, packages: list[str]):
        """Request package installation inside the sandbox.

        Args:
            packages: List of package specifiers (e.g., ["requests==2.32.3", "numpy"]).

        Returns:
            Any: JSON response from the sandbox.
        """
        # Loads the packages needed for the file
        if self.pid is None:
            raise RuntimeError("Interpreter not initialized. Call initialize() first.")

        return await self._send_instruction_post(
            command=CommandsInterpreter.INSTALL_PACKAGES,
            key="packages",
            data=packages
        )


    async def run_file(self, filename: str, _session_id: str | None = None):
        """Execute a Python file within the configured working directory.

        Args:
            filename: Relative path to the file to execute.
            session_id: Optional override of the current session identifier.

        Returns:
            Any: JSON response from the sandbox with execution result.
        """
        # Run a file present in the directory specified
        return await self._send_instruction_post(
            command=CommandsInterpreter.RUN_SCRIPT,
            key="filename",
            data=filename
        )


    async def run_code(self, code: str):
        """Execute inline Python code in the sandbox (not implemented)."""
        raise NotImplementedError

    async def _send_instruction_post(self, command: str, key: str, data: Any):
        """Send a JSON POST request to the sandbox.

        Args:
            command: Target URL (an entry from `CommandsInterpreter`).
            key: JSON key for the payload.
            data: JSON value to send under `key`.

        Returns:
            Any: Parsed JSON response.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(url=command, json={key: data}) as resp:
                return await resp.json()

    async def shutdown(self, timeout: float = 5.0):
        """Gracefully terminate the sandbox process.

        Sends SIGTERM and waits up to `timeout`. If the process does not exit,
        sends SIGKILL and waits for termination.

        Args:
            timeout: Seconds to wait after terminate before force-killing.
        """
        if not self.pid:
            return
        if self.pid.returncode is not None:
            self.pid = None
            return 
        try:
            self.pid.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self.pid.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                self.pid.kill()
            except ProcessLookupError:
                pass
            await self.pid.wait()
        finally:
            self.pid = None
