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
from deadend_sdk.models.registry import AIModel
from deadend_sdk.tools import sandboxed_shell_tool
from deadend_prompts import render_agent_instructions, render_tool_description
from .factory import AgentRunner


class ShellReconOutput(BaseModel):
    reasoning: str
    state: str
    raw_response: str

class ReconShellAgent(AgentRunner):
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
            agent_name="recon_shell",
            tools=tools_metadata,
            target=target_information
        )
        super().__init__(
            name="recon_shell",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[ShellReconOutput, DeferredToolRequests],
            tools=[
                Tool(sandboxed_shell_tool, requires_approval=requires_approval),
            ]
        )

    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None,
    ):
        return await super().run(
            user_prompt=user_prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
