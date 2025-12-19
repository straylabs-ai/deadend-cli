# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.
"""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel
from pydantic_ai import Agent, capture_run_messages, DeferredToolResults, UnexpectedModelBehavior
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel


class AgentOutput(BaseModel):
    """Standard output format for agent execution results.
    
    This model provides a consistent structure for agent outputs, including
    confidence scores, execution notes, and updated context state.
    
    Attributes:
        confidence_score: Confidence score (0.0-1.0) indicating the agent's
            confidence in the execution result
        notes: Optional notes or reasoning from the agent about the execution
        updated_state: Optional dictionary containing updated context state
            from the agent's execution
    """
    confidence_score: float
    notes: str | None = None
    updated_state: dict[str, Any] | None = None


class AgentRunner:
    """
    Wrapper for Pydantic AI agents that provides a consistent interface for agent execution.
    
    This class encapsulates a Pydantic AI Agent instance and provides methods to run
    agent tasks with proper configuration, error handling, and usage tracking.
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
        """Initialize an AgentRunner instance.
        
        Args:
            name: Unique identifier for this agent instance
            model: The AI model to use for agent execution
            instructions: System instructions/prompt for the agent
            deps_type: Optional dependency type for the agent
            output_type: Expected output type for the agent's responses
            tools: List of tools available to the agent
        """
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
        prompt: str,
        deps: Any,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        """Execute the agent with the given prompt and parameters.
        
        Args:
            prompt: The user prompt/task for the agent to process
            deps: Optional dependencies to pass to the agent
            message_history: Previous conversation messages for context
            usage: Optional usage tracking object
            usage_limits: Optional limits for token usage
            deferred_tool_results: Optional deferred tool results from previous runs
            
        Returns:
            AgentRunResult containing the agent's output and metadata
            
        Note:
            Future enhancements will include token limit checking, rate-limit handling,
            and interruption support.
        """
        with capture_run_messages() as messages:
            try:
                result = await self.agent.run(
                    user_prompt=prompt,
                    deps=deps,
                    message_history=message_history,
                    usage=usage,
                    usage_limits=usage_limits,
                    deferred_tool_results=deferred_tool_results
                )
            except UnexpectedModelBehavior:
                print("exception UnexpectedModelBehavior raised")
                result = messages
        return result
