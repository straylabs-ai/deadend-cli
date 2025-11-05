from typing import Any
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_sdk.context import MemoryHandler
from deadend_sdk.models import AIModel
from deadend_sdk.tools import run_python_file
from deadend_prompts import render_agent_instructions, render_tool_description
from .factory import AgentRunner


class PythonInterpreterOutput(BaseModel):
    filename: str
    goal: str
    reasoning: str
    vulnerability_category: str
    attempt: str
    script_stdout: str
    script_stderr: str


class PythonInterpreterAgent(AgentRunner):
    def __init__(
        self,
        model: AIModel,
        deps_type: Any | None,
        output_type: Any | None,
        tools: list
    ):
        tools_metadata = {
            "run_python_file" : render_tool_description("run_python_file")
        }
        self.name = "python_interpreter"
        self.instructions = render_agent_instructions(
            agent_name=self.name,
            tools=tools_metadata,
        )

        super().__init__(
            name=self.name,
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=PythonInterpreterOutput,
            tools=[
                Tool(run_python_file)
            ]
        )

    async def run(
        self,
        user_prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None, 
        deferred_tool_results: DeferredToolResults | None = None,
        memory: MemoryHandler | None = None
    ):

        agent_response = await super().run(
            user_prompt,
            deps,
            message_history,
            usage,
            usage_limits,
            deferred_tool_results
        )

        if memory:
            agent_output = agent_response.output
            if isinstance(agent_output, PythonInterpreterOutput):
                memory.add_agent_result_to_memory(
                    agent_name=self.name,
                    vulnerability_category=agent_output.vulnerability_category,
                    attempt=agent_output.attempt,
                    filename=agent_output.filename,
                    goal=agent_output.goal,
                    stdout=agent_output.script_stdout,
                    stderr=agent_output.script_stderr
                )
        return agent_response