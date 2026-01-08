# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Event hooks interface for agent execution.

This module provides a protocol-based interface for emitting events during
agent execution. The hooks can be set externally (e.g., by the RPC server)
to stream events to a frontend without creating circular dependencies.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol


class EventHooks(Protocol):
    """Protocol for event hooks during agent execution."""

    def emit_agent_start(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        task_id: Optional[str] = None,
        depth: int = 0,
        parent_task_id: Optional[str] = None,
    ) -> None:
        """Called when an agent starts executing."""
        ...

    def emit_agent_end(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        confidence_score: float,
        task_id: Optional[str] = None,
        notes: Optional[str] = None,
        thought_summary: Optional[str] = None,
        attempts: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Called when an agent finishes executing."""
        ...

    def emit_agent_error(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        error_type: str,
        error_message: str,
        task_id: Optional[str] = None,
        partial_reasoning: Optional[str] = None,
    ) -> None:
        """Called when an agent encounters an error."""
        ...

    def emit_agent_thought(
        self,
        session_id: str,
        agent_name: str,
        thought: str,
        summary: Optional[str] = None,
        relevance: float = 0.5,
    ) -> None:
        """Called when agent reasoning is extracted."""
        ...

    def emit_agent_routed(
        self,
        session_id: str,
        task: str,
        selected_agent: str,
        reasoning: str,
        available_agents: Optional[list[str]] = None,
    ) -> None:
        """Called when a task is routed to an agent."""
        ...

    def emit_tool_call_start(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        args: str = "",
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Called when a tool call starts."""
        ...

    def emit_tool_call_end(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        success: bool,
        result: str = "",
        error: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Called when a tool call completes."""
        ...

    def emit_task_expanded(
        self,
        session_id: str,
        parent_task: str,
        parent_task_id: str,
        subtasks: list[dict[str, Any]],
    ) -> None:
        """Called when a task is expanded into subtasks."""
        ...

    def emit_confidence_update(
        self,
        session_id: str,
        task: str,
        task_id: str,
        old_confidence: float,
        new_confidence: float,
        decision: str,
    ) -> None:
        """Called when confidence score is updated."""
        ...

    def emit_validation_result(
        self,
        session_id: str,
        task: str,
        task_id: str,
        valid: bool,
        confidence_score: float,
        critique: str,
        validation_token: Optional[str] = None,
    ) -> None:
        """Called when validation completes."""
        ...

    def emit_log_message(
        self,
        session_id: str,
        message: str,
        level: str = "info",
        source: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> None:
        """Called to emit a log message."""
        ...

    def is_interrupted(self, session_id: str) -> bool:
        """Check if the session has been interrupted."""
        ...


class NullEventHooks:
    """No-op implementation of event hooks.

    Used as the default when no external hooks are configured.
    """

    def emit_agent_start(self, *args, **kwargs) -> None:
        pass

    def emit_agent_end(self, *args, **kwargs) -> None:
        pass

    def emit_agent_error(self, *args, **kwargs) -> None:
        pass

    def emit_agent_thought(self, *args, **kwargs) -> None:
        pass

    def emit_agent_routed(self, *args, **kwargs) -> None:
        pass

    def emit_tool_call_start(self, *args, **kwargs) -> None:
        pass

    def emit_tool_call_end(self, *args, **kwargs) -> None:
        pass

    def emit_task_expanded(self, *args, **kwargs) -> None:
        pass

    def emit_confidence_update(self, *args, **kwargs) -> None:
        pass

    def emit_validation_result(self, *args, **kwargs) -> None:
        pass

    def emit_log_message(self, *args, **kwargs) -> None:
        pass

    def is_interrupted(self, session_id: str) -> bool:
        return False


# Global event hooks instance (can be replaced by RPC server)
_event_hooks: EventHooks = NullEventHooks()


def set_event_hooks(hooks: EventHooks) -> None:
    """Set the global event hooks instance."""
    global _event_hooks
    _event_hooks = hooks


def get_event_hooks() -> EventHooks:
    """Get the current event hooks instance."""
    return _event_hooks


__all__ = [
    "EventHooks",
    "NullEventHooks",
    "set_event_hooks",
    "get_event_hooks",
]
