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
from typing import Callable, Type, Any
from contextlib import contextmanager

from pydantic import BaseModel, Field
from pydantic_ai import RunUsage
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Rich console for colored output - force_terminal ensures colors work in scripts/pipes
console = Console(force_terminal=True)

try:
    import litellm
    from litellm import acompletion
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

from . import UsageLimitExceeded
from .telemetry import tracer


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

    def __init__(
        self,
        model: str,
        instructions: str,
        tools: list[Callable] | None = None,
        output_schema: Type[BaseModel] | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        rate_limit_rpm: int = 60,
        name: str = "agent",
    ):
        """Initialize CoreAgent.

        Args:
            model: Model identifier (e.g., "gpt-4o", "claude-3-5-sonnet")
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

        # Rate limiting - simple AsyncLimiter
        if AIOLIMITER_AVAILABLE:
            self.rate_limiter = AsyncLimiter(rate_limit_rpm, 60)
        else:
            self.rate_limiter = None
            print("Warning: aiolimiter not available, rate limiting disabled")

        # Usage counters - simple ints
        self.request_count = 0
        self.tool_call_count = 0
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

        # Instructor client for structured output
        if INSTRUCTOR_AVAILABLE and output_schema:
            self.instructor_client = instructor.from_litellm(acompletion)
        else:
            self.instructor_client = None
            if output_schema and not INSTRUCTOR_AVAILABLE:
                print("Warning: instructor not available, structured output disabled")

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
            console.print(f"[bold dim][Tool Added][/bold dim] {func.__name__}")
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
        # Check limits
        if usage_limits:
            if self.request_count >= usage_limits.get("requests", float('inf')):
                raise UsageLimitExceeded(f"Request limit reached: {usage_limits['requests']}")
            if self.tool_call_count >= usage_limits.get("tools", float('inf')):
                raise UsageLimitExceeded(f"Tool call limit reached: {usage_limits['tools']}")

        # Build messages
        messages = self._build_messages(prompt, message_history)

        # Build tool schemas (auto-generated from function signatures)
        tool_schemas = self._build_tool_schemas() if self.tools else None

        # Debug: Log registered tools
        if self.tools:
            tool_names = [f.__name__ for f in self.tools]
            try:
                console.print(f"[bold dim][Tools Registered][/bold dim] {', '.join(tool_names)}")
            except BlockingIOError:
                pass

        # Agent loop with telemetry
        with self._trace_span("agent_run") as span:
            span.set_attribute("agent.model", self.model)
            span.set_attribute("agent.prompt_length", len(prompt))

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
                assistant_message = {
                    "role": "assistant",
                    "content": content,
                }

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
                    break

                # Execute tool calls if present
                if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                    tool_results = await self._execute_tools(choice.message.tool_calls, deps)
                    messages.extend(tool_results)
                    self.tool_call_count += len(tool_results)

                    # Check tool limit
                    if usage_limits and self.tool_call_count >= usage_limits.get("tools", float('inf')):
                        raise UsageLimitExceeded(f"Tool call limit reached: {usage_limits['tools']}")

            span.set_attribute("agent.iterations", iteration)
            span.set_attribute("agent.total_tokens", self.total_tokens)

        # Extract structured output
        if self.output_schema and self.instructor_client:
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

        return AgentResult(
            output=output,
            thoughts=thoughts,
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
                    "name": func.__name__,
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

        Args:
            messages: List of messages
            tools: List of tool schemas (optional)

        Returns:
            LiteLLM response object

        Raises:
            Various LiteLLM exceptions on permanent failures
        """
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((
                getattr(litellm, 'RateLimitError', Exception),
                getattr(litellm, 'ServiceUnavailableError', Exception),
                getattr(litellm, 'Timeout', Exception),
            ))
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

            return await acompletion(**kwargs)

        return await _call()

    async def _execute_tools(self, tool_calls: list, deps: Any) -> list[dict]:
        """Execute tool calls with dependency injection.

        Args:
            tool_calls: List of tool call objects from LLM
            deps: Dependencies to inject (dict or object, optional)

        Returns:
            List of tool result message dicts
        """
        results = []

        for tc in tool_calls:
            func = self._find_tool(tc.function.name)

            if func is None:
                # Tool not found, return error
                results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "name": tc.function.name,
                    "content": f"Error: Tool '{tc.function.name}' not found"
                })
                continue

            try:
                # Parse arguments
                args = json.loads(tc.function.arguments)

                # Log tool call (truncate if too long)
                display_args = tc.function.arguments
                if len(display_args) > 8000:
                    display_args = display_args[:8000] + "\n... [truncated]"
                try:
                    console.print(Panel(
                        display_args,
                        title=f"[bold orange3][Tool Call] {tc.function.name}[/bold orange3]",
                        border_style="orange3"
                    ))
                except BlockingIOError:
                    pass

                # Get function signature to check for special parameters
                sig = inspect.signature(func)
                params = sig.parameters

                # Inject deps if function expects it (CoreAgent style)
                if "deps" in params:
                    args["deps"] = deps

                # Inject ctx if function expects it (Pydantic AI RunContext style)
                # This provides compatibility with @agent.tool decorated functions
                if "ctx" in params:
                    # Create a RunContext-compatible wrapper
                    # deps should be a dataclass/object with the actual dependencies
                    ctx = RunContextCompat(
                        deps=deps,
                        usage=RunUsage(requests=self.request_count)
                    )
                    args["ctx"] = ctx

                # Execute tool with telemetry
                # Handle both sync and async functions
                # Note: Exception handling is INSIDE the trace span to prevent
                # OpenTelemetry from logging/re-raising exceptions
                with self._trace_span(f"tool:{tc.function.name}"):
                    try:
                        if asyncio.iscoroutinefunction(func):
                            result = await func(**args)
                        else:
                            # Sync function - call directly without await
                            result = func(**args)
                            # If it returns an awaitable anyway, await it
                            if asyncio.iscoroutine(result):
                                result = await result

                        # Serialize result for LLM
                        serialized = self._serialize_tool_result(result)

                        # Log tool result (truncated to ~4000 tokens / 16000 chars)
                        display_result = serialized
                        if len(serialized) > 16000:
                            display_result = serialized[:16000] + "\n... [truncated]"
                        try:
                            console.print(Panel(
                                display_result,
                                title=f"[bold purple][Tool Result] {tc.function.name}[/bold purple]",
                                border_style="purple"
                            ))
                        except BlockingIOError:
                            pass  # Ignore if stdout buffer is full

                        results.append({
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "name": tc.function.name,
                            "content": serialized
                        })

                    except Exception as e:
                        # Log and return error to LLM
                        try:
                            console.print(Panel(
                                str(e),
                                title=f"[bold red][Tool Error] {tc.function.name}[/bold red]",
                                border_style="red"
                            ))
                        except BlockingIOError:
                            pass
                        results.append({
                            "tool_call_id": tc.id,
                            "role": "tool",
                            "name": tc.function.name,
                            "content": f"Error executing tool: {str(e)}"
                        })

            except Exception as e:
                # Fallback for any other errors (e.g., JSON parsing)
                try:
                    console.print(Panel(
                        str(e),
                        title=f"[bold red][Tool Error] {tc.function.name}[/bold red]",
                        border_style="red"
                    ))
                except BlockingIOError:
                    pass
                results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "name": tc.function.name,
                    "content": f"Error executing tool: {str(e)}"
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
            if func.__name__ == tool_name:
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
                # Check if it's a grammar/schema not supported error
                error_str = str(instructor_error)
                if "Invalid grammar" in error_str or "response_format" in error_str.lower():
                    try:
                        console.print("[bold yellow][Instructor Failed][/bold yellow] Model doesn't support structured output, trying manual JSON extraction...")
                    except BlockingIOError:
                        pass
                    # Fall through to manual extraction
                else:
                    # Re-raise other errors to trigger fallback
                    raise instructor_error

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
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.api_base and self.model.startswith("openai/"):
            kwargs["api_key"] = "sk-dummy-key-for-local-model"

        response = await acompletion(**kwargs)
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
            return self.output_schema.model_validate(data)
        except (json.JSONDecodeError, Exception):
            return None

    def _extract_thoughts(self, messages: list[dict]) -> str:
        """Extract agent thoughts/reasoning from message history.

        Args:
            messages: Full message history

        Returns:
            Concatenated thoughts from assistant messages
        """
        thoughts = []
        max_chars = 1500

        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                if content and isinstance(content, str):
                    thoughts.append(content)
                    if sum(len(t) for t in thoughts) > max_chars:
                        break

        result = "\n".join(thoughts)
        if len(result) > max_chars:
            result = result[:max_chars] + "..."

        return result

    @contextmanager
    def _trace_span(self, name: str):
        """Create OpenTelemetry span context manager.

        Args:
            name: Span name

        Yields:
            Span object
        """
        try:
            with tracer.start_as_current_span(name) as span:
                yield span
        except Exception:
            # If telemetry fails, continue without it
            class NoOpSpan:
                def set_attribute(self, _key, _value): pass

            yield NoOpSpan()
