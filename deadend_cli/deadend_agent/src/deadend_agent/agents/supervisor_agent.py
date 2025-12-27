# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Supervisor agent for orchestrating workflow execution between different AI agents.

This module implements an AI agent that decomposes security assessment goals into
explicit, atomic subtasks and delegates them to specialized agents. The supervisor
interprets agent outputs and determines task completion status.
"""
from typing import Dict
from deadend_agent.context.context_engine import Any
from pydantic import BaseModel
from pydantic_ai import RunUsage, UsageLimits, DeferredToolResults
from deadend_prompts import render_agent_instructions
from .factory import AgentRunner

class SupervisorOutput(BaseModel):
    task_achieved: bool
    confidence_score: float
    detailed_summary: str
    proofs: str

class SupervisorAgent(AgentRunner):
    """
    Supervisor agent orchestrates security assessments by decomposing goals
    into atomic subtasks and delegating to specialized agents.
    """
    def __init__(self, model, deps_type, tools, available_agents: Dict[str, str]):
        router_instructions = render_agent_instructions(
            "supervisor", 
            tools={},
            available_agents_length=len(available_agents),
            available_agents=available_agents
            )
        self._set_description()
        super().__init__(
            name="supervisor",
            model=model,
            instructions=router_instructions,
            deps_type=deps_type,
            output_type=SupervisorOutput,
            tools=[]
        )

    async def run(
        self,
        prompt: str,
        deps: Any,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        return await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )

    def _set_description(self):
        self.description = "The supervisor agent orchestrates security assessments by decomposing goals into atomic subtasks and delegating to specialized agents."
