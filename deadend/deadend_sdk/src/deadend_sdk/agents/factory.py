# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.
"""

from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits

from typing import Any

from deadend_sdk.models.registry import AIModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)

class AgentRunner:
    """
    AgentRunner sets up the Pydantic_ai agent.
    This can be viewed as a wrapper that adds clean up to agent calls

    """

    def __init__(
        self,
        name: str,
        model: AIModel,
        instructions: str | None,
        deps_type: Any | None,
        output_type: Any | None,
        tools: list,
    ):
        self.name = name
        self.agent = Agent(
            model=model,
            instructions=instructions,
            deps_type=deps_type,
            output_type=output_type,
            tools=tools
        )
        self.response = None

    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None,
    ):
        # Checking if the number of tokens doesn't exceed the number of tokens accepted by the 
        # Model
        # Handling rate-limits
        # Handling token number reports
        # Handling interruptions
        # Normal running
        return await self.agent.run(
            user_prompt=user_prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )

    def get_response(self):
        if self.response != None:
            return self.response
