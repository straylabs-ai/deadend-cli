# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Authenticator agent: single-purpose subagent that owns authentication.

The AuthenticatorAgent drives the ``authenticate`` tool to perform the target's
real authentication workflow (form login, SPA/JWT login, same-tab OAuth, popup
OAuth). It persists the resulting cookies / browser storage / derived headers
as a reusable ``AuthContext`` profile so that downstream subagents can opt into
authenticated execution by passing ``auth_profile=<profile>`` to their tools.

This agent must NEVER perform vulnerability testing or any task outside the
authentication workflow itself.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, Tool
from pydantic_ai.usage import RunUsage, UsageLimits

from deadend_agent.agents.factory import AgentOutput, AgentRunner
from deadend_agent.config.settings import ModelSpec
from deadend_agent.tools import authenticate, refresh_auth_context, validate_auth_context
from deadend_prompts import render_agent_instructions, render_tool_description


class AuthenticatorOutput(AgentOutput):
    """Output model for the authenticator agent.

    Inherits from :class:`AgentOutput`: ``detailed_summary``, ``proofs``,
    ``confidence_score``, ``thoughts``. The agent must NEVER include raw cookie
    values, bearer tokens, refresh tokens, passwords or API keys in any field.
    """

    pass


class AuthenticatorAgent(AgentRunner):
    """Single-purpose subagent that authenticates against the current target.

    The agent uses one tool (``authenticate``) which itself uses
    :class:`BrowserSession` and :class:`AuthContextHandler` to persist the
    resulting auth context under
    ``~/.deadend/agents/<agent_id>/<session_id>/auth_context/<profile>.json``.
    Downstream tools (``browser_run_steps``, ``pw_send_payload``) can later
    reuse that context via the ``auth_profile`` argument.
    """

    def __init__(
        self,
        model: ModelSpec,
        deps_type: Any | None,
        target_information: str,
        requires_approval: bool,
    ) -> None:
        tools_metadata = {
            "authenticate": render_tool_description("authenticate"),
            "validate_auth_context": render_tool_description("validate_auth_context"),
            "refresh_auth_context": render_tool_description("refresh_auth_context"),
        }

        self.instructions = render_agent_instructions(
            agent_name="authenticator",
            tools=tools_metadata,
            target=target_information,
        )

        super().__init__(
            name="authenticator",
            model=model,
            instructions=self.instructions,
            deps_type=deps_type,
            output_type=[AuthenticatorOutput, DeferredToolRequests],
            tools=[
                Tool(authenticate, requires_approval=requires_approval),
                Tool(validate_auth_context, requires_approval=requires_approval),
                Tool(refresh_auth_context, requires_approval=requires_approval),
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
    ):
        agent_response = await super().run(
            prompt=prompt,
            deps=deps,
            message_history=message_history,
            usage=usage,
            usage_limits=usage_limits,
            deferred_tool_results=deferred_tool_results,
        )
        return agent_response
