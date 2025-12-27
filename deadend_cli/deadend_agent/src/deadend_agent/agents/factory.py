# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Agent factory for creating and managing AI agent instances.

This module provides a factory pattern implementation for creating and
configuring AI agents with proper error handling, retry logic, and
usage tracking for the security research framework.
"""
from __future__ import annotations
from typing import Any, List
from pydantic import BaseModel, Field
from pydantic_ai import Agent, capture_run_messages, DeferredToolResults, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel
from deadend_agent.hooks import get_event_hooks


class ToolAttempt(BaseModel):
    """Record of a single tool call made during agent execution.

    Captures the tool name, arguments, and result for each tool call,
    enabling full visibility into what the agent tried during its run.

    Attributes:
        tool_name: Name of the tool that was called
        tool_args: Arguments passed to the tool (truncated for size)
        tool_result: Result returned by the tool (truncated for size)
        success: Whether the tool call succeeded
    """
    tool_name: str
    tool_args: str = ""
    tool_result: str = ""
    success: bool = True

    @classmethod
    def from_call_and_return(
        cls,
        call: ToolCallPart,
        return_part: ToolReturnPart | None = None
    ) -> "ToolAttempt":
        """Create ToolAttempt from pydantic-ai message parts."""
        # Extract args as string, truncate if too long
        args_str = str(call.args)[:500] if call.args else ""

        # Extract result as string, truncate if too long
        result_str = ""
        success = True
        if return_part:
            result_str = str(return_part.content)[:1500]
            # Check for error indicators
            if "error" in result_str.lower()[:100] or "exception" in result_str.lower()[:100]:
                success = False

        return cls(
            tool_name=call.tool_name,
            tool_args=args_str,
            tool_result=result_str,
            success=success
        )


class AgentOutput(BaseModel):
    """Standard output format for agent execution results.

    This model provides a consistent structure for agent outputs, including
    confidence scores, execution notes, updated context state, and all tool
    attempts made during execution.

    Attributes:
        confidence_score: Confidence score (0.0-1.0) indicating the agent's
            confidence in the execution result
        notes: Optional notes or reasoning from the agent about the execution
        updated_state: Optional dictionary containing updated context state
            from the agent's execution
        attempts: List of all tool calls made during this agent run
        agent_reasoning: Extracted text reasoning from agent's responses
            (populated on failure to preserve agent's thoughts)
        thought_summary: Concise summary of the agent's key insight
    """
    confidence_score: float
    notes: str | None = None
    updated_state: dict[str, Any] | None = None
    attempts: List[ToolAttempt] = Field(default_factory=list)
    agent_reasoning: str | None = None
    thought_summary: str | None = None


def extract_tool_attempts_from_messages(messages: List[ModelMessage]) -> List[ToolAttempt]:
    """Extract all tool attempts from pydantic-ai captured messages.

    Pairs tool calls with their corresponding returns to create
    a complete record of all tool invocations during an agent run.

    Args:
        messages: List of ModelMessage from capture_run_messages()

    Returns:
        List of ToolAttempt objects representing each tool call
    """
    attempts: List[ToolAttempt] = []

    # Build a map of tool_call_id -> ToolCallPart
    tool_calls: dict[str, ToolCallPart] = {}
    tool_returns: dict[str, ToolReturnPart] = {}

    for msg in messages:
        # ModelResponse contains tool calls
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    tool_calls[part.tool_call_id] = part

        # ModelRequest contains tool returns
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    tool_returns[part.tool_call_id] = part

    # Match calls with returns
    for call_id, call in tool_calls.items():
        return_part = tool_returns.get(call_id)
        attempt = ToolAttempt.from_call_and_return(call, return_part)
        attempts.append(attempt)

    return attempts


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
        attempts: Tool attempts extracted from the failed run
    """

    def __init__(
        self,
        output: AgentOutput,
        error: str = "",
        raw_messages: Any = None,
        attempts: List[ToolAttempt] | None = None
    ):
        self.output = output
        self.error = error
        self.raw_messages = raw_messages
        # Attach attempts to output
        if attempts:
            self.output.attempts = attempts


class AgentRunner:
    """
    Wrapper for Pydantic AI agents that provides a consistent interface for agent execution.

    This class encapsulates a Pydantic AI Agent instance and provides methods to run
    agent tasks with proper configuration, error handling, and usage tracking.
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
            deps_type: Optional dependency type for the agent
            output_type: Expected output type for the agent's responses
            tools: List of tools available to the agent
        """
        self.name = name
        self.agent = Agent(
            model=model,
            instructions=instructions,
            deps_type=deps_type,
            output_type=output_type,
            tools=tools
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
            deferred_tool_results: Optional deferred tool results from previous runs

        Returns:
            AgentRunResult or FallbackAgentResult containing the agent's output.
            The output includes all tool attempts made during execution.
            FallbackAgentResult is returned when UnexpectedModelBehavior occurs,
            with a low confidence score (0.1) to signal the failure to callers.

        Note:
            Future enhancements will include token limit checking, rate-limit handling,
            and interruption support.
        """
        with capture_run_messages() as messages:
            try:
                result = await self.agent.run(
                    user_prompt=prompt,
                    deps=deps,
                    message_history=message_history,
                    usage=usage,
                    usage_limits=usage_limits,
                    deferred_tool_results=deferred_tool_results
                )

                # Extract tool attempts from captured messages
                msg_list = list(messages)
                attempts = extract_tool_attempts_from_messages(msg_list)

                # Extract agent's reasoning for successful runs too
                agent_reasoning = extract_text_from_messages(msg_list, max_chars=1500)
                thought_summary = summarize_agent_thought(agent_reasoning) if agent_reasoning else None

                # Emit AGENT_THOUGHT event if reasoning was extracted
                if agent_reasoning:
                    hooks = get_event_hooks()
                    # Try to get session_id from deps
                    session_id = getattr(deps, "session_id", None) or "unknown"
                    hooks.emit_agent_thought(
                        session_id=session_id,
                        agent_name=self.name,
                        thought=agent_reasoning,
                        summary=thought_summary,
                        relevance=0.7,  # Higher relevance for successful runs
                    )

                # Attach attempts and thought summary to the output
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    result.output.attempts = attempts
                    result.output.agent_reasoning = agent_reasoning
                    result.output.thought_summary = thought_summary
                elif hasattr(result, 'output') and hasattr(result.output, 'attempts'):
                    # For subclasses that have attempts field
                    result.output.attempts = attempts
                    if hasattr(result.output, 'agent_reasoning'):
                        result.output.agent_reasoning = agent_reasoning
                    if hasattr(result.output, 'thought_summary'):
                        result.output.thought_summary = thought_summary

            except UnexpectedModelBehavior as e:
                error_msg = str(e)
                print(f"[AgentRunner] UnexpectedModelBehavior: {error_msg}")

                # Extract any tool attempts that occurred before failure
                msg_list = list(messages)
                attempts = extract_tool_attempts_from_messages(msg_list)

                # Extract agent's text reasoning/thoughts from messages
                agent_reasoning = extract_text_from_messages(msg_list, max_chars=2500)
                thought_summary = summarize_agent_thought(agent_reasoning) if agent_reasoning else None
                if agent_reasoning:
                    print(f"[AgentRunner] Preserved agent reasoning ({len(agent_reasoning)} chars)")
                    # Emit AGENT_THOUGHT event even on error to preserve reasoning
                    hooks = get_event_hooks()
                    session_id = getattr(deps, "session_id", None) or "unknown"
                    hooks.emit_agent_thought(
                        session_id=session_id,
                        agent_name=self.name,
                        thought=agent_reasoning,
                        summary=thought_summary,
                        relevance=0.4,  # Lower relevance for failed runs
                    )

                # Build comprehensive notes with error and preserved reasoning
                notes_parts = [f"Agent behavior error: {error_msg}"]
                if thought_summary:
                    notes_parts.append(f"Key insight: {thought_summary}")

                # Create a fallback result with low confidence but preserved context
                fallback_output = AgentOutput(
                    confidence_score=0.1,  # Low confidence signals failure
                    notes="\n".join(notes_parts),
                    updated_state={
                        "error": error_msg,
                        "agent": self.name,
                        "partial_reasoning": agent_reasoning[:500] if agent_reasoning else ""
                    },
                    attempts=attempts,  # Include attempts even on failure
                    agent_reasoning=agent_reasoning,  # Store full reasoning
                    thought_summary=thought_summary
                )
                result = FallbackAgentResult(
                    output=fallback_output,
                    error=error_msg,
                    raw_messages=msg_list,
                    attempts=attempts
                )
        return result
