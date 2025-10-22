# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web application reconnaissance agent for information gathering and analysis.

This module implements an AI agent that performs comprehensive reconnaissance
on web applications, including directory enumeration, technology detection,
vulnerability scanning, and information gathering for security assessments.
"""
from typing import Any
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_sdk.models.registry import AIModel
from deadend_sdk.tools import (
    sandboxed_shell_tool, 
    is_valid_request_detailed,
    pw_send_payload,
    webapp_code_rag
)
from .factory import AgentRunner
from deadend_prompts import render_agent_instructions, render_tool_description

class RequesterOutput(BaseModel):
    reasoning: str
    state: str
    raw_response: str

class WebappReconAgent(AgentRunner):
    """
    The webapp recon agent is the agent in charge of doing the recon on the target. 
    The goal is to retrieve all the important information that we can 
    """

    def __init__(
        self,
        model: AIModel,
        deps_type: Any | None,
        target_information: str,
        requires_approval: bool,
    ):
        tools_metadata = {
            "is_valid_request_detailed": render_tool_description("is_valid_request_detailed"),
            "pw_send_payload": render_tool_description("send_payload"),
            # "sandboxed_shell_tool": render_tool_description("sandboxed_shell_tool"),
            "webapp_code_rag": render_tool_description("webapp_code_rag")
        }

        self.instructions = render_agent_instructions(
            agent_name="webapp_recon",
            tools=tools_metadata,
            target=target_information
        )
        super().__init__(
            name="webapp_recon",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[RequesterOutput, DeferredToolRequests],
            tools=[
                Tool(is_valid_request_detailed),
                Tool(pw_send_payload, requires_approval=requires_approval),
                # Tool(sandboxed_shell_tool),
                Tool(webapp_code_rag)
            ]
        )

    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits:UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None,
    ):
        return await super().run(
            user_prompt=user_prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
