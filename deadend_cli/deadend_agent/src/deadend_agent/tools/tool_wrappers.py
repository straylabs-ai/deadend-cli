# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Tool wrappers for emitting real-time tool call events.

This module provides decorators and utilities for wrapping pydantic-ai tools
to emit TOOL_CALL_START and TOOL_CALL_END events to the event hooks system,
enabling real-time tool execution monitoring.

It also supports an optional approval workflow where tools can require
user approval before execution.
"""

from __future__ import annotations

import functools
import time
import uuid
from typing import Any, Callable, Optional, Protocol, TypeVar, ParamSpec

from deadend_agent.hooks import get_event_hooks

P = ParamSpec("P")
R = TypeVar("R")


class ApprovalProvider(Protocol):
    """Protocol for approval request handling.

    This is implemented by the EventBus or a similar class that can
    request and wait for user approval.
    """

    async def request_approval(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        tool_args: dict[str, Any],
        description: str,
        timeout: float = 300.0,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        """Request user approval for a tool call.

        Returns:
            Tuple of (approved: bool, modified_args: Optional[dict])
        """
        ...


# Global approval provider (set by RPC server when initialized)
_approval_provider: Optional[ApprovalProvider] = None

# Session-level approval mode (all tools require approval when True)
_approval_mode_enabled: bool = False


def set_approval_provider(provider: Optional[ApprovalProvider]) -> None:
    """Set the global approval provider."""
    global _approval_provider
    _approval_provider = provider


def get_approval_provider() -> Optional[ApprovalProvider]:
    """Get the current approval provider."""
    return _approval_provider


def enable_approval_mode() -> None:
    """Enable approval mode - all tool calls will require user approval."""
    global _approval_mode_enabled
    _approval_mode_enabled = True


def disable_approval_mode() -> None:
    """Disable approval mode - tools execute without approval."""
    global _approval_mode_enabled
    _approval_mode_enabled = False


def is_approval_mode_enabled() -> bool:
    """Check if approval mode is currently enabled."""
    return _approval_mode_enabled


def _get_session_id_from_context(ctx: Any) -> str:
    """Extract session_id from a RunContext's deps."""
    if hasattr(ctx, "deps"):
        deps = ctx.deps
        if hasattr(deps, "session_id"):
            return deps.session_id
    return "unknown"


def _get_agent_name_from_context(ctx: Any) -> str:
    """Extract agent name from a RunContext if available."""
    if hasattr(ctx, "deps"):
        deps = ctx.deps
        if hasattr(deps, "agent_name"):
            return deps.agent_name
    return "unknown"


def _truncate_str(value: Any, max_length: int = 500) -> str:
    """Truncate a value to a maximum length for event data."""
    s = str(value)
    if len(s) > max_length:
        return s[:max_length] + "..."
    return s


class ToolApprovalDenied(Exception):
    """Raised when a tool requires approval but the user denies it."""

    def __init__(self, tool_name: str, reason: str = "User denied approval"):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Tool '{tool_name}' approval denied: {reason}")


