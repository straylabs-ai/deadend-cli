from typing import Any
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models import AIModel
from deadend_agent.tools import webapp_code_rag
from deadend_agent.utils.structures import PlannerOutput
from deadend_prompts import render_agent_instructions, render_tool_description
from .factory import AgentRunner

class GeneralInfoOutput(BaseModel):
    information_gathering: str = ""

class ThreatModelOutput(PlannerOutput, GeneralInfoOutput):
    pass

class ReconThreatModelAgent(AgentRunner):
    def __init__(
        self,
        name: str,
        model: AIModel,
        deps_type: Any | None,
        tools: list
    ):
        tools_metadata = {
            "webapp_code_rag": render_tool_description("webapp_code_rag")
        } 
        self.instructions = render_agent_instructions(
            agent_name="recon_threatmodel",
            tools=tools_metadata
        )
        super().__init__(
            name,
            model,
            self.instructions,
            deps_type,
            output_type=ThreatModelOutput,
            tools=[Tool(webapp_code_rag)]
        )

    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):

        return await super().run(
            prompt,
            deps,
            message_history,
            usage,
            usage_limits,
            deferred_tool_results
        )
    