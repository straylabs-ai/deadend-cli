# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web application reconnaissance agent for information gathering and analysis.

This module implements an AI agent that performs comprehensive reconnaissance
on web applications, including directory enumeration, technology detection,
vulnerability scanning, and information gathering for security assessments.
"""
from deadend_agent.constants import REUSABLE_CREDENTIALS_FILE
from typing import Any
from pathlib import Path
import json
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.agents.factory import AgentRunner, AgentOutput
from deadend_agent.config.settings import ModelSpec
from deadend_agent.tools import browser_run_steps, pw_send_payload
from deadend_prompts import render_agent_instructions, render_tool_description

class RequesterOutput(AgentOutput):
    """Output model for Playwright's requester.

    Inherits from AgentOutput: detailed_summary, proofs, confidence_score, thoughts
    """
    pass


class RequesterAgent(AgentRunner):
    """
    The webapp recon agent is the agent in charge of doing the recon on the target. 
    The goal is to retrieve all the important information that we can 
    """

    def __init__(
        self,
        model: ModelSpec,
        deps_type: Any | None,
        target_information: str,
        requires_approval: bool,
    ):
        tools_metadata = {
            "pw_send_payload": render_tool_description("send_payload"),
            "browser_run_steps": render_tool_description("browser_run_steps"),
        }

        self.instructions = render_agent_instructions(
            agent_name="requester",
            tools=tools_metadata,
            target=target_information
        )

        super().__init__(
            name="requester",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[RequesterOutput, DeferredToolRequests],
            tools=[
                Tool(pw_send_payload, requires_approval=requires_approval),
                Tool(browser_run_steps, requires_approval=requires_approval),
            ]
        )

    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits:UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        agent_response = await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
        return agent_response
