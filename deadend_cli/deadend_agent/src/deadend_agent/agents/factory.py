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
from deadend_agent.context.memory import MemoryHandler
from deadend_agent.models.registry import AIModel
from deadend_agent.utils.structures import PlannerOutput
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
        prompt: str,
        deps: Any,
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
            user_prompt=prompt,
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

    def add_child(self, child: TaskNode) -> None:
        child.parent = self
        self.children.append(child)

class AgentOutput(BaseModel):
    confidence_score: float
    notes: str | None = None
    updated_state: dict[str, Any] | None = None


class Planner:
    def __init__(self, planner_agent: AgentRunner) -> None:
        self.agent = planner_agent

    async def expand(
        self,
        parent_task: TaskNode,
        context: dict[str, Any]

    ) -> list[TaskNode]:
        # Adding to the system prompt instructions about the subtasking
        result = await self.agent.run(
            prompt=f"Break down this task into subtasks: {parent_task.task}",
            deps=context,
            message_history=[],
            usage=None,
            usage_limits=None
        )

        # Populating task nodes
        nested_tasks = []
        if isinstance(result.output, PlannerOutput):
            for _, (task, confidence_score) in enumerate(result.output.tasks.items()):
                new_task = TaskNode(
                    task=task,
                    depth=parent_task.depth+1,
                    confidence_score=confidence_score,
                    status="pending",
                    parent=parent_task,
                    children=[]
                )
                nested_tasks.append(new_task)
        return nested_tasks

class AgentExecutor:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner
    async def execute(
        self,
        task_node: TaskNode,
        context: dict[str, Any],
        deps: Any | None = None,
        usage: RunUsage = RunUsage(),
        usage_limits: UsageLimits = UsageLimits(),
        deferred_tool_results: DeferredToolResults | None = None,
        message_history: list | None = None
    ) -> Any:
        try:
            result = await self.runner.run(
                prompt=task_node.task,
                deps=deps,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deferred_tool_results=deferred_tool_results
            )

            output = result.output

            if isinstance(output, AgentOutput):
                confidence_score = output.confidence_score
                notes = output.notes or ""
                updated_state = output.updated_state or {} 
            else:
                confidence_score = getattr(output, 'confidence_score', 0.3)
                notes = getattr(output, 'notes', str(output))
                updated_state = getattr(output, 'updated_state', {})

            updated_context = context.copy()
            updated_context.setdefault("log", "")
            updated_context["log"] += f"\n[EXECUTOR] Task: {task_node.task}\nNotes: {notes}"
            updated_context.update(updated_state)
            updated_context["last_output"] = output.model_dump() \
                if isinstance(output, AgentOutput) else str(output)
            return confidence_score, updated_context

        except Exception as e:
            # On error, return low confidence failure
            updated_context = context.copy()
            updated_context.setdefault("log", "")
            updated_context["log"] += f"\n[EXECUTOR] Error: {str(e)}"
            return 0.0, updated_context

class ValidatorOutput(BaseModel):
    valid: bool
    confidence_score: float
    critique: str

class Validator:
    """Validator, double-checks the results obtained for coherence and validity of the tooling.
    utilizes LLM as judge method.
    """

    def __init__(self, model: AIModel) -> None:
        self.agent = AgentRunner(
            name="validator",
            model=model,
            deps_type=None,
            instructions="",
            output_type=ValidatorOutput,
            tools=[]
        )

    async def verify(self, task: TaskNode, context: dict[str, Any]) -> tuple[bool, float, str]:
        prompt = f"""
You are the Validator. Judge whether the task is satisfied.

Task: {task.task}
confidence task : {task.confidence_score}
Execution trace:
{context.get("log", "∅")}

- valid (true/false)
- confidence (float 0-1)
- critique (string)
"""
        result = await self.agent.run(
            prompt=prompt,
            deps=None,
            message_history="",
            usage=None,
            usage_limits=None,
            deferred_tool_results=None
        )

        if isinstance(result.output, ValidatorOutput):
            valid = result.output.valid
            confidence_score = float(result.output.confidence_score)
            critique = result.output.critique
        else:
            valid = getattr(result.output, "valid", False)
            confidence_score = getattr(result.output, "confidence_score", 0.0)
            critique = str(result.output)

        # adding to context
        return (valid, confidence_score, critique)

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
    memory: MemoryHandler
    context: dict[str, Any]

    FAIL_THRESHOLD = 0.20
    REPLAN_THRESHOLD = 0.40
    EXPLORE_THRESHOLD = 0.60
    VALIDATE_THRESHOLD = 0.80

    def __init__(
        self,
        session_id: str,
        executor: AgentExecutor,
        planner: Planner,
        validator: Validator,
        max_depth: int = 3
    ):
        self.session = session_id
        self.max_depth = max_depth
        self.executor = executor
        self.planner = planner
        self.validator = validator

    async def _solve(self, node: TaskNode, depth: int):
        if depth > self.max_depth:
            node.status = "aborted:max_depth"
            node.confidence_score = 0.0
            return

        confidence_score, new_context = await self.executor.execute(
            task_node=node,
            context=self.context
        )

        self.context = new_context
        decision = self._policy(confidence_score)
        if decision == "fail":
            node.status = "failed"
            return

        if decision == "validate":
            # Validate the task
            node.status = await self._validate(node)
            return

        subtasks = await self.planner.expand(
            node,
            context = self.context
        )
        if not subtasks or len(subtasks) <1:
            node.status = "refine"
            if node.parent:
                await self._solve(node.parent, depth=node.depth)

        node.status = "expand"
        node.children = subtasks
        for subtask in subtasks:
            await self._solve(subtask, depth+1)

    def _policy(self, confidence_score: float) -> Literal["fail", "expand", "refine", "validate"]:
        """
        The policy is given a confidence score, and depending on the information given
        is capable to determine the next step for the task.
        - <20% : treated as unrecoverable. Even though the goal is well defined, we need to propagate
        the failure and move on.
        - 20-60% : stays in exploration mode, this stage trigger more granular subtasks or gather
        missing information.
        - 60%-80% : keep executing and reiterating. At this stage we can either make simple changes 
        to increase the confidence score or run the generic agents for executing and testing.
        - > 80% : move to validator/controller.
        the policy could be assertions, tool verification, or LLM judge, and before the task is done.
        """
        if confidence_score < self.FAIL_THRESHOLD:
            return "fail"
        elif confidence_score < self.EXPLORE_THRESHOLD:
            return "expand"
        elif confidence_score >= self.VALIDATE_THRESHOLD:
            return "validate"
        return "refine"

    async def _validate(self, node: TaskNode) -> str:
        if not self.validator:
            return "completed"

        (ok, validation, critique) = await self.validator.verify(task=node, context=self.context)

        self.context["log"] += f"\nVALIDATOR: {validation} : {critique}"
        node.confidence_score = validation

        return "completed" if ok else "failed-validation"


    async def run(self, task: str, context: dict[str, Any] | None = None) -> TaskNode:
        """Runs the ADaPT agent."""
        self.context = context or {}
        self.context.setdefault("log", "")

        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.0,
            status="pending",
            parent=None,
            children=[]
        )

        await self._solve(root, depth=0)
        return root
