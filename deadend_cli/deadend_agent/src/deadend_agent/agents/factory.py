# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.
"""
from __future__ import annotations
from typing import Any, Literal, Protocol
from pydantic import BaseModel, Field
from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
# from deadend_agent.context import MemoryHandler
from deadend_agent.models.registry import AIModel
# from tenacity import (
#     retry,
#     stop_after_attempt,
#     wait_random_exponential,
# )

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
        deferred_tool_results: DeferredToolResults | None = None
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

class TaskNode(BaseModel):
    task: str
    depth: int
    confidence_score: float
    status: str
    parent: TaskNode | None
    children: list[TaskNode] = Field(default_factory=list)

class AgentOutput(BaseModel):
    confidence_score: float
    notes: str | None = None
    updated_state: dict[str, Any] | None = None


class Planner(Protocol):
    pass

class Executor(Protocol):
    def execute(self, task, context):
        """Returns success flag, confidence and updated context."""
        ...

class AgentExecutor:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner
        output_type = runner.agent.output_type


    def execute(self, task: TaskNode, context: dict[str, Any]):
        pass
        

class Validator(Protocol):
    pass


class ADaPTAgent:
    """
    ADaPT Agent is a recursive agent from the paper 
    ADaPT: As-Needed Decomposition and Planning with Language Models
    (https://arxiv.org/abs/2311.05772)

    This implementation follows the algorithm presented in the paper, 
    by retaking the most relevant information:
    - Usage of 3 components Executors, Planner and Controller.
    """
    session_id: str
    task_node: TaskNode
    max_depth: int

    FAIL_THRESHOLD = 0.20
    REPLAN_THRESHOLD = 0.40
    EXPLORE_THRESHOLD = 0.60
    VALIDATE_THRESHOLD = 0.80

    def __init__(
        self,
        session_id: str,
        executor: Executor,
        planner: Planner,
        validator: Validator,
        max_depth: int = 3
    ):
        self.session = session_id
        self.max_depth = max_depth
        self.executor = executor
        self.planner = planner
        self.validator = validator

    def _executor(
        self,
        task: str,
        agent: AgentRunner
    ):
        return True

    def _planner(
        self,
        task
    ) -> tuple[list[TaskNode], Literal['and', 'or']]:
        return ([], "and")

    def _batch_tasks_validation(self, outputs, logic) -> bool:
        """
        After the controller assign a task as done, the batch_tasks_validation
        is to see if all subtasks of a parent task are logically valid 
        it should return a completion and confidence score
        """
        return True

    def _controller(self, confidence_score: float):
        """
        The controller is given a confidence score, and depending on the information given
        is capable to determine the next step for the task.
        - <20% : treated as unrecoverable. Even though the goal is well defined, we need to propagate
        the failure and move on.
        - 20-60% : stays in exploration mode, this stage trigger more granular subtasks or gather
        missing information.
        - 60%-80% : keep executing and reiterating. At this stage we can either make simple changes 
        to increase the confidence score or run the generic agents for executing and testing.
        - > 80% : move to validator/controller.
        the controller could be assertions, tool verification, or LLM judge, and before the task is done.
        """
        pass

    def run(self, task, agent: AgentRunner, iteration: int) -> dict[str, bool]:
        """Runs the ADaPT agent. 

        This is an recursive function. 

        """
        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.3,
            status="pending",
            parent=None,
            children=[]
        )

        if iteration > self.max_depth:
            return { task :False }

        completed = self._executor(
            task=task,
            agent=agent
        )
        # Add confidence score here


        outputs = {}
        if not completed:
            subtasks, logic = self._planner(task=task)
            for subtask in subtasks:
                output = self.run(task=subtask, agent=agent, iteration=iteration+1)
                outputs[subtask] = output

            completed = self._batch_tasks_validation(outputs, logic)
        return { task : completed }
