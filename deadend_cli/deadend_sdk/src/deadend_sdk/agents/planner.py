# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Planning agent for orchestrating security research workflows.

This module implements an AI agent that analyzes targets, creates comprehensive
security assessment plans, and coordinates the execution of various security
testing tasks based on the target's characteristics and requirements.
"""

import uuid
from typing import List, Any
from pydantic import BaseModel
from pydantic_ai import Tool
from pydantic_ai.usage import Usage, UsageLimits
from openai import AsyncOpenAI

from deadend_sdk.utils.structures import Task
from .factory import AgentRunner
from deadend_sdk.rag.db_cruds import RetrievalDatabaseConnector
from deadend_sdk.models.registry import AIModel
from deadend_sdk.utils.structures import RagDeps
from deadend_prompts import render_agent_instructions,render_tool_description
from deadend_sdk.tools import webapp_code_rag


class PlannerOutput(BaseModel):
    tasks: List[Task]


class PlannerAgent(AgentRunner):
    """The planner agent """
    
    def __init__(
            self, 
            model: AIModel, 
            output_type: Any | None, 
        ):
        tools_metadata = {
            "webapp_code_rag": render_tool_description("webapp_code_rag")
        } 
        self.instructions = render_agent_instructions(
            agent_name="planner", 
            tools=tools_metadata
        )

        super().__init__(
            name="planner_agent", 
            model=model,  
            instructions=self.instructions, 
            deps_type=RagDeps, 
            output_type=output_type, 
            tools=[Tool(webapp_code_rag, max_retries=5)]
        )
    
    async def run(self, user_prompt, deps, message_history, usage, usage_limits):
        return await super().run(
            user_prompt=user_prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=None,
        )



class Planner:
    """
    The planner plans and tracks the information related to the goal

    We supply to it several information: 
    - the target URL
    - web crawler results of the page
    - the authentication data if needed
    - API endpoints or OpenAPI specification file

    It manages these information in addition to managing 
    the tasks and replanning if necessary.

    When a task is pending, it calls the testing grounds and awaits a response. 
    The response is analyzed by an LLM call, and add the final result to the task. 
    It then call the testing grounds for the following task testing and so on. 
    """
    def __init__(self, model: AIModel, target: str, api_spec: str):
        self.target = target
        self.api_spec = api_spec
        self.tasks = List[Task]

        self.agent = PlannerAgent(
            model=model, 
            output_type=PlannerOutput,
        )

    async def run(self, 
            user_prompt: str, 
            message_history: str, 
            usage: Usage, 
            usage_limits: UsageLimits, 
            openai: AsyncOpenAI, 
            rag: RetrievalDatabaseConnector,
            session_id: uuid.UUID
        ):
        
        rag_deps = RagDeps(
            openai=openai,
            rag=rag,
            target=self.target,
            session_id=session_id
        )

        return await self.agent.run(
            user_prompt=user_prompt,
            deps=rag_deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits
        )

