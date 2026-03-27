from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, Tool
from pydantic_ai.usage import RunUsage, UsageLimits

from deadend_agent.agents.factory import AgentRunner
from deadend_agent.config.settings import ModelSpec
from deadend_agent.tools import avfs_grep, avfs_list, avfs_read, avfs_write
from deadend_prompts import render_agent_instructions, render_tool_description


class MemoryAgent(AgentRunner):
    """Agent dedicated to reading and writing the persistent memory workspace."""

    def __init__(
        self,
        model: ModelSpec,
        deps_type: Any | None,
    ):
        tools_metadata = {
            "avfs_list": render_tool_description("avfs_list"),
            "avfs_read": render_tool_description("avfs_read"),
            "avfs_write": render_tool_description("avfs_write"),
            "avfs_grep": render_tool_description("avfs_grep"),
        }

        self.instructions = render_agent_instructions(
            agent_name="memory",
            tools=tools_metadata,
        )

        super().__init__(
            name="memory",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[str, DeferredToolRequests],
            tools=[
                Tool(avfs_list),
                Tool(avfs_read),
                Tool(avfs_write),
                Tool(avfs_grep),
            ],
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
        **kwargs,
    ):
        return await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results,
        )
