# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Core agent implementation using LiteLLM and Instructor.

- Uses LiteLLM for universal model access
- Uses Instructor for structured output
- Auto-generates tool schemas from function signatures
- Implements retry logic with tenacity
- Tracks usage with simple counters
- Integrates OpenTelemetry for observability
"""
from __future__ import annotations

import json
import inspect
import asyncio
import os
from typing import Callable, Type, Any, cast
from rich.console import Console
from rich.panel import Panel
from pydantic import BaseModel, Field
from pydantic_ai import RunUsage
from opentelemetry import trace
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError
)
from litellm.exceptions import (
    RateLimitError as LiteLLMRateLimitError,
    ServiceUnavailableError,
    Timeout as LiteLLMTimeout,
    APIConnectionError as LiteLLMConnectionError,
    ContentPolicyViolationError,
)
from deadend_agent.logging import get_module_logger
from . import (
    UsageLimitExceeded,
    LLMError,
    RateLimitError as CoreRateLimitError,
    QuotaExceededError,
    AuthenticationError,
    ConnectionError as CoreConnectionError,
    ModelNotFoundError,
    InvalidRequestError,
)
from deadend_agent.hooks import get_event_hooks

# OpenInference span attributes for tool tracing (generic pattern usable by any agent)
try:
    from openinference.semconv.trace import MessageAttributes as _MsgAttrs
    from openinference.semconv.trace import SpanAttributes as _SpanAttrs
    _TOOL_ATTR_KIND = _SpanAttrs.OPENINFERENCE_SPAN_KIND
    _TOOL_ATTR_NAME = _SpanAttrs.TOOL_NAME
    _TOOL_ATTR_PARAMS = _SpanAttrs.TOOL_PARAMETERS
    _TOOL_ATTR_INPUT = _SpanAttrs.INPUT_VALUE
    _TOOL_ATTR_OUTPUT = _SpanAttrs.OUTPUT_VALUE
    _LLM_INPUT_PREFIX = _SpanAttrs.LLM_INPUT_MESSAGES
    _LLM_OUTPUT_PREFIX = _SpanAttrs.LLM_OUTPUT_MESSAGES
    _LLM_MSG_ROLE = _MsgAttrs.MESSAGE_ROLE
    _LLM_MSG_CONTENT = _MsgAttrs.MESSAGE_CONTENT
    _LLM_MSG_TOOL_CALLS = _MsgAttrs.MESSAGE_TOOL_CALLS
    _LLM_MODEL_NAME = _SpanAttrs.LLM_MODEL_NAME
except ImportError:
    _TOOL_ATTR_KIND = "openinference.span.kind"
    _TOOL_ATTR_NAME = "tool.name"
    _TOOL_ATTR_PARAMS = "tool.parameters"
    _TOOL_ATTR_INPUT = "input.value"
    _TOOL_ATTR_OUTPUT = "output.value"
    _LLM_INPUT_PREFIX = "llm.input_messages"
    _LLM_OUTPUT_PREFIX = "llm.output_messages"
    _LLM_MSG_ROLE = "message.role"
    _LLM_MSG_CONTENT = "message.content"
    _LLM_MSG_TOOL_CALLS = "message.tool_calls"
    _LLM_MODEL_NAME = "llm.model_name"

# Custom attribute for LLM thinking/reasoning content (not part of OpenInference yet)
_ATTR_LLM_THINKING = "llm.thinking_content"

logger = get_module_logger(__name__)
# Rich console for colored output - uses stderr to avoid breaking RPC communication
console = Console(force_terminal=True, stderr=True)

try:
    import litellm
    from litellm import acompletion
    # Suppress litellm debug info
    cast(Any, litellm).suppress_debug_info = True
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False

try:
    import instructor
    INSTRUCTOR_AVAILABLE = True
except ImportError:
    INSTRUCTOR_AVAILABLE = False

try:
    from aiolimiter import AsyncLimiter
    AIOLIMITER_AVAILABLE = True
except ImportError:
    AIOLIMITER_AVAILABLE = False

class TokenUsageInfo(BaseModel):
    """Token usage information from LLM response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RunContextCompat:
    """Compatibility wrapper to mimic pydantic_ai's RunContext.

    This allows tools written for Pydantic AI's @agent.tool decorator to work
    with CoreAgent. Tools can access ctx.deps and ctx.usage.
    """

    def __init__(self, deps: Any, usage: RunUsage | None = None):
        self.deps = deps
        self.usage = usage or RunUsage()


class AgentResult(BaseModel):
    """Result from agent execution.

    Attributes:
        output: The agent's output (structured if schema provided, else string)
        thoughts: Extracted agent reasoning/thoughts from message history
        usage: Token usage information
        request_count: Number of LLM requests made
        tool_call_count: Number of tool calls executed
    """
    output: Any = Field(..., description="Agent output")
    thoughts: str = Field(default="", description="Agent reasoning/thoughts")
    raw_messages: list[dict] = Field(default_factory=list, description="Full conversation transcript including tool results")
    usage: TokenUsageInfo = Field(default_factory=TokenUsageInfo, description="Token usage")
    request_count: int = Field(default=0, description="LLM requests made")
    tool_call_count: int = Field(default=0, description="Tool calls executed")


