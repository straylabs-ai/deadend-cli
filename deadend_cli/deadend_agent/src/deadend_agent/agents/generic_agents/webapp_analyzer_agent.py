# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.
from typing import Any
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.config.settings import ModelSpec
from deadend_agent.agents.factory import AgentRunner, AgentOutput
from deadend_agent.tools import webapp_analyzer
from deadend_prompts import render_agent_instructions, render_tool_description


class WebAppAnalyzerAgent(AgentRunner):

    def __init__(
        self,
        model: ModelSpec,
        deps_type: Any | None,
    ):
        tools_metadata = {
            "webapp_analyzer": render_tool_description("webapp_analyzer"),
        }

        self.instructions = render_agent_instructions(
            agent_name="webapp_analyzer",
            tools=tools_metadata
        )

        super().__init__(
            name="webapp_analyzer",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[AgentOutput, DeferredToolRequests],
            tools=[
                Tool(webapp_analyzer),
            ]
        )

    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None,
        *args,
        **kwargs
    ):
        return await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
