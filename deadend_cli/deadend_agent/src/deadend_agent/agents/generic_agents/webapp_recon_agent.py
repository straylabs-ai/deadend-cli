# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web application reconnaissance agent for information gathering and analysis.

This module implements an AI agent that performs comprehensive reconnaissance
on web applications, including directory enumeration, technology detection,
vulnerability scanning, and information gathering for security assessments.
"""
from typing import Any
from pathlib import Path
import json
from pydantic import BaseModel
from pydantic_ai import Tool, DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.agents.factory import AgentRunner
from deadend_agent.context.memory import MemoryHandler
from deadend_agent.models.registry import AIModel
from deadend_agent.tools import (
    is_valid_request_detailed,
    pw_send_payload,
    webapp_code_rag
)
from deadend_prompts import render_agent_instructions, render_tool_description


class RequesterOutput(BaseModel):
    """Output model for web reconnaissance request operations.
    
    Captures the agent's reasoning process, current state, and raw response data
    from reconnaissance activities on the target web application.
    
    Attributes:
        reasoning: The agent's reasoning or justification for the request action.
        state: The current state of the reconnaissance operation.
        raw_response: The raw response data received from the request.
    """
    reasoning: str
    state: str
    raw_response: str

class RequesterSecOutput(BaseModel):
    """Output model for Playwright's requester.

    This playwright requester contains pour specific information for the agent to 
    work on.
    
    """
    payload: str
    vulnerability_category: str
    attempt: bool
    request: str
    response: str


class DummyCreds(BaseModel):
    """Dummy credentials model for testing and automation purposes.
    
    Stores test credentials used during web application reconnaissance to
    interact with authentication systems without using real user accounts.
    
    Attributes:
        dummy_email: Optional dummy email address for testing authentication.
        dummy_username: Optional dummy username for testing authentication.
        dummy_password: Optional dummy password for testing authentication.
    """
    dummy_email: str | None = None
    dummy_username: str | None = None
    dummy_password: str | None = None

class WebappReconAgent(AgentRunner):
    """
    The webapp recon agent is the agent in charge of doing the recon on the target. 
    The goal is to retrieve all the important information that we can 
    """

    def __init__(
        self,
        model: AIModel,
        deps_type: Any | None,
        target_information: str,
        requires_approval: bool,
    ):
        tools_metadata = {
            "is_valid_request_detailed": render_tool_description("is_valid_request_detailed"),
            "pw_send_payload": render_tool_description("send_payload"),
            "webapp_code_rag": render_tool_description("webapp_code_rag")
        }

        path_creds = Path.home() / ".cache" / "deadend" / "memory" / "reusable_credentials.json"
        with open(path_creds, 'r', encoding="utf-8") as creds_file:
            all_creds = creds_file.read()
            json_creds = json.loads(all_creds)
            dummy_email = json_creds["accounts"][0]["dummy_email"]
            dummy_password = json_creds["accounts"][0]["dummy_password"]
            dummy_username = json_creds["accounts"][0]["dummy_username"]
        dummycreds = DummyCreds(
            dummy_email=dummy_email,
            dummy_password=dummy_password,
            dummy_username=dummy_username
        )

        self.instructions = render_agent_instructions(
            agent_name="webapp_recon",
            tools=tools_metadata,
            target=target_information,
            creds = dummycreds
        )

        super().__init__(
            name="webapp_recon",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[RequesterSecOutput, DeferredToolRequests],
            tools=[
                Tool(is_valid_request_detailed),
                Tool(pw_send_payload, requires_approval=requires_approval),
                Tool(webapp_code_rag)
            ]
        )

    async def run(
        self,
        prompt,
        deps,
        message_history,
        usage: RunUsage | None,
        usage_limits:UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        agent_response = await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results
        )
        # if memory:
        #     agent_output = agent_response.output
        #     if isinstance(agent_output, RequesterSecOutput):
        #         deps.memory.add_agent_result_to_memory(
        #             agent_name=self.name,
        #             payload=agent_output.payload,
        #             vulnerability_category=agent_output.vulnerability_category,
        #             attempt=agent_output.attempt,
        #             request=agent_output.request,
        #             response=agent_output.response
        #         )
        return agent_response
