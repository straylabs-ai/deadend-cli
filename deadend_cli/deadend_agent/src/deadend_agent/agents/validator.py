# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Routing agent for directing workflow execution between different AI agents.

This module implements an AI agent that analyzes the current state of security
research workflows and determines which agent should be invoked next based on
the context, progress, and requirements of the ongoing assessment.
"""
from typing import Dict
from pydantic import BaseModel
from pydantic_ai import AgentRunResult
from deadend_prompts import render_agent_instructions
from .factory import AgentRunner

class ValidatorOutput(BaseModel):
    reasoning: str
    exploit: str

class ValidatorAgent(AgentRunner):
    """
    Router agent reroutes the workflow to the specific agent
    that we need to use. 
    """
    def __init__(self, model, deps_type, tools, available_agents: Dict[str, str]):

        router_instructions = render_agent_instructions(
            "validator", 
            tools={},
            available_agents_length=len(available_agents),
            available_agents=available_agents
            )
        self._set_description()
        super().__init__(
            name="validator",
            model=model,
            instructions=router_instructions,
            deps_type=deps_type,
            output_type=ValidatorOutput,
            tools=[]
        )


    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage,
        usage_limits,
        deferred_tool_results
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
        self.description = "The validator agent role is validate the results found."
