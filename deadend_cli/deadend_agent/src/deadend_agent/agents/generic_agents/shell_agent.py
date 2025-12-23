# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Reconnaissance shell agent for command-line reconnaissance and analysis.

This module implements an AI agent that performs reconnaissance tasks using
shell commands within a sandboxed environment, including system enumeration,
network scanning, file system analysis, and other command-line security tools
for comprehensive security assessments.
"""
from typing import Any
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel
from deadend_agent.agents.factory import AgentRunner, AgentOutput
from deadend_agent.tools import sandboxed_shell_tool
from deadend_prompts import render_agent_instructions, render_tool_description


class ExecutedCommand(BaseModel):
    """Record of a shell command executed with its outcome.

    Attributes:
        command: The exact command executed
        target: What was targeted (endpoint, host, port)
        purpose: Why this command was run (e.g., "port scan", "dir bruteforce")
        result: What happened (success, failed, timeout, no_results)
        key_output: Most important part of the output
        why_failed: Explanation if it didn't work
    """
    command: str
    target: str
    purpose: str
    result: str  # success, failed, timeout, no_results
    key_output: str = ""
    why_failed: str = ""


class ShellOutput(AgentOutput):
    """Output model for shell agent execution results.

    Captures comprehensive shell command execution details for downstream
    agents to learn from.

    Attributes:
        objective: The objective/goal of the shell command
        stdin: The primary command that was executed
        stdout: Standard output from the command
        stderr: Standard error from the command
        commands_executed: List of all commands run with outcomes
        key_findings: Most important discovery from this execution
        next_steps: Suggested next actions based on findings
        attempts: (inherited) List of all tool calls made during agent run
        thought_summary: (inherited) Concise summary of agent's key insight
    """
    objective: str
    stdin: str
    stdout: str
    stderr: str
    commands_executed: list[ExecutedCommand] = []
    key_findings: str = ""
    next_steps: str = ""

class ShellAgent(AgentRunner):
    """
    The recon shell agent is responsible for performing reconnaissance tasks
    using shell commands within a sandboxed environment. The goal is to gather
    system information, enumerate services, analyze file systems, and perform
    various command-line security assessments.
    """

    def __init__(
        self,
        model: AIModel,
        deps_type: Any | None,
        target_information: str,
        requires_approval: bool,
    ):
        tools_metadata = {
            "sandboxed_shell_tool": render_tool_description("sandboxed_shell_tool"),
        }

        self.instructions = render_agent_instructions(
            agent_name="shell",
            tools=tools_metadata,
            target=target_information
        )
        super().__init__(
            name="shell",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[ShellOutput, DeferredToolRequests],
            tools=[
                Tool(sandboxed_shell_tool, requires_approval=requires_approval),
            ]
        )

    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None,
    ):
        return await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
