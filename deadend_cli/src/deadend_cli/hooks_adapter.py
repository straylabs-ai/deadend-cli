# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Adapter connecting EventBus to agent hooks interface."""

from __future__ import annotations

from typing import Any, Optional

from deadend_agent.hooks import EventHooks

from .event_bus import EventBus


class EventBusHooksAdapter:
    """Adapter that implements EventHooks protocol using EventBus.

    This class bridges the deadend_agent hooks interface with the
    deadend_cli event bus system for RPC event streaming.
    """

    def __init__(self, event_bus: EventBus):
        self._bus = event_bus

    def emit_agent_start(
        self,
        session_id: str,
        agent_name: str,
        task: str,
        task_id: Optional[str] = None,
        depth: int = 0,
        parent_task_id: Optional[str] = None,
    ) -> None:
        self._bus.emit_agent_start(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            task_id=task_id,
            depth=depth,
            parent_task_id=parent_task_id,
        )

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
        self._bus.emit_agent_end(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            confidence_score=confidence_score,
            task_id=task_id,
            notes=notes,
            thought_summary=thought_summary,
            attempts=attempts,
        )

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
        self._bus.emit_agent_error(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            error_type=error_type,
            error_message=error_message,
            task_id=task_id,
            partial_reasoning=partial_reasoning,
        )

    def emit_agent_thought(
        self,
        session_id: str,
        agent_name: str,
        thought: str,
        summary: Optional[str] = None,
        relevance: float = 0.5,
    ) -> None:
        self._bus.emit_agent_thought(
            session_id=session_id,
            agent_name=agent_name,
            thought=thought,
            summary=summary,
            relevance=relevance,
        )

    def emit_agent_routed(
        self,
        session_id: str,
        task: str,
        selected_agent: str,
        reasoning: str,
        available_agents: Optional[list[str]] = None,
    ) -> None:
        self._bus.emit_agent_routed(
            session_id=session_id,
            task=task,
            selected_agent=selected_agent,
            reasoning=reasoning,
            available_agents=available_agents,
        )

    def emit_tool_call_start(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        args: str = "",
        tool_call_id: Optional[str] = None,
    ) -> None:
        self._bus.emit_tool_call_start(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            args=args,
            tool_call_id=tool_call_id,
        )

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
        self._bus.emit_tool_call_end(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            success=success,
            result=result,
            error=error,
            tool_call_id=tool_call_id,
            duration_ms=duration_ms,
        )

    def emit_task_expanded(
        self,
        session_id: str,
        parent_task: str,
        parent_task_id: str,
        subtasks: list[dict[str, Any]],
    ) -> None:
        self._bus.emit_task_expanded(
            session_id=session_id,
            parent_task=parent_task,
            parent_task_id=parent_task_id,
            subtasks=subtasks,
        )

    def emit_confidence_update(
        self,
        session_id: str,
        task: str,
        task_id: str,
        old_confidence: float,
        new_confidence: float,
        decision: str,
    ) -> None:
        self._bus.emit_confidence_update(
            session_id=session_id,
            task=task,
            task_id=task_id,
            old_confidence=old_confidence,
            new_confidence=new_confidence,
            decision=decision,
        )

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
        self._bus.emit_validation_result(
            session_id=session_id,
            task=task,
            task_id=task_id,
            valid=valid,
            confidence_score=confidence_score,
            critique=critique,
            validation_token=validation_token,
        )

    def emit_log_message(
        self,
        session_id: str,
        message: str,
        level: str = "info",
        source: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> None:
        self._bus.emit_log_message(
            session_id=session_id,
            message=message,
            level=level,
            source=source,
            agent_name=agent_name,
        )

    def is_interrupted(self, session_id: str) -> bool:
        return self._bus.is_interrupted(session_id)


__all__ = ["EventBusHooksAdapter"]
