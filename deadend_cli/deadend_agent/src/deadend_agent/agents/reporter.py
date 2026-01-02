# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Reporter agent for summarizing workflow context and maintaining token limits.

This module implements an AI agent that analyzes the accumulated workflow context,
summarizes key information, and ensures the context remains within manageable token
limits (under 150,000 tokens) for optimal AI model performance and cost efficiency.
"""

from pydantic import BaseModel
from deadend_agent.context.context_engine import ContextEngine
from deadend_prompts import render_agent_instructions
from .factory import AgentRunner

class ReporterOutput(BaseModel):
    summarized_context: str

class ReporterAgent(AgentRunner):
    """
    Reporter Agent 
    """
    def __init__(self, model, deps_type, tools, validation_type: str | None, validation_format: str | None):
        reporter_instructions = render_agent_instructions(
            "reporter", 
            tools={},
            validation_type=validation_type,
            validation_format=validation_format
        )
        self._set_description()
        super().__init__(
            name="reporter",
            model=model,
            instructions=reporter_instructions,
            deps_type=deps_type,
            output_type=ReporterOutput,
            tools=[]
        )
    async def run(self, prompt, deps, message_history, usage, usage_limits, deferred_tool_results=None):
        return await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=None,
        )

    async def summarize_context(self, context_engine: ContextEngine):
        """Summarize the workflow context and update it using the context engine setter.
        
        Args:
            context_engine: The ContextEngine instance containing the workflow context to summarize.
        
        Returns:
            ReporterOutput: The summarized context output.
        """
        # Get the current workflow context (with possible summarization)
        current_context = context_engine.workflow_context

        # Create a prompt for summarization
        summarization_prompt = f"""
analyze and summarize the following workflow context while preserving all critical security information, vulnerabilities, and technical details. Keep the summary under 150,000 tokens while maintaining actionable intelligence for continued security testing.
Current workflow context:
{current_context}
        """

        # Run the reporter agent to get the summary
        result = await self.run(
            prompt=summarization_prompt,
            deps=None,
            message_history="",
            usage=None,
            usage_limits=None
        )
        # Extract the summarized context from the result
        if hasattr(result, 'output') and hasattr(result.output, 'summarized_context'):
            summarized_context = result.output.summarized_context
        else:
            # Fallback if the output structure is different
            summarized_context = str(result.output)
        print(f"result reporter : {result}")
        print(f"result reporter output : {result.output}")
        # Update the context engine with the summarized context
        context_engine.set_new_workflow(summarized_context)

        return result

    def _set_description(self):
        self.description = "The reporter summarize the context as it understood it."
