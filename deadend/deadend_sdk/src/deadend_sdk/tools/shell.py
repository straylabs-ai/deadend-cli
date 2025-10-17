# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Sandboxed shell execution tool for secure command execution.

This module provides a tool for executing shell commands within a sandboxed
environment, ensuring security and isolation during security research tasks
while capturing command output and execution logs.
"""

from typing import Dict

from pydantic_ai import RunContext



from rich import print as console_printer
from deadend_sdk.sandbox.sandbox import Sandbox, SandboxStatus
from deadend_sdk.utils.structures import WebappreconDeps, CmdLog


def sandboxed_shell_tool(
    ctx: RunContext[WebappreconDeps],
    command: str,
    timeout_seconds: int = 30
) -> Dict[int, CmdLog]:
    """Execute a shell command in the sandbox environment.
    
    Args:
        ctx: Runtime context containing dependencies
        command: Shell command to execute (supports quotes, pipes, redirects)
        timeout_seconds: Maximum execution time (default: 30 seconds)
        
    Returns:
        Dictionary mapping command numbers to execution results
    """
    console_printer.print(f"Command to be executed: {command}")
    if ctx.deps.shell_runner.sandbox.status == SandboxStatus.RUNNING:
        result = ctx.deps.shell_runner.run_command(command, timeout_seconds)
        console_printer.print(
            f"Command execution completed in \
                {result.get('execution_time', 0):.2f}s"
            )
        if result.get('timed_out', False):
            print(f"⚠️  Command timed out after {timeout_seconds} seconds")
        return ctx.deps.shell_runner.get_cmd_log()
    else:
        console_printer.print("Sandbox is not running")
        return {}
