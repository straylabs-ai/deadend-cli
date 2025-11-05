from typing import Any
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models import AIModel
from deadend_prompts import render_agent_instructions, render_tool_description
from .factory import AgentRunner


class ReconThreatModelAgent(AgentRunner):
    def __init__(
        self,
        name: str,
        model: AIModel,
        deps_type: Any | None,
        output_type: Any | None,
        tools: list
    ):
        self.instructions = render_agent_instructions(
            agent_name="recon_threatmodel",
            tools={}
        )
        super().__init__(
            name,
            model,
            self.instructions,
            deps_type,
            output_type,
            []
        )

    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        return await super().run(
            user_prompt,
            deps,
            message_history,
            usage,
            usage_limits,
            deferred_tool_results
        )
    