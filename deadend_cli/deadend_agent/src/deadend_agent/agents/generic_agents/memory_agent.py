from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, Tool
from pydantic_ai.usage import RunUsage, UsageLimits

from deadend_agent.agents.factory import AgentRunner
from deadend_agent.config.settings import ModelSpec
from deadend_agent.tools import (
    grep_memory_files,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)
from deadend_prompts import render_agent_instructions, render_tool_description


class MemoryAgent(AgentRunner):
    """Agent dedicated to reading and writing the persistent memory workspace."""

    def __init__(
        self,
        model: ModelSpec,
        deps_type: Any | None,
    ):
        tools_metadata = {
            "list_memory_files": render_tool_description("list_memory_files"),
            "read_memory_file": render_tool_description("read_memory_file"),
            "write_memory_file": render_tool_description("write_memory_file"),
            "grep_memory_files": render_tool_description("grep_memory_files"),
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
                Tool(list_memory_files),
                Tool(read_memory_file),
                Tool(write_memory_file),
                Tool(grep_memory_files),
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
