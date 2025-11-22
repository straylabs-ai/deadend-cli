# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Python interpreter agent for generating and executing security testing scripts.

This module implements an AI agent that generates Python code for security testing,
vulnerability assessment, and exploit development, then executes the code in a
sandboxed WebAssembly-based Python interpreter environment.
"""
from typing import Any
from pydantic_ai import Tool, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
# from deadend_agent.context import MemoryHandler
from deadend_agent.models import AIModel
from deadend_agent.agents.factory import AgentRunner, AgentOutput
from deadend_agent.tools import run_python_file, read_auth_storage
from deadend_prompts import render_agent_instructions, render_tool_description

class PythonInterpreterOutput(AgentOutput):
    """Output model for Python interpreter agent execution results.
    
    Captures the results of Python script execution including the script's
    standard output, standard error, and metadata about the security testing
    attempt.
    
    Attributes:
        filename: Name of the Python script file that was executed.
        goal: The security testing goal that the script was designed to achieve.
        reasoning: The agent's reasoning for generating and executing the script.
        vulnerability_category: Category of vulnerability being tested
            (e.g., "SQL Injection", "XSS").
        attempt: Description of the security testing attempt or approach.
        script_stdout: Standard output from the Python script execution.
        script_stderr: Standard error output from the Python script execution.
    """
    filename: str
    goal: str
    reasoning: str
    vulnerability_category: str
    attempt: str
    script_stdout: str
    script_stderr: str


class PythonInterpreterAgent(AgentRunner):
    """AI agent for generating and executing Python security testing scripts.
    
    This agent specializes in creating Python code for security research tasks
    such as vulnerability testing, exploit development, and security analysis.
    The agent generates Python scripts based on security testing goals and
    executes them in a sandboxed WebAssembly environment for safe testing.
    
    The agent uses the `run_python_file` tool which combines writing Python code
    to a file and executing it in an isolated sandbox, ensuring safe execution
    of security testing scripts.
    """

    def __init__(
        self,
        model: AIModel,
        deps_type: Any | None,
    ):
        """Initialize the Python interpreter agent.
        
        Args:
            model: The AI model to use for code generation and reasoning.
            deps_type: Optional dependency type for the agent.
            output_type: Optional output type override (defaults to PythonInterpreterOutput).
            tools: Optional list of additional tools (defaults to run_python_file).
        """
        tools_metadata = {
            # "read_auth_storage": render_tool_description("read_auth_storage"),
            "run_python_file" : render_tool_description("run_python_file"),

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
                Tool(run_python_file),
            ]
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
        """Execute the agent with a user prompt and optional memory handling.
        
        Runs the agent to generate and execute Python code based on the security
        testing goal. If memory is provided, saves the execution results for
        future reference and context building.
        
        Args:
            user_prompt: The security testing goal or task description.
            deps: Optional dependencies for the agent execution.
            message_history: Previous conversation messages for context.
            usage: Optional usage tracking information.
            usage_limits: Optional usage limits for the execution.
            deferred_tool_results: Optional deferred tool results from previous runs.
            memory: Optional memory handler for persisting execution results.
        
        Returns:
            AgentRunResult containing the PythonInterpreterOutput with execution results.
        """
        auth_info = read_auth_storage(ctx=deps)
        prompt_with_auth = f"""Auth info :
{str(auth_info)}
You task is :
{prompt}
"""
        print(f"prompt pythoninterpreter: {prompt_with_auth}")
        agent_response = await super().run(
            prompt_with_auth,
            deps,
            message_history,
            usage,
            usage_limits,
            deferred_tool_results
        )
        return agent_response