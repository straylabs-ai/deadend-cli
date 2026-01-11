# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.

COMPATIBILITY LAYER: AgentRunner now wraps the new CoreAgent implementation
while maintaining the same interface as Pydantic AI for backward compatibility.
"""
from __future__ import annotations
from typing import Any, List
from pydantic import BaseModel
from pydantic_ai import DeferredToolResults, UnexpectedModelBehavior
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel
from deadend_agent.core_agent import CoreAgent, AgentResult as CoreAgentResult, get_session_metrics, UsageLimitExceeded
from deadend_agent.hooks import get_event_hooks


class AgentOutput(BaseModel):
    """Standard output format for agent execution results.

    Simplified output with 4 essential fields for all agents.

    Attributes:
        detailed_summary: Summary of what was done, techniques used,
            what worked/failed, and suggested next steps
        proofs: Evidence including tool outputs, requests/responses,
            flags found, credentials discovered
        confidence_score: Confidence in findings (0.0-1.0)
        thoughts: Agent's reasoning and analysis during execution
    """
    detailed_summary: str = ""
    proofs: str = ""
    confidence_score: float = 0.5
    thoughts: str = ""


def extract_text_from_messages(messages: List[ModelMessage], max_chars: int = 3000) -> str:
    """Extract text content (agent's reasoning/thoughts) from captured messages.

    Extracts all TextPart content from ModelResponse messages to capture
    the agent's reasoning, analysis, and thoughts during execution.

    Args:
        messages: List of ModelMessage from capture_run_messages()
        max_chars: Maximum characters to extract (default 3000)

    Returns:
        Concatenated text content from the agent's responses
    """
    text_parts: List[str] = []
    total_chars = 0

    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    text = part.content
                    if text and isinstance(text, str):
                        # Truncate if adding this would exceed max
                        remaining = max_chars - total_chars
                        if remaining <= 0:
                            break
                        if len(text) > remaining:
                            text = text[:remaining] + "..."
                        text_parts.append(text)
                        total_chars += len(text)
            if total_chars >= max_chars:
                break

    return "\n".join(text_parts)


def summarize_agent_thought(raw_thought: str, max_length: int = 200) -> str:
    """Summarize a raw agent thought into a concise insight.

    Extracts the key actionable insight from verbose agent reasoning.
    This is a heuristic-based summarization (no LLM call).

    Args:
        raw_thought: The raw reasoning text from the agent
        max_length: Maximum length of the summary

    Returns:
        A concise summary of the thought
    """
    if not raw_thought:
        return ""

    # Keywords that indicate important insights
    insight_keywords = [
        "found", "discovered", "detected", "vulnerable", "blocked",
        "filtered", "successful", "failed", "confirmed", "indicates",
        "suggests", "requires", "because", "therefore", "however",
        "important", "key finding", "result", "conclusion"
    ]

    # Split into sentences
    sentences = []
    for sep in [".", "!", "\n\n"]:
        if not sentences:
            sentences = raw_thought.split(sep)
        else:
            new_sentences = []
            for s in sentences:
                new_sentences.extend(s.split(sep))
            sentences = new_sentences

    # Clean and filter sentences
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 20]

    if not sentences:
        # Fallback: just truncate
        return raw_thought[:max_length] + "..." if len(raw_thought) > max_length else raw_thought

    # Score sentences by keyword presence
    scored_sentences = []
    for sentence in sentences:
        score = sum(1 for kw in insight_keywords if kw.lower() in sentence.lower())
        # Boost sentences that look like conclusions (start with certain words)
        if any(sentence.lower().startswith(s) for s in ["the ", "this ", "i found", "result:"]):
            score += 1
        scored_sentences.append((score, sentence))

    # Sort by score (highest first)
    scored_sentences.sort(key=lambda x: -x[0])

    # Take the best sentence(s) that fit
    summary_parts = []
    current_length = 0
    for score, sentence in scored_sentences:
        if current_length + len(sentence) + 2 <= max_length:
            summary_parts.append(sentence)
            current_length += len(sentence) + 2
        if current_length >= max_length * 0.8:
            break

    if not summary_parts:
        # Fallback: use first sentence truncated
        return sentences[0][:max_length] + "..." if len(sentences[0]) > max_length else sentences[0]

    return ". ".join(summary_parts)


class ExtractedThought:
    """Container for an extracted and summarized agent thought."""

    def __init__(self, agent_name: str, raw_thought: str, summary: str = "", relevance: float = 0.5):
        self.agent_name = agent_name
        self.raw_thought = raw_thought
        self.summary = summary or summarize_agent_thought(raw_thought)
        self.relevance = relevance

    def to_dict(self) -> dict:
        """Convert to dictionary for context engine."""
        return {
            "agent_name": self.agent_name,
            "thought": self.raw_thought,
            "summary": self.summary,
            "relevance": self.relevance
        }


class FallbackAgentResult:
    """Fallback result wrapper when agent execution fails.

    Provides a consistent interface with .output attribute that matches
    the expected AgentRunResult interface, allowing callers to handle
    failures gracefully without special-casing.

    Attributes:
        output: The fallback AgentOutput with low confidence
        error: The original error message
        raw_messages: Raw messages captured during failed execution
    """

    def __init__(
        self,
        output: AgentOutput,
        error: str = "",
        raw_messages: Any = None
    ):
        self.output = output
        self.error = error
        self.raw_messages = raw_messages


class AgentRunner:
    """
    Backward-compatible wrapper that uses CoreAgent under the hood.

    This class maintains the same interface as the previous Pydantic AI implementation
    but uses the new CoreAgent system internally. This allows existing code to work
    without modifications.
    """
    def __init__(
        self,
        name: str,
        model: AIModel,
        instructions: str | None,
        deps_type: Any | None,
        output_type: Any | None,
        tools: list,
    ):
        """Initialize an AgentRunner instance.

        Args:
            name: Unique identifier for this agent instance
            model: The AI model to use for agent execution
            instructions: System instructions/prompt for the agent
            deps_type: Optional dependency type for the agent (not used in CoreAgent)
            output_type: Expected output type for the agent's responses
            tools: List of tool functions or Tool objects available to the agent
        """
        self.name = name
        self.deps_type = deps_type

        # Handle list output_type (e.g., [RequesterOutput, DeferredToolRequests])
        # Use the first element as the primary output schema
        if isinstance(output_type, list) and len(output_type) > 0:
            self.output_type = output_type[0]  # Primary output type for fallbacks
            output_schema = output_type[0]  # For CoreAgent
        else:
            self.output_type = output_type
            output_schema = output_type

        # Extract model info from AIModel
        model_name, api_key, api_base = self._extract_model_info(model)

        # Extract tool functions from Tool objects or use directly if callable
        tool_functions = []
        for tool in tools:
            if callable(tool):
                tool_functions.append(tool)
            elif hasattr(tool, 'function') and callable(tool.function):
                # Pydantic AI Tool object
                tool_functions.append(tool.function)

        # Create CoreAgent instance
        self.agent = CoreAgent(
            model=model_name,
            instructions=instructions,
            tools=tool_functions,
            output_schema=output_schema,
            api_key=api_key,
            api_base=api_base,
            name=name,
        )

        self.response = None

    async def run(
        self,
        prompt: str,
        deps: Any,
        message_history,
        usage: RunUsage | None,
        usage_limits: UsageLimits | None,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        """Execute the agent with the given prompt and parameters.

        Args:
            prompt: The user prompt/task for the agent to process
            deps: Optional dependencies to pass to the agent
            message_history: Previous conversation messages for context
            usage: Optional usage tracking object
            usage_limits: Optional limits for token usage
            deferred_tool_results: Optional deferred tool results (not used in CoreAgent)

        Returns:
            CoreAgentResult or FallbackAgentResult containing the agent's output.
            FallbackAgentResult is returned when UsageLimitExceeded or other errors occur,
            with a low confidence score (0.1) to signal the failure to callers.
        """
        try:
            # Pass deps as-is to CoreAgent (it will be wrapped in RunContextCompat for tools)
            # This preserves the original object (e.g., SupervisorDeps) so tools can access
            # attributes like .requester_agent, .shell_agent, etc.

            # Convert usage_limits to dict
            limits_dict = {}
            if usage_limits:
                limits_dict["requests"] = getattr(usage_limits, 'request_limit', None) or float('inf')
                limits_dict["tools"] = getattr(usage_limits, 'tool_call_limit', None) or float('inf')

            # Run CoreAgent
            result = await self.agent.run(
                prompt=prompt,
                deps=deps,  # Pass original deps object, not converted dict
                message_history=message_history,
                usage_limits=limits_dict,
            )

            # Update usage object if provided
            # Note: RunUsage.total_tokens is a read-only computed property,
            # so we only update the request count
            if usage:
                usage.requests = self.agent.request_count

            # Record session metrics
            # Extract session_id from deps (could be dict or object)
            # Convert to string in case it's a UUID
            if deps is None:
                session_id = "default"
            elif isinstance(deps, dict):
                session_id = deps.get("session_id", "default")
            else:
                session_id = getattr(deps, "session_id", "default")
            # Convert UUID to string if needed
            if session_id and session_id != "default":
                session_id = str(session_id)
                session_metrics = get_session_metrics(session_id)
                session_metrics.record_completion(
                    agent_name=self.name,
                    prompt_tokens=self.agent.prompt_tokens,
                    completion_tokens=self.agent.completion_tokens,
                )
                session_metrics.record_tool_call(count=self.agent.tool_call_count)
                session_metrics.save()

            # Ensure thoughts are populated
            if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                if not result.output.thoughts and result.thoughts:
                    result.output.thoughts = result.thoughts

            return result

        except UsageLimitExceeded as e:
            error_msg = str(e)
            print(f"[AgentRunner] UsageLimitExceeded: {error_msg}")

            # Create a fallback result with the correct output type
            fallback_output = self._create_fallback_output(error_msg, "Usage limit exceeded")
            return FallbackAgentResult(
                output=fallback_output,
                error=error_msg,
                raw_messages=[]
            )

        except Exception as e:
            error_msg = str(e)
            print(f"[AgentRunner] Error: {error_msg}")

            # Create a fallback result with the correct output type
            fallback_output = self._create_fallback_output(error_msg, "Agent error")
            return FallbackAgentResult(
                output=fallback_output,
                error=error_msg,
                raw_messages=[]
            )

    def _deps_to_dict(self, deps: Any) -> dict:
        """Convert dataclass/object deps to dict for CoreAgent.

        Args:
            deps: Dependencies object (usually a dataclass)

        Returns:
            Dict with all non-private attributes
        """
        if deps is None:
            return {}

        if isinstance(deps, dict):
            return deps

        # Convert dataclass or object to dict
        result = {}
        for attr_name in dir(deps):
            if not attr_name.startswith("_") and not callable(getattr(deps, attr_name)):
                try:
                    result[attr_name] = getattr(deps, attr_name)
                except Exception:
                    pass

        return result

    def _extract_model_info(self, model: AIModel) -> tuple[str, str | None, str | None]:
        """Extract model name, API key, and base URL from AIModel.

        For OpenAI-compatible custom endpoints (local models), formats the model
        name as "openai/<model_name>" for litellm compatibility.

        Args:
            model: AIModel instance

        Returns:
            Tuple of (model_name, api_key, api_base)
        """
        # Handle different model types
        model_name = str(model)
        api_key = None
        api_base = None

        if hasattr(model, 'model_name'):
            model_name = model.model_name

        # Extract from provider (preferred - this is where config values are stored)
        # Pydantic AI stores provider as _provider (private field)
        if hasattr(model, '_provider'):
            provider = model._provider

            # Pydantic AI providers store api_key/base_url in the underlying client
            # For OpenAIProvider, access via provider.client property
            if hasattr(provider, 'client'):
                try:
                    client = provider.client

                    # Extract api_key from client
                    if hasattr(client, 'api_key'):
                        raw_key = client.api_key
                        # Handle SecretStr or similar types - convert to string
                        if hasattr(raw_key, 'get_secret_value'):
                            api_key = raw_key.get_secret_value()
                        else:
                            api_key = str(raw_key) if raw_key else None

                    # Extract base_url from client
                    if hasattr(client, 'base_url'):
                        # OpenAI client stores base_url as httpx.URL object
                        api_base = str(client.base_url)

                except Exception:
                    pass

            # Also try provider properties (some providers expose these)
            if not api_base and hasattr(provider, 'base_url'):
                try:
                    api_base = provider.base_url
                except Exception:
                    pass

        # Fallback: extract directly from model
        if not api_key and hasattr(model, 'api_key'):
            api_key = model.api_key

        if not api_base:
            for attr in ['api_base', 'base_url']:
                if hasattr(model, attr):
                    val = getattr(model, attr, None)
                    if val:
                        api_base = val
                        break

        # For OpenAI-compatible custom endpoints (local models), format for litellm
        # If we have a custom base_url, this is an OpenAI-compatible endpoint
        if api_base and api_base not in [
            "https://api.openai.com/v1",
            "https://api.anthropic.com",
            "https://generativelanguage.googleapis.com",
            "https://openrouter.ai/api/v1"
        ]:
            # Custom endpoint - prefix with "openai/" for litellm
            # But only if the model doesn't already have a provider prefix
            known_prefixes = ("openai/", "azure_ai/", "anthropic/", "gemini/", "openrouter/", "bedrock/", "vertex_ai/")
            if not any(model_name.startswith(prefix) for prefix in known_prefixes):
                model_name = f"openai/{model_name}"

        # Debug logging
        print(f"[AgentRunner] Extracted model info: model_name={model_name}, api_key={'***' if api_key else None}, api_base={api_base}")

        return model_name, api_key, api_base

    def _create_fallback_output(self, error_msg: str, error_type: str) -> BaseModel:
        """Create a fallback output with the correct schema type.

        Args:
            error_msg: The error message
            error_type: Type of error (e.g., "Usage limit exceeded", "Agent error")

        Returns:
            Fallback output instance (either output_type or AgentOutput)
        """
        full_msg = f"{error_type}: {error_msg}. Agent: {self.name}"

        # Try to create instance of the specified output_type
        if self.output_type and hasattr(self.output_type, 'model_fields'):
            # Get the model fields to determine what to populate
            fields = self.output_type.model_fields
            fallback_data = {}

            # Map common field names to error values
            field_mappings = {
                'detailed_summary': full_msg,
                'summarized_context': full_msg,
                'summary': full_msg,
                'message': full_msg,
                'content': full_msg,
                'text': full_msg,
                'proofs': "",
                'confidence_score': 0.1,
                'thoughts': "",
            }

            # Populate fields that exist in the schema
            for field_name, default_value in field_mappings.items():
                if field_name in fields:
                    fallback_data[field_name] = default_value

            try:
                return self.output_type(**fallback_data)
            except Exception:
                # If instantiation fails, fall back to AgentOutput
                pass

        # Default fallback to AgentOutput
        return AgentOutput(
            detailed_summary=full_msg,
            proofs="",
            confidence_score=0.1,
            thoughts=""
        )
