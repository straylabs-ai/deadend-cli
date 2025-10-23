# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Routing agent for directing workflow execution between different AI agents.

This module implements an AI agent that analyzes the current state of security
research workflows and determines which agent should be invoked next based on
the context, progress, and requirements of the ongoing assessment.
"""

from pydantic import BaseModel
from typing import Dict

from deadend_prompts import render_agent_instructions
from .factory import AgentRunner

class RouterOutput(BaseModel):
    reasoning: str
    next_agent_name: str

class RouterAgent(AgentRunner):
    """
    Router agent reroutes the workflow to the specific agent
    that we need to use. 
    """
    def __init__(self, model, deps_type, tools, available_agents: Dict[str, str]):
        # if len(tools) == 0:
        router_instructions = render_agent_instructions(
            "router", 
            tools={},
            available_agents_length=len(available_agents),
            available_agents=available_agents
            )
        self._set_description()
        super().__init__(name="router", model=model, instructions=router_instructions, deps_type=deps_type, output_type=RouterOutput, tools=[])


    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage,
        usage_limits,
        deferred_tool_results
    ) -> RouterOutput:
        return await super().run(
            user_prompt=user_prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )

    def _set_description(self):
        self.description = "The router agent role is to chose the appropriate agent depending on which one is the best to use."
