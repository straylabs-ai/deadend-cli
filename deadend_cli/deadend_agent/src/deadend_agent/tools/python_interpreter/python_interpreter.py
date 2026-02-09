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
from enum import Enum, unique
from asyncio.subprocess import PIPE, Process
from pathlib import Path
from typing import Any
import aiohttp

ENDPOINT_PYTHON_SANDBOX="http://127.0.0.1:45555"
PYTHON_SANDBOX_NAME="python-sandbox-tool-linux"

class PythonInterpreterNotFoundException(FileNotFoundError):
    """Raised when the sandbox binary cannot be found locally."""

@unique
class CommandsInterpreter(str, Enum):
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
        # NOTE: the sandbox HTTP server may not be ready immediately after the
        # process starts, so we add a small retry loop here to avoid transient
        # "connection refused" errors that surface as tool failures like:
        # "Error executing tool: CommandsInterpreter.SET_DIRECTORY".
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                resp = await self._send_instruction_post(
                    command=CommandsInterpreter.SET_DIRECTORY,
                    key="directory",
                    data=self.directory,
                )
                print(resp)
                return resp
            except aiohttp.ClientError as exc:  # type: ignore[attr-defined]
                last_exc = exc
                # Back off slightly between attempts to give the server time to boot
                await asyncio.sleep(0.2 * (attempt + 1))

        # If we got here, all attempts failed – raise a clear, high-level error
        raise RuntimeError(
            f"Failed to reach Python sandbox at {str(CommandsInterpreter.SET_DIRECTORY)} "
            f"after 5 attempts. Last error: {last_exc!r}"
        )

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

    async def _send_instruction_post(self, command: str | CommandsInterpreter, key: str, data: Any):
        """Send a JSON POST request to the sandbox.

        Args:
            command: Target URL (an entry from `CommandsInterpreter`).
            key: JSON key for the payload.
            data: JSON value to send under `key`.

        Returns:
            Any: Parsed JSON response.
        """
        # Explicitly convert Enum to string for aiohttp compatibility
        # Using .value for Enums ensures we get the actual string value
        # This is necessary for Python 3.10 compatibility (StrEnum is 3.11+)
        if isinstance(command, Enum):
            url = command.value
        else:
            url = str(command)
        async with aiohttp.ClientSession() as session:
            async with session.post(url=url, json={key: data}) as resp:
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
