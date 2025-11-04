# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.
"""

from pydantic.type_adapter import P
from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits

from typing import Any, Literal

from context import MemoryHandler
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


class ADaPTAgent:
    """
    ADaPT Agent is a recursive agent from the paper 
    ADaPT: As-Needed Decomposition and Planning with Language Models
    (https://arxiv.org/abs/2311.05772)

    This implementation follows the algorithm presented in the paper, 
    by retaking the most relevant information:
    - Usage of 3 components Executors, Planner and Controller.
    """

    def __init__(
        self,
        session_id: str,
        memory: MemoryHandler,
        max_depth: int = 3
    ):
        self.session = session_id
        self.memory = memory
        self.max_depth = max_depth

    def _executor(
        self,
        task: str,
        agent: AgentRunner
    ):
        return True

    def _planner(
        self,
        task
    ) -> tuple[list[str], Literal['and', 'or']]:
        return ([], "and")

    def _validate_outputs(self, outputs, logic) -> bool:
        return True

    def run(self, task, agent: AgentRunner, iteration: int) -> dict[str, bool]:
        """Runs the ADaPT agent. 

        This is an iterative function. 

        """
        if iteration > self.max_depth:
            return { task :False }

        completed = self._executor(
            task=task,
            agent=agent
        )
        outputs = {}
        if not completed:
            subtasks, logic = self._planner(task=task)
            for subtask in subtasks:
                output = self.run(task=subtask, agent=agent, iteration=iteration+1)
                outputs[subtask] = output

            completed = self._validate_outputs(outputs, logic)
        return { task : completed }