class CoreAgent:
    """Core agent implementation using LiteLLM and Instructor.

    Philosophy: Simplest implementation that works.
    - No unnecessary abstractions
    - Plain functions for tools
    - Simple counters for usage tracking
    - Direct use of libraries as intended
    """

    _concurrency_semaphores: dict[str, asyncio.Semaphore] = {}

    def __init__(
        self,
        model: str,
        instructions: str,
        tools: list[Callable] | None = None,
        output_schema: Type[BaseModel] | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        rate_limit_rpm: int = 200,
        name: str = "agent",
    ):
        """Initialize CoreAgent.

        Args:
            model: Model identifier
            instructions: System instructions/prompt for the agent
            tools: List of callable tool functions (default: None)
            output_schema: Pydantic model for structured output (default: None)
            api_key: API key for the model provider (default: None, uses env)
            api_base: Base URL for API (default: None, uses provider default)
            rate_limit_rpm: Rate limit in requests per minute (default: 60)
            name: Name of the agent for logging (default: "agent")
        """
        if not LITELLM_AVAILABLE:
            raise ImportError("litellm is required. Install with: pip install litellm")

        self.name = name
        self.model = model
        self.instructions = instructions
        self.tools = tools or []
        self.output_schema = output_schema
        self.api_key = api_key
        self.api_base = api_base
        self.tracer = trace.get_tracer(name)
        self.concurrent_limiter = self._get_concurrency_limiter()

        # Rate limiting - simple AsyncLimiter
        if AIOLIMITER_AVAILABLE:
            self.rate_limiter = AsyncLimiter(rate_limit_rpm, 60)
        else:
            self.rate_limiter = None
            logger.warning("aiolimiter not available, rate limiting disabled")

        # Usage counters - simple ints
        self.request_count = 0
        self.tool_call_count = 0
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

        # Instructor client for structured output
        # We always *attempt* to use Instructor when available and an output_schema
        # is provided, but will gracefully fall back to manual JSON extraction
        # if the Instructor call fails for any reason.
        # Only use structured output for actual Pydantic BaseModel subclasses,
        # not plain types like str, int, etc.
        _is_pydantic_schema = (
            isinstance(output_schema, type) and issubclass(output_schema, BaseModel)
        )
        if INSTRUCTOR_AVAILABLE and output_schema and _is_pydantic_schema:
            self.instructor_client = instructor.from_litellm(acompletion)
        else:
            self.instructor_client = None
            if output_schema and not INSTRUCTOR_AVAILABLE and _is_pydantic_schema:
                logger.warning("instructor not available, structured output disabled")

    def _get_concurrency_limiter(self) -> asyncio.Semaphore | None:
        """Return a shared concurrency limiter for this backend/model.

        Azure AI surfaces 429s such as "Server at maximum concurrent capacity (8)".
        A small shared semaphore reduces burst concurrency across agent instances
        before requests reach the provider.
        """
        raw_limit = os.getenv("DEADEND_LLM_MAX_CONCURRENCY", "6").strip()
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 6

        if limit <= 0:
            return None

        limiter_key = f"{self.api_base or 'default'}|{self.model}"
        limiter = self._concurrency_semaphores.get(limiter_key)
        if limiter is None:
            limiter = asyncio.Semaphore(limit)
            self._concurrency_semaphores[limiter_key] = limiter
        return limiter

    def tool(self, func: Callable) -> Callable:
        """Decorator to register a tool function.

        This method provides compatibility with Pydantic AI's @agent.tool decorator pattern.
        It adds the function to the agent's tool list.

        Args:
            func: The tool function to register

        Returns:
            The original function (unmodified)

        Example:
            @agent.tool
            async def my_tool(ctx, param: str) -> str:
                return "result"
        """
        self.tools.append(func)
        try:
            console.print(f"[bold dim][Tool Added][/bold dim] {getattr(func, '__name__', repr(func))}")
        except BlockingIOError:
            pass
        return func

    async def run(
        self,
        prompt: str,
        deps: Any = None,
        message_history: list | None = None,
        usage_limits: dict | None = None,
    ) -> AgentResult:
        """Run the agent with the given prompt.

        Main execution loop:
        1. Build messages from prompt and history
        2. Loop: call LLM → execute tools → repeat until done
        3. Extract structured output if schema provided
        4. Extract thoughts from message history
        5. Return result

        Args:
            prompt: User prompt/task for the agent
            deps: Dependencies to pass to tools - can be dict or object (default: None).
                  For tools using RunContext pattern (ctx parameter), deps will be
                  wrapped in RunContextCompat so tools can access ctx.deps attributes.
            message_history: Previous conversation messages (default: None)
            usage_limits: Usage limits dict with "requests" and "tools" keys (default: None)

        Returns:
            AgentResult with output, thoughts, and usage info

        Raises:
            UsageLimitExceeded: If usage limits are exceeded
        """
        input_val = prompt[:16384] + "..." if len(prompt) > 16384 else prompt
        chain_attrs = {
            _TOOL_ATTR_KIND: "AGENT",
            _TOOL_ATTR_INPUT: input_val,
        }
        with self.tracer.start_as_current_span(self.name, attributes=chain_attrs) as parent_span:
            try:
                return await self._run_impl(
                    prompt=prompt,
                    deps=deps,
                    message_history=message_history,
                    usage_limits=usage_limits,
                    parent_span=parent_span,
                )
            except Exception as e:
                parent_span.set_attribute(_TOOL_ATTR_OUTPUT, str(e))
                parent_span.set_status(trace.Status(trace.StatusCode.ERROR))
                raise

    async def _run_impl(
        self,
        prompt: str,
        deps: Any,
        message_history: list | None,
        usage_limits: dict | None,
        parent_span: Any,
    ) -> AgentResult:
        """Implementation of run(); all logic runs under parent_span."""
        # Store context so _handle_llm_error can emit to CLI with session/task
        self._last_session_id = self._get_session_id(deps)
        self._last_task = prompt

        # Check limits
        if usage_limits:
            if self.request_count >= usage_limits.get("requests", float('inf')):
                raise UsageLimitExceeded(f"Request limit reached: {usage_limits['requests']}")
            if self.tool_call_count >= usage_limits.get("tools", float('inf')):
                raise UsageLimitExceeded(f"Tool call limit reached: {usage_limits['tools']}")

        # Get event hooks for streaming to CLI
        hooks = get_event_hooks()
        session_id = self._get_session_id(deps)

        # Build messages
        messages = self._build_messages(prompt, message_history)

        # Build tool schemas (auto-generated from function signatures)
        tool_schemas = self._build_tool_schemas() if self.tools else None

        # Debug: Log registered tools
        if self.tools:
            tool_names = [getattr(f, '__name__', repr(f)) for f in self.tools]
            try:
                console.print(f"[bold dim][Tools Registered][/bold dim] {', '.join(tool_names)}")
            except BlockingIOError:
                pass

        # Agent loop (Phoenix captures traces via Instructor auto-instrumentation)
        iteration = 0
        max_iterations = 50  # Safety limit

        while iteration < max_iterations:
            iteration += 1
            # Log LLM request
            try:
                console.print(
                    f"\n[bold cyan][LLM Request][/bold cyan] \\[{self.name}] Iteration {iteration}, "
                    f"{len(messages)} messages"
                )
                # Show the last message being sent (user prompt or tool results)
                if messages:
                    last_msg = messages[-1]
                    role = last_msg.get("role", "unknown")
                    if role == "user":
                        content = last_msg.get("content", "")
                        # Truncate if too long
                        if len(content) > 16000:
                            content = content[:16000] + "\n... [truncated]"
                        console.print(Panel(
                            content,
                            title="[bold blue]LLM Input - User[/bold blue]",
                            border_style="blue"
                        ))
                    elif role == "tool":
                        tool_name = last_msg.get("name", "unknown")
                        content = last_msg.get("content", "")
                        # Truncate if too long
                        if len(content) > 16000:
                            content = content[:16000] + "\n... [truncated]"
                        console.print(Panel(
                            content,
                            title=f"[bold magenta]LLM Input - Tool Result ({tool_name})[/bold magenta]",
                            border_style="magenta"
                        ))
            except BlockingIOError:
                pass

            # Rate limit check
            if self.rate_limiter:
                async with self.rate_limiter:
                    response = await self._call_llm_with_retry(messages, tool_schemas)
            else:
                response = await self._call_llm_with_retry(messages, tool_schemas)

            self.request_count += 1

            # Record usage
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                prompt_tok = getattr(usage, 'prompt_tokens', 0)
                completion_tok = getattr(usage, 'completion_tokens', 0)
                total_tok = getattr(usage, 'total_tokens', 0) or (prompt_tok + completion_tok)

                self.prompt_tokens += prompt_tok
                self.completion_tokens += completion_tok
                self.total_tokens += total_tok

            # Add assistant message to history
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract thinking/reasoning content from extended-thinking models
            # LiteLLM surfaces this as `reasoning_content` on the message object
            # (works for Anthropic Claude, DeepSeek, and other thinking models).
            thinking_content = getattr(choice.message, "reasoning_content", None) or ""

            assistant_message = {
                "role": "assistant",
                "content": content,
            }

            # Preserve thinking content in message history so _extract_thoughts
            # can pick it up later.
            if thinking_content:
                assistant_message["thinking_content"] = thinking_content

            tool_calls = getattr(choice.message, "tool_calls", None) or []
            llm_trace_full = self._build_llm_trace_output(content, thinking_content, tool_calls)
            llm_trace_attr = self._truncate_for_span_attr(llm_trace_full)

            # Create a child span for this LLM iteration (OpenInference LLM + Phoenix .llm_call UI)
            with self.tracer.start_as_current_span(
                f"{self.name}.llm_call",
                attributes={
                    _TOOL_ATTR_KIND: "LLM",
                    "llm.iteration": iteration,
                },
            ) as llm_span:
                if self.model:
                    llm_span.set_attribute(_LLM_MODEL_NAME, self.model)
                self._set_llm_input_message_attributes(llm_span, messages)
                if llm_trace_attr:
                    llm_span.set_attribute(_TOOL_ATTR_OUTPUT, llm_trace_attr)
                    llm_span.set_attribute(
                        f"{_LLM_OUTPUT_PREFIX}.0.{_LLM_MSG_ROLE}",
                        "assistant",
                    )
                    llm_span.set_attribute(
                        f"{_LLM_OUTPUT_PREFIX}.0.{_LLM_MSG_CONTENT}",
                        llm_trace_attr,
                    )
                self._set_llm_output_tool_call_attributes(llm_span, tool_calls)
                if thinking_content:
                    think_attr = self._truncate_for_span_attr(thinking_content)
                    llm_span.set_attribute(_ATTR_LLM_THINKING, think_attr)
                    llm_span.add_event("llm.thinking", {"llm.thinking_content": think_attr})
                llm_span.set_status(trace.Status(trace.StatusCode.OK))

            # Log thinking content (if any)
            if thinking_content:
                try:
                    display_thinking = thinking_content
                    if len(thinking_content) > 16000:
                        display_thinking = thinking_content[:16000] + "\n... [truncated]"
                    console.print(Panel(
                        display_thinking,
                        title="[bold dim cyan]LLM Thinking[/bold dim cyan]",
                        border_style="dim cyan"
                    ))
                except BlockingIOError:
                    pass

            # Log assistant response (if any content)
            if content:
                try:
                    display_content = content
                    if len(content) > 16000:
                        display_content = content[:16000] + "\n... [truncated]"
                    console.print(Panel(
                        display_content,
                        title="[bold green]LLM Response[/bold green]",
                        border_style="green"
                    ))
                except BlockingIOError:
                    pass

                # Emit agent thought event for CLI (include thinking if present)
                thought_text = content
                if thinking_content:
                    thought_text = f"[Thinking]\n{thinking_content}\n\n[Response]\n{content}"
                hooks.emit_agent_thought(
                    session_id=session_id,
                    agent_name=self.name,
                    thought=self._truncate_for_event(thought_text, 3000),
                    summary=self._truncate_for_event(content, 500),
                )

            # Add tool calls if present
            if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                tool_names = [tc.function.name for tc in choice.message.tool_calls]
                try:
                    console.print(
                        f"[bold yellow][LLM Tool Calls][/bold yellow] {', '.join(tool_names)}"
                    )
                except BlockingIOError:
                    pass
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in choice.message.tool_calls
                ]

            messages.append(assistant_message)

            # Check if done
            if choice.finish_reason == "stop":
                try:
                    console.print(
                        f"[bold white on dark_green][LLM] Finished[/bold white on dark_green] "
                        f"(iteration {iteration})"
                    )
                except BlockingIOError:
                    pass

                # Emit completion event for CLI
                hooks.emit_log_message(
                    session_id=session_id,
                    message=f"LLM completed after {iteration} iterations",
                    level="info",
                    source="llm",
                    agent_name=self.name,
                )
                break

            # Execute tool calls if present
            if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                tool_results = await self._execute_tools(choice.message.tool_calls, deps)
                messages.extend(tool_results)
                self.tool_call_count += len(tool_results)

                # Check tool limit
                if usage_limits and self.tool_call_count >= usage_limits.get("tools", float('inf')):
                    raise UsageLimitExceeded(f"Tool call limit reached: {usage_limits['tools']}")

        # Extract structured output when output_schema is a Pydantic BaseModel.
        # Uses Instructor if available, otherwise falls back to manual JSON extraction.
        _has_pydantic_schema = (
            self.output_schema
            and isinstance(self.output_schema, type)
            and issubclass(self.output_schema, BaseModel)
        )
        if _has_pydantic_schema:
            output = await self._extract_structured(messages)
        else:
            # Return last assistant message content
            output = messages[-1].get("content", "") if messages else ""

        # Extract thoughts from messages
        thoughts = self._extract_thoughts(messages)

        # Print run summary
        try:
            console.print(
                f"\n[bold white on blue]\\[{self.name}] Run Summary[/bold white on blue] "
                f"Requests: {self.request_count} | "
                f"Tool Calls: {self.tool_call_count} | "
                f"Tokens: {self.total_tokens} (prompt: {self.prompt_tokens}, completion: {self.completion_tokens})"
            )
        except BlockingIOError:
            pass

        # Set CHAIN span output and status (same pattern as tool-call-example)
        if isinstance(output, BaseModel):
            out_val = output.model_dump_json()
        elif isinstance(output, str):
            out_val = output
        else:
            out_val = str(output)
        parent_trace = self._build_trace_output(out_val, thoughts)
        if parent_trace:
            parent_span.set_attribute(
                _TOOL_ATTR_OUTPUT,
                self._truncate_for_span_attr(parent_trace),
            )
        if thoughts:
            think_attr = self._truncate_for_span_attr(thoughts)
            parent_span.set_attribute(_ATTR_LLM_THINKING, think_attr)
            parent_span.add_event("llm.thinking", {"llm.thinking_content": think_attr})
        parent_span.set_status(trace.Status(trace.StatusCode.OK))

        return AgentResult(
            output=output,
            thoughts=thoughts,
            raw_messages=messages.copy(),
            usage=TokenUsageInfo(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.total_tokens,
            ),
            request_count=self.request_count,
            tool_call_count=self.tool_call_count,
        )

    def _build_messages(self, prompt: str, message_history: list | None) -> list[dict]:
        """Build message list from prompt and history.

        Args:
            prompt: User prompt
            message_history: Previous messages (default: None)

        Returns:
            List of messages with system instruction, history, and user prompt
        """
        messages = []

        # System message
        if self.instructions:
            messages.append({"role": "system", "content": self.instructions})

        # Add history if provided
        if message_history:
            messages.extend(message_history)

        # User message
        messages.append({"role": "user", "content": prompt})

        return messages

    def _build_tool_schemas(self) -> list[dict] | None:
        """Auto-generate tool schemas from function signatures.

        Uses function name, docstring, and type hints to build OpenAI tool schema.

        Returns:
            List of tool schema dicts, or None if no tools
        """
        if not self.tools:
            try:
                console.print("[bold red][Warning][/bold red] No tools registered!")
            except BlockingIOError:
                pass
            return None

        schemas = []
        for func in self.tools:
            schema = {
                "type": "function",
                "function": {
                    "name": getattr(func, "__name__", None),
                    "description": (func.__doc__ or "").strip(),
                    "parameters": self._extract_params(func),
                }
            }
            schemas.append(schema)

        # Debug: show tool schemas being sent
        try:
            tool_info = [f"{s['function']['name']}" for s in schemas]
            console.print(f"[bold dim][Tool Schemas Built][/bold dim] {', '.join(tool_info)}")
        except BlockingIOError:
            pass

        return schemas

    def _extract_params(self, func: Callable) -> dict:
        """Extract JSON schema from function signature.

        Uses inspect and type hints to build parameters schema.

        Args:
            func: Function to extract parameters from

        Returns:
            JSON schema dict for function parameters
        """
        sig = inspect.signature(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            # Skip 'deps' parameter (injected by CoreAgent)
            if name == "deps":
                continue

            param_type = param.annotation
            properties[name] = self._type_to_jsonschema(param_type, name)

            # Add to required if no default value
            if param.default == inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required if required else [],
        }

    def _type_to_jsonschema(self, param_type: Any, param_name: str) -> dict:
        """Convert Python type hint to JSON schema.

        Args:
            param_type: Python type annotation
            param_name: Parameter name (for description)

        Returns:
            JSON schema dict for the type
        """
        # Handle string annotations
        if param_type == str or param_type == "str":
            return {"type": "string"}
        elif param_type == int or param_type == "int":
            return {"type": "integer"}
        elif param_type == float or param_type == "float":
            return {"type": "number"}
        elif param_type == bool or param_type == "bool":
            return {"type": "boolean"}
        elif param_type == dict or param_type == "dict":
            return {"type": "object"}
        elif param_type == list or param_type == "list":
            return {"type": "array"}

        # Handle typing module types
        if hasattr(param_type, '__origin__'):
            origin = param_type.__origin__
            if origin is list:
                return {"type": "array"}
            elif origin is dict:
                return {"type": "object"}

        # Default to string for unknown types
        return {"type": "string", "description": param_name}

    async def _call_llm_with_retry(self, messages: list[dict], tools: list[dict] | None) -> Any:
        """Call LiteLLM with retry logic using tenacity.

        Retries on:
        - RateLimitError (rate limiting)
        - ServiceUnavailableError (503)
        - Timeout errors
        - Connection errors

        Args:
            messages: List of messages
            tools: List of tool schemas (optional)

        Returns:
            LiteLLM response object

        Raises:
            CoreRateLimitError: When rate limited and retries exhausted
            QuotaExceededError: When API quota/billing limit exceeded
            AuthenticationError: When API authentication fails
            CoreConnectionError: When connection to API fails
            ModelNotFoundError: When requested model not available
            InvalidRequestError: When request is invalid
            LLMError: For other LLM-related errors
        """
        # Get litellm exception types (they're in litellm.exceptions)
        try:

            retryable_exceptions = (
                LiteLLMRateLimitError,
                ServiceUnavailableError,
                LiteLLMTimeout,
                LiteLLMConnectionError,
            )
        except ImportError:
            # Fallback for older litellm versions
            retryable_exceptions = (Exception,)

        def log_retry(retry_state):
            """Log retry attempts."""
            attempt = retry_state.attempt_number
            exception = retry_state.outcome.exception() if retry_state.outcome else None
            exc_name = type(exception).__name__ if exception else "Unknown"
            wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
            logger.warning(
                "Retry %d/5 for %s - waiting %.1fs before next attempt",
                attempt, exc_name, wait_time
            )

        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=12),
            retry=retry_if_exception_type(retryable_exceptions),
            reraise=True,
            before_sleep=log_retry,
        )
        async def _call():
            kwargs = {
                "model": self.model,
                "messages": messages,
            }

            if tools:
                kwargs["tools"] = tools

            # For custom endpoints, we need api_key and api_base
            if self.api_base:
                kwargs["api_base"] = self.api_base

            # API key handling
            if self.api_key:
                kwargs["api_key"] = self.api_key
            elif self.api_base and self.model.startswith("openai/"):
                # For custom OpenAI-compatible endpoints without explicit api_key
                # Use a placeholder - some local models don't require authentication
                kwargs["api_key"] = "sk-dummy-key-for-local-model"

            if self.concurrent_limiter is not None:
                async with self.concurrent_limiter:
                    return await acompletion(**kwargs)
            return await acompletion(**kwargs)

        try:
            return await _call()
        except ContentPolicyViolationError as e:
            self._handle_content_policy_violation(e)
        except RetryError as e:
            # Extract the original exception from RetryError so we surface the real LLM error
            original = e.last_attempt.exception() if e.last_attempt else None
            exc_to_handle = original if isinstance(original, Exception) else e
            self._handle_llm_error(exc_to_handle)
        except Exception as e:
            self._handle_llm_error(e)

    def _handle_llm_error(self, error: Exception) -> None:
        """Convert LLM errors to user-friendly exceptions.

        Emits the error to the event bus so the CLI can display it (e.g. litellm.APIConnectionError, 429 body).

        Args:
            error: The original exception

        Raises:
            Appropriate CoreAgent exception type
        """
        error_str = str(error).lower()
        error_msg = str(error)

        # Log the full error (no truncation) so logs show e.g. 429 body, connection details
        logger.error("LLM error: %s", error_msg)

        # Emit to CLI so user sees the error (e.g. rate limit, connection, auth)
        try:
            hooks = get_event_hooks()
            session_id = getattr(self, "_last_session_id", "unknown")
            task = getattr(self, "_last_task", "")
            hooks.emit_agent_error(
                session_id=session_id,
                agent_name=self.name,
                task=task,
                error_type=type(error).__name__,
                error_message=error_msg,
            )
        except Exception:  # do not let hook failures mask the LLM error
            pass

        # Check for quota exceeded (billing issue - don't retry)
        if "insufficient_quota" in error_str or "exceeded your current quota" in error_str:
            raise QuotaExceededError(
                "API quota exceeded. " + error_msg,
                original_error=error
            )

        # Check for rate limit (temporary - already retried); include full provider message (e.g. 429 body)
        if "rate_limit" in error_str or "rate limit" in error_str or "429" in error_str:
            raise CoreRateLimitError(
                "Rate limit exceeded. " + error_msg,
                original_error=error
            )

        # Check for authentication errors
        if "auth" in error_str or "api_key" in error_str or "401" in error_str or "invalid_api_key" in error_str:
            raise AuthenticationError(
                "API authentication failed. " + error_msg,
                original_error=error
            )

        # Check for model not found
        if "model" in error_str and ("not found" in error_str or "does not exist" in error_str or "404" in error_str):
            raise ModelNotFoundError(
                f"Model '{self.model}' not found. " + error_msg,
                original_error=error
            )

        # Check for connection errors
        if "connection" in error_str or "connect" in error_str or "timeout" in error_str or "unreachable" in error_str:
            raise CoreConnectionError(
                "Failed to connect to the API. " + error_msg,
                original_error=error
            )

        # Check for bad request
        if "bad request" in error_str or "invalid" in error_str or "400" in error_str:
            raise InvalidRequestError(
                "Invalid request to the API: " + error_msg,
                original_error=error
            )

        # Generic LLM error (include full message so user sees provider detail)
        raise LLMError(
            "LLM request failed: " + error_msg,
            original_error=error
        )

    def _handle_content_policy_violation(self, error: ContentPolicyViolationError) -> None:
        """Handle Azure/OpenAI content policy violations with detailed logging.

        This surfaces provider-specific content filter information (when available)
        and then raises a user-facing InvalidRequestError.
        """
        details = getattr(error, "provider_specific_fields", None) or {}
        innererror = details.get("innererror") if isinstance(details, dict) else None

        if innererror:
            content_filter_result = innererror.get("content_filter_result", {}) or {}

            # Access content filter results for common categories
            hate_filtered = (content_filter_result.get("hate") or {}).get("filtered")
            violence_severity = (content_filter_result.get("violence") or {}).get("severity")
            sexual_filtered = (content_filter_result.get("sexual") or {}).get("filtered")
            code = innererror.get("code")

            log_msg = (
                "Content policy violation from provider. "
                f"code={code}, hate_filtered={hate_filtered}, "
                f"violence_severity={violence_severity}, sexual_filtered={sexual_filtered}"
            )

            logger.warning(log_msg)
            try:
                console.print(Panel(
                    log_msg,
                    title="[bold red]Content Policy Violation[/bold red]",
                    border_style="red",
                ))
            except BlockingIOError:
                # If stdout/stderr is blocked, we still raise the error below
                pass

        raise InvalidRequestError(
            "Request blocked by provider content policy. Please adjust the prompt/content and try again.",
            original_error=error,
        )

    async def _execute_tools(self, tool_calls: list, deps: Any) -> list[dict]:
        """Execute tool calls with dependency injection.

        Each tool run is traced with OpenInference TOOL span attributes
        (tool.name, tool.parameters, input.value, output.value, status) so any
        agent using CoreAgent gets consistent observability.
        """
        results = []

        for tc in tool_calls:
            function_name = tc.function.name
            function_args_str = tc.function.arguments
            span_attrs = {
                _TOOL_ATTR_KIND: "TOOL",
                _TOOL_ATTR_NAME: function_name,
                _TOOL_ATTR_PARAMS: function_args_str,
                _TOOL_ATTR_INPUT: function_args_str,
            }

            with self.tracer.start_as_current_span(
                function_name,
                attributes=span_attrs,
            ) as tool_span:
                func = self._find_tool(function_name)

                if func is None:
                    tool_span.set_attribute(_TOOL_ATTR_OUTPUT, f"Error: Tool '{function_name}' not found")
                    tool_span.set_status(trace.Status(trace.StatusCode.ERROR))
                    results.append({
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error: Tool '{function_name}' not found"
                    })
                    continue

                try:
                    args = json.loads(function_args_str)
                except Exception as e:
                    err_msg = f"Invalid JSON arguments: {e}"
                    tool_span.set_attribute(_TOOL_ATTR_OUTPUT, err_msg)
                    tool_span.set_status(trace.Status(trace.StatusCode.ERROR))
                    try:
                        console.print(Panel(str(e), title=f"[bold red][Tool Error] {function_name}[/bold red]", border_style="red"))
                    except BlockingIOError:
                        pass
                    results.append({
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error executing tool: {err_msg}"
                    })
                    continue

                # Log tool call (truncate if too long)
                display_args = function_args_str if len(function_args_str) <= 8000 else function_args_str[:8000] + "\n... [truncated]"
                try:
                    console.print(Panel(
                        display_args,
                        title=f"[bold orange3][Tool Call] {function_name}[/bold orange3]",
                        border_style="orange3"
                    ))
                except BlockingIOError:
                    pass

                sig = inspect.signature(func)
                params = sig.parameters

                if "deps" in params:
                    args["deps"] = deps
                if "ctx" in params:
                    args["ctx"] = RunContextCompat(deps=deps, usage=RunUsage(requests=self.request_count))
                elif "context" in params:
                    args["context"] = RunContextCompat(deps=deps, usage=RunUsage(requests=self.request_count))

                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(**args)
                    else:
                        result = func(**args)
                        if asyncio.iscoroutine(result):
                            result = await result

                    serialized = self._serialize_tool_result(result)

                    display_result = serialized[:16000] + "\n... [truncated]" if len(serialized) > 16000 else serialized
                    try:
                        console.print(Panel(
                            display_result,
                            title=f"[bold purple][Tool Result] {function_name}[/bold purple]",
                            border_style="purple"
                        ))
                    except BlockingIOError:
                        pass

                    out_attr = serialized[:4096] + "..." if len(serialized) > 4096 else serialized
                    tool_span.set_attribute(_TOOL_ATTR_OUTPUT, out_attr)
                    tool_span.set_status(trace.Status(trace.StatusCode.OK))

                    results.append({
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "name": function_name,
                        "content": serialized
                    })

                except Exception as e:
                    err_msg = str(e)
                    tool_span.set_attribute(_TOOL_ATTR_OUTPUT, err_msg)
                    tool_span.set_status(trace.Status(trace.StatusCode.ERROR))
                    try:
                        console.print(Panel(err_msg, title=f"[bold red][Tool Error] {function_name}[/bold red]", border_style="red"))
                    except BlockingIOError:
                        pass
                    results.append({
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "name": function_name,
                        "content": f"Error executing tool: {err_msg}"
                    })

        return results

    def _serialize_tool_result(self, result: Any) -> str:
        """Serialize tool result for LLM.

        Args:
            result: Tool result (string, dict, Pydantic model, or other object)

        Returns:
            Serialized string for LLM
        """
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        elif isinstance(result, dict):
            # Use custom encoder to handle non-serializable objects
            try:
                return json.dumps(result, default=self._json_default)
            except (TypeError, ValueError):
                return str(result)
        elif isinstance(result, (list, tuple)):
            try:
                return json.dumps(result, default=self._json_default)
            except (TypeError, ValueError):
                return str(result)
        else:
            return str(result)

    def _json_default(self, obj: Any) -> Any:
        """Custom JSON encoder for non-serializable objects."""
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        elif hasattr(obj, 'to_dict'):
            return obj.to_dict()
        else:
            return str(obj)

    def _find_tool(self, tool_name: str) -> Callable | None:
        """Find tool function by name.

        Args:
            tool_name: Name of the tool to find

        Returns:
            Tool function, or None if not found
        """
        for func in self.tools:
            if getattr(func, "__name__", None) == tool_name:
                return func
        return None

    async def _extract_structured(self, messages: list[dict]) -> BaseModel:
        """Extract structured output using Instructor or manual JSON parsing.

        Args:
            messages: Full message history

        Returns:
            Pydantic model instance with structured output

        Raises:
            Exception if extraction fails after retries
        """
        if not self.output_schema:
            raise ValueError("Output schema not configured")

        # First try Instructor if available
        if self.instructor_client:
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "response_model": self.output_schema,
                }

                # Ollama requires the 'format' parameter for structured output;
                # other providers (OpenAI, Anthropic, etc.) don't recognise it.
                if self.model.startswith("ollama") or self.model.startswith("ollama_chat"):
                    kwargs["format"] = "json"


                if self.api_base:
                    kwargs["api_base"] = self.api_base

                if self.api_key:
                    kwargs["api_key"] = self.api_key
                elif self.api_base and self.model.startswith("openai/"):
                    kwargs["api_key"] = "sk-dummy-key-for-local-model"

                response = await self.instructor_client.chat.completions.create(**kwargs)
                try:
                    console.print(f"[bold green][Structured Output OK][/bold green] {type(response).__name__}")
                except BlockingIOError:
                    pass
                return response
            except Exception as instructor_error:
                # Any failure in Instructor structured output should fall back to
                # manual JSON extraction so that providers with partial support
                # don't break the agent.
                try:
                    console.print(
                        "[bold yellow][Instructor Failed][/bold yellow] "
                        f"{str(instructor_error)[:200]} - falling back to manual JSON extraction..."
                    )
                except BlockingIOError:
                    pass
                # Fall through to manual extraction below

        # Manual JSON extraction fallback
        # Ask the LLM to output JSON and parse it ourselves
        try:
            return await self._extract_structured_manual(messages)
        except Exception as e:
            # If extraction fails, return a fallback instance with low confidence
            # This matches the current AgentRunner behavior
            try:
                console.print(f"[bold red][Structured Output FAILED][/bold red] {str(e)[:200]}")
            except BlockingIOError:
                pass
            if hasattr(self.output_schema, 'model_fields'):
                # Create fallback with default/error values
                fallback_data = {}
                fields = self.output_schema.model_fields

                # Handle common string fields
                for field_name in ["detailed_summary", "summary", "message", "content",
                                   "reasoning", "highly_possible_vulnerabilities"]:
                    if field_name in fields:
                        fallback_data[field_name] = f"Structured output extraction failed: {str(e)}"

                # Handle confidence score
                if "confidence_score" in fields:
                    fallback_data["confidence_score"] = 0.1

                # Handle proofs/thoughts as empty strings
                for field_name in ["proofs", "thoughts"]:
                    if field_name in fields:
                        fallback_data[field_name] = ""

                # Handle boolean fields
                if "task_achieved" in fields:
                    fallback_data["task_achieved"] = False

                # Handle required list fields (like 'tasks') with empty list
                for field_name in ["tasks", "subtasks", "children"]:
                    if field_name in fields:
                        fallback_data[field_name] = []

                try:
                    return self.output_schema(**fallback_data)
                except Exception:
                    # If still failing, try model_construct for partial validation
                    return self.output_schema.model_construct(**fallback_data)
            raise

    async def _extract_structured_manual(self, messages: list[dict]) -> BaseModel:
        """Manual JSON extraction fallback when Instructor doesn't work.

        First tries to parse JSON from existing messages, then asks LLM if needed.

        Args:
            messages: Full message history

        Returns:
            Pydantic model instance
        """
        # First, try to extract JSON from the last assistant message
        # The LLM might have already output JSON
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if content:
                    result = self._try_parse_json_from_content(content)
                    if result:
                        try:
                            console.print(f"[bold green][Parsed JSON from response][/bold green] {type(result).__name__}")
                        except BlockingIOError:
                            pass
                        return result
                break  # Only check the last assistant message

        # If no JSON found in existing messages, ask LLM explicitly
        if isinstance(self.output_schema, BaseModel):
            schema_json = self.output_schema.model_json_schema()
        json_prompt = f"""Based on the conversation above, provide your response as a JSON object matching this schema:

```json
{json.dumps(schema_json, indent=2)}
```

Output ONLY valid JSON, no other text. The JSON must match the schema exactly."""

        extraction_messages = messages.copy()
        extraction_messages.append({"role": "user", "content": json_prompt})

        kwargs = {
            "model": self.model,
            "messages": extraction_messages,
            "response_format": {"type": "json_object"},
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.api_base and self.model.startswith("openai/"):
            kwargs["api_key"] = "sk-dummy-key-for-local-model"

        try:
            response = await acompletion(**kwargs)
        except ContentPolicyViolationError as e:
            self._handle_content_policy_violation(e)
        content = response.choices[0].message.content or ""

        result = self._try_parse_json_from_content(content)
        if result:
            try:
                console.print(f"[bold green][Manual JSON OK][/bold green] {type(result).__name__}")
            except BlockingIOError:
                pass
            return result

        raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

    def _try_parse_json_from_content(self, content: str) -> BaseModel | None:
        """Try to parse JSON from content and validate against schema.

        Args:
            content: Text content that might contain JSON

        Returns:
            Pydantic model instance if successful, None otherwise
        """
        # Try to extract JSON from the content
        json_str = content.strip()

        # Handle markdown code blocks
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()

        # Try to find JSON object in the content
        if not json_str.startswith("{"):
            # Look for JSON object start
            brace_start = json_str.find("{")
            if brace_start != -1:
                # Find matching closing brace
                depth = 0
                for i, c in enumerate(json_str[brace_start:]):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            json_str = json_str[brace_start:brace_start + i + 1]
                            break

        try:
            data = json.loads(json_str)
            if isinstance(self.output_schema, BaseModel):
                return self.output_schema.model_validate(data)
        except (json.JSONDecodeError, Exception):
            return None

    def _extract_thoughts(self, messages: list[dict]) -> str:
        """Extract agent thoughts/reasoning from message history.

        Includes both regular content and thinking/reasoning content from
        extended-thinking models (stored in the ``thinking_content`` key).

        Args:
            messages: Full message history

        Returns:
            Concatenated thoughts from assistant messages
        """
        thoughts = []
        max_chars = 1500

        for msg in messages:
            if msg.get("role") != "assistant":
                continue

            # Prefer thinking_content (extended-thinking models) over plain content
            thinking = msg.get("thinking_content")
            if thinking and isinstance(thinking, str):
                thoughts.append(thinking)
            elif msg.get("content"):
                content = msg["content"]
                if isinstance(content, str):
                    thoughts.append(content)

            if sum(len(t) for t in thoughts) > max_chars:
                break

        result = "\n".join(thoughts)
        if len(result) > max_chars:
            result = result[:max_chars] + "..."

        return result

    @staticmethod
    def _truncate_for_span_attr(text: str, max_len: int = 4096) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    @staticmethod
    def _get_attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if content is None or content == "":
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        parts.append(block["text"])
                    elif "text" in block:
                        parts.append(str(block["text"]))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p)
        return str(content)

    def _set_llm_input_message_attributes(self, span: Any, messages: list[dict]) -> None:
        """Flatten chat messages into OpenInference ``llm.input_messages.*`` attributes."""
        for index, message in enumerate(messages):
            prefix = f"{_LLM_INPUT_PREFIX}.{index}"
            role = message.get("role")
            if isinstance(role, str) and role:
                span.set_attribute(f"{prefix}.{_LLM_MSG_ROLE}", role)
            text = self._message_content_to_text(message.get("content", ""))
            if text:
                span.set_attribute(
                    f"{prefix}.{_LLM_MSG_CONTENT}",
                    self._truncate_for_span_attr(text),
                )

    def _set_llm_output_tool_call_attributes(self, span: Any, tool_calls: list[Any]) -> None:
        """Flatten tool calls into OpenInference ``llm.output_messages.0.message.tool_calls.*``."""
        base = f"{_LLM_OUTPUT_PREFIX}.0.{_LLM_MSG_TOOL_CALLS}"
        for index, tool_call in enumerate(tool_calls):
            p = f"{base}.{index}.tool_call"
            tid = self._get_attr_or_key(tool_call, "id", "")
            if isinstance(tid, str) and tid:
                span.set_attribute(f"{p}.id", tid)
            function = self._get_attr_or_key(tool_call, "function", None)
            fname = self._get_attr_or_key(function, "name", "")
            if isinstance(fname, str) and fname:
                span.set_attribute(f"{p}.function.name", fname)
            fargs = self._get_attr_or_key(function, "arguments", "")
            if isinstance(fargs, str) and fargs:
                span.set_attribute(
                    f"{p}.function.arguments",
                    self._truncate_for_span_attr(fargs),
                )

    @staticmethod
    def _build_trace_output(final_text: str, thinking_text: str) -> str:
        """Trace-visible text: thinking + final response (matches console-style sections)."""
        if final_text and thinking_text:
            return f"[Thinking]\n{thinking_text}\n\n[Response]\n{final_text}"
        return thinking_text or final_text

    @staticmethod
    def _build_llm_trace_output(
        content: str,
        thinking_content: str,
        tool_calls: list[Any],
    ) -> str:
        """Single-turn LLM trace payload; includes tool-call-only responses."""
        base = CoreAgent._build_trace_output(content, thinking_content)
        if base:
            return base
        if tool_calls:
            names: list[str] = []
            for tc in tool_calls:
                fn = CoreAgent._get_attr_or_key(
                    CoreAgent._get_attr_or_key(tc, "function", None),
                    "name",
                    "",
                )
                if isinstance(fn, str) and fn:
                    names.append(fn)
            if names:
                return "[Tool calls] " + ", ".join(names)
        return ""

    def _get_session_id(self, deps: Any) -> str:
        """Extract session_id from deps.

        Args:
            deps: Dependencies (dict or object)

        Returns:
            Session ID string, or "unknown" if not found
        """
        if deps is None:
            return "unknown"
        if isinstance(deps, dict):
            return str(deps.get("session_id", "unknown"))
        return str(getattr(deps, "session_id", "unknown"))

    def _truncate_for_event(self, text: str, max_length: int = 500) -> str:
        """Truncate text for event emission.

        Args:
            text: Text to truncate
            max_length: Maximum length (default 500)

        Returns:
            Truncated text with ellipsis if needed
        """
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text