def with_tool_events(
    tool_name: str | None = None,
    approval_description: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to wrap a tool function with event emission.

    Emits TOOL_CALL_START before the tool executes and TOOL_CALL_END after,
    capturing execution time, success/failure status, and truncated args/result.

    When approval mode is enabled (via enable_approval_mode()), all tools
    will request user approval before executing.

    Args:
        tool_name: Optional override for tool name. If not provided,
                   uses the function's __name__.
        approval_description: Human-readable description for approval request.
                             If not provided, a default is generated.

    Returns:
        Decorator function that wraps tools with event emission.

    Example:
        @with_tool_events()
        def my_tool(ctx: RunContext[Deps], param: str) -> Result:
            ...

        @with_tool_events("custom_tool_name")
        async def async_tool(ctx: RunContext[Deps]) -> Result:
            ...
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        name = tool_name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            hooks = get_event_hooks()
            tool_call_id = str(uuid.uuid4())

            # Try to extract context info from first arg (typically RunContext)
            ctx = args[0] if args else None
            session_id = _get_session_id_from_context(ctx)
            agent_name = _get_agent_name_from_context(ctx)

            # Build args string for event (exclude ctx)
            args_str = _truncate_str(kwargs) if kwargs else ""
            if len(args) > 1:
                args_str = _truncate_str(args[1:]) + " " + args_str

            # Emit start event
            hooks.emit_tool_call_start(
                session_id=session_id,
                agent_name=agent_name,
                tool_name=name,
                args=args_str,
                tool_call_id=tool_call_id,
            )

            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                # Emit success end event
                hooks.emit_tool_call_end(
                    session_id=session_id,
                    agent_name=agent_name,
                    tool_name=name,
                    success=True,
                    result=_truncate_str(result, 1000),
                    tool_call_id=tool_call_id,
                    duration_ms=duration_ms,
                )
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000

                # Emit error end event
                hooks.emit_tool_call_end(
                    session_id=session_id,
                    agent_name=agent_name,
                    tool_name=name,
                    success=False,
                    error=str(e),
                    tool_call_id=tool_call_id,
                    duration_ms=duration_ms,
                )
                raise

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            hooks = get_event_hooks()
            tool_call_id = str(uuid.uuid4())

            # Try to extract context info from first arg (typically RunContext)
            ctx = args[0] if args else None
            session_id = _get_session_id_from_context(ctx)
            agent_name = _get_agent_name_from_context(ctx)

            # Build args string for event (exclude ctx)
            args_str = _truncate_str(kwargs) if kwargs else ""
            if len(args) > 1:
                args_str = _truncate_str(args[1:]) + " " + args_str

            # Handle approval workflow if approval mode is enabled
            effective_kwargs = dict(kwargs)
            if is_approval_mode_enabled():
                approval_provider = get_approval_provider()
                if approval_provider is not None:
                    # Build approval description
                    desc = approval_description or f"Execute {name} with args: {args_str}"

                    # Request approval (this emits APPROVAL_REQUIRED and waits)
                    approved, modified_args = await approval_provider.request_approval(
                        session_id=session_id,
                        agent_name=agent_name,
                        tool_name=name,
                        tool_args=effective_kwargs,
                        description=desc,
                    )

                    if not approved:
                        raise ToolApprovalDenied(name, "User denied approval")

                    # Apply modified args if provided
                    if modified_args:
                        effective_kwargs.update(modified_args)

            # Emit start event
            hooks.emit_tool_call_start(
                session_id=session_id,
                agent_name=agent_name,
                tool_name=name,
                args=args_str,
                tool_call_id=tool_call_id,
            )

            start_time = time.perf_counter()
            try:
                result = await func(*args, **effective_kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                # Emit success end event
                hooks.emit_tool_call_end(
                    session_id=session_id,
                    agent_name=agent_name,
                    tool_name=name,
                    success=True,
                    result=_truncate_str(result, 1000),
                    tool_call_id=tool_call_id,
                    duration_ms=duration_ms,
                )
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000

                # Emit error end event
                hooks.emit_tool_call_end(
                    session_id=session_id,
                    agent_name=agent_name,
                    tool_name=name,
                    success=False,
                    error=str(e),
                    tool_call_id=tool_call_id,
                    duration_ms=duration_ms,
                )
                raise

        # Choose wrapper based on whether func is async
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def wrap_tool_with_events(
    func: Callable[P, R],
    tool_name: str | None = None
) -> Callable[P, R]:
    """Wrap an existing tool function with event emission.

    This is useful for wrapping tools that are already defined elsewhere,
    without modifying their original definition.

    Args:
        func: The tool function to wrap
        tool_name: Optional override for tool name

    Returns:
        Wrapped function that emits tool events

    Example:
        wrapped_shell = wrap_tool_with_events(sandboxed_shell_tool)
    """
    return with_tool_events(tool_name)(func)


__all__ = [
    "with_tool_events",
    "wrap_tool_with_events",
    "ApprovalProvider",
    "ToolApprovalDenied",
    "set_approval_provider",
    "get_approval_provider",
    "enable_approval_mode",
    "disable_approval_mode",
    "is_approval_mode_enabled",
]
